from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .media import CommandError, require_binary, run_command
from .renderer import motion_filter_graph
from .storyboard import ALLOWED_MOTIONS

MOTION_ROTATION = ["zoom_out", "pan_left", "pan_right", "zoom_in"]

# Real footage (unlike a still image) has nothing to reveal beyond the frame
# it already captured, so "static" is not an applicable motion here.
APPLICABLE_MOTIONS = ALLOWED_MOTIONS - {"static"}

_FRAME_BLOCK_RE = re.compile(r"frame:\d+.*?(?=frame:\d+|\Z)", re.DOTALL)
_PTS_TIME_RE = re.compile(r"pts_time:(?P<time>[0-9.]+)")
_SCENE_SCORE_RE = re.compile(r"lavfi\.scene_score=(?P<score>[0-9.]+)")


@dataclass(slots=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


@dataclass(slots=True)
class MotionSegment:
    start: float
    end: float
    motion: str = "zoom_out"
    zoom: float = 1.12
    focus_x: float = 0.5
    focus_y: float = 0.5
    score: float | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def probe_video_info(path: str | Path) -> VideoInfo:
    ffprobe = require_binary("ffprobe")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandError(f"ffprobe failed for {path}: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    stream = payload["streams"][0]
    num, _, den = stream["r_frame_rate"].partition("/")
    fps = float(num) / float(den or 1)

    has_audio_completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    has_audio = False
    if has_audio_completed.returncode == 0:
        audio_payload = json.loads(has_audio_completed.stdout)
        has_audio = bool(audio_payload.get("streams"))

    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
        duration=float(payload["format"]["duration"]),
        has_audio=has_audio,
    )


def _extract_scene_scores(video: Path, sample_fps: float) -> list[tuple[float, float]]:
    """Run ffmpeg's scene-change scorer and return (time, score) pairs.

    A low score means the frame barely changed from the previous sampled
    frame, i.e. the camera/content was close to static at that moment.
    """
    ffmpeg = require_binary("ffmpeg")
    completed = subprocess.run(
        [
            ffmpeg,
            "-i",
            str(video),
            "-vf",
            f"fps={_safe_num(sample_fps)},select='gte(scene,0)',metadata=print:file=-",
            "-f",
            "null",
            "-",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandError(f"ffmpeg scene detection failed for {video}: {completed.stderr.strip()}")
    return parse_scene_scores(completed.stdout)


def parse_scene_scores(raw_output: str) -> list[tuple[float, float]]:
    """Parse ffmpeg `metadata=print` output into (pts_time, scene_score) pairs.

    Frames are processed block by block (each block starts at its own
    "frame:" header) so a frame missing a scene_score line — the very first
    evaluated frame always lacks one, since there is no prior frame to diff
    against — is simply skipped instead of being paired with the wrong
    frame's score.
    """
    results: list[tuple[float, float]] = []
    for block in _FRAME_BLOCK_RE.finditer(raw_output):
        text = block.group(0)
        time_match = _PTS_TIME_RE.search(text)
        score_match = _SCENE_SCORE_RE.search(text)
        if time_match and score_match:
            results.append((float(time_match.group("time")), float(score_match.group("score"))))
    return results


def find_static_runs(
    scores: list[tuple[float, float]],
    *,
    threshold: float,
    min_duration: float,
    trailing_time: float,
    edge_margin: float = 0.15,
) -> list[tuple[float, float, float]]:
    """Turn a (time, score) series into (start, end, mean_score) static runs.

    A run is a maximal stretch of samples that stay below `threshold`. Runs
    shorter than `min_duration` are dropped. Each kept run is trimmed by
    `edge_margin` on both sides to avoid the cut/settle frame right at a
    shot boundary, where the scene score is naturally elevated.
    """
    runs: list[tuple[float, float, float]] = []
    if not scores:
        return runs

    run_start: float | None = None
    run_scores: list[float] = []
    previous_time = 0.0

    def close_run(end_time: float) -> None:
        nonlocal run_start, run_scores
        if run_start is None:
            return
        start = run_start + edge_margin
        end = end_time - edge_margin
        if end - start >= min_duration:
            runs.append((start, end, sum(run_scores) / len(run_scores)))
        run_start = None
        run_scores = []

    for time_value, score in scores:
        if score < threshold:
            if run_start is None:
                run_start = previous_time
            run_scores.append(score)
        else:
            close_run(time_value)
        previous_time = time_value

    close_run(trailing_time)
    return runs


def detect_static_segments(
    video: str | Path,
    *,
    threshold: float = 0.012,
    min_duration: float = 2.5,
    sample_fps: float = 6.0,
    motions: list[str] | None = None,
    zoom: float = 1.12,
) -> list[MotionSegment]:
    video = Path(video)
    info = probe_video_info(video)
    scores = _extract_scene_scores(video, sample_fps)
    runs = find_static_runs(
        scores,
        threshold=threshold,
        min_duration=min_duration,
        trailing_time=info.duration,
    )

    rotation = motions or MOTION_ROTATION
    segments: list[MotionSegment] = []
    for index, (start, end, mean_score) in enumerate(runs):
        segments.append(
            MotionSegment(
                start=round(start, 3),
                end=round(end, 3),
                motion=rotation[index % len(rotation)],
                zoom=zoom,
                score=round(mean_score, 6),
            )
        )
    return segments


def segments_to_dict(video: str | Path, segments: list[MotionSegment]) -> dict[str, Any]:
    return {
        "video": str(video),
        "segments": [
            {
                "start": segment.start,
                "end": segment.end,
                "motion": segment.motion,
                "zoom": segment.zoom,
                "focus_x": segment.focus_x,
                "focus_y": segment.focus_y,
                **({"score": segment.score} if segment.score is not None else {}),
            }
            for segment in segments
        ],
    }


def save_segments(video: str | Path, segments: list[MotionSegment], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(segments_to_dict(video, segments), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_segments(path: str | Path) -> tuple[str | None, list[MotionSegment]]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    raw_segments = raw.get("segments", []) if isinstance(raw, dict) else raw
    segments = [
        MotionSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            motion=str(item.get("motion", "zoom_out")).strip().lower(),
            zoom=float(item.get("zoom", 1.12)),
            focus_x=float(item.get("focus_x", 0.5)),
            focus_y=float(item.get("focus_y", 0.5)),
            score=item.get("score"),
        )
        for item in raw_segments
    ]
    video = raw.get("video") if isinstance(raw, dict) else None
    return video, segments


def _validate_segments(segments: list[MotionSegment], duration: float) -> None:
    previous_end = 0.0
    for segment in sorted(segments, key=lambda item: item.start):
        if segment.motion not in APPLICABLE_MOTIONS:
            raise ValueError(
                f"Unsupported motion '{segment.motion}'. Allowed: {', '.join(sorted(APPLICABLE_MOTIONS))}."
            )
        if segment.start < 0 or segment.end > duration + 0.05:
            raise ValueError(f"Segment {segment.start:.3f}-{segment.end:.3f}s is outside the video duration.")
        if segment.duration <= 0:
            raise ValueError(f"Segment {segment.start:.3f}-{segment.end:.3f}s has non-positive duration.")
        if segment.start < previous_end - 0.01:
            raise ValueError(f"Segments overlap around {segment.start:.3f}s.")
        previous_end = segment.end


def _safe_num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def apply_motion_segments(
    video: str | Path,
    segments: list[MotionSegment],
    output: str | Path,
    *,
    crf: int = 18,
    preset: str = "medium",
) -> Path:
    video = Path(video)
    output = Path(output)
    if not segments:
        raise ValueError("No segments to apply.")

    info = probe_video_info(video)
    ordered = sorted(segments, key=lambda item: item.start)
    _validate_segments(ordered, info.duration)

    parts: list[str] = []
    labels: list[str] = []
    cursor = 0.0
    label_index = 0

    def add_passthrough(start: float, end: float) -> None:
        nonlocal label_index
        if end - start <= 0.001:
            return
        label = f"seg{label_index}"
        label_index += 1
        parts.append(
            f"[0:v]trim=start={_safe_num(start)}:end={_safe_num(end)},setpts=PTS-STARTPTS[{label}]"
        )
        labels.append(label)

    def add_motion(segment: MotionSegment) -> None:
        nonlocal label_index
        label = f"seg{label_index}"
        label_index += 1
        graph = motion_filter_graph(
            segment.motion,
            segment.focus_x,
            segment.focus_y,
            segment.zoom,
            info.width,
            info.height,
            round(info.fps, 3),
            segment.duration,
        )
        parts.append(
            f"[0:v]trim=start={_safe_num(segment.start)}:end={_safe_num(segment.end)},"
            f"setpts=PTS-STARTPTS,{graph}[{label}]"
        )
        labels.append(label)

    for segment in ordered:
        add_passthrough(cursor, segment.start)
        add_motion(segment)
        cursor = segment.end
    add_passthrough(cursor, info.duration)

    parts.append(f"{''.join(f'[{label}]' for label in labels)}concat=n={len(labels)}:v=1:a=0[outv]")
    filter_complex = ";\n".join(parts)

    ffmpeg = require_binary("ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_file = output.with_suffix(".filter.txt")
    filter_file.write_text(filter_complex + "\n", encoding="utf-8")

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-filter_complex_script",
        str(filter_file),
        "-map",
        "[outv]",
    ]
    if info.has_audio:
        command.extend(["-map", "0:a", "-c:a", "copy"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    try:
        run_command(command, quiet=True)
    finally:
        filter_file.unlink(missing_ok=True)
    return output
