from __future__ import annotations

from pathlib import Path
from typing import Callable

from .media import require_binary, run_command_with_progress
from .motion_editor import VideoInfo, probe_video_info

INTERPOLATION_MODES = {"mci", "blend"}


def _safe_num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_enhance_filter_graph(
    *,
    source_fps: float,
    target_fps: float | None,
    interpolation: str = "blend",
    target_width: int | None = None,
    target_height: int | None = None,
    denoise: bool = False,
    sharpen: bool = False,
) -> str:
    """Build the ffmpeg -vf graph for smoothing/upscaling a single video.

    `target_fps` only takes effect when it is higher than `source_fps` —
    this function adds motion interpolation to make a choppy render
    smoother, not to drop frames.
    """
    if interpolation not in INTERPOLATION_MODES:
        raise ValueError(f"Unsupported interpolation mode: {interpolation}. Use one of {sorted(INTERPOLATION_MODES)}.")

    stages: list[str] = []
    if denoise:
        stages.append("hqdn3d=4:3:6:4")
    if target_fps is not None and round(target_fps, 3) > round(source_fps, 3):
        stage = f"minterpolate=fps={_safe_num(target_fps)}:mi_mode={interpolation}"
        if interpolation == "mci":
            stage += ":mc_mode=aobmc:me_mode=bilat:vsbmc=1"
        stages.append(stage)
    if target_width and target_height:
        stages.append(f"scale={target_width}:{target_height}:flags=lanczos")
    if sharpen:
        stages.append("unsharp=5:5:0.8:5:5:0.0")
    return ",".join(stages) if stages else "null"


def enhance_video(
    video: str | Path,
    output: str | Path,
    *,
    target_fps: float | None = None,
    interpolation: str = "blend",
    upscale_factor: float = 1.0,
    denoise: bool = False,
    sharpen: bool = False,
    crf: int = 18,
    preset: str = "medium",
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """Smooth a choppy render (motion-compensated frame interpolation) and
    optionally upscale/denoise/sharpen it. Designed for renders exported at a
    low or uneven frame rate (e.g. from After Effects) that need to look
    smoother, not for real footage that is already at its intended fps.
    """
    video = Path(video)
    output = Path(output)
    if target_fps is not None and target_fps <= 0:
        raise ValueError("target_fps must be positive.")
    if upscale_factor <= 0:
        raise ValueError("upscale_factor must be positive.")

    info: VideoInfo = probe_video_info(video)

    target_width = target_height = None
    if upscale_factor != 1.0:
        target_width = int(round(info.width * upscale_factor / 2)) * 2
        target_height = int(round(info.height * upscale_factor / 2)) * 2

    filter_graph = build_enhance_filter_graph(
        source_fps=info.fps,
        target_fps=target_fps,
        interpolation=interpolation,
        target_width=target_width,
        target_height=target_height,
        denoise=denoise,
        sharpen=sharpen,
    )
    if filter_graph == "null":
        raise ValueError(
            "No enhancement selected. Choose at least one of: higher frame rate, upscale, denoise, sharpen."
        )

    ffmpeg = require_binary("ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg,
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(video),
        "-vf",
        filter_graph,
        "-map",
        "0:v:0",
    ]
    if info.has_audio:
        command.extend(["-map", "0:a:0", "-c:a", "copy"])
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
    run_command_with_progress(command, total_duration=info.duration, on_progress=on_progress)
    return output
