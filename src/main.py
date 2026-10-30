import os
import re
import json
import requests

from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


# =====================================
# PATH CONFIGURATION
# =====================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "kb_go_playlist.m3u8")
STATE_FILE = os.path.join(BASE_DIR, "state", "last_update.txt")

BDT = timezone(timedelta(hours=6))

DETAIL_WORKERS = 10
STREAM_WORKERS = 15

TIMEOUT = (5, 8)


# =====================================
# LOAD CONFIG
# =====================================

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

RAIL_API = os.getenv("AKASH_RAIL_API")
DETAIL_API = os.getenv("AKASH_DETAIL_API_TEMPLATE")

if not RAIL_API:
    raise RuntimeError("Missing GitHub Secret: AKASH_RAIL_API")

if not DETAIL_API:
    raise RuntimeError("Missing GitHub Secret: AKASH_DETAIL_API_TEMPLATE")


HEADERS = {
    "User-Agent": "AKASH-OTT/1.0",
    "Accept": "application/json"
}


# =====================================
# HTTP JSON REQUEST
# =====================================

def get_json(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# =====================================
# JSON HELPERS
# =====================================

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

        for key in [
            "data",
            "items",
            "channels",
            "content",
            "results",
            "records"
        ]:

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

        if value:
            first = value[0]

            if isinstance(first, dict):
                value = get_value(first, ["name", "title"], "Other")
            else:
                value = first
        else:
            value = "Other"

    return str(value or "Other")


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
# FIND M3U8 STREAMS
# =====================================

def find_streams(data):

    found = set()

    if isinstance(data, dict):

        for value in data.values():
            found.update(find_streams(value))

    elif isinstance(data, list):

        for item in data:
            found.update(find_streams(item))

    elif isinstance(data, str):

        value = data.strip()

        if (
            value.startswith(("http://", "https://"))
            and re.search(r"\.m3u8(?:[?#].*)?$", value, re.I)
        ):
            found.add(value)

    return found


# =====================================
# CHECK STREAM
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

        content = next(response.iter_content(1024), b"")

        response.close()

        if b"#EXTM3U" in content:
            return url

    except requests.RequestException:
        return None

    return None


def check_streams_parallel(streams):

    working = []

    with ThreadPoolExecutor(max_workers=STREAM_WORKERS) as executor:

        futures = {
            executor.submit(check_stream, url): url
            for url in streams
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    working.append(result)

            except Exception:
                pass

    return working


# =====================================
# PROCESS ONE CHANNEL
# =====================================

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

        detail = get_json(detail_url)

        streams = find_streams(detail)

        if not streams:
            print(f"No stream found: {name}")
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
            f"Detail error: {name} | "
            f"{type(error).__name__}"
        )

        return None


# =====================================
# FETCH CHANNELS
# =====================================

def fetch_channels():

    print("Connecting to Rail API...")

    data = get_json(RAIL_API)

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Rail API response format")

    print("API totalCount:", data.get("totalCount", "Unknown"))

    channels = find_channel_list(data)

    if not channels:
        raise RuntimeError(
            "No channel list found. API JSON structure needs adjustment."
        )

    unique = {}

    for channel in channels:

        cid = get_channel_id(channel)

        if cid is not None:
            unique[str(cid)] = channel

    channels = list(unique.values())

    maximum = int(CONFIG.get("max_channels", 56))

    print("Channels received:", len(channels))

    if len(channels) < min(maximum, data.get("totalCount", len(channels))):
        print("WARNING: API may require pagination.")

    return channels[:maximum]


# =====================================
# GENERATE PLAYLIST
# =====================================

def build_playlist():

    print("Starting playlist generation...")

    channels = fetch_channels()

    print("Fetching channel details...")

    results = []

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:

        futures = [
            executor.submit(process_channel, channel)
            for channel in channels
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as error:
                print("Processing error:", type(error).__name__)

    print("Channels with streams:", len(results))

    all_streams = set()

    for channel in results:
        all_streams.update(channel["streams"])

    print("Total unique streams:", len(all_streams))

    print("Checking streams...")

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

    now = datetime.now(BDT).strftime("%Y-%m-%d %H:%M:%S")

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

    # Fixed first entry

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

    # Automatic categories

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

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    temp_file = OUTPUT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    os.replace(temp_file, OUTPUT_FILE)

    print("--------------------------------")
    print("PLAYLIST GENERATED SUCCESSFULLY")
    print("Online channels:", len(online_channels))
    print("Categories:", len(categories))
    print("Working streams:", len(working))
    print("Output file:", OUTPUT_FILE)
    print("--------------------------------")


# =====================================
# UPDATE CONTROL
# =====================================

def main():

    force = os.getenv("FORCE_UPDATE", "false").lower() == "true"

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

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

                    print("105-minute update interval not reached.")
                    print("Use Run workflow for manual generation.")
                    return

            except ValueError:
                pass

    build_playlist()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
