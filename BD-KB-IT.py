#!/usr/bin/env python3
"""BD KB IT — authorized API channel collector and M3U exporter."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests

APP_NAME = "BD KB IT"
OUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "15"))
USER_AGENT = os.getenv("HTTP_USER_AGENT", "BD-KB-IT/1.0")
M3U8_RE = re.compile(r"\.m3u8(?:$|[?#])", re.I)
HTTP_RE = re.compile(r"^https?://", re.I)

# Always pinned at the top of every generated playlist.
PINNED_CHANNEL = {
    "id": "",
    "name": "IPTV LINKS",
    "category": "KB PRO TV",
    "logo": "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg",
    "working_stream": "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4",
    "pinned": True,
}

NAME_KEYS = ("name", "title", "channel_name", "channelTitle", "label")
LOGO_KEYS = ("logo", "logo_url", "image", "image_url", "thumbnail", "icon", "poster")
CATEGORY_KEYS = ("category", "category_name", "group", "genre")
ID_KEYS = ("id", "channel_id", "uuid", "slug")
STREAM_KEYS = ("url", "stream_url", "streamUrl", "hls", "hls_url", "m3u8",
               "play_url", "playback_url", "source")


def headers():
    result = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    token = os.getenv("BD_KB_IT_API_TOKEN", "").strip()
    if token:
        result["Authorization"] = f"Bearer {token}"
    extra = os.getenv("BD_KB_IT_EXTRA_HEADERS", "").strip()
    if extra:
        try:
            extra_headers = json.loads(extra)
            if not isinstance(extra_headers, dict):
                raise ValueError("must be a JSON object")
            result.update({str(k): str(v) for k, v in extra_headers.items()})
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit("BD_KB_IT_EXTRA_HEADERS must be a JSON object") from exc
    return result


def is_http_url(value):
    return isinstance(value, str) and bool(HTTP_RE.match(value.strip()))


def get_first(obj, keys):
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        value = obj.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
        if isinstance(value, dict):
            for nested_key in ("url", "src", "href", "path"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


def collect_urls(node):
    found = []
    if isinstance(node, dict):
        for value in node.values():
            found.extend(collect_urls(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(collect_urls(value))
    elif isinstance(node, str) and is_http_url(node.strip()):
        found.append(node.strip())
    return found


def find_candidate_records(node, found):
    """Recognize common channel records nested in API response structures."""
    if isinstance(node, list):
        for item in node:
            find_candidate_records(item, found)
    elif isinstance(node, dict):
        name = get_first(node, NAME_KEYS)
        urls = collect_urls(node)
        if name and urls:
            found.append(node)
            # Do not recursively re-add the same record's nested objects.
            return
        for value in node.values():
            if isinstance(value, (dict, list)):
                find_candidate_records(value, found)


def extract_streams(record):
    preferred = []
    if isinstance(record, dict):
        for key in STREAM_KEYS:
            value = record.get(key)
            if isinstance(value, str) and is_http_url(value):
                preferred.append(value.strip())
            elif isinstance(value, (dict, list)):
                preferred.extend(collect_urls(value))
    all_urls = preferred + collect_urls(record)
    output, seen = [], set()
    for url in all_urls:
        if M3U8_RE.search(url) and url not in seen:
            seen.add(url)
            output.append(url)
    return output


def request_json(session, url):
    response = session.get(url, headers=headers(), timeout=TIMEOUT)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"API did not return JSON (HTTP {response.status_code})") from exc


def get_next_url(payload, current_url):
    if not isinstance(payload, dict):
        return None
    containers = [payload]
    for key in ("pagination", "meta"):
        if isinstance(payload.get(key), dict):
            containers.append(payload[key])

    for container in containers:
        next_url = container.get("next_url") or container.get("nextUrl")
        if isinstance(next_url, str) and next_url.strip():
            return urljoin(current_url, next_url.strip())

    pagination = payload.get("pagination", {})
    if isinstance(pagination, dict):
        has_more = pagination.get("has_more", pagination.get("hasMore", False))
        cursor = pagination.get("next_cursor") or pagination.get("nextCursor")
        if has_more and cursor:
            parsed = urlparse(current_url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            query["cursor"] = [str(cursor)]
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    return None


def validate_m3u8(session, url):
    """Validate only a direct playlist URL; no DRM/auth bypass or page scraping."""
    try:
        response = session.get(
            url,
            headers={**headers(), "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*"},
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
        status = response.status_code
        content_type = response.headers.get("Content-Type", "").lower()
        prefix = next(response.iter_content(chunk_size=512), b"")
        response.close()
        looks_like_playlist = b"#EXTM3U" in prefix
        looks_like_hls_type = "mpegurl" in content_type or "m3u8" in content_type
        return status == 200 and (looks_like_playlist or looks_like_hls_type), status
    except requests.RequestException:
        return False, "request_error"


def normalize_record(record, base_url):
    logo = get_first(record, LOGO_KEYS)
    if logo and not is_http_url(logo):
        logo = urljoin(base_url, logo)
    return {
        "id": get_first(record, ID_KEYS),
        "name": get_first(record, NAME_KEYS) or "Unnamed channel",
        "category": get_first(record, CATEGORY_KEYS) or "Uncategorized",
        "logo": logo,
        "stream_candidates": extract_streams(record),
    }


def write_outputs(channels):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Pinned item is forcibly first, independent of API order or API contents.
    # Remove accidental duplicate copies of the pinned channel from API results.
    api_channels = [
        channel for channel in channels
        if not (
            channel.get("name", "").strip().casefold() == "iptv links"
            and channel.get("working_stream") == PINNED_CHANNEL["working_stream"]
        )
    ]
    final_channels = [PINNED_CHANNEL] + api_channels

    (OUT_DIR / "BD-KB-IT.json").write_text(
        json.dumps(final_channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # The fixed IPTV LINKS MP4 is intentionally included as the pinned first
    # playlist entry. Remaining entries are API-returned, validated M3U8 URLs.
    lines = ["#EXTM3U"]
    for channel in final_channels:
        name = channel.get("name", "Unnamed channel")
        logo = channel.get("logo", "")
        category = channel.get("category", "Uncategorized")
        channel_id = channel.get("id", "")
        stream = channel.get("working_stream", "")
        lines.append(
            f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{name}" '
            f'tvg-logo="{logo}" group-title="{category}",{name}'
        )
        lines.append(stream)
    (OUT_DIR / "BD-KB-IT.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # This file lists every exported entry, including the pinned MP4 item.
    (OUT_DIR / "BD-KB-IT-WORKING.txt").write_text(
        "\n".join(f'{c["name"]} | {c["working_stream"]}' for c in final_channels) + "\n",
        encoding="utf-8",
    )
    summary = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pinned_first_channel": PINNED_CHANNEL["name"],
        "api_working_m3u8": len(api_channels),
        "total_playlist_entries": len(final_channels),
    }
    (OUT_DIR / "BD-KB-IT-STATUS.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(final_channels)} entries; IPTV LINKS is first.")


def run():
    api_url = os.getenv("BD_KB_IT_API_URL", "").strip()
    if not is_http_url(api_url):
        raise SystemExit("Set BD_KB_IT_API_URL to an authorized http(s) API URL in GitHub Secrets.")

    session = requests.Session()
    seen_pages, records, seen_records = set(), [], set()
    current_url = api_url
    max_pages = int(os.getenv("MAX_PAGES", "500"))

    for page_number in range(1, max_pages + 1):
        if current_url in seen_pages:
            print("Pagination loop detected; stopping safely.")
            break
        seen_pages.add(current_url)
        print(f"Fetching API page {page_number}...")
        payload = request_json(session, current_url)
        page_records = []
        find_candidate_records(payload, page_records)

        for record in page_records:
            key = json.dumps(record, sort_keys=True, ensure_ascii=False)
            if key not in seen_records:
                seen_records.add(key)
                records.append(normalize_record(record, current_url))

        next_url = get_next_url(payload, current_url)
        if not next_url:
            break
        current_url = next_url
    else:
        print(f"Reached MAX_PAGES={max_pages}; stopping.", file=sys.stderr)

    working_channels = []
    seen_channels = set()
    for channel in records:
        dedupe_key = (channel["name"], tuple(channel["stream_candidates"]))
        if dedupe_key in seen_channels:
            continue
        seen_channels.add(dedupe_key)

        for candidate in channel["stream_candidates"]:
            ok, status = validate_m3u8(session, candidate)
            if ok:
                channel["working_stream"] = candidate
                working_channels.append(channel)
                break
            print(f"Skipped non-working M3U8: {channel['name']} ({status})")

    write_outputs(working_channels)


def is_due(state_file, interval_minutes):
    if not state_file.exists():
        return True
    try:
        previous = float(state_file.read_text(encoding="utf-8").strip())
        return time.time() - previous >= interval_minutes * 60
    except (ValueError, OSError):
        return True


def main():
    parser = argparse.ArgumentParser(description="BD KB IT API-to-M3U updater")
    parser.add_argument("--if-due", action="store_true")
    parser.add_argument("--interval-minutes", type=int, default=105)
    parser.add_argument("--state-file", default="output/.last_update")
    args = parser.parse_args()

    state_file = Path(args.state_file)
    if args.if_due and not is_due(state_file, args.interval_minutes):
        print("Refresh interval has not elapsed; skipping.")
        return

    run()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(str(time.time()), encoding="utf-8")


if __name__ == "__main__":
    main()
