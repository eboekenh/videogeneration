from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


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
