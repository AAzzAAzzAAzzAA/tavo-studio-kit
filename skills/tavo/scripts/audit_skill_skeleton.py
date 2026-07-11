#!/usr/bin/env python3
"""Audit the Tavo skill skeleton wiring."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


OLD_SKILL_PATHS = [
    "/Users/<user>/.agents/skills/tavo-complete",
    "/Users/<user>/.agents/skills/tavo-studio",
    "/Users/<user>/.agents/skills/zhimengren",
    "/Users/<user>/.codex/skills/sillytavern-card-worldbook",
    "/Users/<user>/Documents/Codex/.agents/skills/tavo-android-operator",
    "/Users/<user>/Documents/Codex/.agents/skills/tavo-card-craft",
    "/Users/<user>/Documents/Codex/.agents/skills/tavo-card-studio-verified",
    "/Users/<user>/Documents/Codex/.agents/skills/tavo-studio",
]


FORBIDDEN = re.compile("|".join(["TO" + "DO", "place" + "holder", r"\[" + "TO" + "DO"]))


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Tavo skill skeleton.")
    parser.add_argument("skill_dir", nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    skill_dir = Path(args.skill_dir).expanduser().resolve()

    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    refs_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    url_map = refs_dir / "01-official-url-map.md"

    if not skill_md.exists():
        errors.append("SKILL.md is missing")
    if not refs_dir.is_dir():
        errors.append("references/ is missing")
    if not scripts_dir.is_dir():
        errors.append("scripts/ is missing")

    searchable_parts: list[str] = []
    for path in [skill_md, url_map]:
        if path.exists():
            searchable_parts.append(read_text(path))
    skill_and_url_map = "\n".join(searchable_parts)

    all_md_text = []
    for path in [skill_md, *sorted(refs_dir.rglob("*.md"))] if refs_dir.exists() else [skill_md]:
        if path.exists():
            text = read_text(path)
            all_md_text.append(text)
            if FORBIDDEN.search(text):
                errors.append(f"initialization remnant found in {rel(path, skill_dir)}")

    if refs_dir.exists():
        for path in sorted(refs_dir.rglob("*.md")):
            relative = rel(path, skill_dir)
            if relative not in skill_and_url_map:
                errors.append(f"reference not indexed by SKILL.md or 01-official-url-map.md: {relative}")

    all_reference_text = "\n".join(all_md_text)
    if scripts_dir.exists():
        for path in sorted(p for p in scripts_dir.rglob("*") if p.is_file()):
            relative = rel(path, skill_dir)
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if relative not in all_reference_text:
                errors.append(f"script not explained by SKILL.md or references: {relative}")

    for old_path in OLD_SKILL_PATHS:
        resolved = Path(old_path).resolve()
        if resolved == skill_dir or skill_dir in resolved.parents:
            errors.append(f"old-skill path points inside new skill: {old_path}")
        # Historical skills are optional inputs, not dependencies of the new skill.
        # Their absence must not make the canonical skill invalid.

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("audit_skill_skeleton_ok")
    print(f"references={len(list(refs_dir.rglob('*.md')))}")
    print(
        "scripts="
        + str(
            len(
                [
                    path
                    for path in scripts_dir.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
                ]
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
