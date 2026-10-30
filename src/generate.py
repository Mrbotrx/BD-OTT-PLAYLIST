import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

from channels import get_channels
from streams import get_streams
from checker import check_stream

ROOT = Path(__file__).resolve().parents[1]

config = json.loads(
    (ROOT / "config.json").read_text()
)

config["rail_api"] = os.environ["AKASH_RAIL_API"]

config["detail_api"] = os.environ["AKASH_DETAIL_API_TEMPLATE"]

BD_TIME = timezone(timedelta(hours=6))


def current_time():

    return datetime.now(BD_TIME).strftime(
        "%Y-%m-%d %I:%M:%S %p"
    )


def is_promo(name):

    name = name.lower()

    return any(
        word.lower() in name
        for word in config["promo_keywords"]
    )


def main():

    print("Fetching Channels...")

    channels = get_channels(config)

    playlist = ["#EXTM3U"]

    working = []

    print("Checking Streams...")

    for channel in channels:

        name = channel["name"]

        if is_promo(name):
            continue

        try:

            urls = get_streams(
                config,
                channel["id"]
            )

            valid = []

            for url in urls:

                if check_stream(
                    url,
                    config["timeout"]
                ):

                    valid.append(url)

            if valid:

                working.append({
                    "name": name,
                    "logo": channel["logo"],
                    "urls": valid
                })

                print("[ONLINE]", name)

            else:

                print("[OFFLINE]", name)

        except Exception as error:

            print("[ERROR]", name, error)

    total = len(working)

    # CUSTOM HEADER

    playlist.extend([
        "",
        f"# 📺 PLAYLIST NAME : {config['playlist_name']}",
        f"# 👨‍💻 DEV : {config['developer']}",
        f"# 🌐 PANEL : {config['panel']}",
        f"# 💻 GITHUB : {config['github']}",
        f"# 📢 TELEGRAM : {config['telegram']}",
        "#",
        f"# 📺 CHANNELS : {total} CHANNELS ONLINE",
        "# 🔍 STATUS : LOGO & SPEED VERIFIED",
        "#",
        "# • https://t.me/iptvlinksm3u8",
        "# • https://t.me/KBCYBERTEAM",
        "#",
        f"# 🕒 TIME : {current_time()}",
        "# 🔄 STATUS : LIVE / UPDATED",
        "#",
        "# 📬 @KBCYBERTEAM",
        ""
    ])

    # ALWAYS FIRST CHANNEL

    playlist.extend([
        '#EXTINF:-1 tvg-id="" tvg-name="IPTV LINKS" tvg-logo="https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg" group-title="KB TV",IPTV LINKS',
        "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"
    ])

    # ADD WORKING CHANNELS

    for channel in working:

        for index, url in enumerate(channel["urls"]):

            suffix = (
                ""
                if index == 0
                else f" (Backup {index})"
            )

            playlist.append(
                f'#EXTINF:-1 tvg-id="" '
                f'tvg-name="{channel["name"]}" '
                f'tvg-logo="{channel["logo"]}" '
                f'group-title="AKASH OTT",'
                f'{channel["name"]}{suffix}'
            )

            playlist.append(url)

    output = ROOT / config["output"]

    output.write_text(
        "\n".join(playlist) + "\n",
        encoding="utf-8"
    )

    print("Playlist Generated!")
    print("Total Channels:", total)


if __name__ == "__main__":

    main()
