import os, re, json, time, argparse
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import requests

OUT = Path("output")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))
URL_RE = re.compile(r"^https?://", re.I)
M3U8_RE = re.compile(r"\.m3u8(?:$|[?#])", re.I)

# Always the first item in BD-KB-IT.m3u
PINNED = {
    "id": "",
    "name": "IPTV LINKS",
    "logo": "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg",
    "category": "KB PRO TV",
    "stream": "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"
}

NAME_KEYS = ("name", "title", "channel_name", "channelName", "channel_title", "label", "display_name")
ID_KEYS = ("id", "channel_id", "channelId", "uuid", "slug", "tvg_id")
LOGO_KEYS = ("logo", "logo_url", "logoUrl", "image", "image_url", "imageUrl", "thumbnail", "icon", "poster")
CAT_KEYS = ("category", "category_name", "categoryName", "group", "group_title", "groupTitle", "genre", "section_title")
STREAM_KEYS = ("url", "stream_url", "streamUrl", "hls", "hls_url", "hlsUrl", "m3u8", "play_url", "playback_url", "source", "file", "src", "link")

def headers():
    h = {"User-Agent": os.getenv("HTTP_USER_AGENT", "BD-KB-IT/1.2"), "Accept": "application/json, */*"}
    token = os.getenv("BD_KB_IT_API_TOKEN", "").strip()
    if token:
        h["Authorization"] = "Bearer " + token
    extra = os.getenv("BD_KB_IT_EXTRA_HEADERS", "").strip()
    if extra:
        obj = json.loads(extra)
        if not isinstance(obj, dict):
            raise ValueError("BD_KB_IT_EXTRA_HEADERS must be a JSON object")
        h.update({str(k): str(v) for k, v in obj.items()})
    return h

def is_url(v):
    return isinstance(v, str) and bool(URL_RE.match(v.strip()))

def first(obj, keys):
    if not isinstance(obj, dict):
        return ""
    for k in keys:
        v = obj.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()
        if isinstance(v, dict):
            for sk in ("url", "src", "href", "path"):
                if isinstance(v.get(sk), str):
                    return v[sk].strip()
    return ""

def urls_in(node):
    if isinstance(node, dict):
        return sum((urls_in(v) for v in node.values()), [])
    if isinstance(node, list):
        return sum((urls_in(v) for v in node), [])
    if isinstance(node, str) and is_url(node.strip()):
        return [node.strip()]
    return []

def streams_for(obj):
    preferred = []
    for k in STREAM_KEYS:
        if k in obj:
            preferred.extend(urls_in(obj[k]))
    result, seen = [], set()
    for u in preferred + urls_in(obj):
        if M3U8_RE.search(u) and u not in seen:
            seen.add(u)
            result.append(u)
    return result

def walk(node, inherited_category="", base_url=""):
    """Walk nested API data and inherit category/group labels from parent blocks."""
    found = []
    if isinstance(node, list):
        for item in node:
            found.extend(walk(item, inherited_category, base_url))
        return found
    if not isinstance(node, dict):
        return found

    cat = first(node, CAT_KEYS) or inherited_category
    name = first(node, NAME_KEYS)
    stream_urls = streams_for(node)
    if name and stream_urls:
        logo = first(node, LOGO_KEYS)
        if logo and not is_url(logo):
            logo = urljoin(base_url, logo)
        found.append({
            "id": first(node, ID_KEYS),
            "name": name,
            "logo": logo,
            "category": cat or "Uncategorized",
            "stream_candidates": stream_urls
        })
        return found

    for value in node.values():
        if isinstance(value, (dict, list)):
            found.extend(walk(value, cat, base_url))
    return found

