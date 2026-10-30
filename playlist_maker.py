import requests
import json
import os
import re
from datetime import datetime, timezone

# ==============================
# CONFIGURATION
# ==============================

API_URL = "https://live.indiansserials.com/channels"

OUTPUT_DIR = "BDFreechannel"
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "Freeott.m3u8"
)

PROMO_NAME = "IPTV LINKS"

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


# ==============================
# FETCH API
# ==============================

def fetch_api():

    print("Connecting to API...")

    response = requests.get(
        API_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("API connected successfully.")

    return data


# ==============================
# HELPER FUNCTIONS
# ==============================

def clean_text(value):

    if value is None:
        return ""

    value = str(value)

    return re.sub(
        r'[\r\n",]',
        ' ',
        value
    ).strip()


def get_value(item, keys):

    if not isinstance(item, dict):
        return ""

    for key in keys:

        for actual_key, value in item.items():

            if actual_key.lower() == key.lower():

                if isinstance(value, (str, int)):
                    return str(value)

    return ""


def find_channels(data):

    """
    Supports common JSON API structures.
    Only processes channel records containing
    publicly supplied HLS URLs.
    """

    found = []

    def scan(obj):

        if isinstance(obj, dict):

            stream = get_value(
                obj,
                [
                    "url",
                    "streamUrl",
                    "stream_url",
                    "m3u8",
                    "playbackUrl",
                    "manifestUrl"
                ]
            )

            if stream and re.match(
                r'^https?://',
                stream,
                re.I
            ):

                name = get_value(
                    obj,
                    [
                        "channelName",
                        "name",
                        "title",
                        "channel_name"
                    ]
                )

                logo = get_value(
                    obj,
                    [
                        "logo",
                        "image",
                        "thumbnail",
                        "channelLogo"
                    ]
                )

                category = get_value(
                    obj,
                    [
                        "category",
                        "genre",
                        "group",
                        "groupName"
                    ]
                )

                if name and (
                    ".m3u8" in stream.lower()
                    or "mpegurl" in stream.lower()
                ):

                    found.append({
                        "name": clean_text(name),
                        "logo": clean_text(logo),
                        "category": clean_text(category)
                            or "Free OTT",
                        "url": stream.strip()
                    })

            for value in obj.values():
                scan(value)

        elif isinstance(obj, list):

            for item in obj:
                scan(item)

    scan(data)

    return found


# ==============================
# REMOVE DUPLICATES
# ==============================

def remove_duplicates(channels):

    unique = []
    seen = set()

    for channel in channels:

        url = channel["url"]

        if url not in seen:

            seen.add(url)
            unique.append(channel)

    return unique


# ==============================
# GENERATE M3U
# ==============================

def generate_playlist(channels):

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    lines = [
        "#EXTM3U",
        ""
    ]

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

        if not logo:
            logo = ""

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="" '
            f'tvg-name="{name}" '
            f'tvg-logo="{logo}" '
            f'group-title="{category}",{name}'
        )

        lines.append(url)
        lines.append("")

    # WRITE FILE

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("\n".join(lines))

    print("--------------------------------")
    print("PLAYLIST GENERATED")
    print("--------------------------------")

    print("Total channels:", len(channels))
    print("Output:", OUTPUT_FILE)


# ==============================
# MAIN
# ==============================

def main():

    print("Starting BD FreeOTT Generator")

    try:

        data = fetch_api()

        channels = find_channels(data)

        channels = remove_duplicates(channels)

        if not channels:

            raise ValueError(
                "No supported M3U8 channels found. "
                "Check the API JSON structure."
            )

        generate_playlist(channels)

    except Exception as error:

        print("GENERATION FAILED:")
        print(error)

        raise


if __name__ == "__main__":

    main()
