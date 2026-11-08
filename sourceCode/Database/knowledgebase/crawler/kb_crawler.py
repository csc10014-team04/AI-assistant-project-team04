"""
Polite collector for the knowledge base (sourceCode/Database/knowledgebase).

What it does, per site listed in ../sources.json:
  1. reads robots.txt and obeys it (Disallow rules and Crawl-delay);
  2. fetches the home page, finds same-site links, and visits the most useful ones first (faculty
     introduction, staff, departments, programmes, courses, achievements) up to `max_pages`;
  3. extracts the readable text of each page and saves it as Markdown in <repo>/database/UniInfo/<site_id>/;
  4. writes database/UniInfo/index.json (what was collected, when, content hash) so a re-run skips unchanged pages.

Rules it follows: public pages only; never logs in; skips URLs with query strings, files (PDF, images...),
login/admin paths; waits between requests; redacts e-mail addresses and phone numbers from the saved text.

Run from the repository root:
    python sourceCode/Database/knowledgebase/crawler/kb_crawler.py                 # all sites
    python sourceCode/Database/knowledgebase/crawler/kb_crawler.py --site fit      # one site
    python sourceCode/Database/knowledgebase/crawler/kb_crawler.py --max-pages 5   # quick trial
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

KB_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = KB_DIR / "sources.json"
# collected pages live outside sourceCode, at <repo>/database/UniInfo
DATA_DIR = KB_DIR.parents[2] / "database" / "UniInfo"
VN_TZ = timezone(timedelta(hours=7))

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)[\s.-]?\d{2,3}[\s.-]?\d{3}[\s.-]?\d{3,4}(?!\d)")
NOISE_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg", "button", "select")
NOISE_HINTS = ("menu", "navbar", "breadcrumb", "sidebar", "footer", "cookie", "banner", "social", "share", "comment", "pagination")


# ----------------------------------------------------------------------------- helpers
def fold(text: str) -> str:
    """lower-case and remove Vietnamese accents (for keyword matching only)."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def redact_contacts(text: str) -> str:
    return PHONE_RE.sub("[phone removed]", EMAIL_RE.sub("[email removed]", text))


def slugify(url: str) -> str:
    parsed = urlparse(url)
    raw = (parsed.path.strip("/") or "home")
    slug = re.sub(r"[^a-z0-9]+", "-", fold(raw)).strip("-")[:80] or "home"
    return f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


def is_candidate_url(url: str, base_host: str, cfg: dict) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != base_host.removeprefix("www."):
        return False
    if p.query:  # query URLs are crawl traps and some sites disallow them
        return False
    path = p.path.lower()
    if any(path.endswith(ext) for ext in cfg["skip_extensions"]):
        return False
    return not any(w in path for w in cfg["skip_path_words"])


def link_score(url: str, anchor_text: str, keywords: list[str]) -> int:
    hay = f"{fold(urlparse(url).path)} {fold(anchor_text)}"
    return sum(2 for k in keywords if k in hay)


def ascii_url(url: str) -> str:
    """percent-encode non-ASCII characters (Vietnamese in a path) so the HTTP request line is valid."""
    p = urlparse(url)
    return urlunparse(p._replace(path=quote(p.path, safe="/%:@&=+$,;~-._!*'()"), query=quote(p.query, safe="=&%+/:;,@")))


