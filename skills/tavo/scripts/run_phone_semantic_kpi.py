#!/usr/bin/env python3
"""Run 50 direct, feature-specific Tavo model calls on the real phone.

Each of ten feature families must pass five direct calls in its own context.
Fallback chats never count. UI families require UI-tree clicks, TavoJS variable
set/get evidence, MCP input readback, and screenshots. Five negative-control
calls run immediately after their first related positive case and never replace
any primary result.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import traceback
import urllib.parse
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_import_kpi import (  # noqa: E402
    append_event,
    atomic_json,
    import_plugin,
    load_json,
    now_utc,
    response_items,
    response_payload,
    tool_call,
)
from run_phone_kpi_batch import (  # noqa: E402
    TavoMcp,
    capture_phone,
    file_info,
    load_endpoint,
    ok_response,
    redact,
    text_payload,
)


FAMILIES = [
    "character-thread",
    "lorebook-trigger",
    "regex-runtime",
    "preset-stack",
    "persona-binding",
    "macro-ejs",
    "tavojs-variable",
    "advanced-rendering",
    "plugin-action-panel",
    "mcp-message-ops",
]
CALLS_PER_FAMILY = 5
PRIMARY_TARGET = len(FAMILIES) * CALLS_PER_FAMILY
CONTROL_TARGET = 5
UI_FAMILIES = {"tavojs-variable", "advanced-rendering", "plugin-action-panel"}
UI_TOOL = ROOT / "scripts" / "tavo_ui_tree.py"
TEMPLATE_ROOT = ROOT / "assets" / "templates" / "semantic-validation"
MCP_SCHEMA_URIS = [
    "tavo://schemas/character",
    "tavo://schemas/chat",
    "tavo://schemas/lorebook",
    "tavo://schemas/lorebook-entry",
    "tavo://schemas/message",
    "tavo://schemas/persona",
    "tavo://schemas/preset",
    "tavo://schemas/regex",
    "tavo://schemas/regex-entry",
]


@dataclass
class CallSpec:
    family: str
    ordinal: int
    chat_id: int
    prompt: str
    nonce: str
    expected: list[str] = field(default_factory=list)
    expected_any: list[list[str]] = field(default_factory=list)
    expected_patterns: list[str] = field(default_factory=list)
    expected_any_may_use_reasoning: bool = False
    forbidden: list[str] = field(default_factory=list)
    mode: str = "mcp"
    ui_label: str | None = None
    ui_marker: str | None = None
    persona_name: str | None = None
    counts_toward_primary: bool = True
    control_name: str | None = None
    attempt: str = "base"
    variant: str = "base"
    history_trigger: str | None = None
    panel_variant: str | None = None
    panel_source_sha256: str | None = None
    reload_chat_id: int | None = None
    attempt_chat_ids: list[int] = field(default_factory=list)
    attempt_reload_chat_ids: list[int] = field(default_factory=list)
    attempt_panel_sources: list[dict[str, Any]] = field(default_factory=list)
    attempt_ui_markers: list[str] = field(default_factory=list)
    required_prefix: str | None = None
    ordered_markers: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        prefix = "control" if not self.counts_toward_primary else "primary"
        control = f"-{safe_name(self.control_name)}" if self.control_name else ""
        variant = "" if self.variant == "base" else f"-{safe_name(self.variant)}"
        return f"{prefix}-{self.family}-{self.ordinal:02d}{variant}-{self.attempt}{control}"

    @property
    def step_name(self) -> str:
        suffix = "" if self.attempt == "base" else f"-{self.attempt}"
        variant = "" if self.variant == "base" else f"-{safe_name(self.variant)}"
        control = f"-{self.control_name}" if self.control_name else ""
        return f"{self.ordinal:02d}{variant}{suffix}{control}"


class ReconciliationPending(RuntimeError):
    """A send may have reached the model and must not be retried yet."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("A model send remains transport-uncertain; resume must reconcile it before any retry.")
        self.result = result


