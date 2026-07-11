#!/usr/bin/env python3
"""Fetch the current Tavo official docs IA and page text.

This script intentionally crawls the live official docs site. It does not read
old skill caches or historical reference files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_BASE = "https://docs.tavoai.dev/cn/"
USER_AGENT = "Codex-Tavo-Skill-Crawler/1.0"
BARE_EXTERNAL_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/|$)")


class LinkAndTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0:
            self.text_parts.append(text)


def normalize_url(base: str, href: str) -> str | None:
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    if BARE_EXTERNAL_RE.match(href):
        return None
    url = urllib.parse.urljoin(base, href)
    parsed = urllib.parse.urlparse(url)
    parsed = parsed._replace(fragment="", query="")
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc != "docs.tavoai.dev":
        return None
    if not parsed.path.startswith("/cn"):
        return None
    path = re.sub(r"/+", "/", parsed.path)
    normalized = parsed._replace(path=path)
    text = urllib.parse.urlunparse(normalized)
    if text.endswith("/index.html"):
        text = text[: -len("index.html")]
    return text


def safe_name(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/") or "root"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path)
    return name[:180] + ".txt"


def fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def clean_text(parts: list[str]) -> str:
    text = "\n".join(html.unescape(part) for part in parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def write_map(output_dir: Path, result: dict) -> None:
    (output_dir / "url_map.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl(base_url: str, output_dir: Path, max_pages: int, delay: float, timeout: float, time_budget: float) -> dict:
    base_url = normalize_url(base_url, base_url) or base_url
    queue: deque[str] = deque([base_url])
    seen: set[str] = set()
    pages: list[dict] = []
    errors: list[dict] = []
    started = time.monotonic()

    text_dir = output_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "base_url": base_url,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "page_count": 0,
        "complete": False,
        "discovered_count": 0,
        "unfetched_count": 0,
        "unfetched_urls": [],
        "pages": pages,
        "errors": errors,
    }

    while queue and len(seen) < max_pages:
        if time_budget and time.monotonic() - started > time_budget:
            errors.append({"url": queue[0] if queue else "", "error": f"time budget exceeded after {time_budget} seconds"})
            break
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        try:
            body = fetch(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append({"url": url, "error": str(exc)})
            continue

        parser = LinkAndTextParser()
        parser.feed(body)
        title = " ".join(parser.title_parts).strip()
        text = clean_text(parser.text_parts)
        text_file = text_dir / safe_name(url)
        text_file.write_text(text, encoding="utf-8")

        links: list[str] = []
        for href in parser.links:
            normalized = normalize_url(url, href)
            if not normalized:
                continue
            if normalized not in links:
                links.append(normalized)
            if normalized not in seen and normalized not in queue:
                queue.append(normalized)

        pages.append(
            {
                "url": url,
                "title": title,
                "text_file": str(text_file),
                "links": links,
            }
        )
        result["page_count"] = len(pages)
        discovered_urls = sorted({link for page in pages for link in page["links"]})
        fetched_urls = {page["url"] for page in pages}
        result["discovered_count"] = len(discovered_urls)
        result["unfetched_urls"] = [url for url in discovered_urls if url not in fetched_urls]
        result["unfetched_count"] = len(result["unfetched_urls"])
        write_map(output_dir, result)
        if delay:
            time.sleep(delay)

    discovered_urls = sorted({link for page in pages for link in page["links"]})
    fetched_urls = {page["url"] for page in pages}
    result["complete"] = not queue
    result["page_count"] = len(pages)
    result["discovered_count"] = len(discovered_urls)
    result["unfetched_urls"] = [url for url in discovered_urls if url not in fetched_urls]
    result["unfetched_count"] = len(result["unfetched_urls"])
    if queue:
        errors.append({"url": queue[0], "error": f"crawl stopped before queue drained; queued_urls={len(queue)}"})
    write_map(output_dir, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch current Tavo official docs.")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--output", default="")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--time-budget-seconds", type=float, default=120.0)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Return success even when the crawl has errors or unfetched discovered pages.",
    )
    args = parser.parse_args()

    if args.max_pages < 1:
        print("--max-pages must be positive", file=sys.stderr)
        return 2

    if args.output:
        output_dir = Path(args.output).expanduser()
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path(f"/tmp/tavo-official-docs-current-{stamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    socket.setdefaulttimeout(args.timeout)
    try:
        result = crawl(args.base_url, output_dir, args.max_pages, args.delay, args.timeout, args.time_budget_seconds)
    except KeyboardInterrupt:
        map_path = output_dir / "url_map.json"
        if map_path.exists():
            result = json.loads(map_path.read_text(encoding="utf-8"))
            result["complete"] = False
            result.setdefault("errors", []).append({"url": "", "error": "interrupted by user"})
            write_map(output_dir, result)
        else:
            raise
    map_path = output_dir / "url_map.json"
    print(f"fetched_pages={result['page_count']}")
    print(f"errors={len(result['errors'])}")
    print(f"complete={str(result['complete']).lower()}")
    print(f"unfetched_count={result['unfetched_count']}")
    print(f"url_map={map_path}")
    if not result["page_count"]:
        return 1
    if args.allow_partial:
        return 0
    if not result["complete"] or result["errors"] or result["unfetched_count"]:
        print(
            "crawl incomplete; rerun with a higher --max-pages/--time-budget-seconds or pass --allow-partial",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