def extract_links(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        out.append((ascii_url(urldefrag(urljoin(page_url, href))[0]), a.get_text(" ", strip=True)))
    return out


def extract_page(html: str) -> tuple[str, str]:
    """returns (title, markdown-ish text). Keeps headings, paragraphs, lists and simple tables."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:  # already removed together with a noisy parent
            continue
        marker = " ".join(filter(None, [" ".join(tag.get("class") or []), tag.get("id") or ""])).lower()
        if marker and any(h in marker for h in NOISE_HINTS):
            tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.find(id=re.compile("content|main", re.I)) or soup.body or soup
    lines: list[str] = []
    seen: set[str] = set()
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "td", "div"], recursive=True):
        if el.name == "div" and el.find(["p", "li", "tr", "h1", "h2", "h3", "h4", "div"]):
            continue  # only leaf divs; their children are visited separately
        if el.name == "td" and el.find_parent("tr"):
            continue  # cells are read through their row
        if el.name == "li" and el.find(["li"]):
            continue
        if el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["th", "td"])]
            text = " | ".join(c for c in cells if c)
        else:
            text = el.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 3 or text in seen:
            continue
        seen.add(text)
        if el.name in ("h1", "h2", "h3", "h4"):
            lines.append(f"\n{'#' * int(el.name[1])} {text}")
        elif el.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    body = redact_contacts("\n".join(lines).strip())
    return title, re.sub(r"\n{3,}", "\n\n", body)


ERROR_PAGE_HINTS = ("an error has occurred", "page not found", "404 not found", "không tìm thấy bài viết", "lỗi: 404", "access denied")


def is_error_page(title: str, text: str) -> bool:
    """some sites answer an error screen with HTTP 200; such a page is not knowledge and must not be saved."""
    hay = f"{title} {text[:600]}".lower()
    return len(text) < 3000 and any(h in hay for h in ERROR_PAGE_HINTS)


# ----------------------------------------------------------------------------- crawling
class Fetcher:
    def __init__(self, user_agent: str, max_bytes: int, min_delay: float):
        self.user_agent, self.max_bytes, self.min_delay = user_agent, max_bytes, min_delay
        self._last = 0.0
        self.delay = min_delay

    def wait(self) -> None:
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def get(self, url: str, attempts: int = 3) -> tuple[int, str, str]:
        """returns (status, content_type, text). Network errors and 5xx are retried with a growing pause."""
        for attempt in range(attempts):
            status, ctype, text = self._get_once(url)
            if status not in (0, 500, 502, 503, 504) or attempt == attempts - 1:
                return status, ctype, text
            time.sleep(3 * (attempt + 1))
        return 0, "", ""

    def _get_once(self, url: str) -> tuple[int, str, str]:
        self.wait()
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.5", "Accept-Language": "vi,en;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    return 413, ctype, ""
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.status, ctype, raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, "", ""
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError):
            return 0, "", ""


def load_robots(base_url: str, fetcher: Fetcher) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    status, ctype, text = fetcher.get(urljoin(base_url, "/robots.txt"))
    if status == 200 and "html" not in ctype.lower():
        rp.parse(text.splitlines())
    else:
        rp.parse([])  # no robots.txt (or an HTML error page): nothing is disallowed
    return rp


def crawl_site(site: dict, cfg: dict, max_pages: int | None, out_dir: Path, log=print) -> list[dict]:
    fetcher = Fetcher(cfg["user_agent"], cfg["max_page_bytes"], cfg["min_delay_seconds"])
    base = site["base_url"]
    host = urlparse(base).netloc.lower()
    robots = load_robots(base, fetcher)
    declared = robots.crawl_delay(cfg["user_agent"]) or robots.crawl_delay("*")
    fetcher.delay = max(cfg["min_delay_seconds"], float(declared or 0))
    log(f"[{site['id']}] robots.txt read; delay {fetcher.delay:.0f}s between requests")

    limit = max_pages or site["max_pages"]
    frontier: list[tuple[int, int, str]] = [(0, 0, base)]  # (-score, depth, url)
    queued = {base}
    index_path = out_dir / "index.json"
    previous = {p["url"]: p for p in json.loads(index_path.read_text(encoding="utf-8"))["pages"]} if index_path.is_file() else {}
    site_dir = out_dir / site["id"]
    site_dir.mkdir(parents=True, exist_ok=True)
    collected: list[dict] = []

    while frontier and len(collected) < limit:
        frontier.sort(key=lambda t: (t[0], t[1]))
        _, depth, url = frontier.pop(0)
        if not robots.can_fetch(cfg["user_agent"], url):
            log(f"[{site['id']}] robots.txt disallows {url}")
            continue
        status, ctype, html = fetcher.get(url)
        if status != 200 or "html" not in ctype.lower():
            log(f"[{site['id']}] skip {url} (status {status})")
            continue
        title, text = extract_page(html)
        if depth < 2:
            for link, anchor in extract_links(html, url):
                if link not in queued and is_candidate_url(link, host, cfg):
                    queued.add(link)
                    frontier.append((-link_score(link, anchor, cfg["priority_keywords"]), depth + 1, link))
        if is_error_page(title, text):
            log(f"[{site['id']}] skip {url}: it is an error page, not content")
            continue
        if len(text) < 200:
            log(f"[{site['id']}] too little text on {url} ({len(text)} chars); probably a menu or a script-built page")
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        slug = slugify(url)
        fetched_at = datetime.now(VN_TZ).isoformat(timespec="seconds")
        old = previous.get(url)
        if old and old.get("sha256") == digest and (site_dir / f"{slug}.md").is_file():
            fetched_at = old["fetched_at"]  # unchanged: keep the original date
        front = (f"---\nsource_url: {url}\nsite: {site['id']}\nsite_name: {site['name']}\n"
                 f"title: {json.dumps(title, ensure_ascii=False)}\nfetched_at: {fetched_at}\nsha256: {digest}\n---\n\n")
        (site_dir / f"{slug}.md").write_text(front + f"# {title}\n\n{text}\n", encoding="utf-8")
        collected.append({"site": site["id"], "url": url, "title": title, "file": f"{site['id']}/{slug}.md",
                          "fetched_at": fetched_at, "sha256": digest, "chars": len(text)})
        log(f"[{site['id']}] saved {len(collected)}/{limit}: {title[:60]} ({len(text)} chars)")
    return collected


SEP = chr(10) + "---" + chr(10)  # end of the front-matter block


def parse_front_matter(md_text: str) -> dict:
    """read the simple `key: value` block between the first two `---` lines of a collected page."""
    meta: dict = {}
    if md_text.startswith("---"+chr(10)):
        block = md_text.split(SEP, 1)[0].splitlines()[1:]
        for line in block:
            key, _, value = line.partition(": ")
            meta[key.strip()] = json.loads(value) if value.startswith('"') else value.strip()
    return meta


def rebuild_index(data_dir: Path) -> list[dict]:
    """regenerate index.json from the Markdown files themselves, so several runs (even in parallel) never lose entries."""
    pages = []
    for md in sorted(data_dir.glob("*/*.md")):
        text = md.read_text(encoding="utf-8")
        meta = parse_front_matter(text)
        if "source_url" not in meta:
            continue
        pages.append({"site": meta.get("site", md.parent.name), "url": meta["source_url"], "title": meta.get("title", ""),
                      "file": f"{md.parent.name}/{md.name}", "fetched_at": meta.get("fetched_at", ""),
                      "sha256": meta.get("sha256", ""), "chars": len(text.split(SEP, 1)[-1])})
    (data_dir / "index.json").write_text(json.dumps({"generated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"), "pages": pages},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", help="only this site id from sources.json")
    ap.add_argument("--max-pages", type=int, help="override max_pages per site")
    ap.add_argument("--out", type=Path, default=DATA_DIR, help="output folder (default: <repo>/database/UniInfo)")
    ap.add_argument("--reindex", action="store_true", help="only rebuild data/index.json from the saved pages")
    args = ap.parse_args(argv)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sites = [s for s in cfg["sites"] if not args.site or s["id"] == args.site]
    if not sites:
        print(f"unknown site id: {args.site}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    if args.reindex:
        print(f"index rebuilt: {len(rebuild_index(args.out))} pages")
        return 0
    new_pages: list[dict] = []
    for site in sites:
        new_pages += crawl_site(site, cfg, args.max_pages, args.out)
    total = rebuild_index(args.out)
    per_site = {s_["id"]: sum(1 for p in new_pages if p["site"] == s_["id"]) for s_ in sites}
    print(f"done: {len(new_pages)} pages saved {per_site}; index now lists {len(total)} pages: {args.out / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