class RuntimeLockSet:
    def __init__(self, handles: list[Any]) -> None:
        self.handles = handles

    def close(self) -> None:
        for handle in reversed(self.handles):
            handle.close()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def durable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(redact(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def durable_private_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def durable_result_once(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Commit a terminal attempt result without ever replacing prior evidence."""
    if path.exists():
        existing = load_json(path)
        if not isinstance(existing, dict):
            raise RuntimeError(f"Immutable result is not a JSON object: {path}")
        identity_keys = (
            "epochId",
            "scriptHash",
            "planHash",
            "contextHash",
            "deviceHash",
            "importManifestHash",
            "importEvidenceHash",
            "mcpSurfaceHash",
            "uiPreflightEvidenceHash",
            "specHash",
            "family",
            "ordinal",
            "variant",
            "attempt",
            "chatId",
        )
        mismatches = {
            key: {"expected": value.get(key), "actual": existing.get(key)}
            for key in identity_keys
            if value.get(key) != existing.get(key)
        }
        if mismatches:
            raise RuntimeError(f"Immutable result identity mismatch at {path}: {mismatches}")
        return existing
    durable_json(path, value)
    return load_json(path)


def runtime_plugin_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        plugin_id = value.get("pluginId")
        if isinstance(plugin_id, str) and plugin_id:
            found.add(plugin_id)
        for child in value.values():
            found.update(runtime_plugin_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(runtime_plugin_ids(child))
    return found


def semantic_runtime_contract(value: Any, target_plugin_id: str) -> bool:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return bool(
        runtime_plugin_ids(value) == {target_plugin_id}
        and all(
            action_id in rendered
            for action_id in (
                "observe-scene",
                "clarify-goal",
                "check-state",
                "propose-next-step",
                "summarize-evidence",
                "ejs-runtime-seed",
                "ejs-runtime-probe",
            )
        )
        and "semantic-validation-panel" in rendered
    )


def assert_isolated_plugin_runtime(
    client: TavoMcp,
    step_dir: Path,
    target_plugin_id: str,
    label: str,
) -> None:
    response = tool_call(
        client,
        step_dir,
        f"runtime-invariant-{safe_name(label)}.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    payload = response_payload(response)
    passed = bool(ok_response(response) and semantic_runtime_contract(payload, target_plugin_id))
    durable_json(
        step_dir / f"runtime-invariant-{safe_name(label)}-result.json",
        {
            "label": label,
            "targetPluginId": target_plugin_id,
            "runtimePluginIds": sorted(runtime_plugin_ids(payload)),
            "runtimeHash": stable_hash(payload),
            "passed": passed,
        },
    )
    if not passed:
        raise RuntimeError(f"Plugin runtime isolation invariant failed at {label}.")


def list_installed_plugins(client: TavoMcp, output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    seen_cursors: set[int] = set()
    cursor: int | None = None
    page = 1
    while True:
        arguments: dict[str, Any] = {"limit": 100}
        if cursor is not None:
            arguments["cursor"] = cursor
        response = tool_call(
            client,
            output_dir,
            f"page-{page:03d}.json",
            "tavo_plugin_search",
            arguments,
        )
        if not ok_response(response):
            raise RuntimeError("Could not enumerate installed plugins for runtime isolation.")
        payload = response_payload(response)
        page_items = payload.get("items")
        if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
            raise RuntimeError("Plugin search returned an invalid items payload.")
        items.extend(page_items)
        next_cursor = payload.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, int) or next_cursor < 0 or next_cursor in seen_cursors:
            raise RuntimeError("Plugin search returned an invalid or repeated cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        page += 1
    plugin_ids = [str(item.get("pluginId") or "") for item in items]
    if any(not plugin_id for plugin_id in plugin_ids) or len(plugin_ids) != len(set(plugin_ids)):
        raise RuntimeError("Plugin search returned missing or duplicate plugin IDs.")
    return sorted(items, key=lambda item: str(item["pluginId"]))


def snapshot_plugin_runtime(
    client: TavoMcp,
    isolation_dir: Path,
    target_plugin_id: str,
    epoch_id: str,
) -> dict[str, Any]:
    snapshot_dir = isolation_dir / "snapshot"
    search_items = list_installed_plugins(client, snapshot_dir / "search-a")
    records: list[dict[str, Any]] = []
    for item in search_items:
        plugin_id = str(item["pluginId"])
        step_dir = snapshot_dir / "plugins" / safe_name(plugin_id)
        readback = tool_call(client, step_dir, "readback.json", "tavo_plugin_get", {"pluginId": plugin_id})
        payload = response_payload(readback)
        if (
            not ok_response(readback)
            or payload.get("pluginId") != plugin_id
            or not isinstance(payload.get("enabled"), bool)
            or payload.get("enabled") != item.get("enabled")
        ):
            raise RuntimeError(f"Plugin snapshot readback failed for {plugin_id}.")
        records.append(
            {
                "pluginId": plugin_id,
                "name": payload.get("name"),
                "enabled": bool(payload["enabled"]),
                "features": payload.get("features"),
                "payloadHash": stable_hash(payload),
            }
        )
    search_items_check = list_installed_plugins(client, snapshot_dir / "search-b")
    if stable_hash(search_items_check) != stable_hash(search_items):
        raise RuntimeError("Installed plugin inventory changed while its isolation snapshot was being captured.")
    target_records = [record for record in records if record["pluginId"] == target_plugin_id]
    if len(target_records) != 1 or target_records[0]["enabled"] is not True:
        raise RuntimeError("The epoch semantic plugin is missing or disabled before isolation.")
    runtime = tool_call(
        client,
        snapshot_dir,
        "runtime-contributions.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    runtime_payload = response_payload(runtime)
    if not ok_response(runtime) or target_plugin_id not in runtime_plugin_ids(runtime_payload):
        raise RuntimeError("The epoch semantic plugin is absent from the pre-isolation runtime.")
    snapshot = {
        "epochId": epoch_id,
        "targetPluginId": target_plugin_id,
        "capturedAt": now_utc(),
        "pluginCount": len(records),
        "enabledCount": sum(1 for record in records if record["enabled"]),
        "pluginIdsHash": stable_hash([record["pluginId"] for record in records]),
        "searchItemsHash": stable_hash(search_items),
        "runtimeContributionsHash": stable_hash(runtime_payload),
        "runtimePluginIds": sorted(runtime_plugin_ids(runtime_payload)),
        "plugins": records,
    }
    durable_json(snapshot_dir / "snapshot.json", snapshot)
    return snapshot


def restore_plugin_runtime(
    client: TavoMcp,
    isolation_dir: Path,
    snapshot: dict[str, Any],
    reason: str,
) -> bool:
    disk_snapshot_path = isolation_dir / "snapshot" / "snapshot.json"
    disk_snapshot = load_json(disk_snapshot_path)
    if stable_hash(disk_snapshot) != stable_hash(snapshot):
        raise RuntimeError("In-memory plugin snapshot does not match the durable recovery snapshot.")
    snapshot = disk_snapshot
    restore_dir = isolation_dir / f"restore-{safe_name(reason)}"
    restore_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for record in snapshot.get("plugins", []):
        plugin_id = str(record["pluginId"])
        expected_enabled = bool(record["enabled"])
        expected_hash = str(record["payloadHash"])
        step_dir = restore_dir / "plugins" / safe_name(plugin_id)
        try:
            current = tool_call(client, step_dir, "current.json", "tavo_plugin_get", {"pluginId": plugin_id})
            current_payload = response_payload(current)
            current_enabled = current_payload.get("enabled")
            current_hash = stable_hash(current_payload)
            changed = current_enabled != expected_enabled
            dry: dict[str, Any] | None = None
            actual: dict[str, Any] | None = None
            actual_error: str | None = None
            after_dry_payload = current_payload
            if changed:
                dry = tool_call(
                    client,
                    step_dir,
                    "set-enabled-dry-run.json",
                    "tavo_plugin_set_enabled",
                    {"pluginId": plugin_id, "enabled": expected_enabled, "dryRun": True},
                )
                after_dry = tool_call(
                    client,
                    step_dir,
                    "after-dry-run.json",
                    "tavo_plugin_get",
                    {"pluginId": plugin_id},
                )
                after_dry_payload = response_payload(after_dry)
                if (
                    not ok_response(dry)
                    or not ok_response(after_dry)
                    or stable_hash(after_dry_payload) != current_hash
                ):
                    raise RuntimeError(f"Plugin restore dry-run changed state for {plugin_id}.")
                try:
                    actual = tool_call(
                        client,
                        step_dir,
                        "set-enabled-actual.json",
                        "tavo_plugin_set_enabled",
                        {"pluginId": plugin_id, "enabled": expected_enabled, "dryRun": False},
                    )
                except Exception as exc:  # noqa: BLE001
                    actual_error = repr(exc)
                    durable_json(step_dir / "set-enabled-actual-exception.json", {"error": actual_error})
            final = tool_call(client, step_dir, "final.json", "tavo_plugin_get", {"pluginId": plugin_id})
            final_payload = response_payload(final)
            passed = bool(
                ok_response(current)
                and (
                    not changed
                    or (
                        dry is not None
                        and ok_response(dry)
                        and stable_hash(after_dry_payload) == current_hash
                        and ((actual is not None and ok_response(actual)) or actual_error is not None)
                    )
                )
                and ok_response(final)
                and final_payload.get("enabled") is expected_enabled
                and stable_hash(final_payload) == expected_hash
            )
            result = {
                "pluginId": plugin_id,
                "expectedEnabled": expected_enabled,
                "changed": changed,
                "actualError": actual_error,
                "expectedPayloadHash": expected_hash,
                "finalPayloadHash": stable_hash(final_payload),
                "passed": passed,
            }
        except Exception as exc:  # noqa: BLE001
            result = {
                "pluginId": plugin_id,
                "expectedEnabled": expected_enabled,
                "passed": False,
                "error": repr(exc),
            }
        results.append(result)
        durable_json(restore_dir / "progress.json", results)
    time.sleep(1.2)
    search_items: list[dict[str, Any]] = []
    runtime_payload: dict[str, Any] = {}
    final_errors: list[str] = []
    try:
        search_items = list_installed_plugins(client, restore_dir / "final-search")
        search_items_check = list_installed_plugins(client, restore_dir / "final-search-check")
        if stable_hash(search_items_check) != stable_hash(search_items):
            final_errors.append("installed plugin inventory changed during final restoration verification")
        if stable_hash(search_items) != snapshot.get("searchItemsHash"):
            final_errors.append("installed plugin search payload did not return to the snapshot hash")
        if stable_hash([str(item["pluginId"]) for item in search_items]) != snapshot.get("pluginIdsHash"):
            final_errors.append("installed plugin ID set changed during isolation")
        enabled_by_id = {str(item["pluginId"]): item.get("enabled") for item in search_items}
        for record in snapshot.get("plugins", []):
            if enabled_by_id.get(str(record["pluginId"])) != bool(record["enabled"]):
                final_errors.append(f"enabled state mismatch for {record['pluginId']}")
    except Exception as exc:  # noqa: BLE001
        final_errors.append(f"final plugin search failed: {exc!r}")
    try:
        runtime = tool_call(
            client,
            restore_dir,
            "runtime-contributions.json",
            "tavo_plugin_get_runtime_contributions",
            {},
        )
        runtime_payload = response_payload(runtime)
        if not ok_response(runtime) or stable_hash(runtime_payload) != snapshot.get("runtimeContributionsHash"):
            final_errors.append("runtime contributions did not return to the snapshot hash")
    except Exception as exc:  # noqa: BLE001
        final_errors.append(f"final runtime readback failed: {exc!r}")
    passed = all(result.get("passed") for result in results) and not final_errors
    durable_json(
        restore_dir / "result.json",
        {
            "reason": reason,
            "finishedAt": now_utc(),
            "pluginCount": len(results),
            "restoredCount": sum(1 for result in results if result.get("passed")),
            "runtimeContributionsHash": stable_hash(runtime_payload),
            "expectedRuntimeContributionsHash": snapshot.get("runtimeContributionsHash"),
            "errors": final_errors,
            "passed": passed,
        },
    )
    return passed


def recover_plugin_runtime(client: TavoMcp, isolation_dir: Path, reason: str) -> bool:
    snapshot_path = isolation_dir / "snapshot" / "snapshot.json"
    if not snapshot_path.exists():
        raise RuntimeError("No durable plugin snapshot exists for recovery.")
    snapshot = load_json(snapshot_path)
    return restore_plugin_runtime(client, isolation_dir, snapshot, reason)


def list_presets_with_readbacks(client: TavoMcp, output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    search_items: list[dict[str, Any]] = []
    cursor: int | None = None
    page = 1
    while True:
        arguments: dict[str, Any] = {"limit": 100}
        if cursor is not None:
            arguments["cursor"] = cursor
        response = tool_call(
            client,
            output_dir / "search",
            f"page-{page:03d}.json",
            "tavo_preset_search",
            arguments,
        )
        if not ok_response(response):
            raise RuntimeError("Could not enumerate presets while managing the active preset.")
        payload = response_payload(response)
        page_items = payload.get("items")
        if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
            raise RuntimeError("Preset search returned an invalid items payload.")
        search_items.extend(page_items)
        next_cursor = payload.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, int) or next_cursor < 0 or next_cursor == cursor:
            raise RuntimeError("Preset search returned an invalid cursor.")
        cursor = next_cursor
        page += 1
    preset_ids = [int(item.get("id") or 0) for item in search_items]
    if any(preset_id < 1 for preset_id in preset_ids) or len(preset_ids) != len(set(preset_ids)):
        raise RuntimeError("Preset search returned missing or duplicate IDs.")
    records: list[dict[str, Any]] = []
    for preset_id in sorted(preset_ids):
        readback = tool_call(
            client,
            output_dir / "presets" / str(preset_id),
            "readback.json",
            "tavo_preset_get",
            {"id": preset_id},
        )
        payload = response_payload(readback)
        if (
            not ok_response(readback)
            or int(payload.get("id") or 0) != preset_id
            or not isinstance(payload.get("active"), bool)
        ):
            raise RuntimeError(f"Preset readback failed while enumerating active state for {preset_id}.")
        records.append(
            {
                "id": preset_id,
                "name": payload.get("name"),
                "active": bool(payload["active"]),
                "revision": payload.get("revision"),
                "payloadHash": stable_hash(payload),
            }
        )
    return records


def snapshot_active_preset_runtime(client: TavoMcp, state_dir: Path, epoch_id: str) -> dict[str, Any]:
    if state_dir.exists() and any(state_dir.iterdir()):
        raise RuntimeError("Active-preset state evidence already exists and is immutable.")
    records = list_presets_with_readbacks(client, state_dir / "snapshot")
    active_ids = [int(record["id"]) for record in records if record["active"]]
    if len(active_ids) != 1:
        raise RuntimeError(f"Expected exactly one active preset before model testing, found {active_ids}.")
    snapshot = {
        "epochId": epoch_id,
        "capturedAt": now_utc(),
        "presetCount": len(records),
        "activePresetIds": active_ids,
        "presetIdSetHash": stable_hash([record["id"] for record in records]),
        "records": records,
    }
    durable_json(state_dir / "snapshot.json", snapshot)
    return snapshot


def activate_preset_exact(
    client: TavoMcp,
    step_dir: Path,
    preset_id: int,
    request_scope: str,
) -> bool:
    before = tool_call(client, step_dir, "preset-before.json", "tavo_preset_get", {"id": preset_id})
    before_payload = response_payload(before)
    if not ok_response(before) or int(before_payload.get("id") or 0) != preset_id:
        raise RuntimeError(f"Could not read target preset {preset_id} before activation.")
    changed = before_payload.get("active") is not True
    dry: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    actual_error: str | None = None
    if changed:
        arguments = {
            "id": preset_id,
            "dryRun": True,
            "expectedRevision": str(before_payload.get("revision") or ""),
            "clientRequestId": f"semantic-{safe_name(request_scope)}-preset-{preset_id}-dry",
        }
        dry = tool_call(client, step_dir, "preset-activate-dry-run.json", "tavo_preset_set_active", arguments)
        after_dry = tool_call(client, step_dir, "preset-after-dry-run.json", "tavo_preset_get", {"id": preset_id})
        after_dry_payload = response_payload(after_dry)
        if (
            not ok_response(dry)
            or not ok_response(after_dry)
            or stable_hash(after_dry_payload) != stable_hash(before_payload)
        ):
            raise RuntimeError(f"Preset activation dry-run changed target preset {preset_id}.")
        arguments["dryRun"] = False
        arguments["clientRequestId"] = f"semantic-{safe_name(request_scope)}-preset-{preset_id}-actual"
        try:
            actual = tool_call(
                client,
                step_dir,
                "preset-activate-actual.json",
                "tavo_preset_set_active",
                arguments,
            )
        except Exception as exc:  # noqa: BLE001
            actual_error = repr(exc)
            durable_json(step_dir / "preset-activate-actual-exception.json", {"error": actual_error})
    final = tool_call(client, step_dir, "preset-final.json", "tavo_preset_get", {"id": preset_id})
    final_payload = response_payload(final)
    passed = bool(
        ok_response(before)
        and (
            not changed
            or ((actual is not None and ok_response(actual)) or actual_error is not None)
        )
        and ok_response(final)
        and final_payload.get("active") is True
    )
    durable_json(
        step_dir / "preset-activation-result.json",
        {
            "presetId": preset_id,
            "changed": changed,
            "actualError": actual_error,
            "beforeRevision": before_payload.get("revision"),
            "finalRevision": final_payload.get("revision"),
            "passed": passed,
        },
    )
    return passed


def activate_chat_preset(client: TavoMcp, step_dir: Path, chat_id: int, request_scope: str) -> int:
    chat = tool_call(client, step_dir, "preset-chat-readback.json", "tavo_chat_get", {"id": chat_id})
    chat_payload = response_payload(chat)
    preset_id = int(chat_payload.get("presetId") or 0)
    if not ok_response(chat) or int(chat_payload.get("id") or 0) != chat_id or preset_id < 1:
        raise RuntimeError(f"Chat {chat_id} has no valid preset binding to activate.")
    if not activate_preset_exact(client, step_dir / "preset-activation", preset_id, request_scope):
        raise RuntimeError(f"Could not activate chat {chat_id}'s bound preset {preset_id}.")
    return preset_id


def recover_active_preset_runtime(client: TavoMcp, state_dir: Path, reason: str) -> bool:
    snapshot = load_json(state_dir / "snapshot.json")
    active_ids = snapshot.get("activePresetIds")
    if not isinstance(active_ids, list) or len(active_ids) != 1:
        raise RuntimeError("Durable active-preset snapshot is invalid.")
    restore_dir = state_dir / f"restore-{safe_name(reason)}"
    target_id = int(active_ids[0])
    activated = activate_preset_exact(client, restore_dir / "activation", target_id, f"{snapshot['epochId']}-{reason}")
    records = list_presets_with_readbacks(client, restore_dir / "final")
    final_active_ids = [int(record["id"]) for record in records if record["active"]]
    passed = bool(
        activated
        and final_active_ids == [target_id]
        and stable_hash([record["id"] for record in records]) == snapshot.get("presetIdSetHash")
    )
    durable_json(
        restore_dir / "result.json",
        {
            "reason": reason,
            "targetActivePresetId": target_id,
            "finalActivePresetIds": final_active_ids,
            "presetCount": len(records),
            "passed": passed,
        },
    )
    return passed


def isolate_plugin_runtime(
    client: TavoMcp,
    isolation_dir: Path,
    target_plugin_id: str,
    epoch_id: str,
    expected_target_hash: str | None = None,
) -> dict[str, Any]:
    if isolation_dir.exists() and any(isolation_dir.iterdir()):
        raise RuntimeError("Plugin isolation evidence already exists and is immutable.")
    isolation_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_plugin_runtime(client, isolation_dir, target_plugin_id, epoch_id)
    target_record = next(record for record in snapshot["plugins"] if record["pluginId"] == target_plugin_id)
    if expected_target_hash and target_record["payloadHash"] != expected_target_hash:
        raise RuntimeError("The epoch semantic plugin changed after context preparation.")
    disabled: list[dict[str, Any]] = []
    try:
        for record in snapshot["plugins"]:
            plugin_id = str(record["pluginId"])
            if plugin_id == target_plugin_id or record["enabled"] is not True:
                continue
            step_dir = isolation_dir / "disable" / safe_name(plugin_id)
            before = tool_call(client, step_dir, "before.json", "tavo_plugin_get", {"pluginId": plugin_id})
            before_payload = response_payload(before)
            if not ok_response(before) or stable_hash(before_payload) != record["payloadHash"]:
                raise RuntimeError(f"Plugin {plugin_id} drifted after the durable isolation snapshot.")
            dry = tool_call(
                client,
                step_dir,
                "dry-run.json",
                "tavo_plugin_set_enabled",
                {"pluginId": plugin_id, "enabled": False, "dryRun": True},
            )
            after_dry = tool_call(
                client,
                step_dir,
                "after-dry-run.json",
                "tavo_plugin_get",
                {"pluginId": plugin_id},
            )
            after_dry_payload = response_payload(after_dry)
            if (
                not ok_response(dry)
                or not ok_response(after_dry)
                or stable_hash(after_dry_payload) != record["payloadHash"]
            ):
                raise RuntimeError(f"Plugin isolation dry-run changed state for {plugin_id}.")
            actual: dict[str, Any] | None = None
            actual_error: str | None = None
            try:
                actual = tool_call(
                    client,
                    step_dir,
                    "actual.json",
                    "tavo_plugin_set_enabled",
                    {"pluginId": plugin_id, "enabled": False, "dryRun": False},
                )
            except Exception as exc:  # noqa: BLE001
                actual_error = repr(exc)
                durable_json(step_dir / "actual-exception.json", {"error": actual_error})
            readback = tool_call(client, step_dir, "readback.json", "tavo_plugin_get", {"pluginId": plugin_id})
            payload = response_payload(readback)
            passed = bool(
                ok_response(dry)
                and ((actual is not None and ok_response(actual)) or actual_error is not None)
                and ok_response(readback)
                and payload.get("pluginId") == plugin_id
                and payload.get("enabled") is False
            )
            result = {
                "pluginId": plugin_id,
                "actualError": actual_error,
                "passed": passed,
                "finishedAt": now_utc(),
            }
            disabled.append(result)
            durable_json(isolation_dir / "disable-progress.json", disabled)
            if not passed:
                raise RuntimeError(f"Could not disable unrelated plugin {plugin_id}.")
        time.sleep(1.2)
        current_items = list_installed_plugins(client, isolation_dir / "isolated-search")
        expected_ids = [str(record["pluginId"]) for record in snapshot["plugins"]]
        current_ids = [str(item["pluginId"]) for item in current_items]
        enabled_ids = sorted(str(item["pluginId"]) for item in current_items if item.get("enabled") is True)
        if current_ids != expected_ids or enabled_ids != [target_plugin_id]:
            raise RuntimeError("Isolated plugin list or enabled-state set does not match the snapshot contract.")
        target = tool_call(
            client,
            isolation_dir,
            "target-readback.json",
            "tavo_plugin_get",
            {"pluginId": target_plugin_id},
        )
        runtime = tool_call(
            client,
            isolation_dir,
            "isolated-runtime-contributions.json",
            "tavo_plugin_get_runtime_contributions",
            {},
        )
        target_payload = response_payload(target)
        runtime_payload = response_payload(runtime)
        runtime_ids = runtime_plugin_ids(runtime_payload)
        if (
            not ok_response(target)
            or target_payload.get("enabled") is not True
            or not ok_response(runtime)
            or not semantic_runtime_contract(runtime_payload, target_plugin_id)
        ):
            raise RuntimeError("Runtime isolation did not leave exactly the epoch semantic plugin active.")
        result = {
            "epochId": epoch_id,
            "targetPluginId": target_plugin_id,
            "pluginCount": snapshot["pluginCount"],
            "originalEnabledCount": snapshot["enabledCount"],
            "disabledCount": len(disabled),
            "isolatedRuntimePluginIds": sorted(runtime_ids),
            "isolatedAt": now_utc(),
            "passed": True,
        }
        durable_json(isolation_dir / "isolation-result.json", result)
        return {"root": str(isolation_dir), "snapshot": snapshot, "result": result}
    except Exception as exc:  # noqa: BLE001
        durable_json(
            isolation_dir / "isolation-failure.json",
            {"failedAt": now_utc(), "error": repr(exc), "traceback": traceback.format_exc()},
        )
        emergency_restored = recover_plugin_runtime(client, isolation_dir, "isolation-failure")
        durable_json(isolation_dir / "emergency-restore.json", {"passed": emergency_restored})
        if not emergency_restored:
            raise RuntimeError(f"Plugin isolation failed and exact emergency restoration also failed: {exc!r}") from exc
        raise


def runner_bundle_records() -> list[dict[str, str]]:
    paths = [
        Path(__file__).resolve(),
        ROOT / "scripts" / "run_phone_import_kpi.py",
        ROOT / "scripts" / "run_phone_kpi_batch.py",
        ROOT / "scripts" / "run_phone_semantic_ui_preflight.py",
        ROOT / "scripts" / "tavo_phone_capture.py",
        UI_TOOL,
    ]
    paths.extend(path for path in TEMPLATE_ROOT.rglob("*") if path.is_file())
    records = [
        {
            "path": str(path.resolve().relative_to(ROOT)),
            "sha256": sha256(path.resolve()),
        }
        for path in sorted(set(paths))
    ]
    return records


def spec_record(spec: CallSpec) -> dict[str, Any]:
    record = dict(spec.__dict__)
    record["specHash"] = stable_hash(record)
    return record


def derive_attempt_specs(spec: CallSpec) -> list[CallSpec]:
    if len(spec.attempt_chat_ids) != 3 or len(set(spec.attempt_chat_ids)) != 3:
        raise RuntimeError(f"{spec.key} has no immutable three-chat attempt plan.")
    attempts: list[CallSpec] = []
    for attempt_number, chat_id in enumerate(spec.attempt_chat_ids, start=1):
        nonce = f"{spec.nonce}_ATTEMPT_{attempt_number}"
        prompt = spec.prompt.replace(spec.nonce, nonce) if spec.prompt else spec.prompt
        updates: dict[str, Any] = {}
        if spec.mode == "ar-ui":
            if (
                len(spec.attempt_reload_chat_ids) != 3
                or len(set(spec.attempt_reload_chat_ids)) != 3
                or len(spec.attempt_panel_sources) != 3
                or len(spec.attempt_ui_markers) != 3
                or len(set(spec.attempt_ui_markers)) != 3
            ):
                raise RuntimeError(f"{spec.key} has no isolated three-attempt AR evidence plan.")
            panel = spec.attempt_panel_sources[attempt_number - 1]
            marker = spec.attempt_ui_markers[attempt_number - 1]
            updates = {
                "reload_chat_id": int(spec.attempt_reload_chat_ids[attempt_number - 1]),
                "panel_variant": str(panel["variant"]),
                "panel_source_sha256": str(panel["sourceSha256"]),
                "ui_marker": marker,
                "expected": [marker],
            }
        attempts.append(
            replace(
                spec,
                chat_id=int(chat_id),
                prompt=prompt,
                nonce=nonce,
                attempt=f"attempt-{attempt_number}",
                **updates,
            )
        )
    return attempts


def spec_plan_record(spec: CallSpec) -> dict[str, Any]:
    record = spec_record(spec)
    record["attemptPlan"] = [spec_record(attempt) for attempt in derive_attempt_specs(spec)]
    return record


def context_identity(registry: dict[str, Any]) -> dict[str, Any]:
    assets = {
        kind: [
            {
                "objectId": item.get("objectId"),
                "name": item.get("name"),
                "evidenceMarker": item.get("evidenceMarker"),
                "sourceSha256": (item.get("sourceInfo") or {}).get("sha256"),
            }
            for item in items
        ]
        for kind, items in registry.get("assets", {}).items()
    }
    chats = {
        family: [{"id": chat.get("id"), "name": chat.get("name"), "payload": chat.get("payload")} for chat in items]
        for family, items in registry.get("chats", {}).items()
    }
    controls = {
        name: {"id": chat.get("id"), "name": chat.get("name"), "payload": chat.get("payload")}
        for name, chat in registry.get("controls", {}).items()
    }
    preflight_chats = {
        family: [{"id": chat.get("id"), "name": chat.get("name"), "payload": chat.get("payload")} for chat in items]
        for family, items in registry.get("preflightChats", {}).items()
    }
    return {
        "runId": registry.get("runId"),
        "importArtifact": registry.get("importArtifact"),
        "assets": assets,
        "liveAssetReadbacks": registry.get("liveAssetReadbacks"),
        "semanticLorebooks": registry.get("semanticLorebooks"),
        "semanticPresets": registry.get("semanticPresets"),
        "ejsCharacter": registry.get("ejsCharacter"),
        "semanticPlugin": registry.get("semanticPlugin"),
        "neutralPersona": registry.get("neutralPersona"),
        "neutralPreset": registry.get("neutralPreset"),
        "personas": registry.get("personas"),
        "chats": chats,
        "preflightChats": preflight_chats,
        "ejsPluginPreflightChat": registry.get("ejsPluginPreflightChat"),
        "controls": controls,
        "retryChats": registry.get("retryChats"),
        "uiReloadAnchors": registry.get("uiReloadAnchors"),
        "panelSources": registry.get("panelSources"),
        "preflightPanelSources": registry.get("preflightPanelSources"),
    }


def render_template(path: Path, replacements: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def parse_import_assets(path: Path) -> dict[str, list[dict[str, Any]]]:
    results = load_json(path / "import-results.json")
    if not isinstance(results, list):
        raise RuntimeError("Strict import artifact has no valid import-results.json list.")
    grouped = {kind: [] for kind in ("character", "lorebook", "regex", "preset", "plugin")}
    for result in results:
        if not isinstance(result, dict) or not result.get("passed") or not result.get("countable"):
            continue
        kind = result.get("kind")
        if kind in grouped:
            grouped[kind].append(result)
    expected_counts = {"character": 15, "lorebook": 10, "regex": 10, "preset": 10, "plugin": 5}
    all_source_hashes: list[str] = []
    all_source_paths: list[str] = []
    for kind, expected_count in expected_counts.items():
        grouped[kind].sort(key=lambda item: int(item["index"]))
        if len(grouped[kind]) != expected_count:
            raise RuntimeError(
                f"Strict import artifact has {len(grouped[kind])} passing {kind} items; expected exactly {expected_count}."
            )
        indexes = [int(item["index"]) for item in grouped[kind]]
        object_ids = [str(item.get("objectId")) for item in grouped[kind]]
        if indexes != list(range(1, expected_count + 1)):
            raise RuntimeError(f"Strict import artifact has missing or duplicate {kind} indexes: {indexes}.")
        if any(value in {"", "None", "0"} for value in object_ids) or len(set(object_ids)) != expected_count:
            raise RuntimeError(f"Strict import artifact has missing or duplicate {kind} object IDs.")
        for item in grouped[kind]:
            source_path = Path(str(item.get("sourcePath") or "")).expanduser().resolve()
            expected_info = item.get("sourceInfo") if isinstance(item.get("sourceInfo"), dict) else {}
            if not source_path.exists():
                raise RuntimeError(f"Strict import source no longer exists: {source_path}.")
            current_info = file_info(source_path)
            if current_info.get("sha256") != expected_info.get("sha256"):
                raise RuntimeError(f"Strict import source changed after validation: {source_path}.")
            all_source_hashes.append(str(current_info["sha256"]))
            all_source_paths.append(str(source_path))
    if len(set(all_source_hashes)) != sum(expected_counts.values()):
        raise RuntimeError("Strict import artifact does not contain 50 unique source hashes.")
    if len(set(all_source_paths)) != sum(expected_counts.values()):
        raise RuntimeError("Strict import artifact does not contain 50 unique source paths.")
    return grouped


def verify_import_assets_live(
    client: TavoMcp,
    artifact_dir: Path,
    assets: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    verified: dict[str, list[dict[str, Any]]] = {kind: [] for kind in assets}
    for kind, items in assets.items():
        for item in items:
            index = int(item["index"])
            object_id = item["objectId"]
            step_dir = artifact_dir / "setup" / "strict-assets-live" / kind / f"{index:02d}"
            step_dir.mkdir(parents=True, exist_ok=True)
            arguments = {"pluginId": str(object_id)} if kind == "plugin" else {"id": int(object_id)}
            live = tool_call(client, step_dir, "readback.json", f"tavo_{kind}_get", arguments)
            if not ok_response(live):
                raise RuntimeError(f"Live readback failed for strict {kind} asset {object_id}.")
            historical_path = Path(str(item.get("artifactDir") or "")) / "readback.json"
            if not historical_path.exists():
                raise RuntimeError(f"Historical readback is missing for strict {kind} asset {object_id}.")
            historical_payload = response_payload(load_json(historical_path))
            live_payload = response_payload(live)
            historical_hash = stable_hash(historical_payload)
            live_hash = stable_hash(live_payload)
            comparison = {
                "kind": kind,
                "index": index,
                "objectId": object_id,
                "historicalReadback": str(historical_path),
                "historicalPayloadHash": historical_hash,
                "livePayloadHash": live_hash,
                "passed": historical_hash == live_hash,
            }
            atomic_json(step_dir / "comparison.json", comparison)
            if not comparison["passed"]:
                atomic_json(
                    step_dir / "mismatch.json",
                    {"historical": historical_payload, "live": live_payload},
                )
                raise RuntimeError(f"Strict {kind} asset {object_id} changed after its validated import.")
            verified[kind].append(comparison)
    return verified


def search_exact(
    client: TavoMcp,
    step_dir: Path,
    kind: str,
    query: str,
) -> list[dict[str, Any]]:
    response = tool_call(
        client,
        step_dir,
        f"search-{safe_name(kind)}.json",
        f"tavo_{kind}_search",
        {"query": query, "match": "exact", "limit": 10},
    )
    if not ok_response(response):
        raise RuntimeError(f"Exact {kind} search failed for {query!r}.")
    return response_items(response)


def ensure_character(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    source_dir = artifact_dir / "semantic-sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "ejs-macro-character-card.json"
    rendered = render_template(TEMPLATE_ROOT / "ejs-macro-character-card.json", {"RUN_ID": run_id})
    source_path.write_text(rendered, encoding="utf-8")
    payload = json.loads(rendered)
    name = payload["data"]["name"]
    step_dir = artifact_dir / "setup" / "ejs-character"
    step_dir.mkdir(parents=True, exist_ok=True)
    matches = search_exact(client, step_dir, "character", name)
    if len(matches) > 1:
        raise RuntimeError("Multiple exact EJS validation characters exist.")
    if matches:
        character_id = int(matches[0]["id"])
    else:
        fingerprint = sha256(source_path)[:16]
        dry = tool_call(
            client,
            step_dir,
            "dry-run.json",
            "tavo_character_import_card",
            {
                "card": payload,
                "dryRun": True,
                "clientRequestId": f"semantic-{run_id}-ejs-{fingerprint}-dry",
            },
        )
        actual = tool_call(
            client,
            step_dir,
            "actual.json",
            "tavo_character_import_card",
            {
                "card": payload,
                "dryRun": False,
                "clientRequestId": f"semantic-{run_id}-ejs-{fingerprint}-actual",
            },
        )
        parsed = response_payload(actual)
        character_id = int(parsed.get("characterId") or parsed.get("id") or 0)
        if not ok_response(dry) or not ok_response(actual) or character_id < 1:
            raise RuntimeError("Could not import EJS semantic character.")
    readback = tool_call(client, step_dir, "readback.json", "tavo_character_get", {"id": character_id})
    readback_payload = response_payload(readback)
    rendered_readback = json.dumps(readback_payload, ensure_ascii=False)
    if not ok_response(readback) or f"EJS-CARD-{run_id}" not in rendered_readback:
        raise RuntimeError("EJS semantic character readback lost its validation marker.")
    return {
        "id": character_id,
        "name": name,
        "sourcePath": str(source_path),
        "sourceSha256": sha256(source_path),
        "readbackHash": stable_hash(readback_payload),
    }


def ensure_semantic_plugin(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    plugin_id = f"codex.semantic.{run_id.lower()}"
    source_dir = artifact_dir / "semantic-sources" / "plugin"
    replacements = {"RUN_ID": run_id, "PLUGIN_ID": plugin_id}
    source_files = [
        ("manifest.json", TEMPLATE_ROOT / "plugin" / "manifest.json"),
        ("entry.js", TEMPLATE_ROOT / "plugin" / "entry.js"),
        ("ui/panel.html", TEMPLATE_ROOT / "plugin" / "ui" / "panel.html"),
    ]
    for relative, template in source_files:
        output = source_dir / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_template(template, replacements), encoding="utf-8")

    step_dir = artifact_dir / "setup" / "semantic-plugin"
    step_dir.mkdir(parents=True, exist_ok=True)
    existing = tool_call(
        client,
        step_dir,
        "search.json",
        "tavo_plugin_search",
        {"query": plugin_id, "match": "exact", "limit": 10},
    )
    matches = response_items(existing)
    if len(matches) > 1:
        raise RuntimeError("Multiple exact semantic plugins exist.")
    if not matches:
        item = {
            "kind": "plugin",
            "index": 1,
            "name": f"Semantic Validation Plugin {run_id}",
            "pluginId": plugin_id,
            "sourcePath": str(source_dir),
        }
        installed_id, installed = import_plugin(client, step_dir, item)
        if not installed or installed_id != plugin_id:
            raise RuntimeError("Could not install semantic validation plugin.")
    readback = tool_call(client, step_dir, "readback.json", "tavo_plugin_get", {"pluginId": plugin_id})
    runtime = tool_call(
        client,
        step_dir,
        "runtime-contributions.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    runtime_text = json.dumps(response_payload(runtime), ensure_ascii=False)
    readback_payload = response_payload(readback)
    if not ok_response(readback) or not ok_response(runtime) or plugin_id not in runtime_text:
        raise RuntimeError("Semantic plugin is not present in runtime contributions.")
    for action_id in (
        "observe-scene",
        "clarify-goal",
        "check-state",
        "propose-next-step",
        "summarize-evidence",
        "ejs-runtime-seed",
        "ejs-runtime-probe",
    ):
        if action_id not in runtime_text:
            raise RuntimeError(f"Semantic plugin runtime lost action {action_id}.")
    return {
        "id": plugin_id,
        "sourcePath": str(source_dir),
        "sourceSha256": str(file_info(source_dir)["sha256"]),
        "readbackHash": stable_hash(readback_payload),
        "runtimeContributionsHash": stable_hash(response_payload(runtime)),
    }


def ensure_personas(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> list[dict[str, Any]]:
    personas: list[dict[str, Any]] = []
    for index in range(1, 6):
        name = f"Codex Semantic Persona {run_id} {index:02d}"
        code = f"PERSONA-{run_id}-{index:02d}"
        description = (
            f"当前用户是现场证据审计员，用户的身份协议码是 {code}。"
            "用户的工作原则是区分亲眼所见、转述和推测，并要求对方给出可复核依据。"
            "这段 persona 只定义当前用户，不改变 assistant 的角色卡身份。"
        )
        step_dir = artifact_dir / "setup" / "personas" / f"{index:02d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        matches = search_exact(client, step_dir, "persona", name)
        if len(matches) > 1:
            raise RuntimeError(f"Multiple exact personas exist for {name}.")
        if matches:
            persona_id = int(matches[0]["id"])
        else:
            payload = {"name": name, "description": description, "active": False}
            dry = tool_call(
                client,
                step_dir,
                "dry-run.json",
                "tavo_persona_create",
                {"persona": payload, "dryRun": True, "clientRequestId": f"semantic-{run_id}-persona-{index:02d}-dry"},
            )
            actual = tool_call(
                client,
                step_dir,
                "actual.json",
                "tavo_persona_create",
                {"persona": payload, "dryRun": False, "clientRequestId": f"semantic-{run_id}-persona-{index:02d}-actual"},
            )
            persona_id = int(response_payload(actual).get("id") or 0)
            if not ok_response(dry) or not ok_response(actual) or persona_id < 1:
                raise RuntimeError(f"Could not create semantic persona {index}.")
        readback = tool_call(client, step_dir, "readback.json", "tavo_persona_get", {"id": persona_id})
        readback_payload = response_payload(readback)
        readback_text = json.dumps(readback_payload, ensure_ascii=False)
        if not ok_response(readback) or code not in readback_text:
            raise RuntimeError(f"Persona {index} readback lost identity protocol code.")
        personas.append({"id": persona_id, "name": name, "code": code, "readbackHash": stable_hash(readback_payload)})
    return personas


def ensure_neutral_persona(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    name = f"Codex Semantic Neutral Persona {run_id}"
    description = (
        "当前用户是本轮真机测试的中性协作者。用户不携带任何角色、世界书、正则、预设或插件事实；"
        "用户只提供当前对话中实际出现的信息，未知内容保持未知。"
        "这段 persona 只定义当前用户，不改变 assistant 的角色卡身份。"
    )
    step_dir = artifact_dir / "setup" / "neutral-persona"
    step_dir.mkdir(parents=True, exist_ok=True)
    matches = search_exact(client, step_dir, "persona", name)
    if len(matches) > 1:
        raise RuntimeError("Multiple exact neutral personas exist for this epoch.")
    if matches:
        persona_id = int(matches[0]["id"])
    else:
        payload = {"name": name, "description": description, "active": False}
        dry = tool_call(
            client,
            step_dir,
            "dry-run.json",
            "tavo_persona_create",
            {"persona": payload, "dryRun": True, "clientRequestId": f"semantic-{run_id}-neutral-persona-dry"},
        )
        actual = tool_call(
            client,
            step_dir,
            "actual.json",
            "tavo_persona_create",
            {"persona": payload, "dryRun": False, "clientRequestId": f"semantic-{run_id}-neutral-persona-actual"},
        )
        persona_id = int(response_payload(actual).get("id") or 0)
        if not ok_response(dry) or not ok_response(actual) or persona_id < 1:
            raise RuntimeError("Could not create the neutral semantic persona.")
    readback = tool_call(client, step_dir, "readback.json", "tavo_persona_get", {"id": persona_id})
    parsed = response_payload(readback)
    if not ok_response(readback) or parsed.get("name") != name or parsed.get("description") != description:
        raise RuntimeError("Neutral semantic persona failed exact readback validation.")
    return {
        "id": persona_id,
        "name": name,
        "description": description,
        "readbackHash": stable_hash(parsed),
    }


def ensure_neutral_preset(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    source_dir = artifact_dir / "semantic-sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "neutral-preset.json"
    rendered = render_template(TEMPLATE_ROOT / "neutral-preset.json", {"RUN_ID": run_id})
    source_path.write_text(rendered, encoding="utf-8")
    payload = json.loads(rendered)
    name = str(payload["name"])
    step_dir = artifact_dir / "setup" / "neutral-preset"
    step_dir.mkdir(parents=True, exist_ok=True)
    matches = search_exact(client, step_dir, "preset", name)
    if len(matches) > 1:
        raise RuntimeError("Multiple exact neutral presets exist for this epoch.")
    if matches:
        preset_id = int(matches[0]["id"])
    else:
        dry = tool_call(
            client,
            step_dir,
            "dry-run.json",
            "tavo_preset_create",
            {"preset": payload, "dryRun": True, "clientRequestId": f"semantic-{run_id}-neutral-preset-dry"},
        )
        actual = tool_call(
            client,
            step_dir,
            "actual.json",
            "tavo_preset_create",
            {"preset": payload, "dryRun": False, "clientRequestId": f"semantic-{run_id}-neutral-preset-actual"},
        )
        preset_id = int(response_payload(actual).get("id") or 0)
        if not ok_response(dry) or not ok_response(actual) or preset_id < 1:
            raise RuntimeError("Could not create the neutral semantic preset.")
    readback = tool_call(client, step_dir, "readback.json", "tavo_preset_get", {"id": preset_id})
    parsed = response_payload(readback)
    entries = parsed.get("entries") if isinstance(parsed.get("entries"), list) else []
    identifiers = {str(entry.get("identifier")) for entry in entries if isinstance(entry, dict)}
    required_identifiers = {
        f"neutral-main-{run_id}",
        "worldInfoBefore",
        "personaDescription",
        "charDescription",
        "charPersonality",
        "scenario",
        "worldInfoAfter",
        "dialogueExamples",
        "chatHistory",
    }
    readback_text = json.dumps(parsed, ensure_ascii=False)
    if (
        not ok_response(readback)
        or parsed.get("name") != name
        or not required_identifiers.issubset(identifiers)
        or "Do not invent facts, secret markers" not in readback_text
    ):
        raise RuntimeError("Neutral semantic preset failed exact semantic readback validation.")
    return {
        "id": preset_id,
        "name": name,
        "sourcePath": str(source_path),
        "sourceSha256": sha256(source_path),
        "readbackHash": stable_hash(parsed),
    }


def ensure_semantic_presets(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> list[dict[str, Any]]:
    base = json.loads(render_template(TEMPLATE_ROOT / "neutral-preset.json", {"RUN_ID": run_id}))
    presets: list[dict[str, Any]] = []
    source_dir = artifact_dir / "semantic-sources" / "presets"
    source_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, 6):
        payload = json.loads(json.dumps(base, ensure_ascii=False))
        marker_digest = hashlib.sha256(f"{run_id}:preset:{index}".encode("utf-8")).hexdigest()[:16].upper()
        marker = f"SEM_PRESET_{marker_digest}"
        name = f"Codex Semantic Runtime Preset {run_id} {index:02d}"
        payload["name"] = name
        payload["active"] = False
        main = payload["entries"][0]
        main["identifier"] = f"semantic-runtime-main-{run_id}-{index:02d}"
        main["name"] = f"Semantic Runtime Main {index:02d}"
        main["content"] = (
            f"When the user asks for a three-part audit, begin the visible reply with {marker}. "
            "Immediately honor any exact challenge marker requested by the user. "
            "Then use the exact ASCII section labels OBSERVE, QUESTION, VERIFY in that order, "
            "with substantive Chinese content under every label."
        )
        source_path = source_dir / f"{index:02d}-preset.json"
        source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        step_dir = artifact_dir / "setup" / "semantic-presets" / f"{index:02d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        matches = search_exact(client, step_dir, "preset", name)
        if len(matches) > 1:
            raise RuntimeError(f"Multiple exact semantic runtime presets exist for {name}.")
        if matches:
            preset_id = int(matches[0]["id"])
        else:
            dry = tool_call(
                client,
                step_dir,
                "dry-run.json",
                "tavo_preset_create",
                {
                    "preset": payload,
                    "dryRun": True,
                    "clientRequestId": f"semantic-{run_id}-runtime-preset-{index:02d}-dry",
                },
            )
            actual = tool_call(
                client,
                step_dir,
                "actual.json",
                "tavo_preset_create",
                {
                    "preset": payload,
                    "dryRun": False,
                    "clientRequestId": f"semantic-{run_id}-runtime-preset-{index:02d}-actual",
                },
            )
            preset_id = int(response_payload(actual).get("id") or 0)
            if not ok_response(dry) or not ok_response(actual) or preset_id < 1:
                raise RuntimeError(f"Could not create semantic runtime preset {index}.")
        readback = tool_call(client, step_dir, "readback.json", "tavo_preset_get", {"id": preset_id})
        readback_payload = response_payload(readback)
        if (
            not ok_response(readback)
            or readback_payload.get("name") != name
            or readback_payload.get("active") is not False
            or marker not in json.dumps(readback_payload, ensure_ascii=False)
        ):
            raise RuntimeError(f"Semantic runtime preset {index} failed exact readback validation.")
        presets.append(
            {
                "id": preset_id,
                "name": name,
                "marker": marker,
                "sourcePath": str(source_path),
                "sourceSha256": sha256(source_path),
                "readbackHash": stable_hash(readback_payload),
            }
        )
    return presets


def semantic_token(run_id: str, purpose: str, index: int) -> str:
    digest = hashlib.sha256(f"{run_id}:{purpose}:{index}".encode("utf-8")).hexdigest()[:16].upper()
    return f"{purpose.upper()}_{digest}"


def ensure_semantic_lorebooks(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> list[dict[str, Any]]:
    """Create isolated constant lorebooks plus non-counting keyword probes."""
    lorebooks: list[dict[str, Any]] = []
    source_dir = artifact_dir / "semantic-sources" / "lorebooks"
    source_dir.mkdir(parents=True, exist_ok=True)
    natural_triggers = ["琥珀潮汐港", "银叶观测站", "青瓷雨巷", "赤砂钟楼", "白桦档案桥"]
    for index in range(1, 6):
        name = f"Codex Semantic Isolated Lorebook {run_id} {index:02d}"
        trigger = natural_triggers[index - 1]
        fact = semantic_token(run_id, "lore_fact", index)
        keyword_fact = semantic_token(run_id, "lore_keyword_probe", index)
        payload = {
            "name": name,
            "entries": [
                {
                    "identifier": f"semantic-constant-{run_id.lower()}-{index:02d}",
                    "name": f"isolated constant fact {index:02d}",
                    "content": (
                        f"事实码 {fact}。{trigger}只在潮位最低时开放；"
                        "绿色桥灯明确表示结构不安全，禁止通行。"
                    ),
                    "strategy": "constant",
                    "injectionPosition": "lorebookAfter",
                    "injectionDepth": 4,
                    "injectionRole": "system",
                    "keywords": [],
                    "secondaryKeywords": [],
                    "secondaryKeywordStrategy": "none",
                    "scanDepth": 10,
                    "caseSensitive": False,
                    "matchWholeWord": False,
                    "probability": 100,
                    "sticky": 0,
                    "cooldown": 0,
                    "delay": 0,
                    "enabled": True,
                },
                {
                    "identifier": f"semantic-keyword-probe-{run_id.lower()}-{index:02d}",
                    "name": f"keyword probe {index:02d}",
                    "content": f"关键词探针事实码 {keyword_fact}。",
                    "strategy": "keyword",
                    "injectionPosition": "lorebookAfter",
                    "injectionDepth": 4,
                    "injectionRole": "system",
                    "keywords": [trigger],
                    "secondaryKeywords": [],
                    "secondaryKeywordStrategy": "none",
                    "scanDepth": 10,
                    "caseSensitive": False,
                    "matchWholeWord": False,
                    "probability": 100,
                    "sticky": 0,
                    "cooldown": 0,
                    "delay": 0,
                    "enabled": True,
                },
            ],
        }
        source_path = source_dir / f"{index:02d}-constant-with-keyword-probe-lorebook.json"
        source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        step_dir = artifact_dir / "setup" / "semantic-lorebooks" / f"{index:02d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        matches = search_exact(client, step_dir, "lorebook", name)
        if len(matches) > 1:
            raise RuntimeError(f"Multiple exact isolated lorebooks exist for {name}.")
        if matches:
            lorebook_id = int(matches[0]["id"])
        else:
            dry = tool_call(
                client,
                step_dir,
                "dry-run.json",
                "tavo_lorebook_create",
                {
                    "lorebook": payload,
                    "dryRun": True,
                    "clientRequestId": f"semantic-{run_id}-isolated-lore-{index:02d}-dry",
                },
            )
            actual = tool_call(
                client,
                step_dir,
                "actual.json",
                "tavo_lorebook_create",
                {
                    "lorebook": payload,
                    "dryRun": False,
                    "clientRequestId": f"semantic-{run_id}-isolated-lore-{index:02d}-actual",
                },
            )
            lorebook_id = int(response_payload(actual).get("id") or 0)
            if not ok_response(dry) or not ok_response(actual) or lorebook_id < 1:
                raise RuntimeError(f"Could not create isolated semantic lorebook {index}.")
        readback = tool_call(client, step_dir, "readback.json", "tavo_lorebook_get", {"id": lorebook_id})
        parsed = response_payload(readback)
        entries = parsed.get("entries") if isinstance(parsed.get("entries"), list) else []
        entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict)
                and item.get("identifier") == f"semantic-constant-{run_id.lower()}-{index:02d}"
            ),
            {},
        )
        keyword_entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict)
                and item.get("identifier") == f"semantic-keyword-probe-{run_id.lower()}-{index:02d}"
            ),
            {},
        )
        required_fields = {
            "strategy": "constant",
            "injectionPosition": "lorebookAfter",
            "injectionDepth": 4,
            "injectionRole": "system",
            "scanDepth": 10,
            "caseSensitive": False,
            "matchWholeWord": False,
            "probability": 100,
            "enabled": True,
        }
        mismatches = {
            key: {"expected": expected, "actual": entry.get(key)}
            for key, expected in required_fields.items()
            if entry.get(key) != expected
        }
        if (
            not ok_response(readback)
            or parsed.get("name") != name
            or len(entries) != 2
            or entry.get("keywords") != []
            or fact not in str(entry.get("content") or "")
            or keyword_entry.get("strategy") != "keyword"
            or keyword_entry.get("keywords") != [trigger]
            or keyword_fact not in str(keyword_entry.get("content") or "")
            or mismatches
        ):
            atomic_json(step_dir / "readback-mismatch.json", {"mismatches": mismatches, "parsed": parsed})
            raise RuntimeError(f"Isolated semantic lorebook {index} failed exact readback validation.")
        lorebooks.append(
            {
                "id": lorebook_id,
                "name": name,
                "trigger": trigger,
                "fact": fact,
                "keywordFact": keyword_fact,
                "sourcePath": str(source_path),
                "sourceSha256": sha256(source_path),
                "readbackHash": stable_hash(parsed),
            }
        )
    return lorebooks


def ensure_chat(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
    family: str,
    ordinal: int,
    chat_payload: dict[str, Any],
) -> dict[str, Any]:
    name = f"Codex Semantic {family} {run_id} {ordinal:02d}"
    step_dir = artifact_dir / "setup" / "chats" / family / f"{ordinal:02d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    matches = search_exact(client, step_dir, "chat", name)
    if len(matches) > 1:
        raise RuntimeError(f"Multiple exact chats exist for {name}.")
    if matches:
        chat_id = int(matches[0]["id"])
    else:
        payload = {**chat_payload, "title": name}
        dry = tool_call(
            client,
            step_dir,
            "dry-run.json",
            "tavo_chat_create",
            {"chat": payload, "dryRun": True, "clientRequestId": f"semantic-{run_id}-{family}-{ordinal:02d}-chat-dry"},
        )
        actual = tool_call(
            client,
            step_dir,
            "actual.json",
            "tavo_chat_create",
            {"chat": payload, "dryRun": False, "clientRequestId": f"semantic-{run_id}-{family}-{ordinal:02d}-chat-actual"},
        )
        chat_id = int(response_payload(actual).get("id") or 0)
        if not ok_response(dry) or not ok_response(actual) or chat_id < 1:
            raise RuntimeError(f"Could not create chat {name}.")
    readback = tool_call(client, step_dir, "readback.json", "tavo_chat_get", {"id": chat_id, "includeMessages": False})
    parsed = response_payload(readback)
    binding_mismatches = {
        key: {"expected": expected, "actual": parsed.get(key)}
        for key, expected in chat_payload.items()
        if parsed.get(key) != expected
    }
    if not ok_response(readback) or int(parsed.get("id") or 0) != chat_id or binding_mismatches:
        atomic_json(step_dir / "binding-mismatch.json", {"mismatches": binding_mismatches, "readback": parsed})
        raise RuntimeError(f"Chat {chat_id} readback failed.")
    return {"id": chat_id, "name": name, "payload": chat_payload}


def message_count(client: TavoMcp, chat_id: int) -> int:
    response = client.tool("tavo_message_count", {"chatId": chat_id}, timeout=60)
    parsed = response_payload(response)
    return int(parsed.get("count")) if ok_response(response) and isinstance(parsed.get("count"), int) else -1


def all_messages(client: TavoMcp, chat_id: int, step_dir: Path, filename: str) -> list[dict[str, Any]]:
    count = message_count(client, chat_id)
    if count < 0:
        raise RuntimeError(f"Could not count messages in chat {chat_id}.")
    response = tool_call(
        client,
        step_dir,
        filename,
        "tavo_message_find",
        {"chatId": chat_id, "range": [0, max(1, count + 1)]},
        timeout=60,
    )
    if not ok_response(response):
        raise RuntimeError(f"Could not read messages in chat {chat_id}.")
    return response_items(response)


def ensure_chat_seed(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
    family: str,
    ordinal: int,
    chat: dict[str, Any],
) -> None:
    chat_id = int(chat["id"])
    marker = f"SEMANTIC_CHAT_SEED_{safe_name(run_id)}_{safe_name(family)}_{ordinal:02d}"
    step_dir = artifact_dir / "setup" / "chat-seeds" / safe_name(family) / f"{ordinal:02d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    messages = all_messages(client, chat_id, step_dir, "messages-before.json")
    matching_seeds = [message for message in messages if marker in str(message.get("content") or "")]
    if matching_seeds:
        if (
            len(matching_seeds) != 1
            or matching_seeds[0].get("role") != "assistant"
            or matching_seeds[0].get("hidden") is not True
        ):
            raise RuntimeError(f"Chat {chat_id} has an ambiguous or invalid epoch seed.")
        ordered = sorted(messages, key=lambda message: int(message.get("index") or 0))
        seed_position = ordered.index(matching_seeds[0])
        trailing = ordered[seed_position + 1 :]
        if seed_position != 0 or len(trailing) > 3:
            atomic_json(step_dir / "foreign-history.json", {"messages": messages})
            raise RuntimeError(f"Chat {chat_id} contains history outside its single-attempt epoch shape.")
        return
    if messages:
        raise RuntimeError(f"Chat {chat_id} contains non-seed history and cannot be claimed by this epoch.")
    payload = {
        "chatId": chat_id,
        "message": {
            "role": "assistant",
            "content": f"{marker} Context initialized without feature result markers.",
            "hidden": True,
        },
        "dryRun": False,
        "clientRequestId": f"semantic-{run_id}-{safe_name(family)}-{ordinal:02d}-seed-{chat_id}",
    }
    appended = tool_call(client, step_dir, "append.json", "tavo_message_append", payload)
    parsed = response_payload(appended)
    if not ok_response(appended) or int(parsed.get("chatId") or 0) != chat_id:
        raise RuntimeError(f"Could not seed chat {chat_id}.")
    readback = all_messages(client, chat_id, step_dir, "messages-after.json")
    if (
        len(readback) != 1
        or marker not in str(readback[0].get("content") or "")
        or readback[0].get("hidden") is not True
    ):
        raise RuntimeError(f"Chat {chat_id} seed readback was not isolated.")


def build_panel_source(
    artifact_dir: Path,
    run_id: str,
    variant: str,
) -> dict[str, Any]:
    panel_run_id = f"{run_id}{variant}"
    marker = f"AR_PANEL_{panel_run_id}"
    html = render_template(TEMPLATE_ROOT / "advanced-rendering-panel.html", {"RUN_ID": panel_run_id})
    source = artifact_dir / "semantic-sources" / f"advanced-rendering-{variant.lower()}.html"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(html, encoding="utf-8")
    return {
        "variant": variant,
        "panelRunId": panel_run_id,
        "marker": marker,
        "sourcePath": str(source),
        "sourceSha256": sha256(source),
        "contentHash": stable_hash(html),
    }


def append_live_panel(
    client: TavoMcp,
    artifact_dir: Path,
    step_dir: Path,
    chat_id: int,
    run_id: str,
    variant: str,
    expected_source_sha256: str,
    request_scope: str,
) -> dict[str, Any]:
    source_spec = build_panel_source(artifact_dir, run_id, variant)
    if source_spec["sourceSha256"] != expected_source_sha256:
        raise RuntimeError(f"Live {variant} panel source hash changed after epoch preparation.")
    html = Path(str(source_spec["sourcePath"])).read_text(encoding="utf-8")
    marker = str(source_spec["marker"])
    messages_before = all_messages(client, chat_id, step_dir, "panel-messages-before.json")
    marker_messages = [message for message in messages_before if marker in str(message.get("content") or "")]
    if marker_messages:
        raise RuntimeError(f"A {variant} panel already exists without a matching immutable action result.")
    message = {"role": "assistant", "content": html, "hidden": False}
    request_base = f"semantic-{run_id}-{safe_name(request_scope)}-{chat_id}-{safe_name(variant)}"
    dry = tool_call(
        client,
        step_dir,
        "append-dry-run.json",
        "tavo_message_append",
        {"chatId": chat_id, "message": message, "dryRun": True, "clientRequestId": request_base + "-dry"},
    )
    actual = tool_call(
        client,
        step_dir,
        "append-actual.json",
        "tavo_message_append",
        {"chatId": chat_id, "message": message, "dryRun": False, "clientRequestId": request_base + "-actual"},
    )
    actual_payload = response_payload(actual)
    message_id = int(actual_payload.get("id") or 0)
    if (
        not ok_response(dry)
        or not ok_response(actual)
        or message_id < 1
        or int(actual_payload.get("chatId") or 0) != int(chat_id)
    ):
        raise RuntimeError(f"Could not append {variant} semantic panel.")
    readback = tool_call(client, step_dir, "message-readback.json", "tavo_message_get", {"chatId": chat_id, "id": message_id})
    if not ok_response(readback) or marker not in json.dumps(response_payload(readback), ensure_ascii=False):
        raise RuntimeError(f"{variant} panel message readback lost its marker.")
    messages_after = all_messages(client, chat_id, step_dir, "panel-messages-after.json")
    stored = [message for message in messages_after if int(message.get("id") or 0) == message_id]
    if len(stored) != 1 or str(stored[0].get("content") or "") != html:
        raise RuntimeError(f"{variant} panel stored content did not exactly match its source.")
    current = tool_call(client, step_dir, "current-chat-after-append.json", "tavo_current_chat_get", {})
    current_payload = response_payload(current).get("chat")
    current_chat = current_payload if isinstance(current_payload, dict) else {}
    if not ok_response(current) or int(current_chat.get("id") or 0) != int(chat_id):
        raise RuntimeError(f"Appending {variant} panel changed away from target chat {chat_id}.")
    return {
        "id": message_id,
        **source_spec,
    }


def prepare_contexts(
    client: TavoMcp,
    artifact_dir: Path,
    import_artifact: Path,
    run_id: str,
) -> dict[str, Any]:
    assets = parse_import_assets(import_artifact)
    live_asset_readbacks = verify_import_assets_live(client, artifact_dir, assets)
    current = client.tool("tavo_current_chat_get", {})
    current_payload = response_payload(current).get("chat")
    current_chat = current_payload if isinstance(current_payload, dict) else {}
    ejs_character = ensure_character(client, artifact_dir, run_id)
    neutral_persona = ensure_neutral_persona(client, artifact_dir, run_id)
    default_persona = int(neutral_persona["id"])
    neutral_preset = ensure_neutral_preset(client, artifact_dir, run_id)
    default_preset = int(neutral_preset["id"])
    semantic_presets = ensure_semantic_presets(client, artifact_dir, run_id)
    personas = ensure_personas(client, artifact_dir, run_id)
    semantic_plugin = ensure_semantic_plugin(client, artifact_dir, run_id)
    semantic_lorebooks = ensure_semantic_lorebooks(client, artifact_dir, run_id)

    character_ids = [int(item["objectId"]) for item in assets["character"]]
    regex_ids = [int(item["objectId"]) for item in assets["regex"]]
    chats: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILIES}

    for index in range(1, 6):
        chats["character-thread"].append(
            ensure_chat(client, artifact_dir, run_id, "character-thread", index, {"characterIds": [character_ids[index - 1]], "personaId": default_persona, "presetId": default_preset})
        )
        chats["lorebook-trigger"].append(
            ensure_chat(
                client,
                artifact_dir,
                run_id,
                "lorebook-trigger-natural-v1",
                index,
                {
                    "characterIds": [character_ids[5]],
                    "personaId": default_persona,
                    "presetId": default_preset,
                    "lorebookIds": [int(semantic_lorebooks[index - 1]["id"])],
                },
            )
        )
        regex_setup_family = "regex-runtime-clean" if index == 1 else "regex-runtime"
        chats["regex-runtime"].append(
            ensure_chat(client, artifact_dir, run_id, regex_setup_family, index, {"characterIds": [character_ids[6]], "personaId": default_persona, "presetId": default_preset, "regexIds": [regex_ids[index - 1]]})
        )
        chats["preset-stack"].append(
            ensure_chat(client, artifact_dir, run_id, "preset-stack", index, {"characterIds": [character_ids[7]], "personaId": default_persona, "presetId": int(semantic_presets[index - 1]["id"])})
        )
        chats["persona-binding"].append(
            ensure_chat(client, artifact_dir, run_id, "persona-binding", index, {"characterIds": [character_ids[8]], "personaId": int(personas[index - 1]["id"]), "presetId": default_preset})
        )

    for index in range(1, 6):
        chats["macro-ejs"].append(
            ensure_chat(
                client,
                artifact_dir,
                run_id,
                "macro-ejs-runtime",
                index,
                {
                    "characterIds": [int(ejs_character["id"])],
                    "personaId": default_persona,
                    "presetId": default_preset,
                },
            )
        )
    for index in range(1, 6):
        chats["mcp-message-ops"].append(
            ensure_chat(
                client,
                artifact_dir,
                run_id,
                "mcp-message-ops",
                index,
                {"characterIds": [character_ids[12]], "personaId": default_persona, "presetId": default_preset},
            )
        )

    ui_payloads = {
        "tavojs-variable": {"characterIds": [character_ids[9]], "personaId": default_persona, "presetId": default_preset},
        "advanced-rendering": {"characterIds": [character_ids[10]], "personaId": default_persona, "presetId": default_preset},
        "plugin-action-panel": {"characterIds": [character_ids[11]], "personaId": default_persona, "presetId": default_preset},
    }
    for family, payload in ui_payloads.items():
        for index in range(1, 6):
            chats[family].append(ensure_chat(client, artifact_dir, run_id, family, index, payload))

    ui_reload_anchors: dict[str, list[list[dict[str, Any]]]] = {
        "tavojs-variable": [],
        "advanced-rendering": [],
    }
    for family in ui_reload_anchors:
        for index in range(1, 6):
            ordinal_anchors: list[dict[str, Any]] = []
            for attempt_number in range(1, 4):
                anchor_family = f"reload-anchor-{family}-attempt-{attempt_number}"
                anchor = ensure_chat(
                    client,
                    artifact_dir,
                    run_id,
                    anchor_family,
                    index,
                    ui_payloads[family],
                )
                ensure_chat_seed(
                    client,
                    artifact_dir,
                    run_id,
                    anchor_family,
                    index,
                    anchor,
                )
                ordinal_anchors.append(anchor)
            ui_reload_anchors[family].append(ordinal_anchors)

    preflight_chats: dict[str, list[dict[str, Any]]] = {family: [] for family in UI_FAMILIES}
    for family, payload in ui_payloads.items():
        for index in range(1, 6):
            preflight_chats[family].append(
                ensure_chat(client, artifact_dir, run_id, f"preflight-{family}", index, payload)
            )
    ejs_plugin_preflight_chat = ensure_chat(
        client,
        artifact_dir,
        run_id,
        "preflight-ejs-plugin-runtime",
        1,
        ui_payloads["plugin-action-panel"],
    )

    controls = {
        "lorebook-negative": ensure_chat(client, artifact_dir, run_id, "control-lorebook", 1, {"characterIds": [character_ids[5]], "personaId": default_persona, "presetId": default_preset}),
        "lorebook-decoy": ensure_chat(
            client,
            artifact_dir,
            run_id,
            "control-lorebook-bound-decoy",
            1,
            {
                "characterIds": [character_ids[5]],
                "personaId": default_persona,
                "presetId": default_preset,
                "lorebookIds": [int(semantic_lorebooks[0]["id"])],
            },
        ),
        "regex-negative": ensure_chat(client, artifact_dir, run_id, "control-regex", 1, {"characterIds": [character_ids[6]], "personaId": default_persona, "presetId": default_preset}),
        "preset-negative": ensure_chat(client, artifact_dir, run_id, "control-preset", 1, {"characterIds": [character_ids[7]], "personaId": default_persona, "presetId": default_preset}),
        "persona-negative": ensure_chat(client, artifact_dir, run_id, "control-persona", 1, {"characterIds": [character_ids[8]], "personaId": default_persona, "presetId": default_preset}),
    }

    for family, family_chats in chats.items():
        for index, chat in enumerate(family_chats, start=1):
            ensure_chat_seed(client, artifact_dir, run_id, family, index, chat)
    for control_name, chat in controls.items():
        ensure_chat_seed(client, artifact_dir, run_id, f"control-{control_name}", 1, chat)
    for family, family_chats in preflight_chats.items():
        for index, chat in enumerate(family_chats, start=1):
            ensure_chat_seed(client, artifact_dir, run_id, f"preflight-{family}", index, chat)
    ensure_chat_seed(
        client,
        artifact_dir,
        run_id,
        "preflight-ejs-plugin-runtime",
        1,
        ejs_plugin_preflight_chat,
    )

    retry_primary: dict[str, list[list[dict[str, Any]]]] = {family: [] for family in FAMILIES}
    for family, family_chats in chats.items():
        for index, base_chat in enumerate(family_chats, start=1):
            attempts: list[dict[str, Any]] = []
            for attempt_number in (2, 3):
                retry = ensure_chat(
                    client,
                    artifact_dir,
                    run_id,
                    f"retry-{attempt_number}-{family}",
                    index,
                    dict(base_chat["payload"]),
                )
                ensure_chat_seed(
                    client,
                    artifact_dir,
                    run_id,
                    f"retry-{attempt_number}-{family}",
                    index,
                    retry,
                )
                attempts.append(retry)
            retry_primary[family].append(attempts)

    retry_controls: dict[str, list[dict[str, Any]]] = {}
    for control_name, base_chat in controls.items():
        attempts: list[dict[str, Any]] = []
        for attempt_number in (2, 3):
            retry = ensure_chat(
                client,
                artifact_dir,
                run_id,
                f"retry-{attempt_number}-control-{control_name}",
                1,
                dict(base_chat["payload"]),
            )
            ensure_chat_seed(
                client,
                artifact_dir,
                run_id,
                f"retry-{attempt_number}-control-{control_name}",
                1,
                retry,
            )
            attempts.append(retry)
        retry_controls[control_name] = attempts

    panel_sources = {
        "tavojs-variable": [
            [
                build_panel_source(artifact_dir, run_id, f"JS{index:02d}A{attempt}")
                for attempt in range(1, 4)
            ]
            for index in range(1, 6)
        ],
        "advanced-rendering": [
            [
                build_panel_source(artifact_dir, run_id, f"AR{index:02d}A{attempt}")
                for attempt in range(1, 4)
            ]
            for index in range(1, 6)
        ],
    }
    preflight_panel_sources = {
        "tavojs-variable": [
            build_panel_source(artifact_dir, run_id, f"PJS{index:02d}")
            for index in range(1, 6)
        ],
        "advanced-rendering": [
            build_panel_source(artifact_dir, run_id, f"PAR{index:02d}")
            for index in range(1, 6)
        ],
    }
    registry = {
        "runId": run_id,
        "createdAt": now_utc(),
        "importArtifact": str(import_artifact),
        "originalChatId": current_chat.get("id"),
        "defaultPersonaId": default_persona,
        "neutralPersona": neutral_persona,
        "neutralPreset": neutral_preset,
        "assets": assets,
        "liveAssetReadbacks": live_asset_readbacks,
        "semanticLorebooks": semantic_lorebooks,
        "semanticPresets": semantic_presets,
        "ejsCharacter": ejs_character,
        "ejsCharacterId": int(ejs_character["id"]),
        "semanticPlugin": semantic_plugin,
        "semanticPluginId": str(semantic_plugin["id"]),
        "personas": personas,
        "chats": chats,
        "preflightChats": preflight_chats,
        "ejsPluginPreflightChat": ejs_plugin_preflight_chat,
        "controls": controls,
        "retryChats": {"primary": retry_primary, "controls": retry_controls},
        "uiReloadAnchors": ui_reload_anchors,
        "panelSources": panel_sources,
        "preflightPanelSources": preflight_panel_sources,
    }
    atomic_json(artifact_dir / "context-registry.json", registry)
    return registry


def verify_frozen_context_live(
    client: TavoMcp,
    artifact_dir: Path,
    import_artifact: Path,
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Reread a prepared epoch without recreating or updating any phone object."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    audit_dir = artifact_dir / "resume-verification" / f"{stamp}-{os.getpid()}"
    audit_dir.mkdir(parents=True, exist_ok=False)
    assets = parse_import_assets(import_artifact)
    if stable_hash(assets) != stable_hash(registry.get("assets")):
        raise RuntimeError("Frozen strict-import asset registry changed before resume.")

    strict_verified = 0
    for kind, items in assets.items():
        for item in items:
            object_id = item["objectId"]
            arguments = {"pluginId": str(object_id)} if kind == "plugin" else {"id": int(object_id)}
            live = tool_call(
                client,
                audit_dir / "strict-assets" / kind / f"{int(item['index']):02d}",
                "readback.json",
                f"tavo_{kind}_get",
                arguments,
            )
            historical_path = Path(str(item.get("artifactDir") or "")) / "readback.json"
            if not ok_response(live) or not historical_path.exists():
                raise RuntimeError(f"Frozen strict {kind} asset {object_id} could not be reread.")
            expected_hash = stable_hash(response_payload(load_json(historical_path)))
            live_hash = stable_hash(response_payload(live))
            comparison = {
                "kind": kind,
                "index": int(item["index"]),
                "objectId": object_id,
                "expectedHash": expected_hash,
                "liveHash": live_hash,
                "passed": expected_hash == live_hash,
            }
            durable_json(
                audit_dir / "strict-assets" / kind / f"{int(item['index']):02d}" / "comparison.json",
                comparison,
            )
            if not comparison["passed"]:
                raise RuntimeError(f"Frozen strict {kind} asset {object_id} changed before resume.")
            strict_verified += 1

    object_records: list[tuple[str, str | int, str]] = []
    ejs_character = registry.get("ejsCharacter") or {}
    object_records.append(("character", int(ejs_character["id"]), str(ejs_character["readbackHash"])))
    neutral_persona = registry.get("neutralPersona") or {}
    object_records.append(("persona", int(neutral_persona["id"]), str(neutral_persona["readbackHash"])))
    neutral_preset = registry.get("neutralPreset") or {}
    object_records.append(("preset", int(neutral_preset["id"]), str(neutral_preset["readbackHash"])))
    for persona in registry.get("personas") or []:
        object_records.append(("persona", int(persona["id"]), str(persona["readbackHash"])))
    for preset in registry.get("semanticPresets") or []:
        object_records.append(("preset", int(preset["id"]), str(preset["readbackHash"])))
    for lorebook in registry.get("semanticLorebooks") or []:
        object_records.append(("lorebook", int(lorebook["id"]), str(lorebook["readbackHash"])))
    semantic_plugin = registry.get("semanticPlugin") or {}
    object_records.append(("plugin", str(semantic_plugin["id"]), str(semantic_plugin["readbackHash"])))

    object_verified = 0
    for sequence, (kind, object_id, expected_hash) in enumerate(object_records, start=1):
        arguments = {"pluginId": str(object_id)} if kind == "plugin" else {"id": int(object_id)}
        live = tool_call(
            client,
            audit_dir / "semantic-objects" / f"{sequence:03d}-{kind}-{safe_name(str(object_id))}",
            "readback.json",
            f"tavo_{kind}_get",
            arguments,
        )
        live_hash = stable_hash(response_payload(live))
        comparison = {
            "kind": kind,
            "objectId": object_id,
            "expectedHash": expected_hash,
            "liveHash": live_hash,
            "passed": bool(ok_response(live) and live_hash == expected_hash),
        }
        durable_json(
            audit_dir / "semantic-objects" / f"{sequence:03d}-{kind}-{safe_name(str(object_id))}" / "comparison.json",
            comparison,
        )
        if not comparison["passed"]:
            raise RuntimeError(f"Frozen semantic {kind} object {object_id} changed before resume.")
        object_verified += 1

    runtime = tool_call(
        client,
        audit_dir / "semantic-plugin-runtime",
        "runtime-contributions.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    runtime_text = json.dumps(response_payload(runtime), ensure_ascii=False)
    required_actions = {
        "observe-scene",
        "clarify-goal",
        "check-state",
        "propose-next-step",
        "summarize-evidence",
        "ejs-runtime-seed",
        "ejs-runtime-probe",
    }
    if (
        not ok_response(runtime)
        or str(semantic_plugin["id"]) not in runtime_text
        or any(action not in runtime_text for action in required_actions)
    ):
        raise RuntimeError("Frozen semantic plugin is missing required live runtime contributions.")

    chat_records: list[dict[str, Any]] = []
    for family, chats in (registry.get("chats") or {}).items():
        chat_records.extend({**chat, "registryGroup": f"chats/{family}"} for chat in chats)
    for family, chats in (registry.get("preflightChats") or {}).items():
        chat_records.extend({**chat, "registryGroup": f"preflight/{family}"} for chat in chats)
    for name, chat in (registry.get("controls") or {}).items():
        chat_records.append({**chat, "registryGroup": f"controls/{name}"})
    for family, groups in ((registry.get("retryChats") or {}).get("primary") or {}).items():
        for ordinal, attempts in enumerate(groups, start=1):
            chat_records.extend(
                {**chat, "registryGroup": f"retry/primary/{family}/{ordinal:02d}"}
                for chat in attempts
            )
    for name, chats in ((registry.get("retryChats") or {}).get("controls") or {}).items():
        chat_records.extend({**chat, "registryGroup": f"retry/controls/{name}"} for chat in chats)
    for family, ordinal_groups in (registry.get("uiReloadAnchors") or {}).items():
        for ordinal, chats in enumerate(ordinal_groups, start=1):
            chat_records.extend(
                {**chat, "registryGroup": f"anchors/{family}/{ordinal:02d}"}
                for chat in chats
            )
    if registry.get("ejsPluginPreflightChat"):
        chat_records.append({**registry["ejsPluginPreflightChat"], "registryGroup": "preflight/ejs-plugin"})

    chat_ids = [int(chat["id"]) for chat in chat_records]
    if len(chat_ids) != len(set(chat_ids)):
        raise RuntimeError("Frozen context registry contains duplicated chat ownership.")
    for sequence, chat in enumerate(chat_records, start=1):
        chat_id = int(chat["id"])
        live = tool_call(
            client,
            audit_dir / "chats" / f"{sequence:03d}-{chat_id}",
            "readback.json",
            "tavo_chat_get",
            {"id": chat_id, "includeMessages": False},
        )
        payload = response_payload(live)
        expected_payload = chat.get("payload") if isinstance(chat.get("payload"), dict) else {}
        mismatches = {
            key: {"expected": expected, "actual": payload.get(key)}
            for key, expected in expected_payload.items()
            if payload.get(key) != expected
        }
        comparison = {
            "chatId": chat_id,
            "registryGroup": chat.get("registryGroup"),
            "mismatches": mismatches,
            "passed": bool(ok_response(live) and int(payload.get("id") or 0) == chat_id and not mismatches),
        }
        durable_json(audit_dir / "chats" / f"{sequence:03d}-{chat_id}" / "comparison.json", comparison)
        if not comparison["passed"]:
            raise RuntimeError(f"Frozen chat {chat_id} binding changed before resume.")

    source_records: list[dict[str, Any]] = []
    for key in ("ejsCharacter", "semanticPlugin", "neutralPreset"):
        value = registry.get(key)
        if isinstance(value, dict):
            source_records.append(value)
    source_records.extend(item for item in registry.get("semanticPresets") or [] if isinstance(item, dict))
    source_records.extend(item for item in registry.get("semanticLorebooks") or [] if isinstance(item, dict))
    def collect_source_records(value: Any) -> None:
        if isinstance(value, dict):
            if "sourcePath" in value and "sourceSha256" in value:
                source_records.append(value)
            else:
                for child in value.values():
                    collect_source_records(child)
        elif isinstance(value, list):
            for child in value:
                collect_source_records(child)

    collect_source_records(registry.get("panelSources") or {})
    collect_source_records(registry.get("preflightPanelSources") or {})
    for record in source_records:
        source_path = Path(str(record.get("sourcePath") or "")).expanduser().resolve()
        expected_hash = str(record.get("sourceSha256") or "")
        current_hash = str(file_info(source_path).get("sha256") or "") if source_path.exists() else ""
        if not source_path.exists() or not expected_hash or current_hash != expected_hash:
            raise RuntimeError(f"Frozen semantic source changed before resume: {source_path}")

    summary = {
        "verifiedAt": now_utc(),
        "strictAssetsVerified": strict_verified,
        "semanticObjectsVerified": object_verified,
        "chatsVerified": len(chat_records),
        "sourcesVerified": len(source_records),
        "semanticPluginRuntimeVerified": True,
        "registryHash": stable_hash(context_identity(registry)),
        "passed": strict_verified == 50,
    }
    durable_json(audit_dir / "summary.json", summary)
    if not summary["passed"]:
        raise RuntimeError("Frozen context live verification did not cover all 50 strict assets.")
    return {"artifactDir": str(audit_dir), **summary}


def nonce_for(run_id: str, family: str, ordinal: int, control: bool = False) -> str:
    label = re.sub(r"[^A-Za-z0-9]", "_", family).upper()
    prefix = "CONTROL" if control else "NONCE"
    return f"{prefix}_{run_id}_{label}_{ordinal:02d}"


def with_nonce(prompt: str, nonce: str) -> str:
    return (
        f"可见答案第一行必须且只写以下标记：{nonce}\n"
        f"写完该标记后再完成任务：{prompt}\n"
        "回答必须有实质内容；不要只在思考过程里提到标记，也不要省略可见答案第一行。"
    )


def with_nonce_after_context_prefix(prompt: str, nonce: str, prefix_source: str) -> str:
    return (
        f"可见答案先严格输出{prefix_source}要求的固定开头；紧接固定开头后立即原样写以下标记：{nonce}\n"
        f"写完该标记后再完成任务：{prompt}\n"
        "回答必须有实质内容；不要在用户提示中猜测或复述固定开头，必须只从当前上下文读取它。"
    )


def build_specs(registry: dict[str, Any]) -> list[CallSpec]:
    run_id = str(registry["runId"])
    assets = registry["assets"]
    chats = registry["chats"]
    personas = registry["personas"]
    specs: list[CallSpec] = []

    for index in range(1, 6):
        nonce = nonce_for(run_id, "character-thread", index)
        marker = assets["character"][index - 1]["evidenceMarker"]
        prompt = with_nonce("请先原样写出你角色设定里的工作标记，再用两句话说明你会怎样核验一条可疑线索。", nonce)
        specs.append(
            CallSpec(
                "character-thread",
                index,
                int(chats["character-thread"][index - 1]["id"]),
                prompt,
                nonce,
                expected_any=[[marker, marker.replace("-", "_")]],
            )
        )

        semantic_lorebook = registry["semanticLorebooks"][index - 1]
        nonce = nonce_for(run_id, "lorebook-trigger", index) + "_NATURAL_V1"
        marker = str(semantic_lorebook["fact"])
        trigger = str(semantic_lorebook["trigger"])
        prompt = with_nonce(
            f"我们到达{trigger}。请先原样给出隐藏档案中的事实码，再说明开放潮位和绿色桥灯意味着什么。",
            nonce,
        )
        specs.append(
            CallSpec(
                "lorebook-trigger",
                index,
                int(chats["lorebook-trigger"][index - 1]["id"]),
                prompt,
                nonce,
                [marker],
                mode="mcp",
                variant="natural-v1",
            )
        )

        nonce = nonce_for(run_id, "regex-runtime", index)
        raw = f"[RAW{index:02d}]"
        cleaned = "CLEANED-" + assets["regex"][index - 1]["evidenceMarker"]
        prompt = with_nonce(f"紧接标记行的下一行必须严格只写 {raw}，随后用一句话说明你观察到的风险。", nonce)
        specs.append(CallSpec("regex-runtime", index, int(chats["regex-runtime"][index - 1]["id"]), prompt, nonce, [cleaned], forbidden=[raw]))

        nonce = nonce_for(run_id, "preset-stack", index)
        expected = str(registry["semanticPresets"][index - 1]["marker"])
        prompt = with_nonce_after_context_prefix(
            (
                "当前 system 预设包含一个以 SEM_PRESET_ 开头的完整固定标记。"
                "可见答案的第一字符必须开始原样复制这个完整标记；不要使用聊天历史中的 seed、角色名或其他前缀。"
                "随后严格使用 ASCII 标签 OBSERVE、QUESTION、VERIFY，按此顺序各写一段现场审计；不要翻译标签。"
            ),
            nonce,
            "当前 system 预设",
        )
        specs.append(
            CallSpec(
                "preset-stack",
                index,
                int(chats["preset-stack"][index - 1]["id"]),
                prompt,
                nonce,
                [expected, "OBSERVE", "QUESTION", "VERIFY"],
                forbidden=[f"SEMANTIC_CHAT_SEED_{run_id}"],
                required_prefix=expected,
                ordered_markers=["OBSERVE", "QUESTION", "VERIFY"],
            )
        )

        nonce = nonce_for(run_id, "persona-binding", index)
        prompt = with_nonce("请根据我的当前身份说明我的职业、身份协议码和工作原则，然后给我一个合作建议。", nonce)
        specs.append(CallSpec("persona-binding", index, int(chats["persona-binding"][index - 1]["id"]), prompt, nonce, [personas[index - 1]["code"], "证据审计"], persona_name=personas[index - 1]["name"]))

    ejs_expected = [
        f"SET_{run_id}",
        f"DEFAULT_{run_id}",
        "ALPHA",
        "1,2,3",
        f"Semantic EJS Validator {run_id}",
    ]
    ejs_questions = [
        "请读取 EJS-SET-GET 的值并解释它证明了哪一步，同时原样给出 EJS-INC 的当前整数值。",
        "请读取 EJS-DEFAULT 的值并说明缺失变量发生了什么，同时原样给出 EJS-INC 的当前整数值。",
        "请读取 EJS-CONDITION 的分支值并说明条件结果，同时原样给出 EJS-INC 的当前整数值。",
        "请读取 EJS-LOOP 的输出并说明循环顺序，同时原样给出 EJS-INC 的当前整数值。",
        "请读取 EJS-TO-MACRO 两侧展开后的角色名与用户名，同时原样给出 EJS-INC 的当前整数值。",
    ]
    for index in range(1, 6):
        nonce = nonce_for(run_id, "macro-ejs", index)
        specs.append(
            CallSpec(
                "macro-ejs",
                index,
                int(chats["macro-ejs"][index - 1]["id"]),
                with_nonce_after_context_prefix(
                    (
                        "请先把当前上下文中的 [EJS-EXTERNAL] 整行原样复制到可见答案，"
                        + ejs_questions[index - 1]
                    ),
                    nonce,
                    "assistant 角色卡",
                ),
                nonce,
                [f"[EJS-CARD-{run_id}]", f"[EJS-EXTERNAL:{run_id}]", ejs_expected[index - 1]],
                forbidden=["<%", "{{char}}", "{{user}}"],
                mode="ejs-runtime",
            )
        )

    action_names = ["OBSERVE", "CLARIFY", "STATE", "PLAN", "EVIDENCE"]
    ar_labels = ["AR 观察场景", "AR 澄清目标", "AR 核对状态", "AR 规划下一步", "AR 汇总证据"]
    for index, action in enumerate(action_names, start=1):
        js_chat = int(chats["tavojs-variable"][index - 1]["id"])
        ar_chat = int(chats["advanced-rendering"][index - 1]["id"])
        js_panels = registry["panelSources"]["tavojs-variable"][index - 1]
        ar_panels = registry["panelSources"]["advanced-rendering"][index - 1]
        js_anchors = registry["uiReloadAnchors"]["tavojs-variable"][index - 1]
        ar_anchors = registry["uiReloadAnchors"]["advanced-rendering"][index - 1]
        js_markers = [f"AR_{run_id}{panel['variant']}_{action} state=clicked" for panel in js_panels]
        ar_markers = [f"AR_{run_id}{panel['variant']}_{action} state=clicked" for panel in ar_panels]
        nonce = nonce_for(run_id, "tavojs-variable", index)
        specs.append(CallSpec("tavojs-variable", index, js_chat, "", nonce, [js_markers[0]], mode="ar-ui", ui_label=ar_labels[index - 1], ui_marker=js_markers[0], panel_variant=str(js_panels[0]["variant"]), panel_source_sha256=str(js_panels[0]["sourceSha256"]), reload_chat_id=int(js_anchors[0]["id"]), attempt_reload_chat_ids=[int(chat["id"]) for chat in js_anchors], attempt_panel_sources=js_panels, attempt_ui_markers=js_markers))
        nonce = nonce_for(run_id, "advanced-rendering", index)
        specs.append(CallSpec("advanced-rendering", index, ar_chat, "", nonce, [ar_markers[0]], mode="ar-ui", ui_label=ar_labels[index - 1], ui_marker=ar_markers[0], panel_variant=str(ar_panels[0]["variant"]), panel_source_sha256=str(ar_panels[0]["sourceSha256"]), reload_chat_id=int(ar_anchors[0]["id"]), attempt_reload_chat_ids=[int(chat["id"]) for chat in ar_anchors], attempt_panel_sources=ar_panels, attempt_ui_markers=ar_markers))

    plugin_labels = [
        f"观察场景 {run_id}",
        f"澄清目标 {run_id}",
        f"核对状态 {run_id}",
        f"规划下一步 {run_id}",
        f"汇总证据 {run_id}",
    ]
    for index, action in enumerate(action_names, start=1):
        plugin_chat = int(chats["plugin-action-panel"][index - 1]["id"])
        nonce = nonce_for(run_id, "plugin-action-panel", index)
        plugin_marker = f"TPG_{run_id}_{action} state=clicked"
        specs.append(CallSpec("plugin-action-panel", index, plugin_chat, "", nonce, [plugin_marker], mode="plugin-ui", ui_label=plugin_labels[index - 1], ui_marker=plugin_marker))

    for index in range(1, 6):
        mcp_chat = int(chats["mcp-message-ops"][index - 1]["id"])
        nonce = nonce_for(run_id, "mcp-message-ops", index)
        context_marker = f"MCP_UPDATED_{run_id}_{index:02d}"
        prompt = with_nonce("请原样引用最近一条经过更新的证据码，再用一句话说明它为什么比旧版本可靠。", nonce)
        specs.append(CallSpec("mcp-message-ops", index, mcp_chat, prompt, nonce, [context_marker], forbidden=[f"MCP_ORIGINAL_{run_id}_{index:02d}"], mode="mcp-context"))

    controls = registry["controls"]
    index = 1
    nonce = nonce_for(run_id, "lorebook-negative", index, True)
    target = str(registry["semanticLorebooks"][0]["fact"])
    trigger = str(registry["semanticLorebooks"][0]["trigger"])
    specs.append(CallSpec("lorebook-trigger", index, int(controls["lorebook-negative"]["id"]), with_nonce(f"请查阅关键词 {trigger} 的资料；若上下文没有资料，请明确说资料不足，不要编造事实码。", nonce), nonce, forbidden=[target], counts_toward_primary=False, control_name="lorebook-unbound"))

    nonce = nonce_for(run_id, "lorebook-decoy", index, True)
    keyword_probe = str(registry["semanticLorebooks"][0]["keywordFact"])
    specs.append(
        CallSpec(
            "lorebook-trigger",
            index,
            int(controls["lorebook-decoy"]["id"]),
            with_nonce("我们到达石榴旱港。请先原样给出当前常驻档案事实码，再说明是否存在这个地点的关键词专属资料。", nonce),
            nonce,
            expected=[target],
            forbidden=[keyword_probe],
            counts_toward_primary=False,
            control_name="lorebook-bound-decoy",
        )
    )

    nonce = nonce_for(run_id, "regex-negative", index, True)
    raw = "[RAW01]"
    specs.append(CallSpec("regex-runtime", index, int(controls["regex-negative"]["id"]), with_nonce(f"紧接标记行的下一行严格只写 {raw}，随后写一句普通说明。", nonce), nonce, [raw], forbidden=["CLEANED-" + assets["regex"][0]["evidenceMarker"]], counts_toward_primary=False, control_name="regex-unbound"))

    nonce = nonce_for(run_id, "preset-negative", index, True)
    target = str(registry["semanticPresets"][0]["marker"])
    specs.append(CallSpec("preset-stack", index, int(controls["preset-negative"]["id"]), with_nonce("请自由做一次简短现场审计，不要使用任何未知的固定前缀。", nonce), nonce, forbidden=[target], counts_toward_primary=False, control_name="preset-unbound"))

    nonce = nonce_for(run_id, "persona-negative", index, True)
    target = personas[0]["code"]
    specs.append(CallSpec("persona-binding", index, int(controls["persona-negative"]["id"]), with_nonce("如果上下文没有我的职业和协议码，请明确说不知道，不要猜测。", nonce), nonce, forbidden=[target], counts_toward_primary=False, control_name="persona-unbound"))

    retry_registry = registry["retryChats"]
    control_retry_keys = {
        "lorebook-unbound": "lorebook-negative",
        "lorebook-bound-decoy": "lorebook-decoy",
        "regex-unbound": "regex-negative",
        "preset-unbound": "preset-negative",
        "persona-unbound": "persona-negative",
    }
    for spec in specs:
        if spec.control_name:
            backups = retry_registry["controls"][control_retry_keys[spec.control_name]]
        else:
            backups = retry_registry["primary"][spec.family][spec.ordinal - 1]
        spec.attempt_chat_ids = [spec.chat_id] + [int(chat["id"]) for chat in backups]
        if len(spec.attempt_chat_ids) != 3 or len(set(spec.attempt_chat_ids)) != 3:
            raise RuntimeError(f"{spec.key} does not have three distinct pre-created attempt chats.")
    all_attempt_chat_ids = [chat_id for spec in specs for chat_id in spec.attempt_chat_ids]
    if len(all_attempt_chat_ids) != 165 or len(set(all_attempt_chat_ids)) != 165:
        raise RuntimeError("The 55 logical specs do not own 165 globally unique attempt chats.")
    reload_anchor_ids = {
        int(chat["id"])
        for family_ordinals in registry["uiReloadAnchors"].values()
        for ordinal_chats in family_ordinals
        for chat in ordinal_chats
    }
    if len(reload_anchor_ids) != 30 or set(all_attempt_chat_ids) & reload_anchor_ids:
        raise RuntimeError("AR reload anchors are missing, duplicated, or overlap attempt chats.")

    primary = [spec for spec in specs if spec.counts_toward_primary]
    if len(primary) != PRIMARY_TARGET:
        raise RuntimeError(f"Internal call plan has {len(primary)} primary calls, expected {PRIMARY_TARGET}.")
    controls_specs = [spec for spec in specs if not spec.counts_toward_primary]
    if len(controls_specs) != CONTROL_TARGET:
        raise RuntimeError(f"Internal call plan has {len(controls_specs)} controls, expected {CONTROL_TARGET}.")
    schedule: list[CallSpec] = []
    for family in FAMILIES:
        family_primary = sorted(
            (spec for spec in primary if spec.family == family),
            key=lambda spec: spec.ordinal,
        )
        family_controls = sorted(
            (spec for spec in controls_specs if spec.family == family),
            key=lambda spec: spec.control_name or "",
        )
        if family_primary:
            schedule.append(family_primary[0])
            schedule.extend(family_controls)
            schedule.extend(family_primary[1:])
    return schedule


def run_ui_tool(arguments: list[str], output: Path) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(UI_TOOL), *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "rawOutput": proc.stdout, "exitCode": proc.returncode}
    atomic_json(output, payload)
    return proc.returncode, payload


def dismiss_greeting(device: str, step_dir: Path) -> None:
    code, payload = run_ui_tool(
        ["tap", "--device", device, "--content-desc", "取消", "--class", "android.widget.Button"],
        step_dir / "dismiss-greeting.json",
    )
    if code not in (0, 4):
        raise RuntimeError(f"Could not safely dismiss greeting selector: {payload}")


def adb(device: str, arguments: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    command = ["adb"] + (["-s", device] if device else []) + arguments
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)


def capture_screen_only(device: str, out: Path, name: str) -> int:
    target = (out / name).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    command = ["adb"] + (["-s", device] if device else []) + ["exec-out", "screencap", "-p"]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    screen = target / "screen.png"
    screen.write_bytes(proc.stdout)
    passed = proc.returncode == 0 and proc.stdout.startswith(b"\x89PNG") and len(proc.stdout) >= 1024
    atomic_json(
        target / "capture.json",
        {
            "capturedAt": now_utc(),
            "command": command,
            "returncode": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="replace"),
            "bytes": len(proc.stdout),
            "passed": passed,
        },
    )
    return 0 if passed else 1


def settle_plugin_runtime_ui(device: str, output_dir: Path, reason: str) -> None:
    started_at = now_utc()
    time.sleep(10)
    launched = adb(
        device,
        ["shell", "monkey", "-p", "app.bitbear.tav", "-c", "android.intent.category.LAUNCHER", "1"],
        timeout=30,
    )
    if launched.returncode != 0:
        raise RuntimeError("Could not foreground Tavo after plugin runtime isolation.")
    time.sleep(3)
    capture_code = capture_screen_only(device, output_dir, "settled-screen")
    evidence = {
        "reason": reason,
        "startedAt": started_at,
        "foregroundReturncode": launched.returncode,
        "foregroundOutput": launched.stdout,
        "settleSecondsBeforeForeground": 10,
        "settleSecondsAfterForeground": 3,
        "screenCapturePassed": capture_code == 0,
        "finishedAt": now_utc(),
        "passed": launched.returncode == 0 and capture_code == 0,
    }
    durable_json(output_dir / "settle-result.json", evidence)
    if not evidence["passed"]:
        raise RuntimeError("Plugin isolation WebView stabilization evidence failed.")


def acquire_phone_runtime_lock(device: str, url: str) -> tuple[RuntimeLockSet, str]:
    normalized_device = device.strip().lower()
    if not normalized_device:
        raise RuntimeError("A non-empty ADB device serial is required for the global phone runtime lock.")
    serial_read = adb(device, ["get-serialno"])
    physical_serial = serial_read.stdout.strip().lower() if serial_read.returncode == 0 else ""
    if not physical_serial or physical_serial == "unknown":
        raise RuntimeError("Could not resolve the physical ADB serial for the global runtime lock.")
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "::1"}:
        host = "127.0.0.1"
    endpoint_identity = urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            f"{host}:{parsed.port}" if parsed.port else host,
            parsed.path.rstrip("/") or "/",
            "",
            "",
        )
    )
    lock_keys = sorted({f"device:{physical_serial}", f"endpoint:{endpoint_identity}"})
    handles: list[Any] = []
    try:
        for key in lock_keys:
            digest = hashlib.sha256(f"tavo-runtime|{key}".encode("utf-8")).hexdigest()
            path = Path("/tmp") / f"tavo-phone-runtime-{digest[:24]}.lock"
            handle = path.open("a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()} keyHash={digest} acquired={now_utc()}\n")
            handle.flush()
            os.fsync(handle.fileno())
            handles.append(handle)
    except Exception:
        RuntimeLockSet(handles).close()
        raise
    identity = stable_hash({"physicalSerial": physical_serial, "endpoint": endpoint_identity})
    return RuntimeLockSet(handles), identity


def require_device_identity(device: str) -> dict[str, Any]:
    if not device:
        raise RuntimeError("--device is required because three semantic families use real UI clicks and screenshots.")
    state = adb(device, ["get-state"])
    if state.returncode != 0 or state.stdout.strip() != "device":
        raise RuntimeError(f"ADB device {device!r} is unavailable: {state.stdout.strip()}")
    model = adb(device, ["shell", "getprop", "ro.product.model"])
    android = adb(device, ["shell", "getprop", "ro.build.version.release"])
    package = adb(device, ["shell", "dumpsys", "package", "app.bitbear.tav"], timeout=60)
    if model.returncode != 0 or android.returncode != 0 or package.returncode != 0:
        raise RuntimeError("Could not read immutable phone/app identity through ADB.")
    version_name = re.search(r"\bversionName=([^\s]+)", package.stdout)
    version_code = re.search(r"\bversionCode=(\d+)", package.stdout)
    if not version_name or not version_code:
        raise RuntimeError("Tavo package app.bitbear.tav is missing or has no readable version.")
    return {
        "serial": device,
        "model": model.stdout.strip(),
        "androidVersion": android.stdout.strip(),
        "package": "app.bitbear.tav",
        "versionName": version_name.group(1),
        "versionCode": int(version_code.group(1)),
    }


def read_mcp_surface_identity(client: TavoMcp, artifact_dir: Path) -> tuple[dict[str, Any], str]:
    initialize = client.initialize()
    tools_list = client.rpc("tools/list", {})
    resources_list = client.rpc("resources/list", {})
    templates_list = client.rpc("resources/templates/list", {})
    prompts_list = client.rpc("prompts/list", {})
    runtime_read = client.rpc("resources/read", {"uri": "tavo://runtime"})
    atomic_json(artifact_dir / "mcp-initialize.json", initialize)
    atomic_json(artifact_dir / "mcp-tools-list.json", tools_list)
    atomic_json(artifact_dir / "mcp-resources-list.json", resources_list)
    atomic_json(artifact_dir / "mcp-resource-templates-list.json", templates_list)
    atomic_json(artifact_dir / "mcp-prompts-list.json", prompts_list)
    atomic_json(artifact_dir / "mcp-runtime-at-start.json", runtime_read)

    schema_results: dict[str, Any] = {}
    for uri in MCP_SCHEMA_URIS:
        response = client.rpc("resources/read", {"uri": uri})
        atomic_json(artifact_dir / f"mcp-{safe_name(uri)}.json", response)
        contents = (response.get("result") or {}).get("contents") if isinstance(response, dict) else None
        if not isinstance(contents, list) or not contents:
            raise RuntimeError(f"MCP resource {uri} returned no schema contents.")
        schema_results[uri] = contents

    server_info = (initialize.get("result") or {}).get("serverInfo") if isinstance(initialize, dict) else None
    tools = (tools_list.get("result") or {}).get("tools") if isinstance(tools_list, dict) else None
    resources = (resources_list.get("result") or {}).get("resources") if isinstance(resources_list, dict) else None
    templates = (templates_list.get("result") or {}).get("resourceTemplates") if isinstance(templates_list, dict) else None
    prompts = (prompts_list.get("result") or {}).get("prompts") if isinstance(prompts_list, dict) else None
    if not isinstance(server_info, dict):
        raise RuntimeError("MCP initialize returned no serverInfo.")
    if not isinstance(tools, list) or not tools:
        raise RuntimeError("MCP tools/list returned no usable tool surface.")
    if not isinstance(resources, list) or not resources:
        raise RuntimeError("MCP resources/list returned no usable resources.")
    if not isinstance(templates, list):
        raise RuntimeError("MCP resources/templates/list returned no usable list.")
    if not isinstance(prompts, list):
        raise RuntimeError("MCP prompts/list returned no usable list.")
    runtime_contents = (runtime_read.get("result") or {}).get("contents") if isinstance(runtime_read, dict) else None
    if not isinstance(runtime_contents, list) or not runtime_contents:
        raise RuntimeError("MCP runtime resource could not be read at epoch start.")
    identity = {
        "serverInfo": server_info,
        "tools": tools,
        "resources": resources,
        "resourceTemplates": templates,
        "prompts": prompts,
        "schemas": schema_results,
    }
    return identity, stable_hash(identity)


def open_plus_menu(device: str, step_dir: Path) -> None:
    code, dump = run_ui_tool(
        ["dump", "--device", device, "--output", str(step_dir / "ui-before-plus.xml")],
        step_dir / "ui-before-plus.json",
    )
    if code != 0:
        raise RuntimeError("Could not dump UI before opening plus menu.")
    nodes = dump.get("nodes") if isinstance(dump.get("nodes"), list) else []
    candidates = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("class") != "android.widget.ImageView":
            continue
        bounds = node.get("bounds") if isinstance(node.get("bounds"), dict) else {}
        center = bounds.get("center") if isinstance(bounds.get("center"), dict) else {}
        if (
            node.get("clickable") is True
            and node.get("enabled") is True
            and int(center.get("x") or 9999) < 250
            and int(center.get("y") or 0) > 2100
            and 30 <= int(bounds.get("width") or 0) <= 240
        ):
            candidates.append(node)
    if len(candidates) != 1:
        atomic_json(step_dir / "plus-candidates.json", {"candidates": candidates})
        raise RuntimeError(f"Expected one bottom-left plus candidate, found {len(candidates)}.")
    target = candidates[0]
    atomic_json(step_dir / "plus-target.json", target)
    center = target["bounds"]["center"]
    proc = adb(device, ["shell", "input", "tap", str(center["x"]), str(center["y"])])
    atomic_json(step_dir / "plus-tap.json", {"returncode": proc.returncode, "output": proc.stdout, "x": center["x"], "y": center["y"]})
    if proc.returncode != 0:
        raise RuntimeError("ADB tap failed while opening plus menu.")


def tap_ar_button(device: str, label: str, step_dir: Path) -> None:
    safe_top = 350
    ordered_labels = ["AR 观察场景", "AR 澄清目标", "AR 核对状态", "AR 规划下一步", "AR 汇总证据"]
    target_order = ordered_labels.index(label) if label in ordered_labels else 0
    for attempt in range(1, 13):
        code, payload = run_ui_tool(
            ["dump", "--device", device, "--output", str(step_dir / f"ui-ar-{attempt}.xml")],
            step_dir / f"ui-ar-{attempt}.json",
        )
        if code != 0:
            raise RuntimeError(f"Could not dump UI while locating AR button {label!r}: {payload}")
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        input_tops = [
            int((node.get("bounds") or {}).get("top") or 0)
            for node in nodes
            if isinstance(node, dict)
            and node.get("class") == "android.widget.EditText"
            and isinstance(node.get("bounds"), dict)
            and int((node.get("bounds") or {}).get("top") or 0) > 0
        ]
        safe_bottom = min(2200, min(input_tops) - 220) if input_tops else 2100
        if safe_bottom <= safe_top:
            raise RuntimeError("The live composer bounds leave no safe AR click band.")
        matches = [
            node
            for node in nodes
            if isinstance(node, dict)
            and node.get("text") == label
            and node.get("class") == "android.widget.Button"
            and node.get("clickable") is True
            and node.get("enabled") is True
        ]
        if len(matches) > 1:
            atomic_json(step_dir / f"ambiguous-ar-{attempt}.json", {"matches": matches})
            raise RuntimeError(f"AR button {label!r} is ambiguous in the current UI tree.")
        if len(matches) == 1:
            target = matches[0]
            bounds = target.get("bounds") if isinstance(target.get("bounds"), dict) else {}
            center = bounds.get("center") if isinstance(bounds.get("center"), dict) else {}
            center_y = int(center.get("y") or 0)
            if safe_top <= center_y <= safe_bottom:
                proc = adb(device, ["shell", "input", "tap", str(center.get("x")), str(center_y)])
                atomic_json(
                    step_dir / "tap-ar-target.json",
                    {
                        "target": target,
                        "safeBand": {"top": safe_top, "bottom": safe_bottom, "inputTops": input_tops},
                        "returncode": proc.returncode,
                        "output": proc.stdout,
                        "attempt": attempt,
                    },
                )
                if proc.returncode != 0:
                    raise RuntimeError(f"ADB tap failed for AR button {label!r}.")
                return
            if center_y > safe_bottom:
                swipe_args = ["shell", "input", "swipe", "600", "1850", "600", "1050", "450"]
                direction = "up"
            else:
                swipe_args = ["shell", "input", "swipe", "600", "850", "600", "1550", "450"]
                direction = "down"
        else:
            visible_labels = [
                str(node.get("text"))
                for node in nodes
                if isinstance(node, dict) and str(node.get("text")) in ordered_labels
            ]
            if not visible_labels:
                atomic_json(
                    step_dir / f"semantics-not-ready-{attempt}.json",
                    {"nodeCount": len(nodes), "reason": "WebView exposed no AR button text; retry without scrolling"},
                )
                time.sleep(1)
                continue
            visible_orders = [ordered_labels.index(value) for value in visible_labels]
            if target_order > max(visible_orders):
                swipe_args = ["shell", "input", "swipe", "600", "1850", "600", "1050", "450"]
                direction = "up-search"
            else:
                swipe_args = ["shell", "input", "swipe", "600", "850", "600", "1550", "450"]
                direction = "down-search"
        swipe = adb(device, swipe_args)
        atomic_json(
            step_dir / f"scroll-{attempt}.json",
            {"returncode": swipe.returncode, "output": swipe.stdout, "direction": direction},
        )
        if swipe.returncode != 0:
            raise RuntimeError(f"Could not scroll while locating AR button {label!r}.")
        time.sleep(0.8)
    raise RuntimeError(f"AR button {label!r} could not be exposed in the safe click band after semantic-tree retries.")


def tap_plugin_action(device: str, label: str, step_dir: Path) -> None:
    open_plus_menu(device, step_dir)
    time.sleep(1.2)
    for attempt in range(1, 13):
        code, payload = run_ui_tool(
            ["dump", "--device", device, "--output", str(step_dir / f"ui-plugin-menu-{attempt}.xml")],
            step_dir / f"ui-plugin-menu-{attempt}.json",
        )
        if code != 0:
            raise RuntimeError(f"Could not dump the plugin action menu for {label!r}.")
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        matches = [
            node
            for node in nodes
            if isinstance(node, dict)
            and node.get("content-desc") == label
            and node.get("enabled") is True
            and isinstance(node.get("bounds"), dict)
        ]
        if len(matches) > 1:
            atomic_json(step_dir / f"ambiguous-plugin-action-{attempt}.json", {"matches": matches})
            raise RuntimeError(f"Plugin action {label!r} is ambiguous in the live UI tree.")
        if len(matches) == 1:
            target = matches[0]
            center = target["bounds"].get("center") or {}
            center_x = int(center.get("x") or 0)
            center_y = int(center.get("y") or 0)
            if 120 <= center_y <= 2470 and 0 < center_x < 1200:
                if capture_screen_only(device, step_dir, f"plugin-menu-ready-{attempt}") != 0:
                    raise RuntimeError("Could not capture the ready plugin action menu.")
                proc = adb(device, ["shell", "input", "tap", str(center_x), str(center_y)])
                atomic_json(
                    step_dir / "tap-plugin-action.json",
                    {
                        "target": target,
                        "attempt": attempt,
                        "x": center_x,
                        "y": center_y,
                        "returncode": proc.returncode,
                        "output": proc.stdout,
                    },
                )
                if proc.returncode != 0:
                    raise RuntimeError(f"ADB tap failed for plugin action {label!r}.")
                return
            swipe_args = (
                ["shell", "input", "swipe", "600", "2200", "600", "1100", "450"]
                if center_y > 2470
                else ["shell", "input", "swipe", "600", "900", "600", "1900", "450"]
            )
        else:
            swipe_args = ["shell", "input", "swipe", "600", "2200", "600", "1100", "450"]
        if attempt in (4, 8):
            closed = adb(device, ["shell", "input", "keyevent", "4"])
            atomic_json(
                step_dir / f"plugin-menu-restart-{attempt}.json",
                {"returncode": closed.returncode, "output": closed.stdout},
            )
            time.sleep(0.8)
            open_plus_menu(device, step_dir / f"restart-{attempt}")
            time.sleep(1.5)
            continue
        swipe = adb(device, swipe_args)
        atomic_json(
            step_dir / f"plugin-menu-scroll-{attempt}.json",
            {"returncode": swipe.returncode, "output": swipe.stdout, "arguments": swipe_args},
        )
        if swipe.returncode != 0:
            raise RuntimeError(f"Could not scroll while locating plugin action {label!r}.")
        time.sleep(0.8)
    raise RuntimeError(f"Plugin action {label!r} could not be exposed after menu polling and restart retries.")


def run_ui_action_until_input_marker(
    client: TavoMcp,
    device: str,
    step_dir: Path,
    label: str,
    marker: str,
    tap: Any,
) -> tuple[dict[str, Any], str]:
    last_response: dict[str, Any] = {}
    last_text = ""
    for action_attempt in range(1, 4):
        tap(device, label, step_dir / f"action-attempt-{action_attempt}")
        for poll in range(1, 6):
            time.sleep(1.0)
            last_response = tool_call(
                client,
                step_dir,
                f"input-readback-action-{action_attempt}-poll-{poll}.json",
                "tavo_input_get",
                {},
            )
            last_text = str(response_payload(last_response).get("text") or "")
            if ok_response(last_response) and marker in last_text:
                durable_json(
                    step_dir / "ui-action-marker-result.json",
                    {
                        "label": label,
                        "marker": marker,
                        "actionAttempt": action_attempt,
                        "poll": poll,
                        "passed": True,
                    },
                )
                return last_response, last_text
        foreground = adb(
            device,
            ["shell", "monkey", "-p", "app.bitbear.tav", "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=30,
        )
        durable_json(
            step_dir / f"foreground-retry-{action_attempt}.json",
            {"returncode": foreground.returncode, "output": foreground.stdout},
        )
        if foreground.returncode != 0:
            break
        time.sleep(2.0)
    durable_json(
        step_dir / "ui-action-marker-result.json",
        {
            "label": label,
            "marker": marker,
            "lastInputText": last_text,
            "passed": False,
        },
    )
    return last_response, last_text


def prepare_ejs_runtime_seed(
    client: TavoMcp,
    artifact_dir: Path,
    step_dir: Path,
    device: str,
    run_id: str,
    spec: CallSpec,
) -> dict[str, Any]:
    target_plugin_id = f"codex.semantic.{run_id.lower()}"
    assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "before-ejs-seed")
    dismiss_greeting(device, step_dir)
    cleared = tool_call(client, step_dir, "ejs-seed-input-clear.json", "tavo_input_clear", {})
    blank = tool_call(client, step_dir, "ejs-seed-input-clear-readback.json", "tavo_input_get", {})
    if (
        not ok_response(cleared)
        or not ok_response(blank)
        or str(response_payload(blank).get("text") or "")
    ):
        raise RuntimeError("Could not prove a blank input before the EJS runtime seed action.")
    if capture_screen_only(device, step_dir, "ejs-before-seed") != 0:
        raise RuntimeError("Could not capture the screen before the EJS runtime seed action.")
    tap_plugin_action(device, f"EJS 随机写入 {run_id}", step_dir / "ejs-seed-action")
    time.sleep(1.0)
    readback = tool_call(client, step_dir, "ejs-seed-input-readback.json", "tavo_input_get", {})
    text = str(response_payload(readback).get("text") or "")
    match = re.fullmatch(
        rf"\[EJS-SEED:{re.escape(run_id)}\] token=(EJS_RUNTIME_{re.escape(run_id)}_[A-Za-z0-9_]+);before=(\d+)",
        text,
    )
    if not ok_response(readback) or match is None:
        raise RuntimeError("The EJS seed action did not expose a parseable runtime-only token and counter.")
    token = match.group(1)
    before = int(match.group(2))
    source_leaks: list[str] = []
    source_root = artifact_dir / "semantic-sources"
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if token in path.read_text(encoding="utf-8"):
                source_leaks.append(str(path))
        except (OSError, UnicodeDecodeError):
            continue
    if token in spec.prompt or source_leaks:
        raise RuntimeError("The runtime-only EJS token leaked into the static prompt or semantic source files.")
    if capture_phone(device, step_dir, "ejs-after-seed") != 0:
        raise RuntimeError("Could not capture EJS seed input evidence.")
    assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "after-ejs-seed")
    evidence = {
        "seedInput": text,
        "runtimeValue": token,
        "beforeRenderCount": before,
        "runtimeValueAbsentFromPrompt": token not in spec.prompt,
        "runtimeValueAbsentFromSources": not source_leaks,
        "sourceLeaks": source_leaks,
    }
    atomic_json(step_dir / "ejs-runtime-seed-evidence.json", evidence)
    return evidence


def probe_ejs_runtime_after_generation(
    client: TavoMcp,
    step_dir: Path,
    device: str,
    run_id: str,
    seed: dict[str, Any],
) -> dict[str, Any]:
    target_plugin_id = f"codex.semantic.{run_id.lower()}"
    assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "before-ejs-probe")
    cleared = tool_call(client, step_dir, "ejs-probe-input-clear.json", "tavo_input_clear", {})
    blank = tool_call(client, step_dir, "ejs-probe-input-clear-readback.json", "tavo_input_get", {})
    if (
        not ok_response(cleared)
        or not ok_response(blank)
        or str(response_payload(blank).get("text") or "")
    ):
        raise RuntimeError("Could not prove a blank input before the EJS runtime probe action.")
    tap_plugin_action(device, f"EJS 状态回读 {run_id}", step_dir / "ejs-probe-action")
    time.sleep(1.0)
    readback = tool_call(client, step_dir, "ejs-probe-input-readback.json", "tavo_input_get", {})
    text = str(response_payload(readback).get("text") or "")
    match = re.fullmatch(
        rf"\[EJS-PROBE:{re.escape(run_id)}\] token=(EJS_RUNTIME_{re.escape(run_id)}_[A-Za-z0-9_]+);after=(\d+)",
        text,
    )
    if not ok_response(readback) or match is None:
        raise RuntimeError("The EJS probe action did not expose a parseable post-generation token and counter.")
    token = match.group(1)
    after = int(match.group(2))
    before = int(seed["beforeRenderCount"])
    passed = bool(token == seed["runtimeValue"] and after > before)
    evidence = {
        **seed,
        "probeInput": text,
        "probeValue": token,
        "afterRenderCount": after,
        "counterDelta": after - before,
        "passed": passed,
    }
    atomic_json(step_dir / "ejs-runtime-proof-provisional.json", evidence)
    if capture_phone(device, step_dir, "ejs-after-probe") != 0:
        raise RuntimeError("Could not capture EJS post-generation probe evidence.")
    final_clear = tool_call(client, step_dir, "ejs-probe-final-clear.json", "tavo_input_clear", {})
    final_blank = tool_call(client, step_dir, "ejs-probe-final-clear-readback.json", "tavo_input_get", {})
    if (
        not ok_response(final_clear)
        or not ok_response(final_blank)
        or str(response_payload(final_blank).get("text") or "")
    ):
        raise RuntimeError("Could not clear the EJS probe text after preserving evidence.")
    assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "after-ejs-probe")
    if not passed:
        raise RuntimeError(
            f"EJS runtime proof failed: value match={token == seed['runtimeValue']}, counter {before}->{after}."
        )
    durable_json(step_dir / "ejs-runtime-proof.json", evidence)
    return evidence


def set_current_chat(client: TavoMcp, step_dir: Path, chat_id: int, request_id: str) -> None:
    response = tool_call(
        client,
        step_dir,
        "set-current-chat.json",
        "tavo_current_chat_set",
        {"id": chat_id, "dryRun": False, "clientRequestId": request_id},
    )
    if not ok_response(response):
        raise RuntimeError(f"Could not set current chat {chat_id}.")
    readback = tool_call(client, step_dir, "set-current-chat-readback.json", "tavo_current_chat_get", {})
    current_payload = response_payload(readback).get("chat")
    current_chat = current_payload if isinstance(current_payload, dict) else {}
    if not ok_response(readback) or int(current_chat.get("id") or 0) != int(chat_id):
        raise RuntimeError(f"Current-chat readback did not match target chat {chat_id}.")


def reload_chat_ui(
    client: TavoMcp,
    step_dir: Path,
    device: str,
    target_chat_id: int,
    anchor_chat_id: int,
    request_scope: str,
    expected_panel_marker: str,
) -> None:
    if target_chat_id == anchor_chat_id:
        raise RuntimeError("A chat UI reload requires a distinct anchor chat.")
    anchor_before = all_messages(client, anchor_chat_id, step_dir / "anchor-baseline", "messages-before.json")
    if (
        len(anchor_before) != 1
        or anchor_before[0].get("hidden") is not True
        or "SEMANTIC_CHAT_SEED_" not in str(anchor_before[0].get("content") or "")
    ):
        raise RuntimeError("AR reload anchor is not an isolated seed-only chat.")
    anchor_hash = stable_hash(canonical_messages(anchor_before))
    set_current_chat(
        client,
        step_dir / "reload-anchor",
        anchor_chat_id,
        f"{request_scope}-anchor-{anchor_chat_id}",
    )
    time.sleep(1.0)
    set_current_chat(
        client,
        step_dir / "reload-target",
        target_chat_id,
        f"{request_scope}-target-{target_chat_id}",
    )
    launched = adb(
        device,
        ["shell", "monkey", "-p", "app.bitbear.tav", "-c", "android.intent.category.LAUNCHER", "1"],
        timeout=30,
    )
    atomic_json(
        step_dir / "reload-foreground.json",
        {"returncode": launched.returncode, "output": launched.stdout},
    )
    if launched.returncode != 0:
        raise RuntimeError("Could not foreground Tavo while reloading a partially rendered chat UI.")
    time.sleep(7.0)
    if capture_phone(device, step_dir, "reload-ready") != 0:
        raise RuntimeError("Could not capture the reloaded chat UI.")
    anchor_after = all_messages(client, anchor_chat_id, step_dir / "anchor-baseline", "messages-after.json")
    if stable_hash(canonical_messages(anchor_after)) != anchor_hash:
        raise RuntimeError("AR reload anchor changed while reloading the target chat.")
    target_messages = all_messages(client, target_chat_id, step_dir / "target-baseline", "messages.json")
    marker_matches = [
        message
        for message in target_messages
        if expected_panel_marker in str(message.get("content") or "")
    ]
    if len(marker_matches) != 1:
        raise RuntimeError("AR target chat does not contain exactly one attempt-specific panel marker.")
    dump_code, dump = run_ui_tool(
        ["dump", "--device", device, "--output", str(step_dir / "attempt-panel-ui.xml")],
        step_dir / "attempt-panel-ui.json",
    )
    visible_marker_nodes = [
        node
        for node in (dump.get("nodes") or [])
        if isinstance(node, dict)
        and expected_panel_marker in (str(node.get("text") or "") + str(node.get("content-desc") or ""))
    ]
    durable_json(
        step_dir / "attempt-panel-marker-visibility.json",
        {
            "marker": expected_panel_marker,
            "visibleNodeCount": len(visible_marker_nodes),
            "dumpPassed": dump_code == 0,
            "note": "A zero count is allowed when the marker is outside the current scroll viewport; the subsequent unique button click and input readback are the action proof.",
        },
    )
    if dump_code != 0:
        raise RuntimeError("Could not read the UI tree after reloading the attempt-specific AR panel.")


def prepare_mcp_context(client: TavoMcp, step_dir: Path, spec: CallSpec, run_id: str) -> None:
    marker = f"MCP_UPDATED_{run_id}_{spec.ordinal:02d}"
    messages = all_messages(client, spec.chat_id, step_dir, "mcp-context-messages-before.json")
    if any(marker in str(message.get("content") or "") for message in messages):
        return
    original = f"MCP_ORIGINAL_{run_id}_{spec.ordinal:02d}"
    append = tool_call(
        client,
        step_dir,
        "mcp-context-append.json",
        "tavo_message_append",
        {
            "chatId": spec.chat_id,
            "message": {"role": "assistant", "content": original, "hidden": False},
            "dryRun": False,
            "clientRequestId": f"semantic-{run_id}-mcp-context-{spec.ordinal:02d}-{spec.chat_id}-{safe_name(spec.attempt)}-append",
        },
    )
    message_id = int(response_payload(append).get("id") or 0)
    if not ok_response(append) or message_id < 1:
        raise RuntimeError("Could not append MCP context message.")
    messages_after_append = all_messages(
        client, spec.chat_id, step_dir, "mcp-context-messages-after-append.json"
    )
    appended_matches = [message for message in messages_after_append if int(message.get("id") or 0) == message_id]
    if (
        len(messages_after_append) != len(messages) + 1
        or len(appended_matches) != 1
        or str(appended_matches[0].get("content") or "") != original
    ):
        raise RuntimeError("MCP append did not add exactly one persistent original message.")
    update = tool_call(
        client,
        step_dir,
        "mcp-context-update.json",
        "tavo_message_update",
        {
            "chatId": spec.chat_id,
            "message": {"id": message_id, "content": marker, "hidden": False},
            "dryRun": False,
            "clientRequestId": f"semantic-{run_id}-mcp-context-{spec.ordinal:02d}-{spec.chat_id}-{safe_name(spec.attempt)}-update",
        },
    )
    readback = tool_call(client, step_dir, "mcp-context-readback.json", "tavo_message_get", {"chatId": spec.chat_id, "id": message_id})
    messages_after_update = all_messages(
        client, spec.chat_id, step_dir, "mcp-context-messages-after-update.json"
    )
    updated_matches = [message for message in messages_after_update if int(message.get("id") or 0) == message_id]
    readback_payload = response_payload(readback)
    if (
        not ok_response(update)
        or not ok_response(readback)
        or str(readback_payload.get("content") or "") != marker
        or len(messages_after_update) != len(messages_after_append)
        or len(updated_matches) != 1
        or str(updated_matches[0].get("content") or "") != marker
        or original in json.dumps(messages_after_update, ensure_ascii=False)
    ):
        raise RuntimeError("MCP append/update/readback chain did not preserve the updated marker.")


def prepare_lorebook_primer(client: TavoMcp, step_dir: Path, spec: CallSpec, run_id: str) -> None:
    if not spec.history_trigger:
        raise RuntimeError("Lorebook history mode requires a non-empty history trigger.")
    primer = f"{spec.history_trigger} WORLD_BOOK_HISTORY_TRIGGER_{run_id}_{spec.ordinal:02d}"
    messages = all_messages(client, spec.chat_id, step_dir, "lore-primer-messages-before.json")
    if any(message.get("role") == "user" and message.get("content") == primer for message in messages):
        return
    request_fingerprint = hashlib.sha256(
        f"{spec.key}:{spec.chat_id}:{primer}".encode("utf-8")
    ).hexdigest()[:16]
    append = tool_call(
        client,
        step_dir,
        "lore-primer-append.json",
        "tavo_message_append",
        {
            "chatId": spec.chat_id,
            "message": {"role": "user", "content": primer, "hidden": False},
            "dryRun": False,
            "clientRequestId": f"semantic-{run_id}-{safe_name(spec.key)}-{spec.chat_id}-{request_fingerprint}",
        },
    )
    appended = response_payload(append)
    if (
        not ok_response(append)
        or int(appended.get("chatId") or 0) != spec.chat_id
        or str(appended.get("message", {}).get("content") or "") != primer
    ):
        raise RuntimeError("Lorebook trigger append returned stale or mismatched idempotency evidence.")
    readback = all_messages(client, spec.chat_id, step_dir, "lore-primer-messages-after.json")
    if not any(message.get("role") == "user" and message.get("content") == primer for message in readback):
        raise RuntimeError("Lorebook trigger primer was not persisted in the target chat.")


def locate_exchange(items: list[dict[str, Any]], prompt: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    ordered = sorted(items, key=lambda item: int(item.get("index") or 0))
    for position, item in enumerate(ordered):
        if item.get("role") != "user" or item.get("content") != prompt:
            continue
        for candidate in ordered[position + 1 :]:
            if candidate.get("role") == "user":
                break
            if candidate.get("role") == "assistant":
                return item, candidate
        return item, None
    return None, None


def canonical_messages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            int(item.get("index") or 0),
            int(item.get("id") or 0),
        ),
    )


def normalized_message_snapshot(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = canonical_messages(items)
    ids = [item.get("id") for item in ordered]
    if any(not isinstance(value, int) or value < 1 for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Message baseline contains missing, non-integer, or duplicate persistent IDs.")
    keys = ("id", "index", "role", "content", "reasoning", "hidden", "speakerName")
    return [{key: item.get(key) for key in keys} for item in ordered]


def validate_exchange(spec: CallSpec, user: dict[str, Any] | None, assistant: dict[str, Any] | None) -> tuple[bool, list[str]]:
    failures: list[str] = []
    content = str(assistant.get("content") or "") if assistant else ""
    reasoning = str(assistant.get("reasoning") or "") if assistant else ""
    if user is None:
        failures.append("exact user prompt was not found in the target chat")
    if assistant is None:
        failures.append("no assistant reply followed the exact user prompt")
    if len(content.strip()) < 30:
        failures.append("assistant reply was too short to be a substantive model result")
    for expected in spec.expected:
        if expected not in content:
            failures.append(f"assistant reply did not include expected semantic marker: {expected}")
    for alternatives in spec.expected_any:
        evidence_text = content + ("\n" + reasoning if spec.expected_any_may_use_reasoning else "")
        if not any(value in evidence_text for value in alternatives):
            failures.append(
                "assistant reply did not include any allowed semantic marker: "
                + " | ".join(alternatives)
            )
    for pattern in spec.expected_patterns:
        if re.search(pattern, content) is None:
            failures.append(f"assistant reply did not match required semantic pattern: {pattern}")
    if spec.required_prefix and not content.lstrip().startswith(spec.required_prefix):
        failures.append(f"assistant reply did not begin with required prefix: {spec.required_prefix}")
    cursor = -1
    for marker in spec.ordered_markers:
        position = content.find(marker, cursor + 1)
        if position < 0:
            failures.append(f"assistant reply omitted ordered marker: {marker}")
            continue
        if position <= cursor:
            failures.append(f"assistant reply placed ordered marker out of sequence: {marker}")
        cursor = position
    for forbidden in spec.forbidden:
        if forbidden in content:
            failures.append(f"assistant reply included forbidden/control marker: {forbidden}")
    if spec.persona_name and user is not None and user.get("speakerName") != spec.persona_name:
        failures.append("stored user message speakerName did not match the bound persona")
    return not failures, failures


def execute_call(
    client: TavoMcp,
    artifact_dir: Path,
    device: str,
    run_id: str,
    spec: CallSpec,
    timeout: int,
    execution_meta: dict[str, str],
) -> dict[str, Any]:
    root = "controls" if not spec.counts_toward_primary else "model-calls"
    step_dir = artifact_dir / root / spec.family / spec.step_name
    step_dir.mkdir(parents=True, exist_ok=True)
    result_path = step_dir / "result.json"
    if result_path.exists():
        previous = load_json(result_path)
        expected_meta = {**execution_meta, "specHash": spec_record(spec)["specHash"]}
        mismatches = {
            key: {"expected": value, "actual": previous.get(key) if isinstance(previous, dict) else None}
            for key, value in expected_meta.items()
            if not isinstance(previous, dict) or previous.get(key) != value
        }
        if isinstance(previous, dict) and not mismatches:
            return previous
        raise RuntimeError(
            f"Existing result for {spec.key} belongs to another execution identity; start a new artifact directory."
        )
    intent_path = step_dir / "intent.private.json"
    if intent_path.exists():
        intent = load_json(intent_path)
        expected_identity = {**execution_meta, "specHash": spec_record(spec)["specHash"]}
        mismatches = {
            key: {"expected": value, "actual": intent.get(key)}
            for key, value in expected_identity.items()
            if intent.get(key) != value
        }
        if mismatches:
            atomic_json(step_dir / "call-intent-identity-mismatch.json", mismatches)
            raise RuntimeError("An unresolved call intent belongs to another execution identity.")
        ejs_evidence = None
        for candidate in (step_dir / "ejs-runtime-proof.json", step_dir / "ejs-runtime-seed-evidence.json"):
            if candidate.exists():
                ejs_evidence = load_json(candidate)
                break
        panel_evidence = load_json(step_dir / "live-panel-result.json") if (step_dir / "live-panel-result.json").exists() else None
        return reconcile_attempt_result(
            client,
            artifact_dir,
            device,
            run_id,
            spec,
            execution_meta,
            {
                **expected_identity,
                "family": spec.family,
                "ordinal": spec.ordinal,
                "chatId": spec.chat_id,
                "activePresetId": intent.get("activePresetId"),
                "mode": spec.mode,
                "controlName": spec.control_name,
                "attempt": spec.attempt,
                "countsTowardPrimary": spec.counts_toward_primary,
                "prompt": spec.prompt,
                "nonce": spec.nonce,
                "inputSendOk": False,
                "panelEvidence": panel_evidence,
                "ejsRuntimeEvidence": ejs_evidence,
                "passed": False,
                "failures": ["reconciling unresolved durable call intent"],
            },
        )

    start_path = step_dir / "start.private.json"
    if start_path.exists():
        interrupted = {
            **execution_meta,
            "specHash": spec_record(spec)["specHash"],
            "family": spec.family,
            "ordinal": spec.ordinal,
            "chatId": spec.chat_id,
            "mode": spec.mode,
            "controlName": spec.control_name,
            "attempt": spec.attempt,
            "variant": spec.variant,
            "countsTowardPrimary": spec.counts_toward_primary,
            "prompt": spec.prompt,
            "nonce": spec.nonce,
            "inputSendOk": False,
            "userMessageId": None,
            "assistantMessageId": None,
            "passed": False,
            "failures": ["attempt was interrupted after durable start and before durable send intent"],
            "interruptedBeforeIntent": True,
            "finishedAt": now_utc(),
            "artifactDir": str(step_dir),
        }
        return durable_result_once(result_path, interrupted)
    start_record = {
        **execution_meta,
        "specHash": spec_record(spec)["specHash"],
        "family": spec.family,
        "ordinal": spec.ordinal,
        "variant": spec.variant,
        "attempt": spec.attempt,
        "chatId": spec.chat_id,
        "plannedPrompt": spec.prompt,
        "plannedNonce": spec.nonce,
        "startedAt": now_utc(),
        "status": "started-before-side-effects",
    }
    durable_private_json(start_path, start_record)
    durable_json(
        step_dir / "start-proof.json",
        {
            "specHash": start_record["specHash"],
            "chatId": spec.chat_id,
            "variant": spec.variant,
            "attempt": spec.attempt,
            "plannedPromptSha256": hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest(),
            "startedAt": start_record["startedAt"],
        },
    )

    set_current_chat(client, step_dir, spec.chat_id, f"semantic-{run_id}-{spec.key}-set-chat")
    active_preset_id = activate_chat_preset(
        client,
        step_dir,
        spec.chat_id,
        f"{run_id}-{spec.key}",
    )
    time.sleep(0.8)
    time.sleep(3 if spec.mode in {"ar-ui", "plugin-ui"} else 0.4)
    if device:
        dismiss_greeting(device, step_dir)
    panel_evidence: dict[str, Any] | None = None
    ejs_runtime_evidence: dict[str, Any] | None = None
    if spec.mode in {"ar-ui", "plugin-ui"}:
        if not device:
            raise RuntimeError("UI semantic calls require --device.")
        target_plugin_id = f"codex.semantic.{run_id.lower()}"
        assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "before-ui-action")
        dismiss_greeting(device, step_dir)
        cleared = tool_call(client, step_dir, "ui-input-clear.json", "tavo_input_clear", {})
        cleared_readback = tool_call(client, step_dir, "ui-input-clear-readback.json", "tavo_input_get", {})
        if (
            not ok_response(cleared)
            or not ok_response(cleared_readback)
            or str(response_payload(cleared_readback).get("text") or "")
        ):
            raise RuntimeError("Could not prove a blank input before the UI action.")
        if spec.mode == "ar-ui":
            if not spec.panel_variant or not spec.panel_source_sha256:
                raise RuntimeError("AR semantic call has no immutable panel source identity.")
            panel_evidence = append_live_panel(
                client,
                artifact_dir,
                step_dir,
                spec.chat_id,
                run_id,
                spec.panel_variant,
                spec.panel_source_sha256,
                spec.key,
            )
            atomic_json(step_dir / "live-panel-result.json", panel_evidence)
            if not spec.reload_chat_id:
                raise RuntimeError("AR semantic call has no distinct chat reload anchor.")
            reload_chat_ui(
                client,
                step_dir / "panel-ui-reload",
                device,
                spec.chat_id,
                int(spec.reload_chat_id),
                f"semantic-{run_id}-{spec.key}-panel-reload",
                str(panel_evidence["marker"]),
            )
        if capture_screen_only(device, step_dir, "ui-before-action") != 0:
            raise RuntimeError("Could not capture the screen before the UI action.")
        time.sleep(0.3)
        tapper = tap_ar_button if spec.mode == "ar-ui" else tap_plugin_action
        input_readback, base_prompt = run_ui_action_until_input_marker(
            client,
            device,
            step_dir / "ui-action",
            str(spec.ui_label),
            str(spec.ui_marker),
            tapper,
        )
        if not ok_response(input_readback) or not spec.ui_marker or spec.ui_marker not in base_prompt:
            raise RuntimeError(f"UI action did not produce the required input/variable marker {spec.ui_marker!r}.")
        if capture_phone(device, step_dir, "ui-after-action") != 0:
            raise RuntimeError("Could not capture UI evidence after the action.")
        assert_isolated_plugin_runtime(client, step_dir, target_plugin_id, "after-ui-action")
        prompt = with_nonce(
            base_prompt + f"\n可见答案必须原样引用这条由界面动作写入的证据码：{spec.ui_marker}",
            spec.nonce,
        )
        prefix_nonce = tool_call(
            client,
            step_dir,
            "prefix-nonce.json",
            "tavo_input_set",
            {"text": prompt},
        )
        if not ok_response(prefix_nonce):
            raise RuntimeError("Could not prefix nonce to UI-generated input.")
        prompt_readback = tool_call(client, step_dir, "prompt-readback.json", "tavo_input_get", {})
        if not ok_response(prompt_readback) or response_payload(prompt_readback).get("text") != prompt:
            raise RuntimeError("UI-generated prompt did not preserve the exact nonce-prefixed text.")
    else:
        prompt = spec.prompt
        if spec.mode == "mcp-context":
            prepare_mcp_context(client, step_dir, spec, run_id)
        elif spec.mode in {"lorebook-primed", "lorebook-history-v3", "lorebook-history-v4"}:
            prepare_lorebook_primer(client, step_dir, spec, run_id)
        elif spec.mode == "ejs-runtime":
            if not device:
                raise RuntimeError("EJS runtime semantic calls require --device.")
            ejs_runtime_evidence = prepare_ejs_runtime_seed(
                client,
                artifact_dir,
                step_dir,
                device,
                run_id,
                spec,
            )
        set_input = tool_call(client, step_dir, "input-set.json", "tavo_input_set", {"text": prompt})
        input_get = tool_call(client, step_dir, "input-get.json", "tavo_input_get", {})
        if not ok_response(set_input) or not ok_response(input_get) or response_payload(input_get).get("text") != prompt:
            raise RuntimeError("MCP input set/get did not preserve the exact prompt.")
        time.sleep(2.0)

    atomic_json(
        step_dir / "prompt.json",
        {
            "prompt": prompt,
            "nonce": spec.nonce,
            "expected": spec.expected,
            "expectedAny": spec.expected_any,
            "expectedPatterns": spec.expected_patterns,
            "requiredPrefix": spec.required_prefix,
            "orderedMarkers": spec.ordered_markers,
            "expectedAnyMayUseReasoning": spec.expected_any_may_use_reasoning,
            "forbidden": spec.forbidden,
        },
    )
    messages_before = all_messages(client, spec.chat_id, step_dir, "messages-before.json")
    baseline_snapshot = normalized_message_snapshot(messages_before)
    messages_before_confirm = all_messages(
        client,
        spec.chat_id,
        step_dir,
        "messages-before-confirm.json",
    )
    confirmed_baseline_snapshot = normalized_message_snapshot(messages_before_confirm)
    if stable_hash(confirmed_baseline_snapshot) != stable_hash(baseline_snapshot):
        raise RuntimeError("Pre-send message baseline changed between two read-only snapshots.")
    messages_before = messages_before_confirm
    if spec.mode == "ejs-runtime" and ejs_runtime_evidence is not None:
        runtime_value = str(ejs_runtime_evidence.get("runtimeValue") or "")
        if not runtime_value or runtime_value in json.dumps(messages_before, ensure_ascii=False):
            raise RuntimeError("The runtime-only EJS value leaked into pre-send chat history.")
        ejs_runtime_evidence["runtimeValueAbsentFromPreSendMessages"] = True
        atomic_json(step_dir / "ejs-runtime-seed-evidence.json", ejs_runtime_evidence)
    existing_user, existing_assistant = locate_exchange(messages_before, prompt)
    if existing_user is not None or existing_assistant is not None:
        raise RuntimeError(
            "An exact prior exchange exists without a matching immutable result artifact; refusing to reuse or resend it."
        )
    before_count = len(messages_before)
    before_ids = sorted(
        int(message["id"])
        for message in messages_before
        if isinstance(message.get("id"), int)
    )
    intent = {
        **execution_meta,
        "specHash": spec_record(spec)["specHash"],
        "family": spec.family,
        "ordinal": spec.ordinal,
        "attempt": spec.attempt,
        "chatId": spec.chat_id,
        "activePresetId": active_preset_id,
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "beforeCount": before_count,
        "beforeMessageIds": before_ids,
        "beforeMessagesHash": stable_hash(confirmed_baseline_snapshot),
        "exactPrompt": prompt,
        "nonce": spec.nonce,
        "variant": spec.variant,
        "panelEvidenceHash": stable_hash(panel_evidence) if panel_evidence is not None else None,
        "ejsEvidenceHash": stable_hash(ejs_runtime_evidence) if ejs_runtime_evidence is not None else None,
        "preparedAt": now_utc(),
        "status": "prepared-before-send",
    }
    durable_private_json(step_dir / "intent.private.json", intent)
    durable_json(
        step_dir / "call-intent.json",
        {
            key: intent.get(key)
            for key in (
                "specHash",
                "family",
                "ordinal",
                "variant",
                "attempt",
                "chatId",
                "activePresetId",
                "promptSha256",
                "beforeCount",
                "beforeMessageIds",
                "beforeMessagesHash",
                "panelEvidenceHash",
                "ejsEvidenceHash",
                "preparedAt",
                "status",
            )
        },
    )
    send_started = now_utc()
    send_start = {
        **execution_meta,
        "specHash": intent["specHash"],
        "chatId": spec.chat_id,
        "variant": spec.variant,
        "attempt": spec.attempt,
        "promptSha256": intent["promptSha256"],
        "status": "entering-non-idempotent-input-send",
        "sendStartedAt": send_started,
    }
    durable_private_json(step_dir / "send-start.private.json", send_start)
    durable_json(
        step_dir / "send-start.json",
        {
            "specHash": send_start["specHash"],
            "chatId": send_start["chatId"],
            "variant": send_start["variant"],
            "attempt": send_start["attempt"],
            "promptSha256": send_start["promptSha256"],
            "status": send_start["status"],
            "sendStartedAt": send_start["sendStartedAt"],
        },
    )
    send = tool_call(client, step_dir, "input-send.json", "tavo_input_send", {}, timeout=timeout)
    send_finished = now_utc()
    send_outcome = {
        "specHash": intent["specHash"],
        "chatId": spec.chat_id,
        "variant": spec.variant,
        "attempt": spec.attempt,
        "status": "send-returned",
        "rpcReturnedOk": ok_response(send),
        "sendResponseHash": stable_hash(send),
        "sendStartedAt": send_started,
        "sendFinishedAt": send_finished,
    }
    durable_private_json(step_dir / "send-outcome.private.json", send_outcome)
    durable_json(step_dir / "call-intent-send-returned.json", send_outcome)
    deadline = time.time() + timeout
    after_count = message_count(client, spec.chat_id)
    while after_count < before_count + 2 and time.time() < deadline:
        time.sleep(2)
        after_count = message_count(client, spec.chat_id)
    messages_after = all_messages(client, spec.chat_id, step_dir, "messages-after.json")
    user, assistant = locate_exchange(messages_after, prompt)
    send_ok = ok_response(send)

    if spec.mode == "ejs-runtime":
        if ejs_runtime_evidence is None:
            raise RuntimeError("EJS runtime call has no pre-generation seed evidence.")
        time.sleep(1.2)
        ejs_runtime_evidence = probe_ejs_runtime_after_generation(
            client,
            step_dir,
            device,
            run_id,
            ejs_runtime_evidence,
        )

    passed, failures = validate_exchange(spec, user, assistant)
    if spec.mode == "ejs-runtime" and ejs_runtime_evidence is not None:
        runtime_token = str(ejs_runtime_evidence.get("runtimeValue") or "")
        assistant_content = str(assistant.get("content") or "") if assistant else ""
        if not runtime_token or runtime_token not in assistant_content:
            failures.append("assistant reply did not include the runtime-only EJS token")
        if ejs_runtime_evidence.get("passed") is not True:
            failures.append("EJS runtime seed/probe proof did not pass")
        passed = not failures
    before_id_set = {message.get("id") for message in messages_before if message.get("id") is not None}
    transport_failures: list[str] = []
    if after_count != before_count + 2:
        transport_failures.append(
            f"message count changed from {before_count} to {after_count}; expected exactly {before_count + 2}"
        )
    if user is not None and user.get("id") in before_id_set:
        transport_failures.append("user message ID already existed before this call")
    if assistant is not None and assistant.get("id") in before_id_set:
        transport_failures.append("assistant message ID already existed before this call")
    if user is not None and user.get("id") is None:
        transport_failures.append("new user message has no persistent ID")
    if assistant is not None and assistant.get("id") is None:
        transport_failures.append("new assistant message has no persistent ID")
    failures.extend(transport_failures)
    passed = passed and not transport_failures
    result = {
        **execution_meta,
        "specHash": spec_record(spec)["specHash"],
        "family": spec.family,
        "ordinal": spec.ordinal,
        "chatId": spec.chat_id,
        "activePresetId": active_preset_id,
        "mode": spec.mode,
        "controlName": spec.control_name,
        "attempt": spec.attempt,
        "variant": spec.variant,
        "countsTowardPrimary": spec.counts_toward_primary,
        "prompt": prompt,
        "nonce": spec.nonce,
        "expected": spec.expected,
        "expectedAny": spec.expected_any,
        "expectedPatterns": spec.expected_patterns,
        "requiredPrefix": spec.required_prefix,
        "orderedMarkers": spec.ordered_markers,
        "expectedAnyMayUseReasoning": spec.expected_any_may_use_reasoning,
        "forbidden": spec.forbidden,
        "inputSendOk": send_ok,
        "rpcReturnedOk": send_ok,
        "transportCommitted": bool(user and user.get("id") not in before_id_set),
        "exchangeComplete": bool(not transport_failures and user is not None and assistant is not None),
        "userMessageId": user.get("id") if user else None,
        "assistantMessageId": assistant.get("id") if assistant else None,
        "assistantContent": assistant.get("content") if assistant else None,
        "nonceVisible": bool(assistant and spec.nonce in str(assistant.get("content") or "")),
        "assistantReasoningPresent": bool(assistant and assistant.get("reasoning")),
        "panelEvidence": panel_evidence,
        "ejsRuntimeEvidence": ejs_runtime_evidence,
        "beforeCount": before_count,
        "afterCount": after_count,
        "sendStartedAt": send_started,
        "sendFinishedAt": send_finished,
        "passed": bool(send_ok and passed),
        "failures": ([] if send_ok else ["tavo_input_send did not return a successful tool response"]) + failures,
        "finishedAt": now_utc(),
        "artifactDir": str(step_dir),
    }
    if result["exchangeComplete"]:
        result = durable_result_once(result_path, result)
        durable_json(
            step_dir / "call-intent-complete.json",
            {
                "specHash": intent["specHash"],
                "chatId": spec.chat_id,
                "variant": spec.variant,
                "attempt": spec.attempt,
                "status": "complete",
                "passed": result["passed"],
                "userMessageId": result["userMessageId"],
                "assistantMessageId": result["assistantMessageId"],
                "finishedAt": result["finishedAt"],
            },
        )
    else:
        durable_json(step_dir / "provisional-result.json", result)
    return result


def reconcile_attempt_result(
    client: TavoMcp,
    artifact_dir: Path,
    device: str,
    run_id: str,
    spec: CallSpec,
    execution_meta: dict[str, str],
    initial_result: dict[str, Any],
    grace_seconds: int = 75,
) -> dict[str, Any]:
    root = "controls" if not spec.counts_toward_primary else "model-calls"
    step_dir = artifact_dir / root / spec.family / spec.step_name
    intent_path = step_dir / "intent.private.json"
    if not intent_path.exists():
        return initial_result
    intent = load_json(intent_path)
    expected_identity = {**execution_meta, "specHash": spec_record(spec)["specHash"]}
    identity_mismatches = {
        key: {"expected": value, "actual": intent.get(key)}
        for key, value in expected_identity.items()
        if intent.get(key) != value
    }
    if identity_mismatches:
        durable_json(step_dir / "reconcile-identity-mismatch.json", identity_mismatches)
        raise RuntimeError("Reconciliation intent belongs to another immutable execution identity.")
    prompt = str(intent.get("exactPrompt") or initial_result.get("prompt") or "")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else ""
    if not prompt or prompt_hash != intent.get("promptSha256"):
        raise RuntimeError("Reconciliation intent has no valid exact prompt identity.")
    reconcile_spec = replace(spec, prompt=prompt)
    before_count = int(intent.get("beforeCount") or 0)
    before_ids = {int(value) for value in intent.get("beforeMessageIds", [])}
    before_messages_hash = str(intent.get("beforeMessagesHash") or "")
    send_start_path = step_dir / "send-start.private.json"
    send_outcome_path = step_dir / "send-outcome.private.json"
    send_start = load_json(send_start_path) if send_start_path.exists() else {}
    send_outcome = load_json(send_outcome_path) if send_outcome_path.exists() else {}
    if not send_start:
        result = {
            **execution_meta,
            "specHash": spec_record(spec)["specHash"],
            "family": spec.family,
            "ordinal": spec.ordinal,
            "chatId": spec.chat_id,
            "activePresetId": intent.get("activePresetId"),
            "mode": spec.mode,
            "controlName": spec.control_name,
            "attempt": spec.attempt,
            "variant": spec.variant,
            "countsTowardPrimary": spec.counts_toward_primary,
            "prompt": prompt,
            "nonce": spec.nonce,
            "inputSendOk": False,
            "rpcReturnedOk": False,
            "transportCommitted": False,
            "exchangeComplete": False,
            "userMessageId": None,
            "assistantMessageId": None,
            "assistantContent": None,
            "beforeCount": before_count,
            "afterCount": before_count,
            "interruptedAfterIntentBeforeSend": True,
            "reconciliationPending": False,
            "reconciliationExhausted": True,
            "passed": False,
            "failures": ["attempt stopped after durable intent but before durable send-start; no model request was entered"],
            "finishedAt": now_utc(),
            "artifactDir": str(step_dir),
        }
        return durable_result_once(step_dir / "result.json", result)
    send_identity_mismatches = {
        key: {"expected": intent.get(key), "actual": send_start.get(key)}
        for key in ("specHash", "chatId", "variant", "attempt", "promptSha256")
        if send_start.get(key) != intent.get(key)
    }
    if send_identity_mismatches:
        durable_json(step_dir / "send-start-identity-mismatch.json", send_identity_mismatches)
        raise RuntimeError("Durable send-start does not match its call intent.")
    deadline = time.time() + grace_seconds
    messages_after: list[dict[str, Any]] = []
    user: dict[str, Any] | None = None
    assistant: dict[str, Any] | None = None
    poll = 1
    while True:
        messages_after = all_messages(
            client,
            spec.chat_id,
            step_dir,
            f"reconcile-messages-{poll:03d}.json",
        )
        user, assistant = locate_exchange(messages_after, prompt)
        if assistant is not None or time.time() >= deadline:
            break
        time.sleep(5)
        poll += 1

    after_count = len(messages_after)
    if assistant is None:
        pending = {
            **execution_meta,
            "specHash": spec_record(spec)["specHash"],
            "family": spec.family,
            "ordinal": spec.ordinal,
            "chatId": spec.chat_id,
            "activePresetId": intent.get("activePresetId"),
            "mode": spec.mode,
            "controlName": spec.control_name,
            "attempt": spec.attempt,
            "variant": spec.variant,
            "countsTowardPrimary": spec.counts_toward_primary,
            "prompt": prompt,
            "nonce": spec.nonce,
            "inputSendOk": bool(send_outcome.get("rpcReturnedOk") or user is not None),
            "rpcReturnedOk": bool(send_outcome.get("rpcReturnedOk")),
            "transportCommitted": bool(user and user.get("id") not in before_ids),
            "exchangeComplete": False,
            "userMessageId": user.get("id") if user else None,
            "assistantMessageId": None,
            "assistantContent": None,
            "panelEvidence": initial_result.get("panelEvidence"),
            "ejsRuntimeEvidence": initial_result.get("ejsRuntimeEvidence"),
            "beforeCount": before_count,
            "afterCount": after_count,
            "sendStartedAt": send_start.get("sendStartedAt"),
            "sendFinishedAt": send_outcome.get("sendFinishedAt"),
            "reconciled": True,
            "reconciliationPolls": poll,
            "reconciliationPending": True,
            "reconciliationExhausted": False,
            "requestMayHaveReachedModel": True,
            "passed": False,
            "failures": ["assistant terminal message is not yet observable; retry is forbidden until this send is reconciled"],
            "observedAt": now_utc(),
            "artifactDir": str(step_dir),
        }
        durable_json(step_dir / f"reconciliation-pending-{time.time_ns()}.json", pending)
        return pending
    passed, failures = validate_exchange(reconcile_spec, user, assistant)
    ejs_runtime_evidence = initial_result.get("ejsRuntimeEvidence")
    if spec.mode == "ejs-runtime":
        evidence = ejs_runtime_evidence if isinstance(ejs_runtime_evidence, dict) else {}
        if not evidence and (step_dir / "ejs-runtime-seed-evidence.json").exists():
            evidence = load_json(step_dir / "ejs-runtime-seed-evidence.json")
        if assistant is not None and evidence.get("passed") is not True and evidence.get("runtimeValue"):
            set_current_chat(
                client,
                step_dir / "reconcile-ejs-current-chat",
                spec.chat_id,
                f"reconcile-{run_id}-{spec.key}-{spec.chat_id}",
            )
            evidence = probe_ejs_runtime_after_generation(
                client,
                step_dir / "reconcile-ejs-probe",
                device,
                run_id,
                evidence,
            )
        ejs_runtime_evidence = evidence
        runtime_value = str(evidence.get("runtimeValue") or "")
        assistant_content = str(assistant.get("content") or "") if assistant else ""
        if not runtime_value or runtime_value not in assistant_content:
            failures.append("assistant reply did not include the runtime-only EJS value during reconciliation")
        if evidence.get("passed") is not True:
            failures.append("EJS runtime seed/probe proof was incomplete during reconciliation")
        passed = not failures
    transport_failures: list[str] = []
    baseline_live = normalized_message_snapshot(
        [message for message in messages_after if message.get("id") in before_ids]
    )
    if (
        len(baseline_live) != before_count
        or not before_messages_hash
        or stable_hash(baseline_live) != before_messages_hash
    ):
        transport_failures.append("reconciled pre-send baseline IDs/content hash changed")
    if after_count != before_count + 2:
        transport_failures.append(
            f"reconciled message count changed from {before_count} to {after_count}; expected {before_count + 2}"
        )
    if user is not None and (user.get("id") is None or user.get("id") in before_ids):
        transport_failures.append("reconciled user message has no fresh persistent ID")
    if assistant is not None and (assistant.get("id") is None or assistant.get("id") in before_ids):
        transport_failures.append("reconciled assistant message has no fresh persistent ID")
    failures.extend(transport_failures)
    passed = passed and not transport_failures
    result = {
        **execution_meta,
        "specHash": spec_record(spec)["specHash"],
        "family": spec.family,
        "ordinal": spec.ordinal,
        "chatId": spec.chat_id,
        "activePresetId": initial_result.get("activePresetId"),
        "mode": spec.mode,
        "controlName": spec.control_name,
        "attempt": spec.attempt,
        "variant": spec.variant,
        "countsTowardPrimary": spec.counts_toward_primary,
        "prompt": prompt,
        "nonce": spec.nonce,
        "expected": spec.expected,
        "expectedAny": spec.expected_any,
        "expectedPatterns": spec.expected_patterns,
        "requiredPrefix": spec.required_prefix,
        "orderedMarkers": spec.ordered_markers,
        "expectedAnyMayUseReasoning": spec.expected_any_may_use_reasoning,
        "forbidden": spec.forbidden,
        "inputSendOk": bool(initial_result.get("inputSendOk") or user is not None),
        "rpcReturnedOk": bool(
            send_outcome.get("rpcReturnedOk")
            or initial_result.get("rpcReturnedOk")
            or initial_result.get("inputSendOk")
        ),
        "transportCommitted": bool(user and user.get("id") not in before_ids),
        "exchangeComplete": bool(not transport_failures and user is not None and assistant is not None),
        "userMessageId": user.get("id") if user else None,
        "assistantMessageId": assistant.get("id") if assistant else None,
        "assistantContent": assistant.get("content") if assistant else None,
        "nonceVisible": bool(assistant and spec.nonce in str(assistant.get("content") or "")),
        "assistantReasoningPresent": bool(assistant and assistant.get("reasoning")),
        "panelEvidence": initial_result.get("panelEvidence"),
        "ejsRuntimeEvidence": ejs_runtime_evidence,
        "beforeCount": before_count,
        "afterCount": after_count,
        "sendStartedAt": initial_result.get("sendStartedAt"),
        "sendFinishedAt": initial_result.get("sendFinishedAt"),
        "reconciled": True,
        "reconciliationPolls": poll,
        "reconciliationPending": False,
        "reconciliationExhausted": False,
        "passed": bool(passed),
        "failures": failures,
        "finishedAt": now_utc(),
        "artifactDir": str(step_dir),
    }
    result_path = step_dir / "result.json"
    result = durable_result_once(result_path, result)
    durable_json(
        step_dir / "call-intent-reconciled.json",
        {
            "status": "reconciled",
            "chatId": spec.chat_id,
            "attempt": spec.attempt,
            "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "passed": result["passed"],
            "userMessageId": result["userMessageId"],
            "assistantMessageId": result["assistantMessageId"],
            "finishedAt": result["finishedAt"],
        },
    )
    return result


def summarize(
    results: list[dict[str, Any]],
    execution_meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    matching: list[dict[str, Any]] = []
    rejected_identity = 0
    for result in results:
        if execution_meta and any(result.get(key) != value for key, value in execution_meta.items()):
            rejected_identity += 1
            continue
        matching.append(result)
    primary = [result for result in matching if result.get("countsTowardPrimary")]
    controls = [result for result in matching if not result.get("countsTowardPrimary")]
    family_counts = {
        family: sum(1 for result in primary if result.get("family") == family and result.get("passed"))
        for family in FAMILIES
    }
    user_ids = [result.get("userMessageId") for result in primary if result.get("passed")]
    assistant_ids = [result.get("assistantMessageId") for result in primary if result.get("passed")]
    return {
        "primaryAttempted": len(primary),
        "primaryPassed": sum(1 for result in primary if result.get("passed")),
        "familyPassedCounts": family_counts,
        "controlsAttempted": len(controls),
        "controlsPassed": sum(1 for result in controls if result.get("passed")),
        "rejectedIdentityResults": rejected_identity,
        "uniquePrimaryUserMessages": len({value for value in user_ids if value is not None}),
        "uniquePrimaryAssistantMessages": len({value for value in assistant_ids if value is not None}),
        "failed": [
            {"family": result.get("family"), "ordinal": result.get("ordinal"), "control": result.get("controlName"), "failures": result.get("failures")}
            for result in matching
            if not result.get("passed")
        ],
    }


def validate_ejs_runtime(results: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    family_results = sorted(
        (
            result
            for result in results
            if result.get("family") == "macro-ejs" and result.get("countsTowardPrimary")
        ),
        key=lambda result: int(result.get("ordinal") or 0),
    )
    tokens: list[str] = []
    before_counts: list[int] = []
    after_counts: list[int] = []
    deltas: list[int] = []
    errors: list[str] = []
    for result in family_results:
        ordinal = result.get("ordinal")
        evidence = result.get("ejsRuntimeEvidence")
        if not isinstance(evidence, dict):
            errors.append(f"macro-ejs ordinal {ordinal} has no runtime seed/probe evidence")
            continue
        token = str(evidence.get("runtimeValue") or "")
        probe_token = str(evidence.get("probeValue") or "")
        before = int(evidence.get("beforeRenderCount") or 0)
        after = int(evidence.get("afterRenderCount") or 0)
        tokens.append(token)
        before_counts.append(before)
        after_counts.append(after)
        deltas.append(after - before)
        if not token.startswith(f"EJS_RUNTIME_{run_id}_"):
            errors.append(f"macro-ejs ordinal {ordinal} has an invalid runtime token identity")
        if token != probe_token:
            errors.append(f"macro-ejs ordinal {ordinal} seed/probe token mismatch")
        if token in str(result.get("prompt") or ""):
            errors.append(f"macro-ejs ordinal {ordinal} leaked the runtime token into the user prompt")
        if evidence.get("runtimeValueAbsentFromPrompt") is not True:
            errors.append(f"macro-ejs ordinal {ordinal} did not prove prompt token absence")
        if evidence.get("runtimeValueAbsentFromPreSendMessages") is not True:
            errors.append(f"macro-ejs ordinal {ordinal} did not prove pre-send history token absence")
        if evidence.get("runtimeValueAbsentFromSources") is not True or evidence.get("sourceLeaks"):
            errors.append(f"macro-ejs ordinal {ordinal} leaked the runtime token into static source")
        if token not in str(result.get("assistantContent") or ""):
            errors.append(f"macro-ejs ordinal {ordinal} model reply omitted the runtime-only token")
        if after <= before or int(evidence.get("counterDelta") or 0) <= 0:
            errors.append(f"macro-ejs ordinal {ordinal} counter did not increase: {before}->{after}")
        if evidence.get("passed") is not True:
            errors.append(f"macro-ejs ordinal {ordinal} runtime proof is not marked passed")
    chat_ids = [int(result.get("chatId") or 0) for result in family_results]
    if len(set(chat_ids)) != len(chat_ids):
        errors.append("macro-ejs runtime calls did not use five independent chats")
    if len(tokens) == 5 and len(set(tokens)) != 5:
        errors.append("macro-ejs runtime tokens were not unique across five calls")
    passed = len(family_results) == 5 and len(tokens) == 5 and not errors
    return {
        "tokens": tokens,
        "beforeCounts": before_counts,
        "afterCounts": after_counts,
        "counterDeltas": deltas,
        "chatIds": chat_ids,
        "errors": errors,
        "passed": passed,
    }


def restore_original_chat(
    client: TavoMcp,
    artifact_dir: Path,
    original_chat_id: int | None,
    epoch_id: str,
) -> bool:
    if not original_chat_id:
        atomic_json(artifact_dir / "restore-original-chat.json", {"skipped": True, "reason": "no original chat id"})
        return True
    request_id = f"semantic-restore-{safe_name(epoch_id)}-{original_chat_id}"
    restored = client.tool(
        "tavo_current_chat_set",
        {"id": int(original_chat_id), "dryRun": False, "clientRequestId": request_id},
    )
    readback = client.tool("tavo_current_chat_get", {})
    current_payload = response_payload(readback).get("chat")
    current_chat = current_payload if isinstance(current_payload, dict) else {}
    passed = bool(
        ok_response(restored)
        and ok_response(readback)
        and int(current_chat.get("id") or 0) == int(original_chat_id)
    )
    atomic_json(
        artifact_dir / "restore-original-chat.json",
        {
            "requestId": request_id,
            "targetChatId": int(original_chat_id),
            "setResponse": restored,
            "readbackResponse": readback,
            "passed": passed,
        },
    )
    return passed


def validate_ui_preflight(
    semantic_artifact: Path,
    epoch_id: str,
    script_hash: str,
) -> tuple[dict[str, Any], str]:
    preflight_dir = semantic_artifact / "ui-preflight"
    preflight_manifest = load_json(preflight_dir / "run-manifest.json")
    results = load_json(preflight_dir / "results.json")
    if (
        preflight_manifest.get("status") != "passed"
        or preflight_manifest.get("countsTowardKpi") is not False
        or preflight_manifest.get("modelRequestsSent") != 0
        or preflight_manifest.get("actionsPassed") != 17
        or preflight_manifest.get("pluginIsolationPassed") is not True
        or preflight_manifest.get("pluginsRestored") is not True
        or preflight_manifest.get("restoredOriginalChat") is not True
        or preflight_manifest.get("epochId") != epoch_id
        or preflight_manifest.get("semanticRunnerBundleHash") != script_hash
    ):
        raise RuntimeError("The mandatory non-counting UI preflight manifest is missing, failed, or belongs to another epoch.")
    if not isinstance(results, list) or len(results) != 17:
        raise RuntimeError("The mandatory UI preflight does not contain exactly 17 action results.")
    isolation_result = load_json(preflight_dir / "plugin-isolation" / "isolation-result.json")
    restore_result = load_json(
        preflight_dir / "plugin-isolation" / "restore-preflight-complete" / "result.json"
    )
    settle_result = load_json(
        preflight_dir / "plugin-isolation" / "webview-settle" / "settle-result.json"
    )
    if (
        isolation_result.get("passed") is not True
        or int(isolation_result.get("pluginCount") or 0) < 1
        or int(isolation_result.get("disabledCount") or 0) < 1
        or restore_result.get("passed") is not True
        or restore_result.get("runtimeContributionsHash")
        != restore_result.get("expectedRuntimeContributionsHash")
        or settle_result.get("passed") is not True
    ):
        raise RuntimeError("UI preflight plugin isolation/restoration evidence is incomplete or failed.")
    expected = {
        (family, ordinal)
        for family in ("tavojs-variable", "advanced-rendering", "plugin-action-panel")
        for ordinal in range(1, 6)
    }
    expected.update({("ejs-plugin-runtime", 1), ("ejs-plugin-runtime", 2)})
    actual = {(str(result.get("family")), int(result.get("ordinal") or 0)) for result in results if isinstance(result, dict)}
    if actual != expected or any(result.get("passed") is not True for result in results if isinstance(result, dict)):
        raise RuntimeError("The mandatory UI preflight has missing, duplicate, or failed action results.")
    if list(preflight_dir.rglob("input-send.json")):
        raise RuntimeError("UI preflight contains a model-send artifact and cannot remain non-counting.")
    for result in results:
        family = str(result["family"])
        ordinal = int(result["ordinal"])
        action = safe_name(str(result["action"]).lower())
        step_dir = preflight_dir / family / f"{ordinal:02d}-{action}"
        before_runtime = load_json(step_dir / "runtime-invariant-before-ui-action-result.json")
        after_runtime = load_json(step_dir / "runtime-invariant-after-ui-action-result.json")
        if before_runtime.get("passed") is not True or after_runtime.get("passed") is not True:
            raise RuntimeError(f"UI preflight runtime isolation invariant failed for {family} action {ordinal}.")
        before_dir = step_dir / "before-click"
        before_screen = before_dir / "screen.png"
        before_manifest = before_dir / "capture.json"
        if not before_screen.exists() or before_screen.stat().st_size < 1024 or not before_manifest.exists():
            raise RuntimeError(f"UI preflight before-click screen evidence is incomplete for {family} action {ordinal}.")
        after_dir = step_dir / "after-click"
        after_screen = after_dir / "screen.png"
        after_ui = after_dir / "ui.xml"
        if not after_screen.exists() or after_screen.stat().st_size < 1024 or not after_ui.exists() or after_ui.stat().st_size < 100:
            raise RuntimeError(f"UI preflight after-click evidence is incomplete for {family} action {ordinal}.")
        panel_evidence = result.get("panelEvidence")
        if family in {"tavojs-variable", "advanced-rendering"}:
            if not isinstance(panel_evidence, dict) or int(panel_evidence.get("id") or 0) < 1:
                raise RuntimeError(f"AR preflight lacks a live-appended panel for {family} action {ordinal}.")
            locator_xml = [path for path in step_dir.rglob("ui-ar-*.xml") if path.stat().st_size >= 100]
            tap_targets = list(step_dir.rglob("tap-ar-target.json"))
            if not locator_xml or not tap_targets:
                raise RuntimeError(f"AR preflight lacks locator/tap evidence for {family} action {ordinal}.")
        elif panel_evidence is not None:
            raise RuntimeError(f"Plugin preflight unexpectedly claims an AR panel for action {ordinal}.")
        elif not list(step_dir.rglob("ui-before-plus.xml")) or not list(step_dir.rglob("tap-plugin-action.json")):
            raise RuntimeError(f"Plugin preflight lacks menu locator/tap evidence for action {ordinal}.")
    evidence_hash = str(file_info(preflight_dir)["sha256"])
    return {"manifest": preflight_manifest, "results": results}, evidence_hash


def recover_unfinished_runtime_phases(
    client: TavoMcp,
    manifest: dict[str, Any],
    artifact_dir: Path,
    device: str,
) -> None:
    phases = list(manifest.get("runtimePhases") or [])
    changed = False
    for phase in phases:
        if phase.get("status") not in {"running", "recovery_required"}:
            continue
        phase_dir = Path(str(phase.get("path") or "")).expanduser().resolve()
        if not phase_dir.is_relative_to(artifact_dir):
            raise RuntimeError("Unfinished runtime phase path escaped the immutable artifact directory.")
        plugin_root = phase_dir / "plugin-isolation"
        preset_root = phase_dir / "active-preset-runtime"
        plugins_restored = True
        preset_restored = True
        if (plugin_root / "snapshot" / "snapshot.json").exists():
            plugins_restored = recover_plugin_runtime(client, plugin_root, "hard-crash-resume")
        if (preset_root / "snapshot.json").exists():
            preset_restored = recover_active_preset_runtime(client, preset_root, "hard-crash-resume")
        chat_restored = restore_original_chat(
            client,
            phase_dir / "hard-crash-recovery",
            int(manifest["originalChatId"]) if manifest.get("originalChatId") else None,
            f"{manifest.get('epochId')}-hard-crash-resume",
        )
        settle_plugin_runtime_ui(
            device,
            phase_dir / "hard-crash-recovery" / "webview-settle",
            "hard-crash-resume",
        )
        if not plugins_restored or not preset_restored or not chat_restored:
            raise RuntimeError("Could not restore an unfinished phone runtime phase before resume.")
        phase.update(
            {
                "status": "hard-crash-restored",
                "finishedAt": now_utc(),
                "pluginsRestored": plugins_restored,
                "activePresetRestored": preset_restored,
                "chatRestored": chat_restored,
            }
        )
        changed = True
    if changed:
        manifest["runtimePhases"] = phases
        atomic_json(artifact_dir / "run-manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 50 direct semantic Tavo model calls plus negative controls.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", default="")
    parser.add_argument("--import-artifact", required=True)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--per-call-timeout", type=int, default=240)
    args = parser.parse_args()

    if not args.resume and not args.prepare_only:
        print("A new semantic epoch must begin with --prepare-only, then pass UI preflight before --resume.", file=sys.stderr)
        return 2
    if args.resume and args.prepare_only:
        print("--prepare-only and --resume are separate phases and cannot be combined.", file=sys.stderr)
        return 2

    try:
        device_identity = require_device_identity(args.device)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2
    device_hash = stable_hash(device_identity)

    import_artifact = Path(args.import_artifact).expanduser().resolve()
    import_manifest = load_json(import_artifact / "run-manifest.json")
    if import_manifest.get("status") != "passed" or import_manifest.get("countsTowardKpi") is not True:
        print("--import-artifact must be a passing strict import KPI artifact.", file=sys.stderr)
        return 2
    import_manifest_hash = sha256(import_artifact / "run-manifest.json")
    import_evidence_hash = str(file_info(import_artifact)["sha256"])

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = (
        Path(args.artifact_dir).expanduser().resolve()
        if args.artifact_dir
        else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{stamp}-semantic-model-kpi"
    )
    manifest_path = artifact_dir / "run-manifest.json"
    if artifact_dir.exists() and any(artifact_dir.iterdir()) and not args.resume:
        print("Artifact directory already exists and is non-empty; pass --resume.", file=sys.stderr)
        return 2
    if args.resume and not manifest_path.exists():
        print("--resume requires an existing run-manifest.json.", file=sys.stderr)
        return 2
    artifact_dir.mkdir(parents=True, exist_ok=True)

    lock_handle = (artifact_dir / ".run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another semantic KPI process is already using this artifact directory.", file=sys.stderr)
        return 2
    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(f"pid={os.getpid()} started={now_utc()}\n")
    lock_handle.flush()

    bundle_records = runner_bundle_records()
    script_hash = stable_hash(bundle_records)
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if manifest.get("status") in {"failed", "invalid", "passed"}:
            print("A failed, invalid, or passed semantic epoch is immutable; start a new artifact directory.", file=sys.stderr)
            return 2
        if manifest.get("scriptHash") != script_hash:
            print("The semantic runner bundle changed since this epoch started; start a new artifact directory.", file=sys.stderr)
            return 2
        if manifest.get("deviceHash") != device_hash or manifest.get("deviceIdentity") != device_identity:
            print("The phone or Tavo app identity changed since this epoch started; start a new artifact directory.", file=sys.stderr)
            return 2
        if manifest.get("importManifestHash") != import_manifest_hash:
            print("The strict import evidence changed since this epoch started; start a new artifact directory.", file=sys.stderr)
            return 2
        if manifest.get("importEvidenceHash") != import_evidence_hash:
            print("The strict import evidence directory changed since this epoch started; start a new artifact directory.", file=sys.stderr)
            return 2
        run_id = str(manifest["runId"])
        epoch_id = str(manifest["epochId"])
    else:
        run_id = f"SV{stamp.replace('-', '')}"
        epoch_id = f"EPOCH-{secrets.token_hex(12)}"
        manifest = {
            "case": "strict-semantic-model-kpi",
            "status": "running",
            "startedAt": now_utc(),
            "runId": run_id,
            "epochId": epoch_id,
            "scriptHash": script_hash,
            "runnerBundle": bundle_records,
            "importArtifact": str(import_artifact),
            "importManifestHash": import_manifest_hash,
            "importEvidenceHash": import_evidence_hash,
            "deviceIdentity": device_identity,
            "deviceHash": device_hash,
            "targets": {"primaryCalls": PRIMARY_TARGET, "callsPerFamily": CALLS_PER_FAMILY, "families": FAMILIES, "negativeControls": CONTROL_TARGET},
            "countingContract": "Only direct calls matching epoch, script, plan, context, and spec hashes count. Every call needs an exact stored user prompt, two fresh persistent message IDs, and family-specific semantic assertions. Nonce echo is diagnostic only; fallback is forbidden.",
            "retention": "leave-in-place",
            "countsTowardKpi": False,
        }
        atomic_json(manifest_path, manifest)

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found.", file=sys.stderr)
        return 2
    global_lock_handle, global_lock_identity = acquire_phone_runtime_lock(args.device, url)
    client = TavoMcp(url, auth)
    events = artifact_dir / "events.jsonl"
    results: list[dict[str, Any]] = []
    attempt_results: list[dict[str, Any]] = []
    execution_meta: dict[str, str] | None = None
    registry: dict[str, Any] | None = None
    plugin_isolation: dict[str, Any] | None = None
    plugins_restored = True
    active_preset_state: dict[str, Any] | None = None
    active_preset_restored = True
    runtime_phase_dir: Path | None = None
    active_preset_dir: Path | None = None
    try:
        if args.resume:
            recover_unfinished_runtime_phases(client, manifest, artifact_dir, args.device)
        manifest.update({"status": "running", "resumedAt": now_utc() if args.resume else None, "countsTowardKpi": False, "globalRuntimeLockIdentity": global_lock_identity})
        atomic_json(manifest_path, manifest)
        if not (artifact_dir / "phone-before").exists():
            if capture_phone(args.device, artifact_dir, "phone-before") != 0:
                raise RuntimeError("phone-before capture failed")
        if args.resume and manifest.get("setupComplete") is not True:
            raise RuntimeError(
                "This epoch stopped before setup was durably completed; start a new prepare-only epoch instead of replaying setup."
            )
        surface_dir = artifact_dir
        if args.resume:
            surface_stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            surface_dir = artifact_dir / "resume-surface" / f"{surface_stamp}-{os.getpid()}"
            surface_dir.mkdir(parents=True, exist_ok=False)
        mcp_surface_identity, mcp_surface_hash = read_mcp_surface_identity(client, surface_dir)
        if manifest.get("mcpSurfaceHash") and manifest.get("mcpSurfaceHash") != mcp_surface_hash:
            raise RuntimeError("MCP server, tools, resources, or schemas changed within this epoch; start a new artifact directory.")
        registry_path = artifact_dir / "context-registry.json"
        if args.resume:
            if not registry_path.exists():
                raise RuntimeError("Prepared epoch has no frozen context-registry.json.")
            registry = load_json(registry_path)
            if not isinstance(registry, dict):
                raise RuntimeError("Frozen context registry is not a JSON object.")
            frozen_context_hash = stable_hash(context_identity(registry))
            if frozen_context_hash != manifest.get("contextHash"):
                raise RuntimeError("Frozen context registry hash changed before resume.")
            live_verification = verify_frozen_context_live(
                client,
                artifact_dir,
                import_artifact,
                registry,
            )
            resume_verifications = list(manifest.get("resumeVerifications") or [])
            resume_verifications.append(live_verification)
            manifest["resumeVerifications"] = resume_verifications
            atomic_json(manifest_path, manifest)
        else:
            registry = prepare_contexts(client, artifact_dir, import_artifact, run_id)
            if registry.get("originalChatId"):
                manifest["originalChatId"] = int(registry["originalChatId"])
            atomic_json(registry_path, registry)
        if manifest.get("originalChatId"):
            registry["originalChatId"] = int(manifest["originalChatId"])
        context_hash = stable_hash(context_identity(registry))
        if manifest.get("contextHash") and manifest.get("contextHash") != context_hash:
            raise RuntimeError("Context identity changed within this epoch; start a new artifact directory.")
        specs = build_specs(registry)
        plan_records = [spec_plan_record(spec) for spec in specs]
        plan_hash = stable_hash(plan_records)
        if manifest.get("planHash") and manifest.get("planHash") != plan_hash:
            raise RuntimeError("Call plan changed within this epoch; start a new artifact directory.")
        plan_path = artifact_dir / "call-plan.json"
        if args.resume:
            if not plan_path.exists() or stable_hash(load_json(plan_path)) != plan_hash:
                raise RuntimeError("Frozen call-plan.json changed before resume.")
        else:
            atomic_json(plan_path, plan_records)
        execution_meta = {
            "epochId": epoch_id,
            "scriptHash": script_hash,
            "planHash": plan_hash,
            "contextHash": context_hash,
            "deviceHash": device_hash,
            "importManifestHash": import_manifest_hash,
            "importEvidenceHash": import_evidence_hash,
            "mcpSurfaceHash": mcp_surface_hash,
        }
        manifest.update(
            {
                "setupComplete": True,
                "contextHash": context_hash,
                "planHash": plan_hash,
                "mcpSurfaceHash": mcp_surface_hash,
                "mcpSurfaceCounts": {
                    "tools": len(mcp_surface_identity["tools"]),
                    "resources": len(mcp_surface_identity["resources"]),
                    "resourceTemplates": len(mcp_surface_identity["resourceTemplates"]),
                    "prompts": len(mcp_surface_identity["prompts"]),
                    "schemas": len(mcp_surface_identity["schemas"]),
                },
                "originalChatId": registry.get("originalChatId"),
            }
        )
        atomic_json(manifest_path, manifest)
        if args.prepare_only:
            manifest.update({"status": "prepared", "countsTowardKpi": False})
            atomic_json(manifest_path, manifest)
            print(f"artifact_dir={artifact_dir}")
            print("status=prepared")
            return 0

        _ui_preflight, ui_preflight_hash = validate_ui_preflight(artifact_dir, epoch_id, script_hash)
        execution_meta["uiPreflightEvidenceHash"] = ui_preflight_hash
        manifest.update(
            {
                "uiPreflightStatus": "passed",
                "uiPreflightEvidenceHash": ui_preflight_hash,
            }
        )
        atomic_json(manifest_path, manifest)

        runtime_phases = list(manifest.get("runtimePhases") or [])
        phase_number = len(runtime_phases) + 1
        runtime_phase_dir = artifact_dir / "runtime-phases" / f"{phase_number:02d}"
        runtime_phase_dir.mkdir(parents=True, exist_ok=False)
        active_preset_dir = runtime_phase_dir / "active-preset-runtime"
        runtime_phases.append(
            {
                "number": phase_number,
                "path": str(runtime_phase_dir),
                "status": "running",
                "startedAt": now_utc(),
            }
        )
        manifest["runtimePhases"] = runtime_phases
        atomic_json(manifest_path, manifest)

        active_preset_state = snapshot_active_preset_runtime(
            client,
            active_preset_dir,
            f"{epoch_id}-phase-{phase_number:02d}",
        )
        plugin_isolation = isolate_plugin_runtime(
            client,
            runtime_phase_dir / "plugin-isolation",
            str(registry["semanticPluginId"]),
            epoch_id + "-all-model-calls",
            str(registry["semanticPlugin"]["readbackHash"]),
        )
        plugins_restored = False
        manifest.update(
            {
                "pluginIsolationPassed": True,
                "isolatedPluginCount": plugin_isolation["result"]["pluginCount"],
                "disabledPluginCount": plugin_isolation["result"]["disabledCount"],
                "pluginsRestored": False,
                "originalActivePresetIds": active_preset_state["activePresetIds"],
                "activePresetRestored": False,
            }
        )
        atomic_json(manifest_path, manifest)
        settle_plugin_runtime_ui(
            args.device,
            runtime_phase_dir / "plugin-isolation" / "webview-settle",
            "all-semantic-model-calls",
        )

        current_ui_family: str | None = None
        for spec in specs:
            if current_ui_family and spec.family not in UI_FAMILIES:
                if capture_phone(args.device, artifact_dir, f"ui-{current_ui_family}-after") != 0:
                    raise RuntimeError(f"Could not capture UI evidence after {current_ui_family}.")
                current_ui_family = None
            if spec.family in UI_FAMILIES and spec.family != current_ui_family:
                if current_ui_family:
                    if capture_phone(args.device, artifact_dir, f"ui-{current_ui_family}-after") != 0:
                        raise RuntimeError(f"Could not capture UI evidence after {current_ui_family}.")
                current_ui_family = spec.family
                if capture_phone(args.device, artifact_dir, f"ui-{current_ui_family}-before") != 0:
                    raise RuntimeError(f"Could not capture UI evidence before {current_ui_family}.")
            append_event(events, {"at": now_utc(), "event": "spec-start", "family": spec.family, "ordinal": spec.ordinal, "control": spec.control_name})
            selected_result: dict[str, Any] | None = None
            last_result: dict[str, Any] | None = None
            for attempt_spec in derive_attempt_specs(spec):
                append_event(
                    events,
                    {
                        "at": now_utc(),
                        "event": "attempt-start",
                        "family": spec.family,
                        "ordinal": spec.ordinal,
                        "control": spec.control_name,
                        "attempt": attempt_spec.attempt,
                        "chatId": attempt_spec.chat_id,
                    },
                )
                try:
                    attempt_result = execute_call(
                        client,
                        artifact_dir,
                        args.device,
                        run_id,
                        attempt_spec,
                        args.per_call_timeout,
                        execution_meta,
                    )
                except Exception as exc:  # noqa: BLE001
                    attempt_result = {
                        **execution_meta,
                        "specHash": spec_record(attempt_spec)["specHash"],
                        "family": attempt_spec.family,
                        "ordinal": attempt_spec.ordinal,
                        "chatId": attempt_spec.chat_id,
                        "mode": attempt_spec.mode,
                        "controlName": attempt_spec.control_name,
                        "attempt": attempt_spec.attempt,
                        "variant": attempt_spec.variant,
                        "countsTowardPrimary": attempt_spec.counts_toward_primary,
                        "prompt": attempt_spec.prompt,
                        "nonce": attempt_spec.nonce,
                        "passed": False,
                        "exchangeComplete": False,
                        "failures": [repr(exc)],
                        "traceback": traceback.format_exc(),
                        "finishedAt": now_utc(),
                    }
                    root = "controls" if not attempt_spec.counts_toward_primary else "model-calls"
                    result_dir = artifact_dir / root / attempt_spec.family / attempt_spec.step_name
                    durable_json(
                        result_dir / f"attempt-exception-{time.time_ns()}.json",
                        attempt_result,
                    )

                transport_complete = bool(
                    attempt_result.get("inputSendOk")
                    and attempt_result.get("userMessageId")
                    and attempt_result.get("assistantMessageId")
                    and int(attempt_result.get("afterCount") or 0)
                    == int(attempt_result.get("beforeCount") or 0) + 2
                )
                if (
                    not attempt_result.get("passed")
                    and not transport_complete
                    and not attempt_result.get("reconciliationExhausted")
                ):
                    attempt_result = reconcile_attempt_result(
                        client,
                        artifact_dir,
                        args.device,
                        run_id,
                        attempt_spec,
                        execution_meta,
                        attempt_result,
                    )
                if attempt_result.get("reconciliationPending") is True:
                    durable_json(
                        artifact_dir / "pending-send.json",
                        {
                            "family": attempt_spec.family,
                            "ordinal": attempt_spec.ordinal,
                            "controlName": attempt_spec.control_name,
                            "attempt": attempt_spec.attempt,
                            "variant": attempt_spec.variant,
                            "chatId": attempt_spec.chat_id,
                            "specHash": attempt_result.get("specHash"),
                            "promptSha256": hashlib.sha256(str(attempt_result.get("prompt") or "").encode("utf-8")).hexdigest(),
                            "userMessageId": attempt_result.get("userMessageId"),
                            "observedAt": attempt_result.get("observedAt"),
                            "reason": attempt_result.get("failures"),
                        },
                    )
                    raise ReconciliationPending(attempt_result)
                root = "controls" if not attempt_spec.counts_toward_primary else "model-calls"
                result_dir = artifact_dir / root / attempt_spec.family / attempt_spec.step_name
                result_path = result_dir / "result.json"
                if result_path.exists():
                    attempt_result = durable_result_once(result_path, attempt_result)
                else:
                    attempt_result = {
                        **attempt_result,
                        "exchangeComplete": False,
                        "reconciliationExhausted": True,
                        "finishedAt": attempt_result.get("finishedAt") or now_utc(),
                        "artifactDir": str(result_dir),
                    }
                    attempt_result = durable_result_once(result_path, attempt_result)
                attempt_results.append(attempt_result)
                atomic_json(artifact_dir / "model-attempt-results.json", attempt_results)
                last_result = attempt_result
                append_event(
                    events,
                    {
                        "at": now_utc(),
                        "event": "attempt-finish",
                        "family": spec.family,
                        "ordinal": spec.ordinal,
                        "control": spec.control_name,
                        "attempt": attempt_spec.attempt,
                        "chatId": attempt_spec.chat_id,
                        "passed": attempt_result.get("passed"),
                    },
                )
                print(
                    "semantic_attempt",
                    spec.family,
                    f"{spec.ordinal:02d}",
                    "control=" + str(spec.control_name or "none"),
                    "attempt=" + attempt_spec.attempt,
                    "passed=" + str(bool(attempt_result.get("passed"))).lower(),
                    flush=True,
                )
                if attempt_result.get("passed"):
                    selected_result = attempt_result
                    break
            if selected_result is None:
                if last_result is None:
                    raise RuntimeError(f"No attempt result was produced for {spec.key}.")
                selected_result = last_result
            results.append(selected_result)
            summary = summarize(results, execution_meta)
            manifest.update(
                {
                    "progress": summary,
                    "lastSpec": spec.key,
                    "attemptsExecuted": len(attempt_results),
                    "countsTowardKpi": False,
                }
            )
            atomic_json(manifest_path, manifest)
            append_event(events, {"at": now_utc(), "event": "spec-finish", "family": spec.family, "ordinal": spec.ordinal, "passed": selected_result.get("passed"), "control": spec.control_name, "selectedAttempt": selected_result.get("attempt")})
            print(
                "semantic_spec",
                spec.family,
                f"{spec.ordinal:02d}",
                "control=" + str(spec.control_name or "none"),
                "passed=" + str(bool(selected_result.get("passed"))).lower(),
                "selected=" + str(selected_result.get("attempt")),
                f"primary={summary['primaryPassed']}/50",
                flush=True,
            )

        if current_ui_family:
            if capture_phone(args.device, artifact_dir, f"ui-{current_ui_family}-after") != 0:
                raise RuntimeError(f"Could not capture final UI evidence after {current_ui_family}.")
        plugins_restored = recover_plugin_runtime(
            client,
            Path(str(plugin_isolation["root"])),
            "all-model-calls-complete",
        )
        if not plugins_restored:
            raise RuntimeError("The original plugin runtime could not be restored exactly after model calls.")
        plugin_isolation = None
        active_preset_restored = recover_active_preset_runtime(
            client,
            active_preset_dir,
            "all-model-calls-complete",
        )
        if not active_preset_restored:
            raise RuntimeError("The original active preset could not be restored after model calls.")
        active_preset_state = None
        settle_plugin_runtime_ui(
            args.device,
            runtime_phase_dir / "plugin-isolation" / "restore-webview-settle",
            "all-plugins-restored",
        )
        runtime_phases[-1].update({"status": "complete", "finishedAt": now_utc(), "pluginsRestored": True, "activePresetRestored": True})
        manifest.update({"pluginsRestored": True, "activePresetRestored": True, "runtimePhases": runtime_phases})
        atomic_json(manifest_path, manifest)
        atomic_json(artifact_dir / "model-results.json", results)
        atomic_json(artifact_dir / "model-attempt-results.json", attempt_results)
        final = summarize(results, execution_meta)
        model_requests_sent = sum(
            1
            for result in attempt_results
            if result.get("inputSendOk") or result.get("userMessageId") is not None
        )
        ejs_runtime = validate_ejs_runtime(results, run_id)
        atomic_json(artifact_dir / "ejs-runtime-validation.json", ejs_runtime)
        passed = (
            final["primaryPassed"] == PRIMARY_TARGET
            and all(final["familyPassedCounts"].get(family) == CALLS_PER_FAMILY for family in FAMILIES)
            and final["uniquePrimaryUserMessages"] == PRIMARY_TARGET
            and final["uniquePrimaryAssistantMessages"] == PRIMARY_TARGET
            and final["controlsPassed"] == CONTROL_TARGET
            and final["rejectedIdentityResults"] == 0
            and ejs_runtime["passed"]
            and plugins_restored
            and active_preset_restored
            and not final["failed"]
        )
        restored_original_chat = restore_original_chat(
            client,
            artifact_dir,
            int(registry["originalChatId"]) if registry.get("originalChatId") else None,
            epoch_id,
        )
        if not restored_original_chat:
            passed = False
        if capture_phone(args.device, artifact_dir, "phone-after") != 0:
            passed = False
        manifest.update(
            {
                "finishedAt": now_utc(),
                "status": "passed" if passed else "failed",
                "countsTowardKpi": passed,
                "progress": final,
                "ejsRuntime": ejs_runtime,
                "restoredOriginalChat": restored_original_chat,
                "pluginsRestored": plugins_restored,
                "activePresetRestored": active_preset_restored,
                "attemptsExecuted": len(attempt_results),
                "modelRequestsSent": model_requests_sent,
                "artifacts": [
                    "context-registry.json",
                    "call-plan.json",
                    "semantic-sources/",
                    "setup/",
                    "model-calls/",
                    "controls/",
                    "runtime-phases/",
                    "model-results.json",
                    "model-attempt-results.json",
                    "events.jsonl",
                    "phone-before/",
                    "phone-after/",
                ],
            }
        )
        atomic_json(manifest_path, manifest)
        print(f"artifact_dir={artifact_dir}")
        print(f"status={manifest['status']}")
        print(f"primary_passed={final['primaryPassed']}")
        print(f"controls_passed={final['controlsPassed']}")
        return 0 if passed else 1
    except ReconciliationPending as exc:
        active_preset_restored_pending = active_preset_restored
        if active_preset_state is not None and active_preset_dir is not None:
            try:
                active_preset_restored_pending = recover_active_preset_runtime(
                    client,
                    active_preset_dir,
                    "pending-send",
                )
            except Exception:  # noqa: BLE001
                active_preset_restored_pending = False
        plugins_restored_pending = plugins_restored
        if plugin_isolation is not None:
            try:
                plugins_restored_pending = recover_plugin_runtime(
                    client,
                    Path(str(plugin_isolation["root"])),
                    "all-model-calls-pending-send",
                )
            except Exception:  # noqa: BLE001
                plugins_restored_pending = False
        chat_restored_pending = False
        if registry and registry.get("originalChatId"):
            try:
                chat_restored_pending = restore_original_chat(
                    client,
                    artifact_dir / "pending-send-recovery",
                    int(registry["originalChatId"]),
                    epoch_id + "-pending-send",
                )
            except Exception:  # noqa: BLE001
                chat_restored_pending = False
        fully_restored_pending = bool(
            active_preset_restored_pending
            and plugins_restored_pending
            and chat_restored_pending
        )
        phase_records = list(manifest.get("runtimePhases") or [])
        if runtime_phase_dir is not None and phase_records:
            phase_records[-1].update(
                {
                    "status": "paused-restored" if fully_restored_pending else "recovery_required",
                    "finishedAt": now_utc(),
                    "activePresetRestored": active_preset_restored_pending,
                    "pluginsRestored": plugins_restored_pending,
                    "chatRestored": chat_restored_pending,
                    "pauseReason": "model-send-reconciliation-pending",
                }
            )
        pending_result = exc.result
        manifest.update(
            {
                "pausedAt": now_utc(),
                "status": "paused" if fully_restored_pending else "recovery_required",
                "countsTowardKpi": False,
                "progress": summarize(results, execution_meta),
                "pauseReason": "model-send-reconciliation-pending",
                "pendingSend": {
                    "family": pending_result.get("family"),
                    "ordinal": pending_result.get("ordinal"),
                    "controlName": pending_result.get("controlName"),
                    "attempt": pending_result.get("attempt"),
                    "variant": pending_result.get("variant"),
                    "chatId": pending_result.get("chatId"),
                    "userMessageId": pending_result.get("userMessageId"),
                    "specHash": pending_result.get("specHash"),
                },
                "activePresetRestoredAfterPendingSend": active_preset_restored_pending,
                "pluginsRestoredAfterPendingSend": plugins_restored_pending,
                "restoredOriginalChatAfterPendingSend": chat_restored_pending,
                "runtimePhases": phase_records,
            }
        )
        atomic_json(manifest_path, manifest)
        append_event(events, {"at": now_utc(), "event": "paused", "reason": "model-send-reconciliation-pending"})
        return 75
    except KeyboardInterrupt:
        active_preset_restored_after_interrupt = active_preset_restored
        if active_preset_state is not None and active_preset_dir is not None:
            try:
                active_preset_restored_after_interrupt = recover_active_preset_runtime(
                    client,
                    active_preset_dir,
                    "interrupt",
                )
            except Exception:  # noqa: BLE001
                active_preset_restored_after_interrupt = False
        plugins_restored_after_interrupt = plugins_restored
        if plugin_isolation is not None:
            try:
                plugins_restored_after_interrupt = recover_plugin_runtime(
                    client,
                    Path(str(plugin_isolation["root"])),
                    "all-model-calls-interrupt",
                )
            except Exception:  # noqa: BLE001
                plugins_restored_after_interrupt = False
        restored_after_interrupt = False
        if registry and registry.get("originalChatId"):
            try:
                restored_after_interrupt = restore_original_chat(
                    client,
                    artifact_dir,
                    int(registry["originalChatId"]),
                    epoch_id + "-interrupt",
                )
            except Exception:  # noqa: BLE001
                restored_after_interrupt = False
        phase_records = list(manifest.get("runtimePhases") or [])
        interrupt_restored = bool(
            active_preset_restored_after_interrupt
            and plugins_restored_after_interrupt
            and restored_after_interrupt
        )
        interrupt_status = "paused" if interrupt_restored else "recovery_required"
        if runtime_phase_dir is not None and phase_records:
            phase_records[-1].update({"status": "paused-restored" if interrupt_restored else "recovery_required", "finishedAt": now_utc(), "activePresetRestored": active_preset_restored_after_interrupt, "pluginsRestored": plugins_restored_after_interrupt, "chatRestored": restored_after_interrupt})
        manifest.update({"pausedAt": now_utc(), "status": interrupt_status, "countsTowardKpi": False, "progress": summarize(results, execution_meta), "pauseReason": "keyboard-interrupt", "activePresetRestoredAfterInterrupt": active_preset_restored_after_interrupt, "pluginsRestoredAfterInterrupt": plugins_restored_after_interrupt, "restoredOriginalChatAfterInterrupt": restored_after_interrupt, "runtimePhases": phase_records})
        atomic_json(manifest_path, manifest)
        append_event(events, {"at": now_utc(), "event": "paused"})
        return 130
    except Exception as exc:  # noqa: BLE001
        active_preset_restored_after_failure = active_preset_restored
        if active_preset_state is not None and active_preset_dir is not None:
            try:
                active_preset_restored_after_failure = recover_active_preset_runtime(
                    client,
                    active_preset_dir,
                    "fatal",
                )
            except Exception:  # noqa: BLE001
                active_preset_restored_after_failure = False
        plugins_restored_after_failure = plugins_restored
        if plugin_isolation is not None:
            try:
                plugins_restored_after_failure = recover_plugin_runtime(
                    client,
                    Path(str(plugin_isolation["root"])),
                    "all-model-calls-fatal",
                )
            except Exception:  # noqa: BLE001
                plugins_restored_after_failure = False
        restored_after_failure = False
        if registry and registry.get("originalChatId"):
            try:
                restored_after_failure = restore_original_chat(
                    client,
                    artifact_dir,
                    int(registry["originalChatId"]),
                    epoch_id + "-fatal",
                )
            except Exception:  # noqa: BLE001
                restored_after_failure = False
        phase_records = list(manifest.get("runtimePhases") or [])
        failure_restored = bool(
            active_preset_restored_after_failure
            and plugins_restored_after_failure
            and restored_after_failure
        )
        failure_status = "failed" if failure_restored else "recovery_required"
        if runtime_phase_dir is not None and phase_records:
            phase_records[-1].update({"status": "fatal-restored" if failure_restored else "recovery_required", "finishedAt": now_utc(), "activePresetRestored": active_preset_restored_after_failure, "pluginsRestored": plugins_restored_after_failure, "chatRestored": restored_after_failure})
        manifest.update({"failedAt": now_utc(), "status": failure_status, "countsTowardKpi": False, "progress": summarize(results, execution_meta), "failure": repr(exc), "activePresetRestoredAfterFailure": active_preset_restored_after_failure, "pluginsRestoredAfterFailure": plugins_restored_after_failure, "restoredOriginalChatAfterFailure": restored_after_failure, "runtimePhases": phase_records})
        atomic_json(manifest_path, manifest)
        atomic_json(artifact_dir / "fatal-exception.json", {"error": repr(exc), "traceback": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