def next_url(data, current):
    if not isinstance(data, dict):
        return None
    containers = [data] + [data[k] for k in ("pagination", "meta", "links") if isinstance(data.get(k), dict)]
    for obj in containers:
        nxt = obj.get("next_url") or obj.get("nextUrl")
        if isinstance(nxt, str) and nxt.strip():
            return urljoin(current, nxt.strip())
    pg = data.get("pagination", {})
    if isinstance(pg, dict) and pg.get("has_more", pg.get("hasMore", False)):
        cursor = pg.get("next_cursor") or pg.get("nextCursor")
        if cursor:
            p = urlparse(current)
            q = parse_qs(p.query, keep_blank_values=True)
            q["cursor"] = [str(cursor)]
            return urlunparse(p._replace(query=urlencode(q, doseq=True)))
    return None

def check_m3u8(session, url):
    try:
        r = session.get(url, headers={**headers(), "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*"},
                        timeout=TIMEOUT, stream=True, allow_redirects=True)
        status = r.status_code
        ctype = r.headers.get("Content-Type", "").lower()
        prefix = next(r.iter_content(1024), b"")
        r.close()
        return status == 200 and (b"#EXTM3U" in prefix or "mpegurl" in ctype or "m3u8" in ctype)
    except requests.RequestException:
        return False

def collect(api_url):
    s = requests.Session()
    page, visited, records, seen = api_url, set(), [], set()
    for n in range(1, MAX_PAGES + 1):
        if not page or page in visited:
            break
        visited.add(page)
        print(f"Reading API page {n}")
        r = s.get(page, headers=headers(), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for item in walk(data, base_url=page):
            key = (item["id"], item["name"], tuple(item["stream_candidates"]))
            if key not in seen:
                seen.add(key)
                records.append(item)
        page = next_url(data, page)

    working = []
    for item in records:
        for candidate in item["stream_candidates"]:
            if check_m3u8(s, candidate):
                item["working_stream"] = candidate
                working.append(item)
                break
    return working

def export(channels):
    OUT.mkdir(exist_ok=True)
    # Remove duplicate copy of the fixed entry, then pin it at position one.
    rest = [c for c in channels if not (
        c["name"].casefold() == "iptv links" and
        c.get("working_stream") == PINNED["stream"]
    )]
    all_items = [PINNED] + rest

    (OUT / "BD-KB-IT.json").write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["#EXTM3U"]
    for c in all_items:
        name = str(c.get("name", "Unnamed")).replace('"', "'")
        logo = str(c.get("logo", "")).replace('"', "%22")
        cat = str(c.get("category", "Uncategorized")).replace('"', "'")
        cid = str(c.get("id", "")).replace('"', "'")
        stream = c.get("working_stream") or c.get("stream", "")
        lines += [f'#EXTINF:-1 tvg-id="{cid}" tvg-name="{name}" tvg-logo="{logo}" group-title="{cat}",{name}', stream]
    (OUT / "BD-KB-IT.m3u").write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    (OUT / "BD-KB-IT-WORKING.txt").write_text(
        "\\n".join(f'{c["name"]} | {c.get("working_stream") or c.get("stream", "")}' for c in all_items) + "\\n",
        encoding="utf-8")
    status = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_working_channels": len(rest),
        "playlist_entries_including_pinned": len(all_items),
        "categories": sorted({c.get("category", "Uncategorized") for c in rest})
    }
    (OUT / "BD-KB-IT-STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(all_items)} entries; IPTV LINKS is first.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-due", action="store_true")
    ap.add_argument("--interval-minutes", type=int, default=105)
    ap.add_argument("--state-file", default="output/.last_update")
    args = ap.parse_args()
    state = Path(args.state_file)
    if args.if_due and state.exists():
        try:
            if time.time() - float(state.read_text()) < args.interval_minutes * 60:
                print("Not due yet; skipping.")
                return
        except (ValueError, OSError):
            pass
    api = os.getenv("BD_KB_IT_API_URL", "").strip()
    if not is_url(api):
        raise SystemExit("Set BD_KB_IT_API_URL in GitHub Actions Secrets.")
    channels = collect(api)
    export(channels)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(str(time.time()))

if __name__ == "__main__":
    main()
