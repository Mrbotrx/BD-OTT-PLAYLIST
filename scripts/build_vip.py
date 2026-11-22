"""
IPTV VIP Aggregator — India + Bangla (সব working চ্যানেল, News সীমিত)
Health-check, classification, caching & resilience.
"""
import os
import re
import sys
import json
import time
import hashlib
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================== CONFIG ==================
# (label, environment variable) — secret থেকে আসে, repo-তে লেখা নেই
SOURCE_ENV = [
    ("India", "IPTV_SOURCE_URL"),
    ("Bangladesh", "IPTV_BD_SOURCE_URL"),
]

OUT_FILE   = Path("india/India_vip.m3u")
CACHE_FILE = Path(".cache/check_cache.json")
STATE_FILE = Path(".cache/state.json")

HEADER_TITLE = "Make by Kallyan Biswas"
FB_LINK      = "Www.Facebook.com/kallyan.biswas.29"
BOT_NAME     = "IND.bot"

CHECK_TIMEOUT      = 6
WORKERS            = 80
MAX_PER_CAT        = 0       # 0 = সব candidate check হবে
TOP_PER_CAT        = 0       # 0 = সীমা নেই (News আলাদা নিয়মে সীমিত)
MAX_LINKS_PER_NAME = 3       # একই নামের চ্যানেলের সর্বোচ্চ backup লিংক
CHECK_CHUNK        = 4096
CACHE_TTL          = 3600 * 3   # 3 ঘণ্টা, update cadence-এর সাথে মেলে
DOWNLOAD_RETRY     = 2

# ---- News নিয়ম ----
NEWS_CATEGORY = "News"
NEWS_MAX      = 20           # News-এ সর্বোচ্চ entry (backup লিংকসহ)

# জনপ্রিয় news channel — উপরের গুলো আগে নেওয়া হবে
NEWS_PRIORITY = [
    r"aaj\s*tak",
    r"ndtv\s*india|ndtv\s*24",
    r"india\s*today",
    r"republic\s*bharat|republic\s*tv",
    r"times\s*now",
    r"zee\s*news",
    r"abp\s*news|abp\s*ananda",
    r"news\s*18|news18",
    r"wion",
    r"dd\s*news",
    r"sudarshan",
    r"cnn",
    r"bbc",
    r"channel\s*24",
    r"channel\s*i\b",
    r"ekattor",
    r"jamuna",
    r"somoy|shomoy",
    r"desh\s*tv",
    r"atn\s*news|atn\s*bangla",
    r"independent\s*tv",
    r"rtv",
    r"btv",
]

LINK_LOGO = "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg"
LINK_URL  = "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"

