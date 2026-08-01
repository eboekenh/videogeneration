from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .media import probe_duration, require_binary, run_command
from .storyboard import Scene, Storyboard


@dataclass(slots=True)
class RenderSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    transition: str = "fade"
    transition_duration: float = 0.35
    crf: int = 18
    preset: str = "medium"
    music_volume: float = 0.08
    narration_volume: float = 1.0
    allow_missing: bool = False
    preview: bool = False
    max_scenes: int | None = None
    cache_dir: Path = Path(".cache/scenes")
    keep_workdir: bool = False

    def normalized(self) -> "RenderSettings":
        result = RenderSettings(**{name: getattr(self, name) for name in self.__dataclass_fields__})
        if result.preview:
            result.width = 960
            result.height = 540
            result.fps = min(result.fps, 24)
            result.crf = max(result.crf, 27)
            result.preset = "veryfast"
        if result.width % 2:
            result.width += 1
        if result.height % 2:
            result.height += 1
        if result.transition not in {"none", "fade", "fadeblack", "fadewhite", "smoothleft", "smoothright"}:
            raise ValueError(f"Unsupported transition: {result.transition}")
        if result.transition_duration < 0:
            raise ValueError("transition_duration cannot be negative")
        return result


def _safe_float(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _motion_filter(scene: Scene, width: int, height: int, fps: int, duration: float) -> str:
    frames = max(2, math.ceil(duration * fps))
    denominator = max(1, frames - 1)
    focus_x = min(1.0, max(0.0, scene.focus_x))
    focus_y = min(1.0, max(0.0, scene.focus_y))
    zoom = min(1.25, max(1.0, scene.zoom))

    cover = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)*{focus_x:.5f}:(ih-oh)*{focus_y:.5f}"
    )

    if scene.motion == "static" or zoom <= 1.0001:
        return f"{cover},fps={fps},format=yuv420p"

    progress = f"on/{denominator}"
    if scene.motion == "zoom_in":
        z_expr = f"1+{zoom - 1:.7f}*{progress}"
        x_expr = f"(iw-iw/zoom)*{focus_x:.5f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.5f}"
    elif scene.motion == "zoom_out":
        z_expr = f"{zoom:.7f}-{zoom - 1:.7f}*{progress}"
        x_expr = f"(iw-iw/zoom)*{focus_x:.5f}"
        y_expr = f"(ih-ih/zoom)*{focus_y:.5f}"
    else:
        z_expr = f"{zoom:.7f}"
        max_x = "(iw-iw/zoom)"
        max_y = "(ih-ih/zoom)"
        if scene.motion == "pan_left":
            x_expr = f"{max_x}*(1-{progress})"
            y_expr = f"{max_y}*{focus_y:.5f}"
        elif scene.motion == "pan_right":
            x_expr = f"{max_x}*{progress}"
            y_expr = f"{max_y}*{focus_y:.5f}"
        elif scene.motion == "pan_up":
            x_expr = f"{max_x}*{focus_x:.5f}"
            y_expr = f"{max_y}*(1-{progress})"
        elif scene.motion == "pan_down":
            x_expr = f"{max_x}*{focus_x:.5f}"
            y_expr = f"{max_y}*{progress}"
        else:
            raise ValueError(f"Unsupported motion: {scene.motion}")

    return (
        f"{cover},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:"
        f"s={width}x{height}:fps={fps},format=yuv420p"
    )


