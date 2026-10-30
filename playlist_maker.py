import os
import re
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


# =====================================
# CONFIGURATION
# =====================================

API_URL = os.getenv("OTT_API_URL", "").strip()

OUTPUT_FILE = "BDFreechannel/Freeott.m3u8"
BACKUP_FILE = OUTPUT_FILE + ".backup"

PLAYLIST_NAME = "BD FreeOTT"

REQUEST_TIMEOUT = 30


# =====================================
# PROMO CHANNEL
# =====================================

PROMO_CHANNEL = {
    "name": "IPTV LINKS",
    "logo": "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg",
    "url": "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"
}


# =====================================
# CLEAN TEXT
# =====================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def clean_attribute(value):
    value = clean_text(value)
    value = value.replace('"', "")
    value = value.replace("\n", " ")
    value = value.replace("\r", " ")

    return value


# =====================================
# FETCH API
# =====================================

def fetch_api():

    if not API_URL:
        raise RuntimeError(
            "OTT_API_URL GitHub Secret পাওয়া যায়নি।"
        )

    headers = {
        "Accept": "application/json",
        "User-Agent": "BD-FreeOTT-Playlist-Generator/1.0"
    }

    print("Connecting to API...")

    try:
        response = requests.get(
            API_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as error:
        raise RuntimeError(
            f"API connection failed: {error}"
        )

    if response.status_code == 403:
        raise RuntimeError(
            "API returned 403 Forbidden. "
            "API provider must authorize this request."
        )

    if response.status_code == 401:
        raise RuntimeError(
            "API returned 401 Unauthorized."
        )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Invalid JSON response.")

    if not isinstance(data, dict):
        raise RuntimeError("Invalid API response format.")

    if not isinstance(data.get("channels"), list):
        raise RuntimeError("API channels list not found.")

    print("API channels:", len(data["channels"]))

    return data


# =====================================
# CHECK DIRECT M3U8 URL
# =====================================

def is_direct_m3u8(url):

    try:
        parsed = urlparse(url)

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and bool(
                re.search(
                    r"\.m3u8$",
                    parsed.path,
                    re.IGNORECASE
                )
            )
        )

    except Exception:
        return False


# =====================================
# PARSE CHANNELS
# =====================================

def parse_channels(data):

    results = []
    seen_urls = set()

    for item in data["channels"]:

        if not isinstance(item, dict):
            continue

        channel_id = clean_attribute(item.get("id"))
        name = clean_attribute(item.get("name"))
        category = clean_attribute(item.get("cat"))
        logo = clean_attribute(item.get("img"))
        channel_type = clean_text(item.get("type")).lower()
        stream_url = clean_text(item.get("url"))

        # Free channels only
        if channel_type != "free":
            continue

        if not name or not stream_url:
            continue

        # Direct M3U8 only
        if not is_direct_m3u8(stream_url):
            continue

        # Duplicate removal
        if stream_url in seen_urls:
            continue

        seen_urls.add(stream_url)

        results.append({
            "id": channel_id,
            "name": name,
            "category": category or "Free OTT",
            "logo": logo,
            "url": stream_url
        })

    print("Direct M3U8 channels:", len(results))

    return results


# =====================================
# GENERATE PLAYLIST
# =====================================

def generate_playlist(channels):

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{PLAYLIST_NAME}",
        f"# Generated: {now}",
        f"# Total API channels: {len(channels)}",
        "# Auto Refresh: GitHub Actions",
        ""
    ]

    # Promo channel first
    lines.append(
        '#EXTINF:-1 tvg-id="" '
        'tvg-name="IPTV LINKS" '
        f'tvg-logo="{PROMO_CHANNEL["logo"]}" '
        'group-title="PROTV KBCT",IPTV LINKS'
    )

    lines.append(PROMO_CHANNEL["url"])
    lines.append("")

    # API channels
    for channel in channels:

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="{channel["id"]}" '
            f'tvg-name="{channel["name"]}" '
            f'tvg-logo="{channel["logo"]}" '
            f'group-title="{channel["category"]}",'
            f'{channel["name"]}'
        )

        lines.append(channel["url"])
        lines.append("")

    return "\n".join(lines)


# =====================================
# SAVE PLAYLIST SAFELY
# =====================================

def save_playlist(content):

    output_dir = os.path.dirname(OUTPUT_FILE)

    os.makedirs(output_dir, exist_ok=True)

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            suffix=".m3u8",
            dir=output_dir,
            delete=False
        ) as file:

            file.write(content)
            temp_path = file.name

        # Backup existing playlist
        if os.path.exists(OUTPUT_FILE):
            shutil.copy2(
                OUTPUT_FILE,
                BACKUP_FILE
            )

        # Replace playlist after successful generation
        os.replace(
            temp_path,
            OUTPUT_FILE
        )

        print("Playlist saved:", OUTPUT_FILE)

    except Exception:

        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

        raise


# =====================================
# MAIN
# =====================================

def main():

    print("=" * 40)
    print("BD FREEOTT GENERATOR")
    print("=" * 40)

    try:

        data = fetch_api()

        channels = parse_channels(data)

        if not channels:
            raise RuntimeError(
                "No direct free M3U8 channels found. "
                "Existing playlist preserved."
            )

        playlist = generate_playlist(channels)

        save_playlist(playlist)

        print("=" * 40)
        print("GENERATION SUCCESSFUL")
        print("API channels:", len(channels))
        print("Promo channel: 1")
        print("Total entries:", len(channels) + 1)
        print("=" * 40)

    except Exception as error:

        print("GENERATION FAILED:", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
