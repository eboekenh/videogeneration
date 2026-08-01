# Mythology Video Automation

A sentence-synchronised video builder for narrated mythology videos. It is inspired by the linked Gemini YouTube automation project, but replaces autonomous lesson generation, gTTS and random stock-image selection with a curated workflow:

> storyboard + existing narration + selected images → validated, animated, synchronised video

Turkish setup instructions: **[README_TR.md](README_TR.md)**

## Core commands

```bash
python validate_storyboard.py --storyboard project/storyboard.json --audio project/audio.mp3 --images project/images

python build_video.py --storyboard project/storyboard.json --audio project/audio.mp3 --images project/images --output output/video.mp4 --preview

python build_video.py --storyboard project/storyboard.json --audio project/audio.mp3 --images project/images --music project/music/background.mp3 --output output/video_1080p.mp4
```

## Features

- Exact start/end timing per sentence
- FFmpeg-based Ken Burns motion without random camera shake
- Optional crossfades and low-volume background music
- Missing-image, timeline-gap, overlap and reused-image validation
- Cached scene renders
- 540p preview and 1080p final modes
- Optional Faster Whisper alignment for untimed storyboards
- Manual GitHub Actions workflow

## Requirements

- Python 3.10–3.12 recommended
- FFmpeg / ffprobe available on PATH
- `pip install -r requirements.txt`

## Attribution

Inspired by `ChaitanyaEswarRajeshJakki/gemini-youtube-automation`, described by its author as MIT licensed. See `NOTICE` and `LICENSE`.