def _cache_key(scene: Scene, image_path: Path, duration: float, settings: RenderSettings) -> str:
    stat = image_path.stat() if image_path.exists() else None
    payload = {
        "scene": {
            "id": scene.id,
            "image": scene.image,
            "motion": scene.motion,
            "focus_x": scene.focus_x,
            "focus_y": scene.focus_y,
            "zoom": scene.zoom,
        },
        "image_mtime": stat.st_mtime_ns if stat else None,
        "image_size": stat.st_size if stat else None,
        "duration": round(duration, 6),
        "width": settings.width,
        "height": settings.height,
        "fps": settings.fps,
        "crf": settings.crf,
        "preset": settings.preset,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _render_black_scene(destination: Path, duration: float, settings: RenderSettings) -> None:
    ffmpeg = require_binary("ffmpeg")
    run_command(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={settings.width}x{settings.height}:r={settings.fps}:d={_safe_float(duration)}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            settings.preset,
            "-crf",
            str(settings.crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        quiet=True,
    )


def render_scene(
    scene: Scene,
    image_path: Path,
    duration: float,
    settings: RenderSettings,
) -> Path:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(scene, image_path, duration, settings)
    cached = settings.cache_dir / f"scene_{scene.id}_{key}.mp4"
    if cached.is_file() and cached.stat().st_size > 1024:
        print(f"♻️  Scene {scene.id}: cache hit")
        return cached

    print(f"🎞️  Scene {scene.id}: {scene.motion}, {duration:.2f}s")
    if not image_path.is_file():
        if not settings.allow_missing:
            raise FileNotFoundError(f"Missing image for scene {scene.id}: {image_path}")
        _render_black_scene(cached, duration, settings)
        return cached

    ffmpeg = require_binary("ffmpeg")
    vf = _motion_filter(scene, settings.width, settings.height, settings.fps, duration)
    run_command(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-vf",
            vf,
            "-t",
            _safe_float(duration),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            settings.preset,
            "-crf",
            str(settings.crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(settings.fps),
            "-movflags",
            "+faststart",
            str(cached),
        ],
        quiet=True,
    )
    return cached


def _concat_without_transition(scene_paths: list[Path], destination: Path) -> None:
    ffmpeg = require_binary("ffmpeg")
    list_file = destination.with_suffix(".concat.txt")
    with list_file.open("w", encoding="utf-8") as handle:
        for path in scene_paths:
            escaped = str(path.resolve()).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    try:
        run_command(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(destination),
            ],
            quiet=True,
        )
    finally:
        list_file.unlink(missing_ok=True)


def _concat_with_xfade(
    scene_paths: list[Path],
    scene_durations: list[float],
    destination: Path,
    settings: RenderSettings,
) -> None:
    if len(scene_paths) == 1:
        shutil.copy2(scene_paths[0], destination)
        return

    ffmpeg = require_binary("ffmpeg")
    filter_file = destination.with_suffix(".filter.txt")
    transition_duration = settings.transition_duration
    lines: list[str] = []
    cumulative = scene_durations[0]
    previous_label = "0:v"

    for index in range(1, len(scene_paths)):
        output_label = f"v{index}"
        lines.append(
            f"[{previous_label}][{index}:v]xfade=transition={settings.transition}:"
            f"duration={_safe_float(transition_duration)}:offset={_safe_float(cumulative)}"
            f"[{output_label}]"
        )
        previous_label = output_label
        cumulative += scene_durations[index]

    lines.append(f"[{previous_label}]format=yuv420p[outv]")
    filter_file.write_text(";\n".join(lines) + "\n", encoding="utf-8")

    command: list[str] = [ffmpeg, "-y"]
    for path in scene_paths:
        command.extend(["-i", str(path)])
    command.extend(
        [
            "-filter_complex_script",
            str(filter_file),
            "-map",
            "[outv]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            settings.preset,
            "-crf",
            str(settings.crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(settings.fps),
            "-t",
            _safe_float(sum(scene_durations)),
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    try:
        run_command(command, quiet=True)
    finally:
        filter_file.unlink(missing_ok=True)


def combine_video_and_audio(
    silent_video: Path,
    narration: Path,
    destination: Path,
    duration: float,
    settings: RenderSettings,
    music: Path | None = None,
) -> None:
    ffmpeg = require_binary("ffmpeg")
    destination.parent.mkdir(parents=True, exist_ok=True)

    if music and music.is_file():
        fade_out_start = max(0.0, duration - 2.0)
        filter_complex = (
            f"[1:a]volume={settings.narration_volume:.5f},atrim=0:{_safe_float(duration)},"
            f"asetpts=N/SR/TB[narr];"
            f"[2:a]volume={settings.music_volume:.5f},atrim=0:{_safe_float(duration)},"
            f"afade=t=in:st=0:d=1,afade=t=out:st={_safe_float(fade_out_start)}:d=2,"
            f"asetpts=N/SR/TB[music];"
            f"[narr][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(narration),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            _safe_float(duration),
            "-movflags",
            "+faststart",
            str(destination),
        ]
    else:
        if abs(settings.narration_volume - 1.0) > 1e-6:
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(narration),
                "-filter:a",
                f"volume={settings.narration_volume:.5f}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                _safe_float(duration),
                "-movflags",
                "+faststart",
                str(destination),
            ]
        else:
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(narration),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                _safe_float(duration),
                "-movflags",
                "+faststart",
                str(destination),
            ]
    run_command(command, quiet=True)


def build_video(
    storyboard: Storyboard,
    images_dir: Path,
    narration: Path,
    output: Path,
    settings: RenderSettings,
    music: Path | None = None,
) -> Path:
    settings = settings.normalized()
    scenes = storyboard.scenes[: settings.max_scenes] if settings.max_scenes else storyboard.scenes
    if not scenes:
        raise ValueError("No scenes selected for rendering.")

    timeline_start = scenes[0].start
    scene_durations = [scene.duration for scene in scenes]
    total_duration = sum(scene_durations)

    if settings.transition != "none" and settings.transition_duration > 0:
        shortest_scene = min(scene_durations)
        maximum_safe_transition = max(0.0, shortest_scene * 0.45)
        if settings.transition_duration > maximum_safe_transition:
            old_duration = settings.transition_duration
            settings.transition_duration = maximum_safe_transition
            print(
                f"⚠️  Transition shortened from {old_duration:.3f}s to "
                f"{settings.transition_duration:.3f}s because one scene is very short."
            )
        if settings.transition_duration < 0.03:
            settings.transition = "none"
            settings.transition_duration = 0.0

    # When a preview stops before the end, the narration is intentionally trimmed.
    audio_duration = probe_duration(narration)
    if timeline_start > 0.05:
        raise ValueError("The selected storyboard must start at 0s.")
    if not settings.max_scenes and abs(audio_duration - total_duration) > 0.3:
        raise ValueError(
            f"Narration is {audio_duration:.3f}s but selected storyboard is {total_duration:.3f}s. "
            "Run validation or alignment first."
        )

    workdir = Path(tempfile.mkdtemp(prefix="mythology_video_"))
    print(f"🧰 Work directory: {workdir}")
    try:
        rendered_paths: list[Path] = []
        use_xfade = settings.transition != "none" and settings.transition_duration > 0
        for index, scene in enumerate(scenes):
            extra = settings.transition_duration if use_xfade and index < len(scenes) - 1 else 0.0
            render_duration = scene.duration + extra
            rendered_paths.append(
                render_scene(scene, images_dir / scene.image, render_duration, settings)
            )

        silent_video = workdir / "silent_video.mp4"
        if use_xfade:
            _concat_with_xfade(rendered_paths, scene_durations, silent_video, settings)
        else:
            _concat_without_transition(rendered_paths, silent_video)

        output.parent.mkdir(parents=True, exist_ok=True)
        combine_video_and_audio(
            silent_video,
            narration,
            output,
            total_duration,
            settings,
            music,
        )
        print(f"✅ Video created: {output}")
        return output
    finally:
        if settings.keep_workdir:
            print(f"🧰 Kept work directory: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
