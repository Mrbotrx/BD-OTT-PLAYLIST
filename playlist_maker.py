import os
import re
import requests
from datetime import datetime, timezone

# =====================================
# CONFIGURATION
# =====================================

API_URL = os.environ.get("OTT_API_URL")

API_TOKEN = os.environ.get("OTT_API_TOKEN")

OUTPUT_DIR = "BDFreechannel"
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "Freeott.m3u8"
)

PROMO_LOGO = (
    "https://raw.githubusercontent.com/Mrbotrx/"
    "Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg"
)

PROMO_VIDEO = (
    "https://github.com/Mrbotrx/Mrbotrx/raw/"
    "refs/heads/main/IPTV_LINKS_VIDEO.mp4"
)

HEADERS = {
    "User-Agent": "BD-FreeOTT-Generator/1.0",
    "Accept": "application/json"
}

if API_TOKEN:
    HEADERS["Authorization"] = f"Bearer {API_TOKEN}"


# =====================================
# CLEAN TEXT
# =====================================

def clean_text(value):

    if value is None:
        return ""

    return re.sub(
        r'[\r\n",]',
        " ",
        str(value)
    ).strip()


# =====================================
# FETCH API
# =====================================

def fetch_api():

    if not API_URL:
        raise ValueError("OTT_API_URL secret missing")

    print("Connecting to API...")

    try:

        response = requests.get(
            API_URL,
            headers=HEADERS,
            timeout=40
        )

        if response.status_code == 403:
            raise RuntimeError(
                "API returned 403 Forbidden. "
                "The API server must authorize GitHub Actions "
                "or provide valid API credentials."
            )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid API JSON structure")

        if "channels" not in data:
            raise ValueError("API JSON missing channels field")

        print("API connected successfully.")

        return data

    except requests.exceptions.Timeout:
        raise RuntimeError("API connection timeout")

    except requests.exceptions.ConnectionError:
        raise RuntimeError("API connection failed")


# =====================================
# EXTRACT CHANNELS
# =====================================

def find_channels(data):

    channels = data.get("channels", [])

    if not isinstance(channels, list):
        raise ValueError("Invalid channels format")

    results = []

    for item in channels:

        if not isinstance(item, dict):
            continue

        name = clean_text(item.get("name"))

        logo = clean_text(item.get("img"))

        category = clean_text(item.get("cat"))

        channel_type = clean_text(item.get("type"))

        stream_url = clean_text(item.get("url"))

        channel_id = clean_text(item.get("id"))

        # Only free channels
        if channel_type.lower() != "free":
            continue

        if not name or not stream_url:
            continue

        # Direct HLS URL only.
        # Opaque references such as w2:g7h3j5
        # require an authorized API resolver.
        if not re.match(r"^https?://", stream_url, re.I):
            print(
                f"Skipping unresolved stream reference: {name}"
            )
            continue

        if ".m3u8" not in stream_url.lower():
            continue

        results.append({
            "id": channel_id,
            "name": name,
            "logo": logo,
            "category": category or "Free OTT",
            "url": stream_url
        })

    return results


# =====================================
# REMOVE DUPLICATES
# =====================================

def remove_duplicates(channels):

    unique = []
    seen = set()

    for channel in channels:

        if channel["url"] not in seen:

            seen.add(channel["url"])
            unique.append(channel)

    return unique


# =====================================
# AUTO HEADER
# =====================================

def generate_header(channels):

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    return [
        "#EXTM3U",
        "#PLAYLIST:BD FreeOTT",
        f"#TOTAL-CHANNELS:{len(channels) + 1}",
        f"#GENERATED:{now}",
        "#AUTO-REFRESH:90 MINUTES",
        ""
    ]


# =====================================
# GENERATE PLAYLIST
# =====================================

def generate_playlist(channels):

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    lines = generate_header(channels)

    # FIRST FIXED CHANNEL

    lines.extend([
        '#EXTINF:-1 tvg-id="" '
        'tvg-name="IPTV LINKS" '
        f'tvg-logo="{PROMO_LOGO}" '
        'group-title="PROTV KBCT",IPTV LINKS',

        PROMO_VIDEO,
        ""
    ])

    # API CHANNELS

    for channel in channels:

        name = channel["name"]
        logo = channel["logo"]
        category = channel["category"]
        url = channel["url"]

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="{channel["id"]}" '
            f'tvg-name="{name}" '
            f'tvg-logo="{logo}" '
            f'group-title="{category}",{name}'
        )

        lines.append(url)
        lines.append("")

    # SAVE FILE

    temporary_file = OUTPUT_FILE + ".tmp"

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("\n".join(lines))

    os.replace(
        temporary_file,
        OUTPUT_FILE
    )

    print("--------------------------------")
    print("PLAYLIST GENERATED SUCCESSFULLY")
    print("--------------------------------")

    print("Total channels:", len(channels) + 1)
    print("Output:", OUTPUT_FILE)


# =====================================
# MAIN
# =====================================

def main():

    print("================================")
    print("BD FREEOTT GENERATOR")
    print("================================")

    data = fetch_api()

    channels = find_channels(data)

    channels = remove_duplicates(channels)

    if not channels:

        raise RuntimeError(
            "No direct M3U8 channels found. "
            "Check the API stream references."
        )

    generate_playlist(channels)


if __name__ == "__main__":
    main()
