from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mythology_video.motion_editor import (
    MotionSegment,
    find_static_runs,
    load_segments,
    parse_scene_scores,
    save_segments,
)

SAMPLE_FFMPEG_OUTPUT = """frame:0    pts:0        pts_time:0
frame:1    pts:166      pts_time:0.166667
lavfi.scene_score=0.002000

frame:2    pts:333      pts_time:0.333333
lavfi.scene_score=0.001500

frame:3    pts:500      pts_time:0.5
lavfi.scene_score=0.450000

frame:4    pts:666      pts_time:0.666667
lavfi.scene_score=0.003000
"""


def test_parse_scene_scores_skips_frame_without_score() -> None:
    scores = parse_scene_scores(SAMPLE_FFMPEG_OUTPUT)
    # frame:0 has no scene_score line and must not be paired with frame:1's score.
    assert scores == [
        (0.166667, 0.002000),
        (0.333333, 0.001500),
        (0.5, 0.450000),
        (0.666667, 0.003000),
    ]


def test_find_static_runs_splits_on_high_score_and_drops_short_runs() -> None:
    scores = [(round(t * 0.1, 3), 0.001) for t in range(30)]  # 0.0..2.9s, all static
    scores += [(3.0, 0.5)]  # a cut
    scores += [(round(3.0 + t * 0.1, 3), 0.001) for t in range(1, 5)]  # 3.1..3.4s, too short

    runs = find_static_runs(scores, threshold=0.01, min_duration=1.0, trailing_time=3.4, edge_margin=0.0)

    assert len(runs) == 1
    start, end, mean_score = runs[0]
    assert start == 0.0
    assert end == 3.0
    assert mean_score < 0.01


def test_save_and_load_segments_round_trip(tmp_path: Path) -> None:
    segments = [
        MotionSegment(start=1.0, end=4.5, motion="zoom_out", zoom=1.15, focus_x=0.5, focus_y=0.4, score=0.002),
        MotionSegment(start=10.0, end=13.0, motion="pan_left", zoom=1.1),
    ]
    path = tmp_path / "segments.json"
    save_segments("input.mp4", segments, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["video"] == "input.mp4"
    assert len(payload["segments"]) == 2

    video, loaded = load_segments(path)
    assert video == "input.mp4"
    assert loaded[0].motion == "zoom_out"
    assert loaded[1].motion == "pan_left"
    assert loaded[0].end == 4.5
