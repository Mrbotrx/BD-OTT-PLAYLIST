import requests

def get_channels(config):

    response = requests.get(
        config["rail_api"],
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    channels = []

    def scan(obj):

        if isinstance(obj, dict):

            cid = (
                obj.get("channelId")
                or obj.get("channel_id")
                or obj.get("id")
            )

            name = (
                obj.get("channelName")
                or obj.get("name")
                or obj.get("title")
            )

            logo = (
                obj.get("logo")
                or obj.get("logoUrl")
                or obj.get("image")
            )

            if cid and name:

                channels.append({
                    "id": str(cid),
                    "name": str(name),
                    "logo": str(logo or "")
                })

            for value in obj.values():
                scan(value)

        elif isinstance(obj, list):

            for item in obj:
                scan(item)

    scan(data)

    unique = {}

    for channel in channels:
        unique[channel["id"]] = channel

    return list(unique.values())
