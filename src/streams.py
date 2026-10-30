import requests
import re

def get_streams(config, channel_id):

    api = config["detail_api"].format(
        channel_id=channel_id
    )

    response = requests.get(
        api,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    urls = []

    def scan(obj):

        if isinstance(obj, dict):

            for value in obj.values():
                scan(value)

        elif isinstance(obj, list):

            for value in obj:
                scan(value)

        elif isinstance(obj, str):

            if re.search(
                r"\.m3u8(?:$|[?#])",
                obj,
                re.I
            ):

                if obj.startswith(("https://", "http://")):
                    urls.append(obj)

    scan(data)

    return list(dict.fromkeys(urls))