# ================== CATEGORIES ==================
CATEGORIES = {
    "Jalsa": r"star\s*jalsha|\bjalsha\b|\bjalsa\b",
    "Zee": (
        r"\bzee\b|zee\s*tv|zee\s*bangla|zee\s*cinema|"
        r"zee\s*action|zee\s*cafe"
    ),
    "Star": (
        r"star\s*plus|star\s*gold|star\s*sports|"
        r"star\s*utsav|star\s*maa|star\s*bharat"
    ),
    "Music": (
        r"\bmusic\b|\bmtv\b|9xm|9x\s*jhatka|9x\s*tashan|"
        r"zoom|\bb4u\b|mastiii|mtunes|\bvh1\b|music\s*india"
    ),
    "Sports": (
        r"sports?|cricket|sony\s*sports|sports18|"
        r"ten\s*sports|eurosport|willow"
    ),
    "Kids": (
        r"cartoon|kids|\bnick\b|nickelodeon|\bpogo\b|"
        r"discovery\s*kids|\bsonic\b|disney|hungama"
    ),
    "Movies": (
        r"movies?|cinema|film|bollywood|"
        r"sony\s*max|max\s*2|colors\s*cineplex"
    ),
    "Entertainment": (
        r"entertainment|colors|sony|sab\s*tv|sun\s*tv|"
        r"gemini\s*tv|vijay\s*tv|asianet|life\s*ok|and\s*tv"
    ),
    "News": (
        r"news|ndtv|aaj\s*tak|india\s*tv|republic|"
        r"times\s*now|news18|\babp\b|tv9|"
        r"\bcnn\b|\bbbc\b|\bwion\b|mirror\s*now"
    ),
    "Infotainment": (
        r"discovery|national\s*geographic|nat\s*geo|"
        r"\bhistory\b|animal\s*planet|travel|food\s*network"
    ),
    "Devotional": (
        r"devotional|bhakti|spiritual|aastha|sanskar|"
        r"\bgod\b|shradha|darshan"
    ),
    "Lifestyle": r"lifestyle|fashion|\bfood\b|living|good\s*times|fox\s*life",
    "24/7": r"24\s*/?\s*7|24x7|24\s*hours?|non\s*stop",
    "Bangla": (
        r"bangla|bengali|bangladesh|"
        r"\bntv\b|\brtv\b|\batn\b|\bbtv\b|\bdbc\b|\bgtv\b|\bmytv\b|\bsa\s*tv\b|"
        r"somoy|shomoy|ekattor|jamuna|deepto|maasranga|boishakhi|"
        r"channel\s*i\b|channel\s*24|channel\s*9|independent\s*tv|"
        r"ekushey|nagorik|asian\s*tv|bangla\s*vision|rising\s*bd|"
        r"gazi|desh\s*tv|mohona|sangbad|news\s*24|news24|"
        r"dhaka|ekhon|ananda"
    ),
    "India": r"india|indian|hindi|regional",
}

# Classification-এর ক্রম (নাম → tvg-name → tvg-id → group-title)
# Indian brand আগে, তারপর Bangla, তারপর সাধারণ category
BRAND_ORDER = ["Jalsa", "Zee", "Star"]
CATEGORY_ORDER = [
    "Jalsa", "Zee", "Star", "Music", "Sports", "Kids",
    "Movies", "Entertainment", "News", "Infotainment",
    "Devotional", "Lifestyle", "24/7", "Bangla", "India",
]

# Pre-compiled
CATEGORY_PATTERNS = {k: re.compile(v, re.I) for k, v in CATEGORIES.items()}
NEWS_PRIORITY_RE  = [re.compile(p, re.I) for p in NEWS_PRIORITY]
HD_RE        = re.compile(r"\b(?:fhd|uhd|4k|hd|1080p?|720p?)\b", re.I)
SD_RE        = re.compile(r"\b(?:sd|360p?|480p?)\b", re.I)
ATTR_RE      = re.compile(r'([\w-]+)="([^"]*)"')
SAFE_NAME_RE = re.compile(r'[\x00-\x1f"\\]')

log = logging.getLogger("iptv")


# ================== DATA MODEL ==================
@dataclass
class Channel:
    name: str
    url: str
    attrs: dict = field(default_factory=dict)
    cat: Optional[str] = None
    latency: Optional[float] = None
    ok: bool = False
    score: float = 1e9

    def fingerprint(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()


# ================== SESSION ==================
def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=DOWNLOAD_RETRY, connect=DOWNLOAD_RETRY, read=1,
        backoff_factor=0.25,
        status_forcelist=(500, 502, 503, 504, 429),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=WORKERS,
        pool_maxsize=WORKERS,
        pool_block=False,
    )
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "Mozilla/5.0 (IPTV-Aggregator/2.0)"})
    return s


# ================== HELPERS ==================
def valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme.lower() in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def sanitize(name: str) -> str:
    return SAFE_NAME_RE.sub("", name).strip()


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[_\-./|()\[\]]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ================== PARSER ==================
def parse_m3u(text: str) -> list[Channel]:
    out: list[Channel] = []
    pending: Optional[dict] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            name = line.rsplit(",", 1)[-1].strip()
            pending = {"attrs": dict(ATTR_RE.findall(line)), "name": name}
        elif pending and not line.startswith("#"):
            if valid_url(line):
                out.append(Channel(name=pending["name"], url=line, attrs=pending["attrs"]))
            pending = None
    return out


