import os
import re
import json
import requests
import threading

from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse


# ==========================================
# AKASH OTT CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "kb_go_playlist.m3u8")
STATE_FILE = os.path.join(BASE_DIR, "state", "last_update.txt")

BDT = timezone(timedelta(hours=6))

# Parallel workers
DETAIL_WORKERS = 12
STREAM_WORKERS = 20

# Timeouts
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 5

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

RAIL_API = os.environ.get("AKASH_RAIL_API")
DETAIL_API = os.environ.get("AKASH_DETAIL_API_TEMPLATE")

if not RAIL_API or not DETAIL_API:
    raise RuntimeError("API GitHub Secrets missing!")


HEADERS = {
    "User-Agent": "AKASH-OTT/1.0",
    "Accept": "application/json"
}


# ==========================================
# HTTP REQUEST
# ==========================================

def request_json(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
    )

    response.raise_for_status()

    return response.json()


# ==========================================
# JSON HELPERS
# ==========================================

def get_value(data, keys, default=None):

    if not isinstance(data, dict):
        return default

    for key in keys:

        value = data.get(key)

        if value is not None and value != "":
            return value

    return default


def find_channel_list(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "items",
            "channels",
            "content",
            "results",
            "records"
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):

                result = find_channel_list(value)

                if result:
                    return result

    return []


def get_channel_id(channel):

    return get_value(
        channel,
        ["channelId", "channel_id", "id"]
    )


def get_channel_name(channel):

    return str(get_value(
        channel,
        ["channelName", "name", "title", "displayName"],
        "Unknown Channel"
    ))


def get_channel_logo(channel):

    return str(get_value(
        channel,
        ["logo", "logoUrl", "image", "imageUrl", "thumbnail"],
        ""
    ))


