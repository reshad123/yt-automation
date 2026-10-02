"""
Central config for the daily Shorts automation.
Edit TOPICS to add/remove niches. The bot rotates through them
so you get variety instead of the same niche every day.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# SilentVision traction: rare animals, human-body oddities, and space wow
# facts outperform motivation and finance by a wide margin.
TOPICS = [
    {
        "niche": "animal_facts",
        "prompt_hint": (
            "one surprising, verifiable fact about a common, well-known animal "
            "(dog, cat, elephant, shark, lion, bird, octopus, bear, horse, etc). "
            "The animal should be instantly recognizable, but the fact must be "
            "genuinely surprising -- a hidden ability, survival trick, or "
            "biological quirk most people don't know."
        ),
        "visual_keywords": [
            "dog closeup",
            "cat closeup",
            "wildlife nature",
            "ocean animal",
            "bird flying",
        ],
        "hashtags": "#animalfacts #curiosity #education #facts #shorts",
    },
     {
        "niche": "pets_and_farm",
        "prompt_hint": (
            "one surprising, verifiable fact about a common pet or farm "
            "animal (dog, cat, horse, cow, chicken, rabbit, etc). The animal "
            "should be instantly recognizable, but the fact must be "
            "genuinely surprising."
        ),
        "visual_keywords": [
            "dog closeup",
            "cat closeup",
            "horse farm",
            "farm animals",
            "rabbit closeup",
        ],
        "hashtags": "#petfacts #curiosity #education #facts #shorts",
    },
]


VIDEOS_PER_DAY = 3

# Uploads and reports must target this channel. The Aug 30 re-auth
# logged into Facelessclipper instead; refuse any other mine=true channel.
SILENTVISION_CHANNEL_ID = "UC6JlX3lps3k-ygVvNwULyKA"
SILENTVISION_CHANNEL_TITLE = "How Come?"

# One Short per window so uploads are spaced, not dumped at once.
# Times are UTC. Nigeria is UTC+1, so these land at 8am / 3pm / 9pm.
POST_WINDOWS = (
    {"name": "morning", "utc_hour": 7},
    {"name": "afternoon", "utc_hour": 14},
    {"name": "night", "utc_hour": 20},
)
SLOT_NAMES = {window["name"]: index for index, window in enumerate(POST_WINDOWS)}


def slot_for_now(name: str | None = None) -> int:
    """
    Map a window name or the current UTC hour to slot 0, 1, or 2.
    Morning < 11:00 UTC, afternoon < 17:00 UTC, otherwise night.
    """
    if name:
        key = name.strip().lower()
        if key.isdigit():
            return max(0, min(VIDEOS_PER_DAY - 1, int(key)))
        if key in SLOT_NAMES:
            return SLOT_NAMES[key]

    from datetime import datetime, timezone

    hour = datetime.now(timezone.utc).hour
    if hour < 11:
        return 0
    if hour < 17:
        return 1
    return 2


def pick_topic_for_slot(slot: int = 0):
    """
    Each daily window posts one niche. Slot 0, 1, 2 rotate through
    TOPICS, shifted by day-of-year so the order changes.
    """
    import datetime

    day_index = datetime.date.today().timetuple().tm_yday
    return TOPICS[(day_index + int(slot)) % len(TOPICS)]


def pick_topic_for_today():
    return pick_topic_for_slot(slot_for_now())


# ---- Video settings ----
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # vertical, for Shorts
TARGET_DURATION_SECONDS = 45
MIN_DURATION_SECONDS = 40
# 55s is TTS jitter only. GuyNeural can land 1-3s past 52 on a 130-word read.
MAX_DURATION_SECONDS = 55
# Spoken at the end of every Short. Captions follow the voice.
END_CTA = "Follow this channel if you enjoy this kind of stuff."
FONT_SIZE = 60
CAPTION_COLOR = "white"
CAPTION_HIGHLIGHT_COLOR = "#FFD700"

# TTS voice (edge-tts). Full list: `edge-tts --list-voices`
TTS_VOICE = "en-US-GuyNeural"

# Output paths
WORKDIR = "workdir"
