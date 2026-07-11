#!/usr/bin/env python3
"""Scan Tavo artifacts for deprecated or risky old TavoJS patterns."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PATTERNS = [
    ("internal-window-tav", re.compile(r"\bwindow\.tav\b")),
    ("deprecated-event-on-off", re.compile(r"\btavo\.event\.(?:on|off)\b")),
    ("deprecated-user-get", re.compile(r"\btavo\.user\.get\b")),
    ("deprecated-character-current", re.compile(r"\btavo\.character\.current\b")),
    ("deprecated-sendMessage", re.compile(r"\btavo\.sendMessage\b")),
    ("unverified-updater-function", re.compile(r"\btavo\.update\s*\([^)]*=>")),
    ("legacy-image-generate-options-object", re.compile(r"\btavo\.image\.generate\s*\(\s*\{")),
    ("inline-onclick-risk", re.compile(r"\bonclick\s*=")),
]

TEXT_SUFFIXES = {".js", ".mjs", ".ts", ".html", ".json", ".md", ".txt"}


def iter_files(paths: list[str]) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            result.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
        elif path.is_file():
            result.append(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for deprecated TavoJS patterns.")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    findings = []
    for path in iter_files(args.paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append((path, line_no, name, line.strip()[:180]))

    for path, line_no, name, line in findings:
        print(f"{path}:{line_no}: {name}: {line}")
    print(f"deprecated_tavojs_findings={len(findings)}")
    if findings and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