# ================== CLASSIFY ==================
def is_bangla_attr(c: Channel) -> bool:
    country = c.attrs.get("tvg-country", "").strip().upper()
    lang    = c.attrs.get("tvg-language", "").strip().lower()
    return country in ("BD", "BANGLADESH") or "bengali" in lang or "bangla" in lang


def classify(c: Channel) -> Optional[str]:
    fields = [
        _normalize(c.name),
        _normalize(c.attrs.get("tvg-name", "")),
        _normalize(c.attrs.get("tvg-id", "")),
        _normalize(c.attrs.get("group-title", "")),
    ]
    fields = [f for f in fields if f]

    # 1) Indian brand: Zee Bangla, Star Jalsha ইত্যাদি আগে
    for cat in BRAND_ORDER:
        if any(CATEGORY_PATTERNS[cat].search(f) for f in fields):
            return cat

    # 2) Bangla keyword বা Bangladesh country/language — News/Entertainment-এর আগে
    if any(CATEGORY_PATTERNS["Bangla"].search(f) for f in fields):
        return "Bangla"
    if is_bangla_attr(c):
        return "Bangla"

    # 3) বাকি category, ক্রম অনুযায়ী
    for f in fields:
        for cat in CATEGORY_ORDER:
            if cat == "Bangla":
                continue
            if CATEGORY_PATTERNS[cat].search(f):
                return cat

    # 4) Country fallback
    country = c.attrs.get("tvg-country", "").strip().upper()
    if country in ("IN", "INDIA"):
        return "India"
    return None


# ================== CACHE ==================
class CheckCache:
    """Health-check ফলাফল সংরক্ষণ, TTL-এর মধ্যে আবার check হবে না।"""
    def __init__(self, path: Path, ttl: int):
        self.path, self.ttl = path, ttl
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            now = time.time()
            self.data = {k: v for k, v in raw.items()
                         if isinstance(v, dict) and now - v.get("ts", 0) < self.ttl}
        except Exception as e:
            log.warning("cache load failed: %s", type(e).__name__)

    def get(self, fp: str) -> Optional[dict]:
        v = self.data.get(fp)
        if v and time.time() - v.get("ts", 0) < self.ttl:
            return v
        return None

    def set(self, fp: str, ok: bool, latency: Optional[float]):
        self.data[fp] = {"ok": ok, "lat": latency, "ts": time.time()}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(json.dumps(self.data), "utf-8")
        except Exception as e:
            log.warning("cache save failed: %s", type(e).__name__)


# ================== HEALTH CHECK ==================
def check_channel(session: requests.Session, c: Channel) -> tuple[Channel, Optional[float]]:
    start = time.time()
    try:
        r = session.get(c.url, timeout=CHECK_TIMEOUT, stream=True, allow_redirects=True)
        try:
            if r.status_code != 200:
                return c, None
            content_type = r.headers.get("Content-Type", "").lower()
            chunk = next(r.iter_content(CHECK_CHUNK), b"")
            if not chunk:
                return c, None
            # HLS playlist যাচাই
            if ".m3u8" in c.url.lower():
                if "#EXTM3U" not in chunk.decode("utf-8", errors="ignore"):
                    return c, None
            # HTML error page বাদ
            if "text/html" in content_type:
                return c, None
        finally:
            r.close()
        return c, time.time() - start
    except Exception:
        # যেকোনো error একটি channel-কে বাদ দেবে, পুরো run-কে নয়
        return c, None


def score_channel(c: Channel) -> float:
    """কম মান = ভালো।"""
    s = c.latency or 1e9
    if HD_RE.search(c.name):
        s -= 0.40
    if SD_RE.search(c.name):
        s += 0.20
    if c.attrs.get("tvg-logo"):
        s -= 0.15
    if c.attrs.get("tvg-id"):
        s -= 0.05
    if "backup" in c.name.lower():
        s += 0.50
    return s


