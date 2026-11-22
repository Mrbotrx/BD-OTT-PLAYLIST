import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

# ================== CONFIG ==================
SOURCES = [
    s.strip() for s in (
        os.environ.get("IPTV_SOURCE_URL", ""),       # India playlist (hidden secret)
        os.environ.get("IPTV_BD_SOURCE_URL", ""),    # Bangladesh playlist (hidden secret)
    ) if s.strip()
]
OUT_FILE = "india/India_vip.m3u"
HEADER_TITLE = "Make by Kallyan Biswas"
FB_LINK = "Www.Facebook.com/kallyan.biswas.29"
BOT_NAME = "IND.bot"

CHECK_TIMEOUT = 6
WORKERS = 60
MAX_PER_CAT = 150
TOP_PER_CAT = 10

LINK_LOGO = "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg"
LINK_URL = "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"

# ক্রম গুরুত্বপূর্ণ: প্রথম মিলটাই ধরা হবে
# Bangla সবশেষে, যাতে Zee Bangla / Star Jalsha আগেই Zee / Jalsa-তে যায়
CATEGORIES = {
    "Movies": r"\bmovies?\b|\bcinema\b|\bbollywood\b|\bpix\b|\bmax\b",
    "24/7":   r"24\s*/?\s*7|24x7",
    "Jalsa":  r"\bjalsa\b",
    "Zee":    r"\bzee\b",
    "Star":   r"\bstar\b",
    "India":  r"\bindia\b|\bsony\b|\bcolors\b|\bndtv\b|\baaj\b|\bdd\b|\bnews\b",
    "Bangla": (
        r"\bbangla\b|\bbengali\b|\bbangladesh\b|\bbd\b|\bntv\b|\brtv\b|\batn\b|"
        r"\bsomoy\b|\bekattor\b|\bjamuna\b|\bdeepto\b|\bmaasranga\b|\bboishakhi\b|"
        r"\bchannel\s*i\b|\bdbc\b|\bgazi\b|\bdesh\b|\bmohona\b|\bsangbad\b|"
        r"\bbtv\b|\bnews24\b|\bdhaka\b|\bsa\s*tv\b|\bekhon\b|\bgtv\b|\bmyTV\b"
    ),
}

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def parse_m3u(text):
    items, info = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            name = line.rsplit(",", 1)[-1].strip()
            info = {"attrs": dict(ATTR_RE.findall(line)), "name": name}
        elif not line.startswith("#") and info:
            info["url"] = line
            items.append(info)
            info = None
    return items


def is_bangla_attr(item):
    """Bangladesh country বা Bengali/Bangla language হলে Bangla ধরবে"""
    a = item["attrs"]
    country = a.get("tvg-country", "").upper()
    lang = a.get("tvg-language", "").lower()
    return country == "BD" or "bengali" in lang or "bangla" in lang


def classify(item):
    """প্রথমে নামের ভিত্তিতে, না মিললে attribute দিয়ে Bangla যাচাই"""
    for cat, pattern in CATEGORIES.items():
        if re.search(pattern, item["name"], re.I):
            return cat
    if is_bangla_attr(item):
        return "Bangla"
    return None


def check_link(item):
    start = time.time()
    try:
        r = requests.get(
            item["url"],
            timeout=CHECK_TIMEOUT,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        ok = r.status_code == 200
        if ok:
            chunk = next(r.iter_content(1024), b"")
            ok = len(chunk) > 0
        r.close()
        return item, (time.time() - start) if ok else None
    except Exception:
        return item, None


def score(item):
    s = item["lat"]
    if re.search(r"\bfhd\b|\bhd\b|1080|720", item["name"], re.I):
        s -= 0.3
    return s


def load_all_sources():
    if not SOURCES:
        sys.exit("ERROR: IPTV_SOURCE_URL / IPTV_BD_SOURCE_URL secret সেট করা নেই")
    channels = []
    for url in SOURCES:
        try:
            print("Downloading a source playlist...")
            channels.extend(parse_m3u(requests.get(url, timeout=30).text))
        except Exception as e:
            print(f"Source failed, skipping: {type(e).__name__}")
    return channels


def main():
    channels = load_all_sources()

    # duplicate URL বাদ
    seen, uniq = set(), []
    for c in channels:
        if c["url"] not in seen:
            seen.add(c["url"])
            uniq.append(c)
    print(f"Parsed {len(uniq)} unique channels")

    buckets = {k: [] for k in CATEGORIES}
    for c in uniq:
        cat = classify(c)
        if cat:
            c["cat"] = cat
            buckets[cat].append(c)

    # logo আছে এমন চ্যানেল আগে চেক
    candidates = []
    for cat in CATEGORIES:
        pool = sorted(buckets[cat], key=lambda c: not c["attrs"].get("tvg-logo"))
        candidates.extend(pool[:MAX_PER_CAT])
    print(f"Checking {len(candidates)} candidate links...")

    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(check_link, c) for c in candidates]
        for f in as_completed(futures):
            item, lat = f.result()
            if lat is not None:
                item["lat"] = lat
                alive.append(item)
    print(f"Working links: {len(alive)}")

    groups = {}
    for cat in CATEGORIES:
        pool = sorted((c for c in alive if c["cat"] == cat), key=score)
        picked, names = [], set()
        for c in pool:
            key = c["name"].lower()
            if key in names:
                continue
            names.add(key)
            picked.append(c)
            if len(picked) >= TOP_PER_CAT:
                break
        groups[cat] = picked

    # ================== OUTPUT ==================
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(v) + 1 for v in groups.values())

    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{BOT_NAME} India + Bangla VIP",
        f"# {HEADER_TITLE}",
        f"# Facebook: {FB_LINK}",
        f"# Bot: {BOT_NAME} | Auto Best-Channel System | Update: every 3 hours",
        f"# Last updated: {now}",
        f"# Total channels: {total}",
    ]
    for cat, items in groups.items():
        lines.append(f"# [{cat}] channels: {len(items) + 1}")
    lines.append("")

    for cat, items in groups.items():
        lines.append(
            f'#EXTINF:-1 tvg-id="" tvg-name="IPTV LINKS" tvg-logo="{LINK_LOGO}" '
            f'group-title="{cat}",IPTV LINKS'
        )
        lines.append(LINK_URL)

        for c in items:
            a = c["attrs"]
            name = c["name"].replace('"', "")
            lines.append(
                f'#EXTINF:-1 tvg-id="{a.get("tvg-id", "")}" tvg-name="{name}" '
                f'tvg-logo="{a.get("tvg-logo", "")}" group-title="{cat}",{name}'
            )
            lines.append(c["url"])

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Done. Written to {OUT_FILE} with {total} entries.")


if __name__ == "__main__":
    main()
