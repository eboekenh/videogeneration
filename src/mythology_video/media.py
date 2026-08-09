from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence


class CommandError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise FileNotFoundError(
            f"Required program '{name}' was not found. Install FFmpeg and ensure it is on PATH."
        )
    return resolved


def run_command(command: Sequence[str], *, quiet: bool = False) -> None:
    if not quiet:
        print("$", " ".join(str(part) for part in command))
    completed = subprocess.run(
        list(map(str, command)),
        text=True,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CommandError(f"Command failed with exit code {completed.returncode}:\n{detail}")


def run_command_with_progress(
    command: Sequence[str],
    *,
    total_duration: float,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Run an ffmpeg command (expected to include `-progress pipe:1`),
    reporting fractional completion (0..1) via `on_progress` as it parses
    the `out_time_ms=` lines ffmpeg writes to stdout."""
    process = subprocess.Popen(
        list(map(str, command)),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        output_lines.append(raw_line)
        line = raw_line.strip()
        if on_progress is not None and total_duration > 0 and line.startswith("out_time_ms="):
            try:
                out_time_ms = int(line.split("=", 1)[1])
            except ValueError:
                continue
            on_progress(min(out_time_ms / 1_000_000 / total_duration, 1.0))
    returncode = process.wait()
    if returncode != 0:
        detail = "".join(output_lines[-40:]).strip()
        raise CommandError(f"Command failed with exit code {returncode}:\n{detail}")
    if on_progress is not None:
        on_progress(1.0)


def probe_duration(path: str | Path) -> float:
    ffprobe = require_binary("ffprobe")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
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
    return float(payload["format"]["duration"])
