import os
import re
import json
import requests

from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


# =====================================
# CONFIGURATION
# =====================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "kb_go_playlist.m3u8")
STATE_FILE = os.path.join(BASE_DIR, "state", "last_update.txt")

BDT = timezone(timedelta(hours=6))

DETAIL_WORKERS = 10
STREAM_WORKERS = 15

TIMEOUT = (5, 8)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

RAIL_API = os.getenv("AKASH_RAIL_API")
DETAIL_API = os.getenv("AKASH_DETAIL_API_TEMPLATE")

if not RAIL_API or not DETAIL_API:
    raise RuntimeError("GitHub API Secrets missing!")


HEADERS = {
    "User-Agent": "AKASH-OTT/1.0",
    "Accept": "application/json"
}


# =====================================
# API REQUEST
# =====================================

def get_json(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    try:
        return response.json()

    except ValueError:
        raise RuntimeError("API did not return valid JSON")


# =====================================
# RECURSIVE JSON SEARCH
# =====================================

def walk_json(data, path="$"):
    """Walk every nested object and list."""

    yield path, data

    if isinstance(data, dict):

        for key, value in data.items():
            yield from walk_json(value, f"{path}.{key}")

    elif isinstance(data, list):

        for index, value in enumerate(data):
            yield from walk_json(value, f"{path}[{index}]")


def normalize_key(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


ID_KEYS = {
    "id",
    "channelid",
    "channel_id",
    "contentid",
    "content_id"
}

NAME_KEYS = {
    "name",
    "channelname",
    "channel_name",
    "title",
    "displayname"
}


def find_channel_list(data):

    candidates = []

    for path, value in walk_json(data):

        if not isinstance(value, list) or not value:
            continue

        objects = [
            item for item in value
            if isinstance(item, dict)
        ]

        if not objects:
            continue

        score = 0

        for item in objects:

            keys = {
                normalize_key(key)
                for key in item.keys()
            }

            has_id = bool(keys & ID_KEYS)
            has_name = bool(keys & NAME_KEYS)

            if has_id:
                score += 2

            if has_name:
                score += 2

            if has_id and has_name:
                score += 3

        if score:
            candidates.append((score, len(objects), path, objects))

    if not candidates:
        return []

    # Prefer the list containing the most recognizable channel objects.
    candidates.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True
    )

    score, count, path, result = candidates[0]

    print("Detected channel list:", path)
    print("Detected channel objects:", count)

    return result


# =====================================
# JSON VALUE HELPERS
# =====================================

def get_value(data, keys, default=None):

    if not isinstance(data, dict):
        return default

    normalized = {
        normalize_key(key): value
        for key, value in data.items()
    }

    for key in keys:

        value = normalized.get(normalize_key(key))

        if value is not None and value != "":
            return value

    return default


def get_channel_id(channel):

    return get_value(
        channel,
        ["channelId", "channel_id", "id", "contentId"]
    )


def get_channel_name(channel):

    return str(get_value(
        channel,
        ["channelName", "name", "title", "displayName"],
        "Unknown Channel"
    ))


def get_logo(channel):

    return str(get_value(
        channel,
        ["logo", "logoUrl", "image", "imageUrl", "thumbnail"],
        CONFIG.get("logo_default", "")
    ))


def get_category(data):

    value = get_value(
        data,
        ["genreName", "categoryName", "genre", "category"],
        "Other"
    )

    if isinstance(value, dict):
        value = get_value(value, ["name", "title"], "Other")

    if isinstance(value, list):

        if not value:
            return "Other"

        first = value[0]

        if isinstance(first, dict):
            value = get_value(first, ["name", "title"], "Other")
        else:
            value = first

    return str(value or "Other")


def find_total_count(data):

    for path, value in walk_json(data):

        if isinstance(value, dict):

            total = get_value(
                value,
                ["totalCount", "total_count", "total"]
            )

            if total is not None:
                return total

    return "Unknown"


# =====================================
# PROMO FILTER
# =====================================

def is_promo(channel):

    name = get_channel_name(channel).lower()

    for keyword in CONFIG.get("promo_keywords", []):

        if str(keyword).lower() in name:
            return True

    return False


# =====================================
# STREAM EXTRACTION
# =====================================

def find_streams(data):

    found = set()

    for _, value in walk_json(data):

        if isinstance(value, str):

            url = value.strip()

            if (
                url.startswith(("http://", "https://"))
                and re.search(
                    r"\.m3u8(?:[?#].*)?$",
                    url,
                    re.IGNORECASE
                )
            ):
                found.add(url)

    return found


# =====================================
# STREAM CHECK
# =====================================

def check_stream(url):

    try:

        response = requests.get(
            url,
            headers={
                **HEADERS,
                "Range": "bytes=0-1023"
            },
            timeout=TIMEOUT,
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


# =====================================
# FETCH CHANNELS
# =====================================

def fetch_channels():

    print("Connecting to Rail API...")

    data = get_json(RAIL_API)

    total = find_total_count(data)

    print("API totalCount:", total)

    channels = find_channel_list(data)

    if not channels:

        # Print structure only, not URLs or tokens.
        if isinstance(data, dict):
            print("Top-level JSON keys:", list(data.keys()))

        print("No recognizable channel array found.")

        raise RuntimeError(
            "Channel list not detected. API JSON structure is required."
        )

    unique = {}

    for channel in channels:

        cid = get_channel_id(channel)

        if cid is not None:
            unique[str(cid)] = channel

    channels = list(unique.values())

    maximum = int(CONFIG.get("max_channels", 56))

    print("Unique channels:", len(channels))

    if isinstance(total, int) and len(channels) < min(total, maximum):
        print("WARNING: API may require pagination.")

    return channels[:maximum]


# =====================================
# PROCESS CHANNEL DETAIL
# =====================================

def process_channel(channel):

    cid = get_channel_id(channel)
    name = get_channel_name(channel)

    if not cid or is_promo(channel):
        return None

    try:

        detail_url = DETAIL_API.replace(
            "{channel_id}",
            str(cid)
        )

        detail = get_json(detail_url)

        streams = find_streams(detail)

        if not streams:
            print("No M3U8 found:", name)
            return None

        category = get_category(channel)

        if category == "Other":
            category = get_category(detail)

        return {
            "name": name,
            "logo": get_logo(channel),
            "category": category,
            "streams": list(streams)
        }

    except Exception as error:

        print(
            "Detail error:",
            name,
            type(error).__name__
        )

        return None


# =====================================
# BUILD PLAYLIST
# =====================================

def build_playlist():

    print("Starting AKASH OTT Generator...")

    channels = fetch_channels()

    print("Fetching channel details...")

    results = []

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
                    results.append(result)

            except Exception:
                pass

    print("Channels with streams:", len(results))

    all_streams = set()

    for channel in results:
        all_streams.update(channel["streams"])

    print("Total unique streams:", len(all_streams))

    print("Checking working streams...")

    working = set(
        check_streams_parallel(list(all_streams))
    )

    print("Working streams:", len(working))

    categories = defaultdict(list)
    online_channels = set()

    for channel in results:

        valid = [
            url for url in channel["streams"]
            if url in working
        ]

        if not valid:
            continue

        online_channels.add(channel["name"])

        for url in valid:

            categories[channel["category"]].append({
                "name": channel["name"],
                "logo": channel["logo"],
                "url": url
            })

    now = datetime.now(BDT).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

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

    for category in sorted(categories):

        for entry in sorted(
            categories[category],
            key=lambda item: item["name"].lower()
        ):

            name = entry["name"].replace('"', "'")
            logo = entry["logo"].replace('"', "'")
            group = category.replace('"', "'")

            lines.extend([
                (
                    f'#EXTINF:-1 tvg-id="" '
                    f'tvg-name="{name}" '
                    f'tvg-logo="{logo}" '
                    f'group-title="{group}",{name}'
                ),
                entry["url"],
                ""
            ])

    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True
    )

    temp_file = OUTPUT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    os.replace(temp_file, OUTPUT_FILE)

    print("================================")
    print("PLAYLIST GENERATED SUCCESSFULLY")
    print("Online channels:", len(online_channels))
    print("Categories:", len(categories))
    print("Working streams:", len(working))
    print("Output:", OUTPUT_FILE)
    print("================================")


# =====================================
# MAIN
# =====================================

def main():

    force = os.getenv(
        "FORCE_UPDATE",
        "false"
    ).lower() == "true"

    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True
    )

    if not force and os.path.exists(STATE_FILE):

        with open(STATE_FILE, "r", encoding="utf-8") as f:
            last = f.read().strip()

        if last:

            try:

                last_time = datetime.fromisoformat(last)

                elapsed = (
                    datetime.now(timezone.utc) - last_time
                ).total_seconds()

                if elapsed < 105 * 60:

                    print("Update interval not reached.")
                    return

            except ValueError:
                pass

    build_playlist()

    with open(STATE_FILE, "w", encoding="utf-8") as f:

        f.write(
            datetime.now(timezone.utc).isoformat()
        )


if __name__ == "__main__":
    main()
