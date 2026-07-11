#!/usr/bin/env python3
"""Normalize a Tavo official docs crawl into durable indexes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


TOPIC_RULES = [
    ("api-settings", ["api-setting", "get-key", "select-model"]),
    ("characters", ["bots", "cards", "persona", "create"]),
    ("chat", ["chat", "group-chat", "translation", "history"]),
    ("prompt-authoring", ["preset", "lore-book", "regular", "long-memory", "supported-macros"]),
    ("macros-ejs", ["ejs-template", "supported-macros"]),
    ("rendering-tavojs", ["advanced-rendering", "javascript-api"]),
    ("plugins", ["plugins", "plugin-development"]),
    ("mcp", ["mcp-server"]),
    ("media", ["voice-connection", "image-sent", "image-setting", "tts"]),
    ("settings-data", ["backup", "storage-space", "theme", "customize-keyboard"]),
    ("policy", ["privacy-policy", "terms-of-service"]),
]

REFERENCE_BY_TOPIC = {
    "api-settings": "references/10-app-settings-data.md",
    "characters": "references/03-characters-cards-personas.md",
    "chat": "references/04-chat-workflows.md",
    "prompt-authoring": "references/05-prompt-authoring.md",
    "macros-ejs": "references/06-macros-ejs.md",
    "rendering-tavojs": "references/07-rendering-tavojs.md",
    "plugins": "references/08-plugins-tpg.md",
    "mcp": "references/11-mcp-runtime.md",
    "media": "references/09-media-voice-image.md",
    "settings-data": "references/10-app-settings-data.md",
    "policy": "references/01-official-url-map.md",
    "general": "references/02-capabilities-overview.md",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def slug_from_url(url: str) -> str:
    value = re.sub(r"^https://docs\.tavoai\.dev/", "", url).strip("/")
    return value or "root"


def topic_for(url: str, title: str) -> str:
    haystack = f"{url} {title}".lower()
    for topic, needles in TOPIC_RULES:
        if any(needle in haystack for needle in needles):
            return topic
    return "general"


def durable_text_path(page: dict[str, Any], text_root: Path) -> Path | None:
    original = Path(str(page.get("text_file", "")))
    candidates = []
    if original.name:
        candidates.append(text_root / original.name)
        candidates.append(original)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def normalize(url_map: Path, text_root: Path, skill_root: Path) -> dict[str, Any]:
    data = json.loads(url_map.read_text(encoding="utf-8"))
    pages = []
    missing_text = []
    for page in data.get("pages", []):
        text_path = durable_text_path(page, text_root)
        topic = topic_for(page.get("url", ""), page.get("title", ""))
        record: dict[str, Any] = {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "slug": slug_from_url(page.get("url", "")),
            "topic": topic,
            "reference": REFERENCE_BY_TOPIC.get(topic, REFERENCE_BY_TOPIC["general"]),
            "links": page.get("links", []),
        }
        if text_path:
            text = text_path.read_text(encoding="utf-8", errors="replace")
            record["text_path"] = text_path.relative_to(skill_root).as_posix() if skill_root in text_path.parents else str(text_path)
            record["sha256"] = sha256(text_path)
            record["line_count"] = text.count("\n") + (0 if text.endswith("\n") else 1)
            record["char_count"] = len(text)
        else:
            missing_text.append(page.get("url", ""))
            record["text_path"] = ""
            record["sha256"] = ""
            record["line_count"] = 0
            record["char_count"] = 0
        pages.append(record)
    topic_counts: dict[str, int] = {}
    for page in pages:
        topic_counts[page["topic"]] = topic_counts.get(page["topic"], 0) + 1
    return {
        "schemaVersion": "0.1.0",
        "sourceUrlMap": str(url_map),
        "baseUrl": data.get("base_url", ""),
        "fetchedAt": data.get("fetched_at", ""),
        "pageCount": data.get("page_count", len(pages)),
        "complete": bool(data.get("complete")),
        "errors": data.get("errors", []),
        "unfetchedCount": data.get("unfetched_count", 0),
        "missingTextCount": len(missing_text),
        "missingTextUrls": missing_text,
        "topicCounts": topic_counts,
        "pages": pages,
    }


def latest_snapshot(skill_root: Path) -> tuple[Path, Path]:
    docs_dir = skill_root / "assets/official-docs"
    maps = sorted(docs_dir.glob("url_map-*.json"))
    if not maps:
        return docs_dir / "url_map-20260709.json", docs_dir / "text-20260709"
    url_map = maps[-1]
    stamp = url_map.stem.removeprefix("url_map-")
    return url_map, docs_dir / f"text-{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Tavo official docs crawl.")
    parser.add_argument("--url-map", default="")
    parser.add_argument("--text-root", default="")
    parser.add_argument("--skill-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).expanduser().resolve()
    default_url_map, default_text_root = latest_snapshot(skill_root)
    url_map = Path(args.url_map).expanduser() if args.url_map else default_url_map
    text_root = Path(args.text_root).expanduser() if args.text_root else default_text_root
    output = Path(args.output).expanduser() if args.output else skill_root / "assets/official-docs/official_manifest.json"

    result = normalize(url_map, text_root, skill_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"official_manifest={output}")
    print(f"page_count={result['pageCount']}")
    print(f"complete={str(result['complete']).lower()}")
    print(f"missing_text_count={result['missingTextCount']}")
    if result["errors"] or result["unfetchedCount"] or result["missingTextCount"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
