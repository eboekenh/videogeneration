from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ALLOWED_MOTIONS = {
    "static",
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
}


@dataclass(slots=True)
class Scene:
    id: str
    sentence: str
    image: str
    start: float
    end: float
    motion: str = "zoom_in"
    focus_x: float = 0.5
    focus_y: float = 0.5
    zoom: float = 1.08
    notes: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(slots=True)
class Storyboard:
    title: str
    scenes: list[Scene]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.scenes[-1].end if self.scenes else 0.0


@dataclass(slots=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    scene_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "scene_id": self.scene_id,
        }


def _number(value: Any, field_name: str, scene_id: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Scene {scene_id}: '{field_name}' must be a number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"Scene {scene_id}: '{field_name}' must be finite.")
    return result


def _normalize_scene(raw: dict[str, Any], index: int) -> Scene:
    scene_id = str(raw.get("id", raw.get("scene", index + 1)))
    sentence = str(raw.get("sentence", raw.get("text", ""))).strip()
    image = str(raw.get("image", raw.get("image_file", ""))).strip()

    if "start" in raw and "end" in raw:
        start = _number(raw["start"], "start", scene_id)
        end = _number(raw["end"], "end", scene_id)
    elif "duration" in raw:
        # The caller later converts relative durations to a contiguous timeline.
        start = float("nan")
        end = _number(raw["duration"], "duration", scene_id)
    else:
        raise ValueError(
            f"Scene {scene_id}: provide either 'start' and 'end', or 'duration'."
        )

    motion = str(raw.get("motion", "zoom_in")).strip().lower()
    focus_x = _number(raw.get("focus_x", 0.5), "focus_x", scene_id)
    focus_y = _number(raw.get("focus_y", 0.5), "focus_y", scene_id)
    zoom = _number(raw.get("zoom", 1.08), "zoom", scene_id)

    return Scene(
        id=scene_id,
        sentence=sentence,
        image=image,
        start=start,
        end=end,
        motion=motion,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        notes=str(raw.get("notes", raw.get("reason", ""))).strip(),
    )


def load_storyboard(path: str | Path) -> Storyboard:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if isinstance(raw, list):
        title = source.stem
        raw_scenes = raw
        metadata: dict[str, Any] = {}
    elif isinstance(raw, dict):
        title = str(raw.get("title", source.stem))
        raw_scenes = raw.get("scenes")
        metadata = {k: v for k, v in raw.items() if k not in {"title", "scenes"}}
    else:
        raise ValueError("Storyboard must be a JSON array or an object with a 'scenes' array.")

    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Storyboard contains no scenes.")

    scenes = [_normalize_scene(item, idx) for idx, item in enumerate(raw_scenes)]

    # Convert duration-only scenes into absolute, contiguous timestamps.
    cursor = 0.0
    for scene in scenes:
        if math.isnan(scene.start):
            duration = scene.end
            scene.start = cursor
            scene.end = cursor + duration
        cursor = scene.end

    return Storyboard(title=title, scenes=scenes, metadata=metadata)


def storyboard_to_dict(storyboard: Storyboard) -> dict[str, Any]:
    result: dict[str, Any] = {"title": storyboard.title, **storyboard.metadata, "scenes": []}
    for scene in storyboard.scenes:
        result["scenes"].append(
            {
                "id": scene.id,
                "sentence": scene.sentence,
                "image": scene.image,
                "start": round(scene.start, 3),
                "end": round(scene.end, 3),
                "motion": scene.motion,
                "focus_x": scene.focus_x,
                "focus_y": scene.focus_y,
                "zoom": scene.zoom,
                **({"notes": scene.notes} if scene.notes else {}),
            }
        )
    return result


