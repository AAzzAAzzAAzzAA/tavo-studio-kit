#!/usr/bin/env python3
"""Locate and tap Android UIAutomator nodes with structured JSON output."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REMOTE_XML_PATH = "/sdcard/window.xml"
BOUNDS_RE = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")
MATCH_FIELDS = {
    "text": "text",
    "content_desc": "content-desc",
    "hint": "hint",
    "node_class": "class",
}


class CliFailure(Exception):
    """A user-facing failure with a stable JSON error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int = 3,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliFailure("invalid_arguments", message, exit_code=2)


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int
    raw: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2

    def as_json(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
            "center": {"x": self.center_x, "y": self.center_y},
        }


@dataclass(frozen=True)
class UiNode:
    order: int
    path: str
    depth: int
    attributes: dict[str, str]
    bounds: Bounds

    def boolean(self, name: str) -> bool | None:
        value = self.attributes.get(name)
        if value is None:
            return None
        if value == "true":
            return True
        if value == "false":
            return False
        raise CliFailure(
            "invalid_xml_attribute",
            f"Node {self.path} has invalid boolean attribute {name!r}: {value!r}",
        )

    def as_json(self) -> dict[str, Any]:
        index_value: int | str = self.attributes.get("index", "")
        try:
            index_value = int(index_value)
        except ValueError:
            pass

        result: dict[str, Any] = {
            "order": self.order,
            "path": self.path,
            "depth": self.depth,
            "index": index_value,
            "text": self.attributes.get("text", ""),
            "content-desc": self.attributes.get("content-desc", ""),
            "hint": self.attributes.get("hint", ""),
            "class": self.attributes.get("class", ""),
            "resource-id": self.attributes.get("resource-id", ""),
            "package": self.attributes.get("package", ""),
            "bounds": self.bounds.as_json(),
        }
        for name in (
            "clickable",
            "enabled",
            "focusable",
            "focused",
            "scrollable",
            "long-clickable",
            "checkable",
            "checked",
            "selected",
            "password",
        ):
            result[name] = self.boolean(name)
        return result


@dataclass(frozen=True)
class UiDocument:
    rotation: int | str
    nodes: tuple[UiNode, ...]


def emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def shorten(value: bytes, limit: int = 2000) -> str:
    text = value.decode("utf-8", errors="replace").strip()
    return text if len(text) <= limit else f"{text[:limit]}...<truncated>"


def adb_command(device: str, arguments: Iterable[str]) -> list[str]:
    command = ["adb"]
    if device:
        command.extend(["-s", device])
    command.extend(arguments)
    return command


