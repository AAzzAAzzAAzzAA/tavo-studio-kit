#!/usr/bin/env python3
"""Capture Android phone state for Tavo validation."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path


def run(command: list[str], binary: bool = False) -> tuple[int, bytes]:
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return proc.returncode, proc.stdout if binary else proc.stdout


def write_text(path: Path, data: bytes) -> None:
    path.write_text(data.decode("utf-8", errors="replace"), encoding="utf-8")


def adb_prefix(device: str) -> list[str]:
    return ["adb", "-s", device] if device else ["adb"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Tavo phone state.")
    parser.add_argument("--device", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--package", default="app.bitbear.tav")
    args = parser.parse_args()

    out = Path(args.output).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "capture-manifest.txt"
    manifest.write_text(f"captured_at={dt.datetime.now(dt.timezone.utc).isoformat()}\n", encoding="utf-8")

    commands = {
        "adb-devices.txt": ["adb", "devices", "-l"],
        "device.txt": [*adb_prefix(args.device), "shell", "getprop"],
        "package.txt": [*adb_prefix(args.device), "shell", "dumpsys", "package", args.package],
        "window.txt": [*adb_prefix(args.device), "shell", "dumpsys", "window"],
        "accessibility.txt": [*adb_prefix(args.device), "shell", "settings", "get", "secure", "enabled_accessibility_services"],
    }
    failures = 0
    for name, command in commands.items():
        code, output = run(command)
        write_text(out / name, output)
        if code:
            failures += 1

    run([*adb_prefix(args.device), "shell", "rm", "-f", "/sdcard/window.xml"])
    ui_attempts: list[str] = []
    ui_output = b""
    ui_passed = False
    for attempt in range(1, 4):
        dump_code, dump_output = run(
            [*adb_prefix(args.device), "shell", "uiautomator", "dump", "/sdcard/window.xml"]
        )
        read_code, candidate = run([*adb_prefix(args.device), "exec-out", "cat", "/sdcard/window.xml"])
        valid = bool(
            dump_code == 0
            and read_code == 0
            and candidate.startswith(b"<?xml")
            and b"<hierarchy" in candidate
            and b"</hierarchy>" in candidate
        )
        ui_attempts.append(
            f"attempt={attempt} dump_code={dump_code} read_code={read_code} bytes={len(candidate)} valid={str(valid).lower()} output={dump_output.decode('utf-8', errors='replace').strip()}"
        )
        if valid:
            ui_output = candidate
            ui_passed = True
            break
        time.sleep(attempt)
    write_text(out / "ui.xml", ui_output)
    (out / "ui-dump-attempts.txt").write_text("\n".join(ui_attempts) + "\n", encoding="utf-8")
    if not ui_passed:
        failures += 1

    screen_output = b""
    screen_attempts: list[str] = []
    screen_passed = False
    for attempt in range(1, 4):
        code, candidate = run([*adb_prefix(args.device), "exec-out", "screencap", "-p"], binary=True)
        valid = bool(code == 0 and candidate.startswith(b"\x89PNG\r\n\x1a\n") and len(candidate) >= 1024)
        screen_attempts.append(
            f"attempt={attempt} code={code} bytes={len(candidate)} valid={str(valid).lower()}"
        )
        if valid:
            screen_output = candidate
            screen_passed = True
            break
        time.sleep(attempt)
    (out / "screen.png").write_bytes(screen_output)
    (out / "screen-attempts.txt").write_text("\n".join(screen_attempts) + "\n", encoding="utf-8")
    if not screen_passed:
        failures += 1

    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(f"ui_passed={str(ui_passed).lower()}\n")
        handle.write(f"screen_passed={str(screen_passed).lower()}\n")
        handle.write(f"failures={failures}\n")

    print(f"phone_capture={out}")
    print(f"failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
