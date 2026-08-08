from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .alignment import align_storyboard
from .media import probe_duration
from .motion_editor import apply_motion_segments, detect_static_segments, load_segments, save_segments
from .renderer import RenderSettings, build_video
from .storyboard import (
    load_storyboard,
    save_storyboard,
    summarize_issues,
    validate_storyboard,
)


def _add_common_storyboard_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--images", required=True, type=Path, help="Directory containing storyboard images")


def validate_command(args: argparse.Namespace) -> int:
    storyboard = load_storyboard(args.storyboard)
    duration = probe_duration(args.audio)
    issues = validate_storyboard(storyboard, args.images, duration)
    errors, warnings = summarize_issues(issues)
    for issue in issues:
        icon = "❌" if issue.level == "error" else "⚠️"
        scene = f" [scene {issue.scene_id}]" if issue.scene_id else ""
        print(f"{icon} {issue.code}{scene}: {issue.message}")
    print(f"\nValidation: {errors} error(s), {warnings} warning(s)")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "storyboard": str(args.storyboard),
                    "audio_duration": duration,
                    "errors": errors,
                    "warnings": warnings,
                    "issues": [issue.as_dict() for issue in issues],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Report written to {args.report}")
    return 1 if errors else 0


def build_command(args: argparse.Namespace) -> int:
    storyboard = load_storyboard(args.storyboard)
    audio_duration = probe_duration(args.audio)
    issues = validate_storyboard(storyboard, args.images, None if args.max_scenes else audio_duration)
    errors, warnings = summarize_issues(issues)
    allowed_error_codes = {"missing_image", "empty_image"} if args.allow_missing else set()
    blocking_issues = [
        issue for issue in issues
        if issue.level == "error" and issue.code not in allowed_error_codes
    ]
    if blocking_issues:
        for issue in blocking_issues:
            print(f"❌ {issue.code}: {issue.message}")
        print("Build stopped. Fix the storyboard timing/format errors first.")
        return 1
    allowed_missing_count = sum(
        issue.level == "error" and issue.code in allowed_error_codes for issue in issues
    )
    if allowed_missing_count:
        print(f"⚠️  {allowed_missing_count} missing-image error(s) will use black placeholders.")
    if warnings:
        print(f"⚠️  Continuing with {warnings} validation warning(s).")

    settings = RenderSettings(
        width=args.width,
        height=args.height,
        fps=args.fps,
        transition=args.transition,
        transition_duration=args.transition_duration,
        crf=args.crf,
        preset=args.preset,
        music_volume=args.music_volume,
        narration_volume=args.narration_volume,
        allow_missing=args.allow_missing,
        preview=args.preview,
        max_scenes=args.max_scenes,
        cache_dir=args.cache_dir,
        keep_workdir=args.keep_workdir,
    )
    music = args.music if args.music and args.music.is_file() else None
    build_video(storyboard, args.images, args.audio, args.output, settings, music)
    return 0


def align_command(args: argparse.Namespace) -> int:
    storyboard = load_storyboard(args.storyboard)
    aligned, diagnostics = align_storyboard(
        storyboard,
        args.audio,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
    )
    save_storyboard(aligned, args.output)
    diagnostics_path = args.diagnostics or args.output.with_suffix(".alignment-report.json")
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    review_count = sum(item["status"] == "review" for item in diagnostics)
    print(f"✅ Aligned storyboard written to {args.output}")
    print(f"🧾 Alignment report written to {diagnostics_path}")
    print(f"Scenes requiring manual review: {review_count}/{len(diagnostics)}")
    return 0


def detect_motion_command(args: argparse.Namespace) -> int:
    segments = detect_static_segments(
        args.video,
        threshold=args.threshold,
        min_duration=args.min_duration,
        sample_fps=args.sample_fps,
        motions=args.motions.split(",") if args.motions else None,
        zoom=args.zoom,
    )
    save_segments(args.video, segments, args.output)
    if not segments:
        print("No static segments found above --min-duration. Try lowering --threshold or --min-duration.")
    else:
        print(f"Found {len(segments)} static segment(s):")
        for segment in segments:
            print(f"  {segment.start:7.2f}s - {segment.end:7.2f}s  ({segment.duration:.2f}s)  -> {segment.motion}")
    print(f"Segments written to {args.output}. Review/edit motion, zoom and focus before running 'apply-motion'.")
    return 0