def run_adb_raw(
    device: str,
    arguments: list[str],
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    command = adb_command(device, arguments)
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CliFailure("adb_not_found", "adb was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CliFailure(
            "adb_timeout",
            f"ADB command exceeded the {timeout:g}s timeout",
            details={
                "argv": command,
                "sideEffectMayHaveOccurred": may_have_tapped,
            },
        ) from exc


def run_adb(
    device: str,
    arguments: list[str],
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    command = adb_command(device, arguments)
    may_have_tapped = arguments[:3] == ["shell", "input", "tap"]
    result = run_adb_raw(device, arguments, timeout)

    if result.returncode != 0:
        raise CliFailure(
            "adb_failed",
            f"ADB command failed with exit code {result.returncode}",
            details={
                "argv": command,
                "stdout": shorten(result.stdout),
                "stderr": shorten(result.stderr),
                "sideEffectMayHaveOccurred": may_have_tapped,
            },
        )
    return result


def capture_xml(device: str, timeout: float) -> tuple[bytes, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        run_adb_raw(device, ["shell", "rm", "-f", REMOTE_XML_PATH], timeout)
        dump_result = run_adb_raw(
            device,
            ["shell", "uiautomator", "dump", REMOTE_XML_PATH],
            timeout,
        )
        read_result = run_adb_raw(
            device,
            ["exec-out", "cat", REMOTE_XML_PATH],
            timeout,
        )
        data = read_result.stdout
        valid = bool(
            read_result.returncode == 0
            and data.startswith(b"<?xml")
            and b"<hierarchy" in data
            and b"</hierarchy>" in data
        )
        attempt_record = {
            "attempt": attempt,
            "dumpReturncode": dump_result.returncode,
            "dumpOutput": shorten(dump_result.stdout or dump_result.stderr),
            "readReturncode": read_result.returncode,
            "readOutput": shorten(read_result.stderr),
            "bytes": len(data),
            "validCompleteXml": valid,
        }
        attempts.append(attempt_record)
        if valid:
            return data, {
                "type": "adb",
                "device": device or None,
                "remotePath": REMOTE_XML_PATH,
                "dumpOutput": attempt_record["dumpOutput"],
                "dumpReturncode": dump_result.returncode,
                "acceptedAttempt": attempt,
                "attempts": attempts,
            }
        time.sleep(attempt)
    raise CliFailure(
        "ui_dump_failed",
        "UIAutomator did not produce a complete fresh XML hierarchy after three attempts",
        details={"attempts": attempts},
    )


def read_xml(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise CliFailure(
            "xml_read_failed",
            f"Could not read XML file: {resolved}",
            details={"reason": str(exc)},
        ) from exc
    if not data.strip():
        raise CliFailure("empty_xml", f"XML file is empty: {resolved}")
    return data, {"type": "file", "path": str(resolved)}


def parse_bounds(raw: str, path: str) -> Bounds:
    match = BOUNDS_RE.fullmatch(raw)
    if not match:
        raise CliFailure(
            "invalid_bounds",
            f"Node {path} has malformed bounds: {raw!r}",
        )
    left, top, right, bottom = (int(value) for value in match.groups())
    if right < left or bottom < top:
        raise CliFailure(
            "invalid_bounds",
            f"Node {path} has inverted bounds: {raw!r}",
        )
    return Bounds(left, top, right, bottom, raw)


def parse_document(data: bytes) -> UiDocument:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CliFailure(
            "invalid_xml",
            "Could not parse UIAutomator XML",
            details={"reason": str(exc)},
        ) from exc
    if root.tag != "hierarchy":
        raise CliFailure(
            "invalid_xml_root",
            f"Expected <hierarchy> root, found <{root.tag}>",
        )

    rotation_raw = root.attrib.get("rotation", "")
    try:
        rotation: int | str = int(rotation_raw)
    except ValueError:
        rotation = rotation_raw

    parsed: list[UiNode] = []

    def visit(parent: ET.Element, parent_path: str, depth: int) -> None:
        for position, child in enumerate(parent):
            path = f"{parent_path}/{position}" if parent_path else str(position)
            if child.tag != "node":
                raise CliFailure(
                    "invalid_xml_node",
                    f"Unexpected <{child.tag}> element at {path}",
                )
            attributes = dict(child.attrib)
            if "bounds" not in attributes:
                raise CliFailure("missing_bounds", f"Node {path} has no bounds attribute")
            parsed.append(
                UiNode(
                    order=len(parsed),
                    path=path,
                    depth=depth,
                    attributes=attributes,
                    bounds=parse_bounds(attributes["bounds"], path),
                )
            )
            visit(child, path, depth + 1)

    visit(root, "", 0)
    if not parsed:
        raise CliFailure("empty_hierarchy", "UIAutomator XML contains no nodes")
    return UiDocument(rotation=rotation, nodes=tuple(parsed))


def selectors_from_args(args: argparse.Namespace) -> dict[str, str]:
    selectors: dict[str, str] = {}
    for argument_name, attribute_name in MATCH_FIELDS.items():
        value = getattr(args, argument_name, None)
        if value is None:
            continue
        if value == "":
            raise CliFailure(
                "empty_selector",
                f"--{attribute_name} must not be empty",
                exit_code=2,
            )
        selectors[attribute_name] = value
    if not selectors:
        raise CliFailure(
            "missing_selector",
            "At least one of --text, --content-desc, --hint, or --class is required",
            exit_code=2,
        )
    return selectors


def find_nodes(
    document: UiDocument,
    selectors: dict[str, str],
    *,
    contains: bool,
) -> list[UiNode]:
    def matches(node: UiNode) -> bool:
        for attribute, expected in selectors.items():
            actual = node.attributes.get(attribute, "")
            if contains:
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
        return True

    return [node for node in document.nodes if matches(node)]


def load_for_query(args: argparse.Namespace) -> tuple[UiDocument, dict[str, Any], bytes]:
    if getattr(args, "xml", None) is not None:
        if args.device:
            raise CliFailure(
                "invalid_arguments",
                "--device cannot be combined with --xml",
                exit_code=2,
            )
        data, source = read_xml(args.xml)
    else:
        data, source = capture_xml(args.device, args.timeout)
    return parse_document(data), source, data


def command_dump(args: argparse.Namespace) -> dict[str, Any]:
    data, source = capture_xml(args.device, args.timeout)
    document = parse_document(data)
    output_path: str | None = None
    if args.output is not None:
        resolved = args.output.expanduser().resolve()
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(data)
        except OSError as exc:
            raise CliFailure(
                "xml_write_failed",
                f"Could not write XML file: {resolved}",
                details={"reason": str(exc)},
            ) from exc
        output_path = str(resolved)

    return {
        "ok": True,
        "command": "dump",
        "source": source,
        "xmlOutput": output_path,
        "rotation": document.rotation,
        "nodeCount": len(document.nodes),
        "nodes": [node.as_json() for node in document.nodes],
    }


def query_payload(
    command: str,
    document: UiDocument,
    source: dict[str, Any],
    selectors: dict[str, str],
    contains: bool,
    matches: list[UiNode],
) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "source": source,
        "matchMode": "contains" if contains else "exact",
        "selectors": selectors,
        "rotation": document.rotation,
        "nodeCount": len(document.nodes),
        "matchCount": len(matches),
        "matches": [node.as_json() for node in matches],
    }


def command_find(args: argparse.Namespace) -> dict[str, Any]:
    selectors = selectors_from_args(args)
    document, source, _ = load_for_query(args)
    matches = find_nodes(document, selectors, contains=args.contains)
    if not matches:
        raise CliFailure(
            "no_matches",
            "No UI node matched all selectors",
            exit_code=4,
            details={
                "source": source,
                "matchMode": "contains" if args.contains else "exact",
                "selectors": selectors,
                "nodeCount": len(document.nodes),
            },
        )
    return query_payload("find", document, source, selectors, args.contains, matches)


def command_tap(args: argparse.Namespace) -> dict[str, Any]:
    selectors = selectors_from_args(args)
    data, source = capture_xml(args.device, args.timeout)
    document = parse_document(data)
    matches = find_nodes(document, selectors, contains=args.contains)
    if not matches:
        raise CliFailure(
            "no_matches",
            "Tap refused because no UI node matched all selectors",
            exit_code=4,
            details={
                "source": source,
                "matchMode": "contains" if args.contains else "exact",
                "selectors": selectors,
            },
        )
    if len(matches) != 1:
        raise CliFailure(
            "ambiguous_match",
            "Tap refused because the selectors matched more than one UI node",
            exit_code=5,
            details={
                "source": source,
                "matchMode": "contains" if args.contains else "exact",
                "selectors": selectors,
                "matchCount": len(matches),
                "matches": [node.as_json() for node in matches],
            },
        )

    target = matches[0]
    if target.boolean("enabled") is not True:
        raise CliFailure(
            "target_disabled",
            "Tap refused because the matched node is not enabled",
            exit_code=6,
            details={"target": target.as_json()},
        )
    if target.boolean("clickable") is not True:
        raise CliFailure(
            "target_not_clickable",
            "Tap refused because the matched node is not marked clickable",
            exit_code=6,
            details={"target": target.as_json()},
        )
    if target.bounds.width <= 0 or target.bounds.height <= 0:
        raise CliFailure(
            "empty_target_bounds",
            "Tap refused because the matched node has empty bounds",
            exit_code=6,
            details={"target": target.as_json()},
        )
    top_level_bounds = [node.bounds for node in document.nodes if node.depth == 0]
    center_is_on_screen = any(
        bounds.left <= target.bounds.center_x < bounds.right
        and bounds.top <= target.bounds.center_y < bounds.bottom
        for bounds in top_level_bounds
    )
    if not center_is_on_screen:
        raise CliFailure(
            "offscreen_target",
            "Tap refused because the target center is outside the top-level UI bounds",
            exit_code=6,
            details={
                "target": target.as_json(),
                "topLevelBounds": [bounds.as_json() for bounds in top_level_bounds],
            },
        )

    tap_result = run_adb(
        args.device,
        [
            "shell",
            "input",
            "tap",
            str(target.bounds.center_x),
            str(target.bounds.center_y),
        ],
        args.timeout,
    )
    return {
        "ok": True,
        "command": "tap",
        "source": source,
        "matchMode": "contains" if args.contains else "exact",
        "selectors": selectors,
        "target": target.as_json(),
        "tap": {"x": target.bounds.center_x, "y": target.bounds.center_y},
        "adbOutput": shorten(tap_result.stdout or tap_result.stderr),
    }


def add_live_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", default=None, help="Optional adb device serial")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Per-command ADB timeout in seconds (default: 30)",
    )


def add_selector_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--text", help="Match the node text attribute")
    parser.add_argument("--content-desc", dest="content_desc", help="Match content-desc")
    parser.add_argument("--hint", help="Match the node hint attribute")
    parser.add_argument("--class", dest="node_class", help="Match the Android class")
    parser.add_argument(
        "--contains",
        action="store_true",
        help="Use case-sensitive substring matching instead of exact matching",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Dump, find, and safely tap Android UIAutomator nodes.",
    )
    parser.add_argument(
        "--device",
        dest="global_device",
        default=None,
        help="Optional adb device serial; accepted before or after the subcommand",
    )
    parser.add_argument(
        "--timeout",
        dest="global_timeout",
        type=float,
        default=None,
        help="Per-command ADB timeout; accepted before or after the subcommand",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dump_parser = subparsers.add_parser("dump", help="Capture the live UI tree as JSON")
    add_live_options(dump_parser)
    dump_parser.add_argument("--output", type=Path, help="Also save the raw XML locally")

    find_parser = subparsers.add_parser("find", help="Find nodes in a file or live UI tree")
    add_live_options(find_parser)
    find_parser.add_argument("--xml", type=Path, help="Read saved XML instead of using ADB")
    add_selector_options(find_parser)

    tap_parser = subparsers.add_parser(
        "tap",
        help="Capture the live tree and tap one unique enabled, clickable match",
    )
    add_live_options(tap_parser)
    add_selector_options(tap_parser)
    return parser


def normalize_runtime_args(args: argparse.Namespace) -> None:
    local_device = getattr(args, "device", None)
    if (
        args.global_device is not None
        and local_device is not None
        and args.global_device != local_device
    ):
        raise CliFailure(
            "conflicting_device",
            "Conflicting --device values were provided",
            exit_code=2,
        )
    args.device = local_device if local_device is not None else (args.global_device or "")

    local_timeout = getattr(args, "timeout", None)
    if (
        args.global_timeout is not None
        and local_timeout is not None
        and args.global_timeout != local_timeout
    ):
        raise CliFailure(
            "conflicting_timeout",
            "Conflicting --timeout values were provided",
            exit_code=2,
        )
    if local_timeout is not None:
        args.timeout = local_timeout
    elif args.global_timeout is not None:
        args.timeout = args.global_timeout
    else:
        args.timeout = 30.0
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise CliFailure(
            "invalid_timeout",
            "--timeout must be greater than zero",
            exit_code=2,
        )


def main() -> int:
    command = None
    try:
        args = build_parser().parse_args()
        command = args.command
        normalize_runtime_args(args)
        handlers = {
            "dump": command_dump,
            "find": command_find,
            "tap": command_tap,
        }
        emit(handlers[args.command](args))
        return 0
    except CliFailure as exc:
        payload: dict[str, Any] = {
            "ok": False,
            "command": command,
            "error": {"code": exc.code, "message": exc.message},
        }
        if exc.details:
            payload["error"]["details"] = exc.details
        emit(payload)
        return exc.exit_code
    except KeyboardInterrupt:
        emit(
            {
                "ok": False,
                "command": command,
                "error": {
                    "code": "interrupted",
                    "message": "Operation interrupted before completion",
                },
            }
        )
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:  # Keep unexpected failures machine-readable and nonzero.
        emit(
            {
                "ok": False,
                "command": command,
                "error": {
                    "code": "internal_error",
                    "message": "Unexpected failure; no successful result can be assumed",
                    "details": {"type": type(exc).__name__, "reason": str(exc)},
                },
            }
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
