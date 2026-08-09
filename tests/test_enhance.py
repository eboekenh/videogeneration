from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mythology_video.enhance import build_enhance_filter_graph


def test_no_options_returns_null_filter() -> None:
    assert build_enhance_filter_graph(source_fps=24.0, target_fps=None) == "null"


def test_target_fps_below_source_is_ignored() -> None:
    graph = build_enhance_filter_graph(source_fps=30.0, target_fps=24.0)
    assert graph == "null"


def test_target_fps_above_source_adds_minterpolate() -> None:
    graph = build_enhance_filter_graph(source_fps=24.0, target_fps=60.0, interpolation="mci")
    assert "minterpolate=fps=60:mi_mode=mci" in graph
    assert "mc_mode=aobmc" in graph


def test_blend_mode_skips_motion_compensation_options() -> None:
    graph = build_enhance_filter_graph(source_fps=24.0, target_fps=60.0, interpolation="blend")
    assert "minterpolate=fps=60:mi_mode=blend" in graph
    assert "mc_mode" not in graph


def test_upscale_adds_lanczos_scale() -> None:
    graph = build_enhance_filter_graph(source_fps=24.0, target_fps=None, target_width=1920, target_height=1080)
    assert graph == "scale=1920:1080:flags=lanczos"


def test_denoise_and_sharpen_stack_in_order() -> None:
    graph = build_enhance_filter_graph(source_fps=24.0, target_fps=None, denoise=True, sharpen=True)
    assert graph.startswith("hqdn3d=")
    assert graph.endswith("unsharp=5:5:0.8:5:5:0.0")


def test_invalid_interpolation_mode_raises() -> None:
    with pytest.raises(ValueError):
        build_enhance_filter_graph(source_fps=24.0, target_fps=60.0, interpolation="bogus")
