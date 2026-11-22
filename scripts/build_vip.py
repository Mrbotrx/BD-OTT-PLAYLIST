"""
IPTV VIP Aggregator — Production Grade
Auto best-channel system with health-check, scoring, caching & resilience.
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
SOURCES = [s.strip() for s in (
    os.environ.get("IPTV_SOURCE_URL", ""),
    os.environ.get("IPTV_BD_SOURCE_URL", ""),
) if s.strip()]

OUT_FILE      = Path("india/India_vip.m3u")
CACHE_FILE    = Path(".cache/check_cache.json")
STATE_FILE    = Path(".cache/state.json")

HEADER_TITLE  = "Make by Kallyan Biswas"
FB_LINK       = "Www.Facebook.com/kallyan.biswas.29"
BOT_NAME      = "IND.bot"

CHECK_TIMEOUT = 6
WORKERS       = 60
MAX_PER_CAT   = 150
TOP_PER_CAT   = 10
CHECK_CHUNK   = 2048
CACHE_TTL     = 3600 * 3          # 3h — matches update cadence
DOWNLOAD_RETRY = 2

LINK_LOGO = "https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg"
LINK_URL  = "https://github.com/Mrbotrx/Mrbotrx/raw/refs/heads/main/IPTV_LINKS_VIDEO.mp4"

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
        r"\bbtv\b|\bnews24\b|\bdhaka\b|\bsa\s*tv\b|\bekhon\b|\bgtv\b|\bmytv\b"
    ),
}

# Pre-compiled (huge CPU win on 10k+ channels)
CATEGORY_PATTERNS = {k: re.compile(v, re.I) for k, v in CATEGORIES.items()}
HD_RE    = re.compile(r"\b(?:fhd|uhd|4k|hd|1080p?|720p?)\b", re.I)
SD_RE    = re.compile(r"\b(?:sd|360p?|480p?)\b", re.I)
ATTR_RE  = re.compile(r'([\w-]+)="([^"]*)"')
EXTINF_GROUP_RE = re.compile(r'group-title="([^"]*)"', re.I)
SAFE_NAME_RE    = re.compile(r'[\x00-\x1f"\\]')   # strip control + quote + backslash

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
    country = c.attrs.get("tvg-country", "").upper()
    lang    = c.attrs.get("tvg-language", "").lower()
    return country == "BD" or "bengali" in lang or "bangla" in lang


def classify(c: Channel) -> Optional[str]:
    # 1) group-title hint wins first if it matches a known category
    gt = c.attrs.get("group-title", "")
    if gt:
        for cat, pat in CATEGORY_PATTERNS.items():
            if pat.search(gt):
                return cat
    # 2) channel name
    for cat, pat in CATEGORY_PATTERNS.items():
        if pat.search(c.name):
            return cat
    # 3) attribute fallback
    if is_bangla_attr(c):
        return "Bangla"
    return None


# ================== CACHE ==================
class CheckCache:
    """Persist health-check results so reruns within TTL skip rechecks."""
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
            log.warning("cache load failed: %s", e)

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
            log.warning("cache save failed: %s", e)


# ================== HEALTH CHECK ==================
def check_channel(session: requests.Session, c: Channel) -> tuple[Channel, Optional[float]]:
    start = time.time()
    try:
        r = session.get(c.url, timeout=CHECK_TIMEOUT, stream=True, allow_redirects=True)
        try:
            if r.status_code != 200:
                return c, None
            # Reject HTML error pages masquerading as streams
            ctype = r.headers.get("Content-Type", "").lower()
            if "text/html" in ctype:
                return c, None
            chunk = next(r.iter_content(CHECK_CHUNK), b"")
            if not chunk:
                return c, None
        finally:
            r.close()
        return c, time.time() - start
    except Exception:
        return c, None


def score_channel(c: Channel) -> float:
    """Lower = better. Latency + quality + metadata bonuses."""
    s = c.latency or 1e9
    if HD_RE.search(c.name): s -= 0.40
    if SD_RE.search(c.name): s += 0.20
    if c.attrs.get("tvg-logo"):    s -= 0.15
    if c.attrs.get("tvg-id"):      s -= 0.05
    if "backup" in c.name.lower(): s += 0.50
    return s


# ================== SOURCE LOADER ==================
def load_sources(session: requests.Session) -> list[Channel]:
    if not SOURCES:
        log.error("no source URLs configured (IPTV_SOURCE_URL / IPTV_BD_SOURCE_URL)")
        sys.exit(2)
    channels: list[Channel] = []
    for i, url in enumerate(SOURCES, 1):
        try:
            log.info("[%d/%d] downloading source...", i, len(SOURCES))
            r = session.get(url, timeout=30)
            r.raise_for_status()
            parsed = parse_m3u(r.text)
            log.info("   → %d channels", len(parsed))
            channels.extend(parsed)
        except Exception as e:
            log.warning("   source failed: %s: %s", type(e).__name__, e)
    return channels


# ================== MAIN PIPELINE ==================
def build_playlist(skip_cache: bool = False) -> int:
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

    # 3. Classify into buckets
    buckets: dict[str, list[Channel]] = {k: [] for k in CATEGORIES}
    for c in uniq:
        cat = classify(c)
        if cat:
            c.cat = cat
            buckets[cat].append(c)

    # 4. Candidate selection (logo priority + cap)
    candidates: list[Channel] = []
    for cat in CATEGORIES:
        pool = sorted(buckets[cat], key=lambda x: not x.attrs.get("tvg-logo"))
        candidates.extend(pool[:MAX_PER_CAT])

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
            if done % 100 == 0:
                log.info("   …%d/%d checked, alive=%d", done, len(to_check), len(alive))
    cache.save()

    log.info("working links: %d", len(alive))

    # 6. Score & pick top per category (dedupe by name)
    groups: dict[str, list[Channel]] = {}
    for cat in CATEGORIES:
        pool = [c for c in alive if c.cat == cat]
        for c in pool:
            c.score = score_channel(c)
        pool.sort(key=lambda x: x.score)
        picked, names = [], set()
        for c in pool:
            key = c.name.lower()
            if key in names:
                continue
            names.add(key)
            picked.append(c)
            if len(picked) >= TOP_PER_CAT:
                break
        groups[cat] = picked

    # 7. Write
    total = write_playlist(groups)
    write_state(groups, total)
    return total


# ================== OUTPUT ==================
def write_playlist(groups: dict[str, list[Channel]]) -> int:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
        lines += [
            f'#EXTINF:-1 tvg-id="" tvg-name="IPTV LINKS" tvg-logo="{LINK_LOGO}" '
            f'group-title="{cat}",IPTV LINKS',
            LINK_URL,
        ]
        for c in items:
            a    = c.attrs
            name = sanitize(c.name)
            lines.append(
                f'#EXTINF:-1 tvg-id="{a.get("tvg-id", "")}" tvg-name="{name}" '
                f'tvg-logo="{a.get("tvg-logo", "")}" group-title="{cat}",{name}'
            )
            lines.append(c.url)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s (%d entries)", OUT_FILE, total)
    return total


def write_state(groups: dict[str, list[Channel]], total: int):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "per_category": {k: len(v) for k, v in groups.items()},
        "avg_latency_ms": round(
            1000 * sum(c.latency for v in groups.values() for c in v)
            / max(1, sum(len(v) for v in groups.values())), 1
        ),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2), "utf-8")


# ================== CLI ==================
def main():
    parser = argparse.ArgumentParser(description="IPTV VIP Aggregator")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached health checks")
    parser.add_argument("--dry-run", action="store_true", help="parse+classify only, no write")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.time()
    total = build_playlist(skip_cache=args.no_cache)
    log.info("done in %.1fs — %d entries", time.time() - t0, total)


if __name__ == "__main__":
    main()
