#!/usr/bin/env python3
"""BD KB IT: collect authorized M3U8 URLs from a paginated JSON API."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
M3U_FILE = OUT / "BD-KB-IT.m3u"
JSON_FILE = OUT / "BD-KB-IT.json"
TXT_FILE = OUT / "BD-KB-IT-WORKING.txt"
STATUS_FILE = OUT / "BD-KB-IT-STATUS.json"
DIAG_FILE = OUT / "BD-KB-IT-DIAGNOSTICS.json"

PINNED = {
    "id": "",
    "name": "IPTV LINKS",
    "logo": "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg",
    "group": "KB PRO TV",
    "url": "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4",
}

NAME_KEYS = ("name", "title", "channel_name", "tvg-name", "label", "display_name")
ID_KEYS = ("id", "uuid", "channel_id", "tvg-id")
LOGO_KEYS = ("logo", "image", "icon", "thumbnail", "poster", "tvg-logo")
GROUP_KEYS = ("group", "category", "category_name", "group_title", "genre")
URL_KEYS = ("url", "stream_url", "stream", "play_url", "link", "hls", "m3u8", "source")


def env_headers():
    headers = {"User-Agent": "BD-KB-IT/3.0", "Accept": "application/json"}
    token = os.getenv("BD_KB_IT_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    extra = os.getenv("BD_KB_IT_EXTRA_HEADERS", "").strip()
    if extra:
        try:
            obj = json.loads(extra)
            if isinstance(obj, dict):
                headers.update({str(k): str(v) for k, v in obj.items()})
        except json.JSONDecodeError as exc:
            raise ValueError("BD_KB_IT_EXTRA_HEADERS must be a valid JSON object") from exc
    return headers


def first_value(obj, keys):
    for key in keys:
        value = obj.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def find_m3u8(value):
    found = []
    if isinstance(value, str):
        if ".m3u8" in value.lower():
            # Handles URLs with query strings and JSON-escaped URLs.
            match = re.search(r'https?://[^\s"\\<>]+?\.m3u8(?:\?[^\s"\\<>]*)?', value, re.I)
            if match:
                found.append(match.group(0).rstrip("),]"))
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(find_m3u8(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_m3u8(child))
    return list(dict.fromkeys(found))


def walk_records(node, inherited_group="", results=None):
    if results is None:
        results = []
    if isinstance(node, dict):
        own_group = first_value(node, GROUP_KEYS) or inherited_group
        urls = []
        for key in URL_KEYS:
            if key in node:
                urls.extend(find_m3u8(node[key]))
        # Search all fields, including nested stream objects, but only associate
        # a URL with this object when this object has a recognizable display name.
        if not urls:
            urls = find_m3u8(node)
        name = first_value(node, NAME_KEYS)
        if name and urls:
            results.append({
                "id": first_value(node, ID_KEYS),
                "name": name,
                "logo": first_value(node, LOGO_KEYS),
                "group": own_group or "Uncategorized",
                "url": urls[0],
            })
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk_records(value, own_group, results)
    elif isinstance(node, list):
        for item in node:
            walk_records(item, inherited_group, results)
    return results


def pagination_info(data, current_url):
    """Return (next URL, has_more, cursor) from common pagination shapes."""
    next_url = ""
    has_more = False
    cursor = ""
    if not isinstance(data, dict):
        return next_url, has_more, cursor

    def inspect(obj):
        nonlocal next_url, has_more, cursor
        if not isinstance(obj, dict):
            return
        for k in ("next_url", "next", "next_page_url"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                next_url = v.strip()
                break
            if isinstance(v, dict) and isinstance(v.get("url"), str):
                next_url = v["url"].strip()
                break
        has_more = has_more or obj.get("has_more") is True or obj.get("hasMore") is True
        for k in ("next_cursor", "nextCursor", "cursor"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                cursor = v.strip()
                break
        for v in obj.values():
            if isinstance(v, dict):
                inspect(v)

    inspect(data)
    if next_url:
        return urljoin(current_url, next_url), has_more, cursor
    if has_more and cursor:
        parsed = urlparse(current_url)
        # This API exposes subsequent live-TV blocks at /blocks?cursor=...
        base = f"{parsed.scheme}://{parsed.netloc}/api/v5/pages/live-tvs/blocks"
        return f"{base}?cursor={requests.utils.quote(cursor, safe='')}", has_more, cursor
    return "", has_more, cursor


def fetch_pages(api_url, headers, max_pages=500):
    session = requests.Session()
    session.headers.update(headers)
    current = api_url
    seen = set()
    all_records, diagnostics = [], []
    for page_no in range(1, max_pages + 1):
        if not current or current in seen:
            break
        seen.add(current)
        response = session.get(current, timeout=30)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"API page {page_no} did not return JSON") from exc
        records = walk_records(data)
        all_records.extend(records)
        next_url, has_more, cursor = pagination_info(data, current)
        diagnostics.append({
            "page": page_no,
            "http_status": response.status_code,
            "records_detected": len(records),
            "has_more": has_more,
            "next_url_found": bool(next_url),
            "cursor_found": bool(cursor),
        })
        if not next_url:
            break
        current = next_url
    return all_records, diagnostics


def check_hls(url, headers, timeout=12):
    """Check that the API-provided URL responds with an HLS playlist."""
    try:
        response = requests.get(
            url, headers={**headers, "Range": "bytes=0-4095"},
            timeout=timeout, allow_redirects=True, stream=True
        )
        if response.status_code not in (200, 206):
            response.close()
            return False
        content_type = response.headers.get("Content-Type", "").lower()
        chunk = next(response.iter_content(chunk_size=4096), b"")
        response.close()
        return b"#EXTM3U" in chunk or "mpegurl" in content_type or url.lower().split("?")[0].endswith(".m3u8")
    except requests.RequestException:
        return False


def write_outputs(records, diagnostics):
    OUT.mkdir(parents=True, exist_ok=True)
    # Keep one entry per stream URL, preserving first-seen order.
    unique, seen = [], set()
    for row in records:
        url = row.get("url", "").strip()
        if url and url not in seen:
            seen.add(url)
            unique.append(row)

    # Pinned entry is always first and is not subjected to API validation.
    lines = ["#EXTM3U", (
        f'#EXTINF:-1 tvg-id="{PINNED["id"]}" tvg-name="{PINNED["name"]}" '
        f'tvg-logo="{PINNED["logo"]}" group-title="{PINNED["group"]}",{PINNED["name"]}'
    ), PINNED["url"]]
    for row in unique:
        def clean(v):
            return str(v or "").replace('"', "'").replace("\r", " ").replace("\n", " ").strip()
        lines.append(
            f'#EXTINF:-1 tvg-id="{clean(row.get("id"))}" '
            f'tvg-name="{clean(row.get("name"))}" tvg-logo="{clean(row.get("logo"))}" '
            f'group-title="{clean(row.get("group") or "Uncategorized")}",{clean(row.get("name"))}'
        )
        lines.append(row["url"])
    M3U_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    JSON_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    TXT_FILE.write_text("\n".join(r["url"] for r in unique) + ("\n" if unique else ""), encoding="utf-8")
    DIAG_FILE.write_text(json.dumps({
        "pages": diagnostics,
        "pages_fetched": len(diagnostics),
        "channels_detected": len(unique),
        "note": "A detected channel requires a name and an M3U8 URL in related JSON data."
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-due", action="store_true")
    parser.add_argument("--interval-minutes", type=int, default=105)
    args = parser.parse_args()

    api_url = os.getenv("BD_KB_IT_API_URL", "").strip()
    if not api_url.startswith(("http://", "https://")):
        print("Set BD_KB_IT_API_URL to an authorized http(s) API URL in GitHub Secrets.", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    if args.if_due and STATUS_FILE.exists():
        try:
            last = int(json.loads(STATUS_FILE.read_text()).get("last_success_epoch", 0))
            if now - last < args.interval_minutes * 60:
                print("Not due yet; keeping existing playlist.")
                return 0
        except (ValueError, json.JSONDecodeError):
            pass

    try:
        headers = env_headers()
        records, diagnostics = fetch_pages(api_url, headers)
        if not records:
            raise RuntimeError("No channel records detected. Check BD-KB-IT-DIAGNOSTICS after supplying a valid API response.")
        working = [r for r in records if check_hls(r["url"], headers)]
        if not working:
            raise RuntimeError("No working HLS playlists found; existing output was not overwritten.")
        write_outputs(working, diagnostics)
        STATUS_FILE.write_text(json.dumps({
            "last_success_epoch": now,
            "last_success_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "working_channels": len(working)
        }, indent=2), encoding="utf-8")
        print(f"Done: {len(working)} working channels from {len(diagnostics)} API pages.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
