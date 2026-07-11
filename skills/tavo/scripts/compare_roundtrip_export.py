#!/usr/bin/env python3
"""Compare submitted and readback/exported JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def diff(a: Any, b: Any, path: str, out: list[str], limit: int) -> None:
    if len(out) >= limit:
        return
    if type(a) is not type(b):
        out.append(f"{path}: type {type(a).__name__} != {type(b).__name__}")
        return
    if isinstance(a, dict):
        keys = sorted(set(a) | set(b))
        for key in keys:
            if key not in a:
                out.append(f"{path}.{key}: added")
            elif key not in b:
                out.append(f"{path}.{key}: removed")
            else:
                diff(a[key], b[key], f"{path}.{key}", out, limit)
            if len(out) >= limit:
                return
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: list length {len(a)} != {len(b)}")
        for index, (left, right) in enumerate(zip(a, b)):
            diff(left, right, f"{path}[{index}]", out, limit)
            if len(out) >= limit:
                return
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare JSON roundtrip artifacts.")
    parser.add_argument("submitted")
    parser.add_argument("readback")
    parser.add_argument("--output", default="")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    submitted = normalize(load(Path(args.submitted).expanduser()))
    readback = normalize(load(Path(args.readback).expanduser()))
    differences: list[str] = []
    diff(submitted, readback, "$", differences, args.limit)
    report = {
        "submitted": args.submitted,
        "readback": args.readback,
        "same": not differences,
        "differenceCountShown": len(differences),
        "differences": differences,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
