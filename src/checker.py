import requests

def check_stream(url, timeout=15):

    try:

        response = requests.get(
            url,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/vnd.apple.mpegurl,*/*"
            }
        )

        if response.status_code != 200:
            return False

        content = next(
            response.iter_content(4096),
            b""
        )

        response.close()

        return b"#EXTM3U" in content.upper()

    except requests.RequestException:

        return False
