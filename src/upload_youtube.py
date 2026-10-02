"""
Uploads the finished video to YouTube via the free YouTube Data API v3.

One-time setup (do this locally, not in CI):
1. Go to https://console.cloud.google.com -> create a project ->
   enable "YouTube Data API v3".
2. Create OAuth Client ID credentials (type: Desktop App). Download
   client_secret.json.
3. Run `python src/get_refresh_token.py` once on your own machine to
   log in with your YouTube account and print a refresh token.
4. Store CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN as GitHub secrets.

Daily quota is 10,000 units (free). Each upload costs ~1600 units,
so this comfortably supports one video/day.
"""

import os
import json
import urllib.request
import urllib.error

from src.youtube_auth import get_access_token

UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)


def upload_video(video_path: str, title: str, description: str, tags: list):
    access_token = get_access_token()

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs; change if desired
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    # Step 1: initiate resumable upload session
    init_req = urllib.request.Request(
        UPLOAD_URL,
        data=json.dumps(metadata).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(init_req, timeout=30) as resp:
            upload_session_url = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube upload init failed ({exc.code}): {body}") from exc

    # Step 2: upload the actual video bytes
    file_size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        video_data = f.read()

    upload_req = urllib.request.Request(
        upload_session_url,
        data=video_data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/*",
            "Content-Length": str(file_size),
        },
        method="PUT",
    )
    with urllib.request.urlopen(upload_req, timeout=600) as resp:
        result = json.loads(resp.read().decode())

    print("Uploaded:", result.get("id"))
    return result
