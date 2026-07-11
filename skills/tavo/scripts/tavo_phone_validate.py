#!/usr/bin/env python3
"""Run repeatable Tavo phone validation cases."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, output: Path | None = None) -> int:
    proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if output:
        output.write_text(proc.stdout, encoding="utf-8")
    else:
        print(proc.stdout, end="")
    return proc.returncode


def write_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tavo phone validation case.")
    parser.add_argument("--case", required=True, choices=["phone-preflight", "mcp-surface"])
    parser.add_argument("--device", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--retain", action="store_true", default=True, help="Retain phone-side validation files/objects; default is true.")
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir).expanduser() if args.artifact_dir else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{stamp}-{args.case}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "case": args.case,
        "status": "running",
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "retention": "leave-in-place",
        "artifacts": [],
        "notes": "Real-phone validation files and disposable objects are retained by default.",
    }
    write_manifest(artifact_dir / "run-manifest.json", manifest)

    failures = 0
    if args.case == "phone-preflight":
        command = [sys.executable, str(ROOT / "scripts/tavo_phone_capture.py"), "--output", str(artifact_dir)]
        if args.device:
            command.extend(["--device", args.device])
        failures += run(command, ROOT, artifact_dir / "phone-capture.log")
        manifest["artifacts"].extend(["adb-devices.txt", "device.txt", "package.txt", "window.txt", "accessibility.txt", "ui.xml", "screen.png", "phone-capture.log"])
    elif args.case == "mcp-surface":
        failures += run([sys.executable, str(ROOT / "scripts/dump_mcp_surface.py"), "--strict", "--output", str(artifact_dir)], ROOT, artifact_dir / "mcp-dump.log")
        manifest["artifacts"].extend(["mcp_surface.json", "mcp-dump.log"])

    manifest["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["status"] = "passed" if failures == 0 else "failed"
    manifest["evidenceLevel"] = "ui-pass" if args.case == "phone-preflight" and failures == 0 else "schema-seen" if args.case == "mcp-surface" and failures == 0 else "needs-live-verify"
    write_manifest(artifact_dir / "run-manifest.json", manifest)
    print(f"artifact_dir={artifact_dir}")
    print(f"status={manifest['status']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