def news_rank(c: Channel) -> int:
    """জনপ্রিয় news channel-এর ক্রম; তালিকায় না থাকলে শেষে।"""
    n = _normalize(c.name)
    for i, pat in enumerate(NEWS_PRIORITY_RE):
        if pat.search(n):
            return i
    return len(NEWS_PRIORITY_RE)


# ================== SOURCE LOADER ==================
def load_sources(session: requests.Session) -> list[Channel]:
    channels: list[Channel] = []
    for label, env in SOURCE_ENV:
        url = os.environ.get(env, "").strip()
        if not url:
            log.warning("%s source: secret %s সেট নেই, skip", label, env)
            continue
        try:
            log.info("%s source downloading...", label)
            r = session.get(url, timeout=30)
            r.raise_for_status()
            parsed = parse_m3u(r.text)
            log.info("   %s → %d channels", label, len(parsed))
            channels.extend(parsed)
        except Exception as e:
            # URL log করা হচ্ছে না, error message-এ secret URL থাকতে পারে
            log.warning("%s source failed: %s", label, type(e).__name__)
    if not channels:
        raise RuntimeError("কোনো source থেকে channel পাওয়া যায়নি; আগের playlist রাখা হলো")
    return channels


# ================== PICKING ==================
def pick_channels(cat: str, pool: list[Channel]) -> list[Channel]:
    """একটি category থেকে চূড়ান্ত তালিকা বাছাই।
    News: জনপ্রিয় channel আগে, মোট NEWS_MAX পর্যন্ত।
    বাকিগুলো: score অনুযায়ী, সীমা TOP_PER_CAT (0 = সীমা নেই)।
    """
    if cat == NEWS_CATEGORY:
        pool.sort(key=lambda c: (news_rank(c), c.score))
        limit = NEWS_MAX
    else:
        pool.sort(key=lambda c: c.score)
        limit = TOP_PER_CAT

    picked: list[Channel] = []
    per_name: dict[str, int] = {}
    for c in pool:
        key = c.name.strip().lower()
        if per_name.get(key, 0) >= MAX_LINKS_PER_NAME:
            continue
        per_name[key] = per_name.get(key, 0) + 1
        picked.append(c)
        if limit > 0 and len(picked) >= limit:
            break
    return picked


