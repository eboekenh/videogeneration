from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .media import probe_duration
from .storyboard import Scene, Storyboard


@dataclass(slots=True)
class TranscriptWord:
    text: str
    normalized: str
    start: float
    end: float


def normalize_text(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("’", "'").replace("`", "'")
    return re.findall(r"[\wçğıöşüâîû]+", text, flags=re.UNICODE)


def _best_span(
    target_tokens: list[str],
    words: list[TranscriptWord],
    cursor: int,
) -> tuple[int, int, float]:
    if not target_tokens:
        return cursor, min(cursor + 1, len(words)), 0.0

    target_len = len(target_tokens)
    start_limit = min(len(words), cursor + max(25, target_len * 3))
    min_len = max(1, int(target_len * 0.65))
    max_len = max(min_len, int(target_len * 1.45) + 3)
    best = (cursor, min(len(words), cursor + target_len), -1.0)
    target_string = " ".join(target_tokens)

    for start in range(cursor, start_limit):
        for length in range(min_len, max_len + 1):
            end = start + length
            if end > len(words):
                break
            candidate = " ".join(word.normalized for word in words[start:end])
            score = SequenceMatcher(None, target_string, candidate, autojunk=False).ratio()
            # Mildly prefer earlier spans when scores are almost equal.
            score -= (start - cursor) * 0.001
            if score > best[2]:
                best = (start, end, score)
    return best


def transcribe_words(
    audio_path: Path,
    model_size: str = "small",
    language: str = "tr",
    device: str = "cpu",
    compute_type: str = "int8",
) -> list[TranscriptWord]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -r requirements-whisper.txt"
        ) from exc

    print(f"🗣️  Loading Whisper model '{model_size}'...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    words: list[TranscriptWord] = []
    for segment in segments:
        for item in segment.words or []:
            tokens = normalize_text(item.word)
            if not tokens or item.start is None or item.end is None:
                continue
            words.append(
                TranscriptWord(
                    text=item.word.strip(),
                    normalized=tokens[0],
                    start=float(item.start),
                    end=float(item.end),
                )
            )
    if not words:
        raise RuntimeError("Whisper produced no word timestamps.")
    return words


def align_storyboard(
    storyboard: Storyboard,
    audio_path: Path,
    *,
    model_size: str = "small",
    language: str = "tr",
    device: str = "cpu",
    compute_type: str = "int8",
) -> tuple[Storyboard, list[dict[str, Any]]]:
    words = transcribe_words(audio_path, model_size, language, device, compute_type)
    audio_duration = probe_duration(audio_path)
    cursor = 0
    matches: list[tuple[int, int, float]] = []
    diagnostics: list[dict[str, Any]] = []

    for scene in storyboard.scenes:
        target = normalize_text(scene.sentence)
        start, end, score = _best_span(target, words, cursor)
        if end <= start:
            end = min(len(words), start + 1)
        matches.append((start, end, score))
        diagnostics.append(
            {
                "scene_id": scene.id,
                "score": round(score, 3),
                "matched_text": " ".join(word.text for word in words[start:end]),
                "status": "ok" if score >= 0.58 else "review",
            }
        )
        cursor = max(cursor + 1, end)

    starts = [words[start].start for start, _, _ in matches]
    if starts and starts[0] < 0.8:
        starts[0] = 0.0

    aligned_scenes: list[Scene] = []
    for index, (scene, match) in enumerate(zip(storyboard.scenes, matches)):
        start = starts[index]
        if index + 1 < len(starts):
            end = max(start + 0.08, starts[index + 1])
        else:
            end = audio_duration
        aligned_scenes.append(
            Scene(
                id=scene.id,
                sentence=scene.sentence,
                image=scene.image,
                start=start,
                end=end,
                motion=scene.motion,
                focus_x=scene.focus_x,
                focus_y=scene.focus_y,
                zoom=scene.zoom,
                notes=scene.notes,
            )
        )

    return Storyboard(storyboard.title, aligned_scenes, storyboard.metadata), diagnostics
