#!/usr/bin/env python3
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "example" / "images"
AUDIO = ROOT / "example" / "demo_audio.wav"
MUSIC = ROOT / "example" / "demo_music.wav"


def make_image(path: Path, title: str, motif: str) -> None:
    image = Image.new("RGB", (1920, 1080), (24, 29, 42))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=54)
    small = ImageFont.load_default(size=30)
    draw.ellipse((160, 120, 1760, 1720), outline=(210, 185, 120), width=16)
    draw.text((120, 90), title, font=font, fill=(245, 239, 220))
    draw.text((120, 960), motif, font=small, fill=(210, 185, 120))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=94)


def make_wave(path: Path, duration: float, frequency: float, volume: float) -> None:
    sample_rate = 44100
    frames = int(duration * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for index in range(frames):
            envelope = min(1.0, index / (sample_rate * 0.2), (frames - index) / (sample_rate * 0.2))
            sample = int(32767 * volume * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            handle.writeframesraw(struct.pack("<hh", sample, sample))


def main() -> None:
    make_image(IMAGES / "001_odysseus.jpg", "ODYSSEUS", "Scene 1 — portrait placeholder")
    make_image(IMAGES / "002_trojan_horse.jpg", "TROJAN HORSE", "Scene 2 — Troy placeholder")
    make_image(IMAGES / "003_sea.jpg", "THE LONG VOYAGE", "Scene 3 — sea placeholder")
    make_wave(AUDIO, 11.0, 220.0, 0.12)
    make_wave(MUSIC, 4.0, 110.0, 0.05)
    print(f"Created demo assets under {ROOT / 'example'}")


if __name__ == "__main__":
    main()
