#!/usr/bin/env python3
"""Render simple {{name}} placeholders in Tavo templates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_.-]+)\}\}")


def parse_vars(items: list[str], vars_json: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if vars_json:
        data = json.loads(Path(vars_json).expanduser().read_text(encoding="utf-8"))
        values.update({str(k): str(v) for k, v in data.items()})
    for item in items:
        if "=" not in item:
            raise ValueError(f"--var must be key=value: {item}")
        key, value = item.split("=", 1)
        values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Tavo artifact from a template.")
    parser.add_argument("template")
    parser.add_argument("--output", required=True)
    parser.add_argument("--vars-json", default="")
    parser.add_argument("--var", action="append", default=[])
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    template_path = Path(args.template).expanduser()
    values = parse_vars(args.var, args.vars_json)
    text = template_path.read_text(encoding="utf-8")
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return values[key]
        missing.add(key)
        return match.group(0)

    rendered = PLACEHOLDER.sub(replace, text)
    if missing and not args.allow_missing:
        print(f"missing template variables: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"generated={output}")
    print(f"missing={len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