def get_category(data):

    category = get_value(
        data,
        [
            "genreName",
            "categoryName",
            "genre",
            "category"
        ],
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

                names.append(str(get_value(
                    item,
                    ["name", "title"],
                    "Other"
                )))

            else:
                names.append(str(item))

        return names[0] if names else "Other"

    return str(category or "Other")


# ==========================================
# PROMO FILTER
# ==========================================

def is_promo(channel):

    name = get_channel_name(channel).lower()

    keywords = CONFIG.get("promo_keywords", [])

    for keyword in keywords:

        if str(keyword).lower() in name:
            return True

    return False


# ==========================================
# STREAM EXTRACTION
# ==========================================

def find_streams(data):

    streams = set()

    if isinstance(data, dict):

        for value in data.values():

            streams.update(find_streams(value))

    elif isinstance(data, list):

        for item in data:

            streams.update(find_streams(item))

    elif isinstance(data, str):

        value = data.strip()

        if re.search(
            r"\.m3u8(?:[?#].*)?$",
            value,
            re.IGNORECASE
        ):

            if value.startswith(("http://", "https://")):
                streams.add(value)

    return streams


# ==========================================
# FAST STREAM CHECKER
# ==========================================

def check_stream(url):

    try:

        response = requests.get(
            url,
            headers={
                **HEADERS,
                "Range": "bytes=0-1023"
            },
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            stream=True
        )

        if response.status_code not in (200, 206):

            response.close()
            return None

        content = next(
            response.iter_content(1024),
            b""
        )

        response.close()

        if b"#EXTM3U" in content:
            return url

    except requests.RequestException:
        pass

    return None


def check_streams_parallel(streams):

    working = []

    if not streams:
        return working

    with ThreadPoolExecutor(
        max_workers=STREAM_WORKERS
    ) as executor:

        futures = [
            executor.submit(check_stream, url)
            for url in streams
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    working.append(result)

            except Exception:
                pass

    return working


# ==========================================
# FETCH CHANNEL DETAIL
# ==========================================

def process_channel(channel):

    cid = get_channel_id(channel)
    name = get_channel_name(channel)

    if not cid:
        return None

    if is_promo(channel):
        return None

    try:

        detail_url = DETAIL_API.replace(
            "{channel_id}",
            str(cid)
        )

        detail = request_json(detail_url)

        streams = find_streams(detail)

        if not streams:
            return None

        logo = (
            get_channel_logo(channel)
            or CONFIG.get("logo_default", "")
        )

        category = get_category(channel)

        if category == "Other":
            category = get_category(detail)

        return {
            "name": name,
            "logo": logo,
            "category": category,
            "streams": list(streams)
        }

    except Exception as error:

        print(
            f"Detail failed: {name} - "
            f"{type(error).__name__}"
        )

        return None


# ==========================================
# FETCH ALL CHANNELS
# ==========================================

def fetch_channels():

    data = request_json(RAIL_API)

    total_count = 0

    if isinstance(data, dict):
        total_count = data.get("totalCount", 0)

    channels = find_channel_list(data)

    # Remove duplicate IDs
    unique = {}

    for channel in channels:

        cid = get_channel_id(channel)

        if cid is not None:
            unique[str(cid)] = channel

    channels = list(unique.values())

    max_channels = CONFIG.get("max_channels", 56)

    print("API totalCount:", total_count)
    print("Channels received:", len(channels))

    if total_count and len(channels) < min(total_count, max_channels):
        print("WARNING: API returned fewer channels than requested.")

    return channels[:max_channels]


# ==========================================
# BUILD PLAYLIST
# ==========================================

def build_playlist():

    print("Starting AKASH OTT Generator...")

    channels = fetch_channels()

    print("Processing channel details...")

    channel_results = []

    # Parallel Detail API requests
    with ThreadPoolExecutor(
        max_workers=DETAIL_WORKERS
    ) as executor:

        futures = [
            executor.submit(process_channel, channel)
            for channel in channels
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    channel_results.append(result)

            except Exception:
                pass

    print("Channels with streams:", len(channel_results))

    # Collect all stream URLs
    all_streams = set()

    for channel in channel_results:

        for stream in channel["streams"]:
            all_streams.add(stream)

    print("Total unique streams:", len(all_streams))

    # Parallel stream checking
    print("Checking working streams...")

    working_streams = check_streams_parallel(
        list(all_streams)
    )

    working_set = set(working_streams)

    print("Working streams:", len(working_set))

    # Group by category
    categories = defaultdict(list)

    online_channels = set()

    for channel in channel_results:

        valid_streams = [
            url for url in channel["streams"]
            if url in working_set
        ]

        if not valid_streams:
            continue

        online_channels.add(channel["name"])

        for url in valid_streams:

            categories[channel["category"]].append({
                "name": channel["name"],
                "logo": channel["logo"],
                "url": url
            })

    # Bangladesh time
    now = datetime.now(BDT).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Playlist Header
    lines = [
        "#EXTM3U",
        f"# PLAYLIST NAME : {CONFIG['playlist_name']}",
        f"# DEV : {CONFIG['developer']}",
        f"# PANEL : {CONFIG['panel']}",
        f"# GITHUB : {CONFIG['github']}",
        f"# TELEGRAM : {CONFIG['telegram']}",
        f"# CHANNELS : {len(online_channels)} WORKING CHANNELS",
        f"# TIME : {now} BDT",
        "# STATUS : LIVE / UPDATED",
        ""
    ]

    # Fixed IPTV LINKS entry first
    fixed = CONFIG["fixed_channel"]

    lines.extend([
        (
            f'#EXTINF:-1 tvg-id="" '
            f'tvg-name="{fixed["name"]}" '
            f'tvg-logo="{fixed["logo"]}" '
            f'group-title="INFO",{fixed["name"]}'
        ),
        fixed["url"],
        ""
    ])

    # Auto Category
    for category in sorted(categories):

        for entry in sorted(
            categories[category],
            key=lambda item: item["name"].lower()
        ):

            name = entry["name"].replace('"', "'")
            logo = entry["logo"].replace('"', "'")
            group = category.replace('"', "'")

            lines.append(
                f'#EXTINF:-1 tvg-id="" '
                f'tvg-name="{name}" '
                f'tvg-logo="{logo}" '
                f'group-title="{group}",{name}'
            )

            lines.append(entry["url"])
            lines.append("")

    # Save Playlist
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("\n".join(lines))

    print("--------------------------------")
    print("AKASH OTT PLAYLIST GENERATED")
    print("Online channels:", len(online_channels))
    print("Categories:", len(categories))
    print("Working streams:", len(working_set))
    print("--------------------------------")


# ==========================================
# UPDATE INTERVAL
# ==========================================

def main():

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    if os.path.exists(STATE_FILE):

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            last = f.read().strip()

        if last:

            try:

                last_time = datetime.fromisoformat(last)

                elapsed = (
                    datetime.now(timezone.utc) - last_time
                ).total_seconds()

                if elapsed < 105 * 60:

                    print("105 minutes not completed.")
                    return

            except ValueError:
                pass

    build_playlist()

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            datetime.now(timezone.utc).isoformat()
        )


if __name__ == "__main__":
    main()
