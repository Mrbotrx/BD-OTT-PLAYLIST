import os
import re
import json
import time
import requests

from datetime import datetime, timezone, timedelta
from collections import defaultdict
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "kb_go_playlist.m3u8")
STATE_FILE = os.path.join(BASE_DIR, "state", "last_update.txt")

BANGLADESH_TZ = timezone(timedelta(hours=6))

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

RAIL_API = os.environ.get("AKASH_RAIL_API")
DETAIL_API = os.environ.get("AKASH_DETAIL_API_TEMPLATE")

if not RAIL_API or not DETAIL_API:
    raise RuntimeError("GitHub Secrets API settings are missing.")

HEADERS = {
    "User-Agent": "AKASH-OTT-Playlist-Generator/1.0",
    "Accept": "application/json"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_json(url):
    response = SESSION.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


def find_list(data):
    """Find channel objects inside common API response structures."""

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "items", "channels", "content", "results"):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                result = find_list(value)
                if result:
                    return result

    return []


def get_value(obj, keys, default=None):
    if not isinstance(obj, dict):
        return default

    for key in keys:
        value = obj.get(key)

        if value is not None and value != "":
            return value

    return default


def channel_id(channel):
    return get_value(
        channel,
        ["channelId", "channel_id", "id"]
    )


def channel_name(channel):
    return str(get_value(
        channel,
        ["channelName", "name", "title", "displayName"],
        "Unknown Channel"
    ))


def channel_logo(channel):
    return get_value(
        channel,
        ["logo", "logoUrl", "image", "imageUrl", "thumbnail"],
        ""
    )


def get_category(channel):
    category = get_value(
        channel,
        ["genre", "category", "genreName", "categoryName"],
        "Other"
    )

    if isinstance(category, dict):
        category = get_value(
            category,
            ["name", "title", "genreName"],
            "Other"
        )

    if isinstance(category, list):
        names = []

        for item in category:
            if isinstance(item, dict):
                names.append(str(get_value(item, ["name", "title"], "Other")))
            else:
                names.append(str(item))

        return names[0] if names else "Other"

    return str(category or "Other")


def is_promo(name):
    name = name.lower()

    for keyword in CONFIG["promo_keywords"]:
        if keyword.lower() in name:
            return True

    return False


def find_streams(data):
    """Extract M3U8 URLs recursively."""

    streams = set()

    if isinstance(data, dict):
        for value in data.values():
            streams.update(find_streams(value))

    elif isinstance(data, list):
        for item in data:
            streams.update(find_streams(item))

    elif isinstance(data, str):
        value = data.strip()

        if re.search(r"\.m3u8(?:[?#].*)?$", value, re.IGNORECASE):
            if value.startswith(("http://", "https://")):
                streams.add(value)

    return sorted(streams)


def check_stream(url):
    """Check that the URL responds and contains an HLS playlist."""

    try:
        response = SESSION.get(
            url,
            headers={"Range": "bytes=0-4095"},
            timeout=15,
            stream=True
        )

        if response.status_code not in (200, 206):
            response.close()
            return False

        content = next(response.iter_content(4096), b"")
        response.close()

        return b"#EXTM3U" in content

    except requests.RequestException:
        return False


def fetch_channels():
    data = get_json(RAIL_API)

    total = data.get("totalCount", 0) if isinstance(data, dict) else 0
    channels = find_list(data)

    print(f"API totalCount: {total}")
    print(f"Channels returned: {len(channels)}")

    if total and len(channels) < min(total, CONFIG["max_channels"]):
        print("WARNING: API returned fewer channels than totalCount.")

    return channels[:CONFIG["max_channels"]]


def fetch_channel_detail(cid):
    url = DETAIL_API.replace("{channel_id}", str(cid))
    return get_json(url)


def build_playlist():
    channels = fetch_channels()

    categories = defaultdict(list)
    online_channels = set()

    checked = 0

    for channel in channels:
        cid = channel_id(channel)
        name = channel_name(channel)

        if not cid:
            continue

        if is_promo(name):
            print("Skipped promo channel")
            continue

        checked += 1

        try:
            detail = fetch_channel_detail(cid)
            streams = find_streams(detail)

            working_streams = [
                stream for stream in streams
                if check_stream(stream)
            ]

            if not working_streams:
                print(f"Offline: {name}")
                continue

            category = get_category(channel)
            logo = channel_logo(channel) or CONFIG["logo_default"]

            for stream in working_streams:
                entry = {
                    "name": name,
                    "logo": logo,
                    "category": category,
                    "url": stream
                }

                categories[category].append(entry)

            online_channels.add(name)
            print(f"Working: {name} ({len(working_streams)} streams)")

        except Exception as error:
            # Do not print API URLs or channel IDs.
            print(f"Channel processing failed: {name} ({type(error).__name__})")

    now = datetime.now(BANGLADESH_TZ).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "#EXTM3U",
        f"# PLAYLIST NAME : {CONFIG['playlist_name']}",
        f"# DEV : {CONFIG['developer']}",
        f"# PANEL : {CONFIG['panel']}",
        f"# GITHUB : {CONFIG['github']}",
        f"# TELEGRAM : {CONFIG['telegram']}",
        f"# CHANNELS : {len(online_channels)} WORKING CHANNELS",
        f"# TIME : {now} (BDT)",
        "# STATUS : LIVE / UPDATED",
        ""
    ]

    fixed = CONFIG["fixed_channel"]

    lines.extend([
        f'#EXTINF:-1 tvg-id="" tvg-name="{fixed["name"]}" tvg-logo="{fixed["logo"]}" group-title="INFO",{fixed["name"]}',
        fixed["url"],
        ""
    ])

    for category in sorted(categories):
        for entry in categories[category]:
            name = entry["name"].replace('"', "'")
            logo = entry["logo"] or ""
            group = category.replace('"', "'")

            lines.append(
                f'#EXTINF:-1 tvg-id="" tvg-name="{name}" '
                f'tvg-logo="{logo}" group-title="{group}",{name}'
            )

            lines.append(entry["url"])
            lines.append("")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Playlist generated: {len(online_channels)} working channels")


def main():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    # GitHub Actions runs every 15 minutes.
    # This check allows one update every 105 minutes.
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            last = f.read().strip()

        if last:
            try:
                last_time = datetime.fromisoformat(last)
                elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()

                if elapsed < 105 * 60:
                    print("Update interval not reached.")
                    return

            except ValueError:
                pass

    build_playlist()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