def save_storyboard(storyboard: Storyboard, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(storyboard_to_dict(storyboard), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_storyboard(
    storyboard: Storyboard,
    images_dir: str | Path,
    audio_duration: float | None = None,
    timing_tolerance: float = 0.08,
) -> list[ValidationIssue]:
    images_root = Path(images_dir)
    issues: list[ValidationIssue] = []
    seen_images: dict[str, list[str]] = {}

    if storyboard.scenes and abs(storyboard.scenes[0].start) > timing_tolerance:
        issues.append(
            ValidationIssue(
                "warning",
                "timeline_not_zero",
                f"Timeline starts at {storyboard.scenes[0].start:.3f}s instead of 0s.",
                storyboard.scenes[0].id,
            )
        )

    previous: Scene | None = None
    for scene in storyboard.scenes:
        if not scene.sentence:
            issues.append(ValidationIssue("warning", "empty_sentence", "Sentence is empty.", scene.id))
        if not scene.image:
            issues.append(ValidationIssue("error", "empty_image", "Image filename is empty.", scene.id))
        else:
            image_path = images_root / scene.image
            if not image_path.is_file():
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_image",
                        f"Image not found: {image_path}",
                        scene.id,
                    )
                )
            seen_images.setdefault(scene.image.casefold(), []).append(scene.id)

        if scene.start < 0:
            issues.append(ValidationIssue("error", "negative_start", "Start time is negative.", scene.id))
        if scene.duration <= 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_duration",
                    f"Scene duration must be positive; got {scene.duration:.3f}s.",
                    scene.id,
                )
            )
        if scene.duration < 0.35:
            issues.append(
                ValidationIssue(
                    "warning",
                    "very_short_scene",
                    f"Scene is only {scene.duration:.3f}s; the cut may feel abrupt.",
                    scene.id,
                )
            )
        if scene.motion not in ALLOWED_MOTIONS:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_motion",
                    f"Unknown motion '{scene.motion}'. Allowed: {', '.join(sorted(ALLOWED_MOTIONS))}.",
                    scene.id,
                )
            )
        if not 0 <= scene.focus_x <= 1 or not 0 <= scene.focus_y <= 1:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_focus",
                    "focus_x and focus_y must be between 0 and 1.",
                    scene.id,
                )
            )
        if not 1.0 <= scene.zoom <= 1.25:
            issues.append(
                ValidationIssue(
                    "warning",
                    "unusual_zoom",
                    f"Zoom {scene.zoom:.3f} is outside the recommended 1.00–1.25 range.",
                    scene.id,
                )
            )

        if previous is not None:
            delta = scene.start - previous.end
            if delta > timing_tolerance:
                issues.append(
                    ValidationIssue(
                        "error",
                        "timeline_gap",
                        f"Gap of {delta:.3f}s after scene {previous.id}.",
                        scene.id,
                    )
                )
            elif delta < -timing_tolerance:
                issues.append(
                    ValidationIssue(
                        "error",
                        "timeline_overlap",
                        f"Overlap of {-delta:.3f}s with scene {previous.id}.",
                        scene.id,
                    )
                )
        previous = scene

    for image_name, scene_ids in seen_images.items():
        if len(scene_ids) > 1:
            issues.append(
                ValidationIssue(
                    "warning",
                    "reused_image",
                    f"Image '{image_name}' is reused in scenes {', '.join(scene_ids)}.",
                )
            )

    if audio_duration is not None and storyboard.scenes:
        difference = storyboard.duration - audio_duration
        if abs(difference) > 0.25:
            issues.append(
                ValidationIssue(
                    "error",
                    "audio_duration_mismatch",
                    f"Storyboard ends at {storyboard.duration:.3f}s, audio is {audio_duration:.3f}s "
                    f"(difference {difference:+.3f}s).",
                )
            )
        elif abs(difference) > timing_tolerance:
            issues.append(
                ValidationIssue(
                    "warning",
                    "audio_duration_small_mismatch",
                    f"Storyboard/audio differ by {difference:+.3f}s.",
                )
            )

    return issues


def summarize_issues(issues: Iterable[ValidationIssue]) -> tuple[int, int]:
    errors = sum(issue.level == "error" for issue in issues)
    warnings = sum(issue.level == "warning" for issue in issues)
    return errors, warnings


def natural_scene_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]
