"""
Converts the script text to speech and captures word timings for karaoke captions.

Engine 1 (default): Kokoro, a free open-source voice that runs on the GitHub runner itself.
  No account, no key, and it does not depend on Microsoft.
Engine 2 (backup):  edge-tts, Microsoft's free online voices.

Returns (word_timings, spoken_duration_seconds). Each timing is
{"word": str, "start": seconds, "duration": seconds}, as before.

Settings (environment variables, all optional):
  TTS_ENGINE      kokoro (default) or edge
  KOKORO_VOICE    default af_heart. Others: af_bella, af_nicole, am_michael, am_fenrir, bf_emma
  KOKORO_SPEED    default 1.0 (0.9 = a bit slower)
"""

import asyncio
import os
import subprocess
import time

from config import TTS_VOICE

TTS_ENGINE = os.environ.get("TTS_ENGINE", "kokoro").strip().lower()
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart").strip() or "af_heart"
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0") or 1.0)
KOKORO_RATE = 24000

# edge-tts (backup)
TTS_VOICES = (TTS_VOICE, "en-US-ChristopherNeural", "en-GB-RyanNeural")
TTS_RATE = "-5%"
TTS_PITCH = "+0Hz"
TTS_ATTEMPTS = 5
MIN_AUDIO_BYTES = 4000
MIN_SPOKEN_SECONDS = 5.0


# --------------------------------------------------------------------------- Kokoro
def _merge_tokens(tokens, offset: float) -> list:
    """Kokoro gives sub-word tokens ("do" + "n't") and separate punctuation. Merge them into
    whole words so the captions show real words."""
    words, current = [], None
    glue = False  # the previous token had no space after it
    for tok in tokens:
        text = getattr(tok, "text", "") or ""
        start, end = getattr(tok, "start_ts", None), getattr(tok, "end_ts", None)
        has_letters = any(ch.isalnum() for ch in text)
        if current is not None and (glue or not has_letters):
            current["word"] += text
            if has_letters and end is not None:
                current["_end"] = offset + end
        elif has_letters and start is not None and end is not None:
            if current is not None:
                words.append(current)
            current = {"word": text, "start": offset + start, "_end": offset + end}
        glue = (getattr(tok, "whitespace", " ") or "") == ""
    if current is not None:
        words.append(current)
    return words


def _estimate_timings(text: str, duration: float) -> list:
    """Last resort when Kokoro gives no timestamps: spread the words over the audio by length."""
    words = text.split()
    if not words or duration <= 0:
        return []
    weights = [len(w) + 2 for w in words]
    total, t, out = float(sum(weights)), 0.0, []
    for w, wt in zip(words, weights):
        d = duration * wt / total
        out.append({"word": w, "start": t, "duration": d})
        t += d
    return out


def _kokoro_synthesize(text: str, out_mp3: str):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a")  # American English
    pieces, words, offset = [], [], 0.0
    for result in pipeline(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED):
        audio = result.audio
        if audio is None:
            continue
        samples = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        samples = samples.astype("float32").reshape(-1)
        words.extend(_merge_tokens(getattr(result, "tokens", None) or [], offset))
        pieces.append(samples)
        offset += len(samples) / KOKORO_RATE
    if not pieces:
        raise RuntimeError("Kokoro returned no audio")

    duration = offset
    wav = out_mp3 + ".wav"
    sf.write(wav, np.concatenate(pieces), KOKORO_RATE)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-codec:a", "libmp3lame", "-q:a", "3", out_mp3],
        check=True,
    )
    os.remove(wav)

    timings = []
    for i, w in enumerate(words):
        end = w["_end"]
        if i + 1 < len(words):  # no gap between words: karaoke highlight stays smooth
            end = max(end, min(words[i + 1]["start"], end + 0.35))
        timings.append({"word": w["word"], "start": w["start"], "duration": max(end - w["start"], 0.05)})
    if len(timings) < max(3, len(text.split()) // 2):
        print(f"Kokoro gave {len(timings)} word timings for {len(text.split())} words; estimating instead.")
        timings = _estimate_timings(text, duration)
    return timings, duration


# --------------------------------------------------------------------------- edge-tts (backup)
async def _edge_synthesize(text: str, out_mp3: str, voice: str):
    import edge_tts

    communicate = edge_tts.Communicate(
        text, voice, rate=TTS_RATE, pitch=TTS_PITCH, boundary="WordBoundary", connect_timeout=20
    )
    timings, audio_bytes = [], 0
    with open(out_mp3, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                timings.append({
                    "word": chunk["text"],
                    "start": chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000,
                })
    return timings, audio_bytes


def _edge_generate(text: str, out_mp3: str):
    last_error = "no attempt"
    for attempt in range(TTS_ATTEMPTS):
        voice = TTS_VOICES[attempt % len(TTS_VOICES)]
        if os.path.exists(out_mp3):
            os.remove(out_mp3)
        try:
            timings, audio_bytes = asyncio.run(_edge_synthesize(text, out_mp3, voice))
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"edge-tts attempt {attempt + 1}/{TTS_ATTEMPTS} ({voice}) failed: {last_error[:200]}")
            time.sleep(2 + attempt * 2)
            continue
        duration = timings[-1]["start"] + timings[-1]["duration"] if timings else 0.0
        if duration >= MIN_SPOKEN_SECONDS and audio_bytes >= MIN_AUDIO_BYTES and timings:
            return timings, duration
        last_error = f"{voice} returned {duration:.1f}s / {audio_bytes} bytes"
        time.sleep(2 + attempt * 2)
    raise RuntimeError(f"edge-tts produced no usable audio after {TTS_ATTEMPTS} tries: {last_error[:300]}")


# --------------------------------------------------------------------------- public
def generate_audio(text: str, out_mp3: str) -> tuple[list, float]:
    """Writes narration to out_mp3. Returns (word_timings, spoken_duration_seconds)."""
    order = ["edge"] if TTS_ENGINE == "edge" else ["kokoro", "edge"]
    errors = []
    for engine in order:
        try:
            if engine == "kokoro":
                print(f"TTS: Kokoro voice {KOKORO_VOICE}, speed {KOKORO_SPEED}")
                timings, duration = _kokoro_synthesize(text, out_mp3)
            else:
                print("TTS: edge-tts")
                timings, duration = _edge_generate(text, out_mp3)
        except Exception as exc:
            errors.append(f"{engine}: {type(exc).__name__}: {str(exc)[:200]}")
            print(f"TTS engine {engine} failed: {errors[-1]}")
            continue
        if duration < MIN_SPOKEN_SECONDS or not timings:
            errors.append(f"{engine}: audio too short ({duration:.1f}s)")
            continue
        print(f"Narration duration: {duration:.1f}s, {len(timings)} caption words ({engine})")
        return timings, duration
    raise RuntimeError("No TTS engine produced usable audio. " + " | ".join(errors))


if __name__ == "__main__":
    import json

    sample = ("Ducks keep their feet warm in freezing water. Their legs use a clever heat trick, "
              "and they don't feel the cold. Subscribe to this channel for a new answer every day.")
    t, d = generate_audio(sample, "test.mp3")
    print("duration", d)
    print(json.dumps(t[:8], indent=2))
