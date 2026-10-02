"""
Stitches downloaded stock clips into one vertical video, lays the TTS
narration on top, and burns in word-synced captions.

Uses MoviePy (free, local, no API). Requires ffmpeg installed on the runner
(the GitHub Actions workflow installs it).
"""

from pathlib import Path

from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    concatenate_videoclips,
)

from config import VIDEO_WIDTH, VIDEO_HEIGHT, FONT_SIZE, CAPTION_COLOR


TITLE_SECONDS = 2.6
# MoviePy 2 uses Pillow, which needs a real .ttf path, not an ImageMagick name.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/Arialbd.ttf",
)


def _caption_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    return "DejaVu-Sans-Bold"


CAPTION_FONT = _caption_font()


def _build_background(clip_paths: list, target_duration: float):
    """Concatenate/loop clips, cropped+resized to fill the vertical frame."""
    clips = []
    total = 0.0
    i = 0
    while total < target_duration:
        path = clip_paths[i % len(clip_paths)]
        c = VideoFileClip(path)

        # cover-crop to vertical aspect ratio
        target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
        cur_ratio = c.w / c.h
        if cur_ratio > target_ratio:
            new_w = int(c.h * target_ratio)
            c = c.cropped(x_center=c.w / 2, width=new_w)
        else:
            new_h = int(c.w / target_ratio)
            c = c.cropped(y_center=c.h / 2, height=new_h)
        c = c.resized((VIDEO_WIDTH, VIDEO_HEIGHT))

        # use at most 6s of each clip to keep variety
        seg_duration = min(c.duration, 6)
        c = c.subclipped(0, seg_duration)

        clips.append(c)
        total += seg_duration
        i += 1

    bg = concatenate_videoclips(clips, method="compose")
    return bg.subclipped(0, target_duration)


def _build_caption_clips(word_timings: list, video_duration: float):
    """
    Groups words into short phrases (~4 words) and creates a TextClip
    for each, timed to appear while those words are spoken.
    """
    caption_clips = []
    group_size = 4
    groups = [
        word_timings[i:i + group_size]
        for i in range(0, len(word_timings), group_size)
    ]

    for group in groups:
        if not group:
            continue
        text = " ".join(w["word"] for w in group).strip()
        if not text:
            continue
        start = group[0]["start"]
        end = group[-1]["start"] + group[-1]["duration"]
        end = min(end, video_duration)
        if end <= start:
            continue

        txt_clip = (
            TextClip(
                text=text,
                font_size=FONT_SIZE,
                color="black",
                font=CAPTION_FONT,
                stroke_color="white",
                stroke_width=3,
                method="caption",
                size=(int(VIDEO_WIDTH * 0.75), None),
            )
            .with_position(("center", int(VIDEO_HEIGHT * 0.85)))
            .with_start(start)
            .with_duration(end - start)
        )
        caption_clips.append(txt_clip)

    return caption_clips


def _title_card(title: str, hold: float):
    text = (title or "").strip()
    if not text:
        return None
    return (
        TextClip(
            text=text,
            font_size=46,
            color="black",
            font=CAPTION_FONT,
            stroke_color="white",
            stroke_width=3,
            method="caption",
            size=(int(VIDEO_WIDTH * 0.9), None),
        )
        .with_position(("center", 260))
        .with_start(0)
        .with_duration(min(hold, TITLE_SECONDS))
    )


def assemble_video(
    clip_paths: list,
    audio_path: str,
    word_timings: list,
    out_path: str,
    title: str = "",
):
    audio = AudioFileClip(audio_path)
    duration = audio.duration
    print(f"Assembling {duration:.1f}s video with {CAPTION_FONT}")

    background = _build_background(clip_paths, duration)
    layers = [background]
    title_clip = _title_card(title, duration)
    if title_clip is not None:
        layers.append(title_clip)
    layers.extend(_build_caption_clips(word_timings, duration))

    final = CompositeVideoClip(layers, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_audio(audio)
    final = final.with_duration(duration)

    final.write_videofile(
        out_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="medium",
    )
    return out_path
