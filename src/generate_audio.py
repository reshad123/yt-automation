"""
Converts the script text to speech using edge-tts (free, no API key,
uses Microsoft Edge's online neural voices).

Also captures word-boundary timing so we can render karaoke-style
captions synced to the audio.

Install: pip install edge-tts
"""

import asyncio
import os
import time

import edge_tts

from config import TTS_VOICE

# GitHub runners sometimes get an empty Microsoft TTS stream. Retry the
# same script on backup male voices instead of asking Groq to rewrite it.
TTS_VOICES = (TTS_VOICE, "en-US-ChristopherNeural", "en-GB-RyanNeural")
TTS_ATTEMPTS = 5
MIN_AUDIO_BYTES = 4000
MIN_SPOKEN_SECONDS = 5.0
TTS_RATE = "-5%"
TTS_PITCH = "-2Hz"


async def _synthesize(text: str, out_mp3: str, voice: str):
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
        boundary="WordBoundary",
        connect_timeout=20,
    )
    word_timings = []
    audio_bytes = 0

    with open(out_mp3, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                word_timings.append(
                    {
                        "word": chunk["text"],
                        "start": chunk["offset"] / 10_000_000,  # 100ns -> s
                        "duration": chunk["duration"] / 10_000_000,
                    }
                )
    return word_timings, audio_bytes


def _duration_from_timings(timings: list) -> float:
    if not timings:
        return 0.0
    last = timings[-1]
    return last["start"] + last["duration"]


def generate_audio(text: str, out_mp3: str) -> tuple[list, float]:
    """
    Writes narration audio to out_mp3.
    Returns (word_timings, spoken_duration_seconds).
    Raises if Microsoft TTS keeps returning empty audio.
    """
    last_error = "no attempt"
    for attempt in range(TTS_ATTEMPTS):
        voice = TTS_VOICES[attempt % len(TTS_VOICES)]
        if os.path.exists(out_mp3):
            os.remove(out_mp3)
        try:
            timings, audio_bytes = asyncio.run(_synthesize(text, out_mp3, voice))
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"TTS attempt {attempt + 1}/{TTS_ATTEMPTS} "
                f"({voice}) failed: {last_error}"
            )
            time.sleep(2 + attempt * 2)
            continue

        duration = _duration_from_timings(timings)
        size = os.path.getsize(out_mp3) if os.path.exists(out_mp3) else 0
        print(
            f"TTS {voice}: {duration:.1f}s, {size} bytes, "
            f"{len(timings)} word timings"
        )
        if (
            duration >= MIN_SPOKEN_SECONDS
            and audio_bytes >= MIN_AUDIO_BYTES
            and timings
        ):
            print(f"Narration duration: {duration:.1f}s")
            return timings, duration

        last_error = f"{voice} returned {duration:.1f}s / {audio_bytes} bytes"
        print(
            f"TTS attempt {attempt + 1}/{TTS_ATTEMPTS} empty or too short: "
            f"{last_error}"
        )
        time.sleep(2 + attempt * 2)

    raise RuntimeError(
        f"TTS produced no usable audio after {TTS_ATTEMPTS} tries: {last_error}"
    )


if __name__ == "__main__":
    import json

    sample = "This is a quick test of the free text to speech engine."
    timings, duration = generate_audio(sample, "test.mp3")
    print("duration", duration)
    print(json.dumps(timings, indent=2))
