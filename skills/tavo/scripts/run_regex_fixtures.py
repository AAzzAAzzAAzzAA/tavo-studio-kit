#!/usr/bin/env python3
"""Run regex before/after fixtures used by the Tavo skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def compile_flags(flags: str) -> int:
    value = 0
    if "i" in flags:
        value |= re.IGNORECASE
    if "m" in flags:
        value |= re.MULTILINE
    if "s" in flags:
        value |= re.DOTALL
    return value


def apply_rules(text: str, rules: list[dict[str, Any]]) -> str:
    result = text
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        pattern = re.compile(rule["pattern"], compile_flags(rule.get("flags", "")))
        count = 0 if "g" in rule.get("flags", "g") else 1
        result = pattern.sub(rule.get("replacement", ""), result, count=count)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tavo regex fixture cases.")
    parser.add_argument("fixture")
    args = parser.parse_args()

    path = Path(args.fixture).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules") or []
    cases = data.get("cases") or []
    failures = []
    for case in cases:
        actual = apply_rules(case["input"], rules)
        if actual != case["expected"]:
            failures.append((case["id"], case["expected"], actual))

    if failures:
        print(f"regex_fixture_failed={path}")
        for case_id, expected, actual in failures:
            print(f"case={case_id}")
            print(f"expected={expected!r}")
            print(f"actual={actual!r}")
        return 1
    print(f"regex_fixture_ok={path}")
    print(f"cases={len(cases)}")
    print(f"rules={len(rules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