def apply_motion_command(args: argparse.Namespace) -> int:
    video_hint, segments = load_segments(args.segments)
    video = args.video or (Path(video_hint) if video_hint else None)
    if video is None:
        print("❌ No --video given and the segments file has no 'video' field.", file=sys.stderr)
        return 1
    if not segments:
        print("❌ No segments to apply.", file=sys.stderr)
        return 1
    apply_motion_segments(video, segments, args.output, crf=args.crf, preset=args.preset)
    print(f"✅ Video created: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mythology-video",
        description="Build sentence-synchronised mythology videos from a storyboard, images and narration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate timestamps and image files")
    _add_common_storyboard_args(validate_parser)
    validate_parser.add_argument("--report", type=Path)
    validate_parser.set_defaults(func=validate_command)

    build_parser_ = subparsers.add_parser("build", help="Render a video")
    _add_common_storyboard_args(build_parser_)
    build_parser_.add_argument("--output", required=True, type=Path)
    build_parser_.add_argument("--music", type=Path)
    build_parser_.add_argument("--width", type=int, default=1920)
    build_parser_.add_argument("--height", type=int, default=1080)
    build_parser_.add_argument("--fps", type=int, default=30)
    build_parser_.add_argument(
        "--transition",
        default="fade",
        choices=["none", "fade", "fadeblack", "fadewhite", "smoothleft", "smoothright"],
    )
    build_parser_.add_argument("--transition-duration", type=float, default=0.35)
    build_parser_.add_argument("--crf", type=int, default=18)
    build_parser_.add_argument("--preset", default="medium")
    build_parser_.add_argument("--music-volume", type=float, default=0.08)
    build_parser_.add_argument("--narration-volume", type=float, default=1.0)
    build_parser_.add_argument("--allow-missing", action="store_true")
    build_parser_.add_argument("--preview", action="store_true", help="Render at 960x540, 24 fps")
    build_parser_.add_argument("--max-scenes", type=int)
    build_parser_.add_argument("--cache-dir", type=Path, default=Path(".cache/scenes"))
    build_parser_.add_argument("--keep-workdir", action="store_true")
    build_parser_.set_defaults(func=build_command)

    align_parser = subparsers.add_parser("align", help="Create timestamps with faster-whisper")
    align_parser.add_argument("--storyboard", required=True, type=Path)
    align_parser.add_argument("--audio", required=True, type=Path)
    align_parser.add_argument("--output", required=True, type=Path)
    align_parser.add_argument("--diagnostics", type=Path)
    align_parser.add_argument("--model", default="small")
    align_parser.add_argument("--language", default="tr")
    align_parser.add_argument("--device", default="cpu")
    align_parser.add_argument("--compute-type", default="int8")
    align_parser.set_defaults(func=align_command)

    detect_parser = subparsers.add_parser(
        "detect-motion",
        help="Scan an existing video for static (low-motion) segments and propose zoom/pan effects",
    )
    detect_parser.add_argument("--video", required=True, type=Path)
    detect_parser.add_argument("--output", required=True, type=Path, help="Where to write the segments JSON")
    detect_parser.add_argument("--threshold", type=float, default=0.012, help="Scene-change score below which a frame counts as static")
    detect_parser.add_argument("--min-duration", type=float, default=2.5, help="Minimum static run length worth animating, in seconds")
    detect_parser.add_argument("--sample-fps", type=float, default=6.0, help="Frame sampling rate used for motion detection")
    detect_parser.add_argument("--zoom", type=float, default=1.12)
    detect_parser.add_argument("--motions", help="Comma-separated motion rotation, e.g. zoom_out,pan_left,pan_right")
    detect_parser.set_defaults(func=detect_motion_command)

    apply_parser = subparsers.add_parser(
        "apply-motion",
        help="Render zoom/pan effects onto the segments listed in a segments JSON, leaving the rest of the video untouched",
    )
    apply_parser.add_argument("--segments", required=True, type=Path)
    apply_parser.add_argument("--video", type=Path, help="Overrides the 'video' field stored in --segments")
    apply_parser.add_argument("--output", required=True, type=Path)
    apply_parser.add_argument("--crf", type=int, default=18)
    apply_parser.add_argument("--preset", default="medium")
    apply_parser.set_defaults(func=apply_motion_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
