from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mythology_video.storyboard import load_storyboard, validate_storyboard


def test_duration_only_storyboard_becomes_contiguous(tmp_path: Path) -> None:
    path = tmp_path / "storyboard.json"
    path.write_text(
        json.dumps(
            [
                {"id": 1, "sentence": "A", "image": "a.jpg", "duration": 2.0},
                {"id": 2, "sentence": "B", "image": "b.jpg", "duration": 3.5},
            ]
        ),
        encoding="utf-8",
    )
    storyboard = load_storyboard(path)
    assert storyboard.scenes[0].start == 0.0
    assert storyboard.scenes[0].end == 2.0
    assert storyboard.scenes[1].start == 2.0
    assert storyboard.scenes[1].end == 5.5


def test_validation_detects_overlap_and_missing_image(tmp_path: Path) -> None:
    path = tmp_path / "storyboard.json"
    path.write_text(
        json.dumps(
            [
                {"id": 1, "sentence": "A", "image": "a.jpg", "start": 0, "end": 2},
                {"id": 2, "sentence": "B", "image": "b.jpg", "start": 1.5, "end": 3},
            ]
        ),
        encoding="utf-8",
    )
    storyboard = load_storyboard(path)
    issues = validate_storyboard(storyboard, tmp_path)
    codes = {issue.code for issue in issues}
    assert "missing_image" in codes
    assert "timeline_overlap" in codes
