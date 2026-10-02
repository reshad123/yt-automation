"""
Generates a short video script using Groq's free-tier LLM API
(OpenAI-compatible endpoint, no cost, generous free rate limits).

Get a free key at https://console.groq.com -> API Keys.
Set it as the GROQ_API_KEY environment variable / GitHub secret.
"""

import os
import json
import urllib.error
import urllib.request
from pathlib import Path

from config import END_CTA, TARGET_DURATION_SECONDS

USED_TOPICS_PATH = Path(__file__).resolve().parent.parent / "reports" / "used_topics.json"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq shut down llama-3.3-70b-versatile and llama-3.1-8b-instant on 2026-08-16.
GROQ_MODELS = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
)
# Counted after the follow CTA is attached. ~2.7 words/sec on GuyNeural
# lands 122-140 words near 45 seconds.
MIN_SCRIPT_WORDS = 122
MAX_SCRIPT_WORDS = 148
SCRIPT_ATTEMPTS = 6


def _with_cta(script: str) -> str:
    """Make sure the spoken follow line is at the end, once."""
    text = (script or "").strip()
    lowered = text.lower()
    if "follow this channel" in lowered or "subscribe" in lowered:
        return text
    if text and text[-1] not in ".!?":
        text += "."
    return f"{text} {END_CTA}".strip()


