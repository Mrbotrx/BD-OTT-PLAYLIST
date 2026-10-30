import os
import re
import requests
from datetime import datetime, timezone

# =====================================
# BD FREEOTT GENERATOR
# =====================================

API_URL = os.environ.get("OTT_API_URL")

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

    print("Connecting to OTT API...")

    response = requests.get(
        API_URL,
        headers=HEADERS,
        timeout=40
    )

    response.raise_for_status()

    print("API connected successfully.")

    return response.json()


# =====================================
# JSON VALUE FINDER
# =====================================

def get_value(item, keys):

    if not isinstance(item, dict):
        return ""

    for key in keys:

        for actual_key, value in item.items():

            if actual_key.lower() == key.lower():

                if isinstance(value, (str, int, float)):
                    return str(value)

    return ""


# =====================================
# AUTO CATEGORY
# =====================================

def get_category(item):

    category = get_value(
        item,
        [
            "category",
            "genre",
            "group",
            "groupName",
            "primaryGenre"
        ]
    )

    return clean_text(category) or "Free OTT"


# =====================================
# CHANNEL FINDER
# =====================================

def find_channels(data):

    channels = []

    name_keys = [
        "channelName",
        "name",
        "title",
        "channel_name"
    ]

    stream_keys = [
        "url",
        "streamUrl",
        "stream_url",
        "m3u8",
        "playbackUrl",
        "manifestUrl"
    ]

    logo_keys = [
        "logo",
        "image",
        "thumbnail",
        "channelLogo"
    ]

    def scan(obj):

        if isinstance(obj, dict):

            name = get_value(obj, name_keys)
            stream = get_value(obj, stream_keys)
            logo = get_value(obj, logo_keys)

            category = get_category(obj)

            if (
                name
                and stream
                and stream.startswith(("http://", "https://"))
                and ".m3u8" in stream.lower()
            ):

                channels.append({
                    "name": clean_text(name),
                    "logo": clean_text(logo),
                    "category": category,
                    "url": stream.strip()
                })

            for value in obj.values():
                scan(value)

        elif isinstance(obj, list):

            for item in obj:
                scan(item)

    scan(data)

    return channels


# =====================================
# REMOVE DUPLICATES
# =====================================

def remove_duplicates(channels):

    unique = []
    seen = set()

    for channel in channels:

        url = channel["url"]

        if url not in seen:

            seen.add(url)
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

    lines.append(
        '#EXTINF:-1 tvg-id="" '
        'tvg-name="IPTV LINKS" '
        f'tvg-logo="{PROMO_LOGO}" '
        'group-title="PROTV KBCT",IPTV LINKS'
    )

    lines.append(PROMO_VIDEO)
    lines.append("")

    # AUTOMATIC CHANNELS

    for channel in channels:

        name = channel["name"]
        logo = channel["logo"]
        category = channel["category"]
        url = channel["url"]

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="" '
            f'tvg-name="{name}" '
            f'tvg-logo="{logo}" '
            f'group-title="{category}",{name}'
        )

        lines.append(url)
        lines.append("")

    # SAVE PLAYLIST SAFELY

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
    print("PLAYLIST GENERATED")
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

    try:

        data = fetch_api()

        channels = find_channels(data)

        channels = remove_duplicates(channels)

        if not channels:

            raise ValueError(
                "No supported M3U8 channels found."
            )

        generate_playlist(channels)

        print("Generation completed successfully.")

    except Exception as error:

        print("ERROR:", str(error))

        raise


if __name__ == "__main__":
    main()
