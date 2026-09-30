"""
Runs the full daily pipeline: pick topic -> generate script -> TTS ->
fetch stock clips -> assemble video with captions -> upload to YouTube.

Triggered daily by .github/workflows/daily.yml

Commands:
  python main.py                 # one Short for this time of day
  python main.py post morning    # force the morning slot
  python main.py post 3          # all 3 Shorts in one run
  python main.py report          # write a channel progress report
  python main.py notify-test     # send a test phone push
"""

import os
import shutil
import sys

from config import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    POST_WINDOWS,
    TARGET_DURATION_SECONDS,
    VIDEOS_PER_DAY,
    WORKDIR,
    pick_topic_for_slot,
    slot_for_now,
)
from src.generate_script import generate_script, record_used_topic
from src.generate_audio import generate_audio
from src.fetch_visuals import fetch_clips
from src.assemble_video import assemble_video
from src.notify import notify_posted
from src.upload_youtube import upload_video
from src.youtube_auth import require_expected_channel

LENGTH_RETRIES = 2


def _write_script_and_audio(topic, audio_path, length_hint=""):
    print("Generating script...")
    script_data = generate_script(topic, length_hint=length_hint)
    print("Title:", script_data["title"])
    print("Script:", script_data["script"])
    print("Generating narration audio...")
    word_timings, duration = generate_audio(script_data["script"], audio_path)
    return script_data, word_timings, duration


def run_pipeline(slot: int = 0):
    print("Checking YouTube login...")
    require_expected_channel()

    if os.path.exists(WORKDIR):
        shutil.rmtree(WORKDIR)
    os.makedirs(WORKDIR)

    topic = pick_topic_for_slot(slot)
    window = POST_WINDOWS[slot % len(POST_WINDOWS)]["name"]
    print(f"Slot {slot + 1}/{VIDEOS_PER_DAY} ({window}) niche: {topic['niche']}")

    audio_path = os.path.join(WORKDIR, "narration.mp3")
    length_hint = ""
    script_data = None
    word_timings = None
    duration = 0.0
    last_good = None
    for attempt in range(LENGTH_RETRIES + 1):
        try:
            script_data, word_timings, duration = _write_script_and_audio(
                topic, audio_path, length_hint
            )
        except RuntimeError as exc:
            if last_good is None:
                raise
            print(f"Length rewrite failed ({exc}). Using previous draft.")
            script_data, word_timings, duration = last_good
            break
        last_good = (script_data, word_timings, duration)
        if MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
            break
        length_hint = (
            f"Previous narration was {duration:.0f} seconds. "
            f"That is not acceptable. Write a {TARGET_DURATION_SECONDS} second "
            f"read-aloud, about 125-140 spoken words, same fact."
        )
        print(
            f"Length retry {attempt + 1}/{LENGTH_RETRIES}: "
            f"{duration:.1f}s is outside {MIN_DURATION_SECONDS}-{MAX_DURATION_SECONDS}s"
        )
    else:
        if last_good is None:
            raise RuntimeError("No narration draft was produced.")
        script_data, word_timings, duration = last_good
        if not (MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS):
            raise RuntimeError(
                f"Narration is {duration:.1f}s, need {MIN_DURATION_SECONDS}-"
                f"{MAX_DURATION_SECONDS}s. Not uploading a short Short."
            )

    clips_dir = os.path.join(WORKDIR, "clips")
    print("Fetching stock clips...")
    clip_paths = fetch_clips(script_data["keywords"], clips_dir, clips_needed=5)
    if not clip_paths:
        raise RuntimeError("No stock clips found — check PEXELS_API_KEY / keywords.")

    video_path = os.path.join(WORKDIR, "final.mp4")
    print("Assembling video...")
    assemble_video(
        clip_paths,
        audio_path,
        word_timings,
        video_path,
        title=script_data["title"],
    )

    description = f"{script_data['script']}\n\n{topic['hashtags']}"
    print("Uploading to YouTube...")
    result = upload_video(
        video_path=video_path,
        title=script_data["title"],
        description=description,
        tags=script_data["keywords"],
    )
    record_used_topic(script_data.get("title") or script_data.get("topic_key") or "")
    notify_posted(
        title=script_data["title"],
        video_id=(result or {}).get("id") or "",
        duration=duration,
        window=window,
    )

    print("Done!")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "post"
    if command in ("report", "analytics"):
        from src.analytics import run_report

        run_report()
        return
    if command in ("notify-test", "test-notify"):
        ok = notify_posted(
            title="How Come? phone test",
            video_id="GVpLZROBLR0",
            duration=49,
            window="test",
        )
        raise SystemExit(0 if ok else 1)
    if command in ("post", "run"):
        requested = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("POST_SLOT", "auto")
        if str(requested).isdigit() and int(requested) > 1:
            count = min(VIDEOS_PER_DAY, int(requested))
            for slot in range(count):
                print(f"\n=== Posting video {slot + 1} of {count} ===")
                run_pipeline(slot)
            return
        slot = slot_for_now(None if requested in (None, "", "auto") else requested)
        print(f"\n=== Posting {POST_WINDOWS[slot]['name']} Short ===")
        run_pipeline(slot)
        return
    raise SystemExit(
        "Usage: python main.py [post [morning|afternoon|night|count]|report|notify-test]"
    )


if __name__ == "__main__":
    main()