# ================== MAIN PIPELINE ==================
def build_playlist(skip_cache: bool = False, dry_run: bool = False) -> int:
    session = build_session()

    # 1. Load
    raw = load_sources(session)

    # 2. Dedupe by URL
    seen, uniq = set(), []
    for c in raw:
        if c.url in seen:
            continue
        seen.add(c.url)
        uniq.append(c)
    log.info("unique channels: %d (dropped %d duplicates)", len(uniq), len(raw) - len(uniq))

    # 3. Classify
    buckets: dict[str, list[Channel]] = {k: [] for k in CATEGORY_ORDER}
    unclassified = 0
    for c in uniq:
        cat = classify(c)
        if cat:
            c.cat = cat
            buckets[cat].append(c)
        else:
            unclassified += 1
    for cat in CATEGORY_ORDER:
        log.info("   candidates %-14s %d", cat, len(buckets[cat]))
    log.info("   unclassified        %d", unclassified)

    # 4. Candidate selection (logo আগে; MAX_PER_CAT=0 হলে সব)
    candidates: list[Channel] = []
    for cat in CATEGORY_ORDER:
        pool = sorted(buckets[cat], key=lambda x: not x.attrs.get("tvg-logo"))
        candidates.extend(pool if MAX_PER_CAT <= 0 else pool[:MAX_PER_CAT])

    # 5. Health-check with cache
    cache = CheckCache(CACHE_FILE, CACHE_TTL)
    if skip_cache:
        cache.data.clear()

    alive: list[Channel] = []
    to_check: list[Channel] = []
    for c in candidates:
        hit = cache.get(c.fingerprint())
        if hit:
            if hit["ok"]:
                c.latency = hit["lat"]
                c.ok = True
                alive.append(c)
            continue
        to_check.append(c)

    log.info("cache hits: %d | to check: %d", len(candidates) - len(to_check), len(to_check))

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(check_channel, session, c): c for c in to_check}
        done = 0
        for f in as_completed(futures):
            item, lat = f.result()
            done += 1
            cache.set(item.fingerprint(), lat is not None, lat)
            if lat is not None:
                item.latency = lat
                item.ok = True
                alive.append(item)
            if done % 200 == 0:
                log.info("   …%d/%d checked, alive=%d", done, len(to_check), len(alive))
    cache.save()

    log.info("working links: %d", len(alive))

    # 6. Score & pick
    groups: dict[str, list[Channel]] = {}
    for cat in CATEGORY_ORDER:
        pool = [c for c in alive if c.cat == cat]
        for c in pool:
            c.score = score_channel(c)
        groups[cat] = pick_channels(cat, pool)
        log.info("   working/picked %-14s %d/%d", cat, len(pool), len(groups[cat]))

    # 7. Guard
    if sum(len(v) for v in groups.values()) == 0:
        raise RuntimeError("no working channels found; keeping previous playlist")

    if dry_run:
        log.info("dry-run: playlist লেখা হলো না")
        return 0

    # 8. Write
    total = write_playlist(groups)
    write_state(groups, total)
    return total


# ================== OUTPUT ==================
def write_playlist(groups: dict[str, list[Channel]]) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # প্রতিটি category/group-এ IPTV LINKS থাকবে, খালি group-এও
    cats = list(CATEGORY_ORDER)
    total = sum(len(groups.get(cat, [])) + 1 for cat in cats)

    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{BOT_NAME} India + Bangla VIP",
        f"# {HEADER_TITLE}",
        f"# Facebook: {FB_LINK}",
        f"# Bot: {BOT_NAME} | Auto Best-Channel System | Update: every 3 hours",
        f"# Last updated: {now}",
        f"# Total entries: {total}",
    ]
    for cat in cats:
        items = groups.get(cat, [])
        lines.append(f"# [{cat}] channels: {len(items) + 1}")
    lines.append("")

    for cat in cats:
        items = groups.get(cat, [])
        lines += [
            f'#EXTINF:-1 tvg-id="" tvg-name="IPTV LINKS" tvg-logo="{LINK_LOGO}" '
            f'group-title="{cat}",IPTV LINKS',
            LINK_URL,
        ]
        for c in items:
            a    = c.attrs
            name = sanitize(c.name)
            lines.append(
                f'#EXTINF:-1 tvg-id="{sanitize(a.get("tvg-id", ""))}" tvg-name="{name}" '
                f'tvg-logo="{sanitize(a.get("tvg-logo", ""))}" group-title="{cat}",{name}'
            )
            lines.append(c.url)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s (%d entries)", OUT_FILE, total)
    return total


def write_state(groups: dict[str, list[Channel]], total: int):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lat_values = [c.latency for v in groups.values() for c in v if c.latency is not None]
    state = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "per_category": {k: len(v) for k, v in groups.items()},
        "avg_latency_ms": round(1000 * sum(lat_values) / max(1, len(lat_values)), 1),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), "utf-8")


# ================== CLI ==================
def main():
    parser = argparse.ArgumentParser(description="IPTV VIP Aggregator")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="cache উপেক্ষা করে সব আবার check")
    parser.add_argument("--dry-run", action="store_true", help="check only, playlist লেখা হবে না")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.time()
    try:
        total = build_playlist(skip_cache=args.no_cache, dry_run=args.dry_run)
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)
    log.info("done in %.1fs — %d entries", time.time() - t0, total)


if __name__ == "__main__":
    main()