def record_used_topic(topic_key: str) -> None:
    """Remember a fact only after the Short is long enough to upload."""
    key = (topic_key or "").strip().lower()
    if not key:
        return
    used = []
    if USED_TOPICS_PATH.exists():
        try:
            used = json.loads(USED_TOPICS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            used = []
    if key in [str(item).lower() for item in used]:
        return
    used.append(key)
    USED_TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USED_TOPICS_PATH.write_text(json.dumps(used, indent=2), encoding="utf-8")


def generate_script(topic: dict, length_hint: str = "") -> dict:
    """
    Returns a dict: {"title": ..., "script": ..., "keywords": [...]}
    'script' is the exact narration text (what the TTS voice will read).
    """
    api_key = os.environ["GROQ_API_KEY"]
    used = []
    if USED_TOPICS_PATH.exists():
        try:
            used = json.loads(USED_TOPICS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            used = []

    system_prompt = (
        "You write YouTube Shorts for How Come?, a curiosity channel. "
        "The videos that get traction are specific rare-animal secrets, "
        "weird human-body facts, and concrete space wow facts. "
        "Do not write motivation, finance, self-help, or generic trivia. "
        "Structure the narration in this order: "
        "1) HOOK: first sentence, 8-12 words, a stop-the-scroll claim. "
        "Open with a contradiction, a hidden mechanism, or a fact that "
        "sounds impossible. Never start with Did you know, Imagine, "
        "What if, Hey, or Welcome. "
        "2) PAYOFF: one widely reported scientific fact with a concrete "
        "image people can picture. "
        "3) TWIST: the weirder detail that makes the fact land. "
        "4) CLOSE: one short line that rewards watching to the end. "
        "Do not ask people to follow, subscribe, like, or comment. "
        "A follow line is added after you write. "
        f"Spoken length must land near {TARGET_DURATION_SECONDS} seconds: "
        "write 115-135 words, punchy, out loud, no filler. "
        "Only use a widely reported scientific fact. Do not invent numbers, "
        "percentages, or fake mechanisms. If you are not sure, pick a simpler fact. "
        "No stage directions, no emojis in the script. "
        "Every title must start with the exact words 'How Come' followed by "
        "a question, e.g.: "
        "'How Come Crocodiles Can Survive Without Eating for a Year?', "
        "'How Come You Never See Baby Pigeons?', "
        "'How Come a Teaspoon of a Neutron Star Weighs 4 Billion Tons?', "
        "'How Come the Moon Has a Permanent Dark Side?', "
        "'How Come the Mantis Shrimp Sees Colors We Cannot Even Imagine?'. "
        "Title must be under 50 characters, no hashtags in the title. "
        "keywords must directly match the exact subject named in the title — if "
        "the title is about a nose, the first keyword must be 'nose closeup', not "
        "'face' or a generic body part. Use the literal noun from the script's "
        "main subject as the first keyword, then 1-2 broader fallback terms "
        "(e.g. 'human body macro', 'skin closeup') in case the exact term has no "
        "stock footage. Never substitute a different body part or animal than "
        "the one actually discussed. "
        "Output ONLY valid JSON, no markdown fences. "
        "JSON schema: "
        '{"title": "<catchy title>", '
        '"script": "<narration text>", '
        '"keywords": ["<3-5 visual search keywords>"], '
        '"topic_key": "<short lowercase phrase naming the exact fact>"}'
    )

    avoid = "; ".join(used[:40]) if used else "none yet"
    user_prompt = (
        f"Write {topic['prompt_hint']}\n"
        f"Make the hook the strongest line in the script. "
        f"Target about {TARGET_DURATION_SECONDS} seconds spoken. "
        f"Write enough for a {TARGET_DURATION_SECONDS} second read-aloud: "
        f"{MIN_SCRIPT_WORDS - 12}-{MAX_SCRIPT_WORDS - 12} words before the follow line. "
        f"Do not reuse any of these already-posted facts or animals: {avoid}. "
        f"If a fact about this general topic has already been used, pick a "
        f"completely different animal, not just a different phrasing of the same fact."
    )
    if length_hint:
        user_prompt += f"\n{length_hint}"

    last_error = None
    data = None
    best = None
    best_distance = None
    target_words = (MIN_SCRIPT_WORDS + MAX_SCRIPT_WORDS) // 2
    used_lower = [str(u).lower() for u in used]

    def _score_candidate(candidate, model):
        nonlocal last_error, data, best, best_distance
        candidate["script"] = _with_cta(candidate.get("script") or "")
        script = candidate["script"]
        word_count = len(script.split())
        print(f"Groq model used: {model} ({word_count} words with CTA)")
        if not script or not candidate.get("title"):
            last_error = f"{model} returned empty title or script"
            print(last_error)
            return False

        title_lower = candidate["title"].strip().lower()
        topic_key_lower = (candidate.get("topic_key") or "").strip().lower()
        if title_lower in used_lower or (
            topic_key_lower and topic_key_lower in used_lower
        ):
            last_error = f"{model} repeated an already-used topic: {candidate['title']}"
            print(last_error)
            return False

        distance = abs(word_count - target_words)
        if best is None or distance < best_distance:
            best = candidate
            best_distance = distance
        if word_count < MIN_SCRIPT_WORDS or word_count > MAX_SCRIPT_WORDS:
            last_error = (
                f"{model} wrote {word_count} words, "
                f"need {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS}"
            )
            print(last_error)
            return False
        data = candidate
        return True

    def _chat(model, messages, force_json):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            GROQ_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "yt-automation/1.0",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    for attempt in range(SCRIPT_ATTEMPTS):
        model = GROQ_MODELS[attempt % len(GROQ_MODELS)]
        extra = ""
        if attempt > 0:
            extra = (
                f" Previous draft was the wrong length or a repeated topic. "
                f"Rewrite it to {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS} spoken words "
                f"including a natural ending, on a genuinely different animal or "
                f"fact than before. Expand the payoff and twist with concrete "
                f"detail. Do not pad with filler."
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + extra},
        ]
        try:
            result = _chat(model, messages, force_json=True)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            last_error = f"{exc.code} {exc.reason}: {body}"
            print(f"Groq model {model} failed: {last_error}")
            if "json_validate_failed" not in body:
                continue
            try:
                print(f"Retrying {model} without forced JSON mode")
                result = _chat(model, messages, force_json=False)
            except urllib.error.HTTPError as retry_exc:
                retry_body = retry_exc.read().decode("utf-8", errors="replace")[:400]
                last_error = f"{retry_exc.code} {retry_exc.reason}: {retry_body}"
                print(f"Groq model {model} failed: {last_error}")
                continue

        content = (result["choices"][0]["message"]["content"] or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        try:
            candidate = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON from {model}: {exc}"
            print(last_error)
            continue

        if _score_candidate(candidate, model):
            break

    if data is None and best is not None:
        print("Using closest draft after word-count retries")
        data = best

    if data is None:
        raise RuntimeError(
            f"Groq script generation failed (no {MIN_SCRIPT_WORDS}-"
            f"{MAX_SCRIPT_WORDS} word draft): {last_error}"
        )

    print("CTA:", END_CTA)

    if not data.get("keywords"):
        data["keywords"] = topic["visual_keywords"]

    return data


if __name__ == "__main__":
    from config import pick_topic_for_today

    t = pick_topic_for_today()
    out = generate_script(t)
    print(json.dumps(out, indent=2))
