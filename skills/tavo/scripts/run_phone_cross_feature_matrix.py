#!/usr/bin/env python3
"""Run a retained, cross-feature Tavo matrix against a real Android phone.

The runner is deliberately fail-closed and non-destructive by default:

* Phone-side characters, lorebooks, regexes, presets, chats, messages, and the
  runner plugin are retained as evidence.
* Existing chats, presets, and plugins are never edited. The original current
  chat, active preset, input text, and existing plugin enabled states are
  snapshotted before setup and restored after preparation, completion, failure,
  interruption, or an explicit recovery run.
* Message and TavoJS lorebook deletion are dry-run/tombstone probes unless
  ``--allow-runner-owned-deletes`` is explicitly supplied. Even then, a delete
  is permitted only after the object id and marker are proved to belong to this
  run in the durable ownership ledger.
* Every planned model send has a unique nonce, exact pre/post MCP readbacks, an
  immutable send intent, and strict exchange validation. Failed or ambiguous
  calls never count.

No phone operation occurs without ``--execute``. Use ``--self-check`` or
``--print-plan`` for offline inspection.
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
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
UI_TOOL = ROOT / "scripts" / "tavo_ui_tree.py"
DEFAULT_ENDPOINT = "/tmp/tavo_mcp_endpoint.json"
MIN_MODEL_CALLS = 23
PLANNED_MODEL_CALLS = 35

sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_import_kpi import response_items, response_payload  # noqa: E402
from run_phone_kpi_batch import (  # noqa: E402
    TavoMcp,
    capture_phone,
    load_endpoint,
    ok_response,
    redact,
)


REQUIRED_TOOLS = {
    "tavo_character_create",
    "tavo_character_get",
    "tavo_character_search",
    "tavo_chat_create",
    "tavo_chat_get",
    "tavo_chat_search",
    "tavo_current_chat_get",
    "tavo_current_chat_set",
    "tavo_input_append",
    "tavo_input_clear",
    "tavo_input_get",
    "tavo_input_send",
    "tavo_input_set",
    "tavo_lorebook_create",
    "tavo_lorebook_delete",
    "tavo_lorebook_entry_upsert",
    "tavo_lorebook_get",
    "tavo_lorebook_search",
    "tavo_message_append",
    "tavo_message_count",
    "tavo_message_delete",
    "tavo_message_find",
    "tavo_message_get",
    "tavo_message_update",
    "tavo_plugin_get",
    "tavo_plugin_get_runtime_contributions",
    "tavo_plugin_install",
    "tavo_plugin_package",
    "tavo_plugin_search",
    "tavo_plugin_set_enabled",
    "tavo_plugin_validate_manifest",
    "tavo_preset_create",
    "tavo_preset_get",
    "tavo_preset_search",
    "tavo_preset_set_active",
    "tavo_regex_create",
    "tavo_regex_get",
    "tavo_regex_search",
}

REQUIRED_RESOURCE_URIS = (
    "tavo://runtime",
    "tavo://docs/tavojs",
    "tavo://docs/plugins",
    "tavo://docs/write-safety",
    "tavo://schemas/character",
    "tavo://schemas/chat",
    "tavo://schemas/lorebook",
    "tavo://schemas/lorebook-entry",
    "tavo://schemas/message",
    "tavo://schemas/preset",
    "tavo://schemas/regex",
    "tavo://schemas/regex-entry",
)

MODEL_FAMILIES = (
    "regex-worldbook",
    "worldbook-activation",
    "worldbook-lifecycle",
    "worldbook-position",
    "character-greetings",
    "preset-depth",
    "input-transport",
    "message-ops",
    "plugin-tavojs-lorebook",
    "thread-tavojs-readback",
)

CASE_DEPENDENCY_GROUPS = (
    ("regex-lorebook-enabled", "regex-lorebook-control"),
    ("worldbook-keyword-hit", "worldbook-keyword-miss"),
    ("worldbook-secondary-any-hit", "worldbook-secondary-any-miss"),
    ("worldbook-probability-100", "worldbook-probability-0"),
    ("worldbook-scan-depth-in-window", "worldbook-scan-depth-outside-window"),
    ("worldbook-sticky-trigger", "worldbook-sticky-carry", "worldbook-sticky-unactivated-control"),
    ("worldbook-cooldown-trigger", "worldbook-cooldown-blocked", "worldbook-cooldown-expired"),
    ("worldbook-delay-before-threshold", "worldbook-delay-after-threshold"),
    ("preset-absolute-depth-0", "preset-absolute-depth-3"),
)


@dataclass(frozen=True)
class CaseSpec:
    ordinal: int
    key: str
    family: str
    chat_key: str
    nonce: str
    prompt: str
    expected: tuple[str, ...]
    forbidden: tuple[str, ...] = ()
    lorebook_key: str | None = None
    regex_key: str | None = None
    preset_key: str = "base"
    input_mode: str = "standard"
    prelude: str = ""
    greeting_marker: str | None = None
    capture_ui: bool = False
    notes: str = ""

    @property
    def step_name(self) -> str:
        return f"{self.ordinal:02d}-{safe_name(self.key)}"


@dataclass(frozen=True)
class ChatProfile:
    key: str
    lorebook_key: str | None = None
    regex_key: str | None = None
    preset_key: str = "base"


@dataclass
class RuntimeContext:
    client: TavoMcp
    artifact_dir: Path
    device: str
    run_id: str
    allow_deletes: bool
    timeout: int
    registry: dict[str, Any]
    plan_hash: str
    script_hash: str
    ledger: "OwnershipLedger"


class RunnerTransportFailure(RuntimeError):
    """A runner, device, MCP transport, or response-envelope failure."""


class DirectRuntimeBehaviorFailure(RuntimeError):
    """A direct phone/runtime effect failed after the harness reached its target."""

    def __init__(self, component: str, cause: BaseException, axis: dict[str, Any]) -> None:
        super().__init__(f"Direct runtime component {component!r} failed: {cause}")
        self.component = component
        self.cause = cause
        self.axis = axis


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_content_hash(value: dict[str, Any], ignored: tuple[str, ...]) -> str:
    """Hash persisted content while runtime flags/revisions are verified separately."""

    return stable_hash({key: item for key, item in value.items() if key not in ignored})


def payload_mismatches(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Return exact recursive mismatches for every submitted payload field."""

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        errors: list[str] = []
        for key, value in expected.items():
            if key not in actual:
                errors.append(f"{path}.{key}: missing")
            else:
                errors.extend(payload_mismatches(value, actual[key], f"{path}.{key}"))
        return errors
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected array, got {type(actual).__name__}"]
        if len(expected) != len(actual):
            return [f"{path}: expected {len(expected)} items, got {len(actual)}"]
        errors: list[str] = []
        for index, value in enumerate(expected):
            errors.extend(payload_mismatches(value, actual[index], f"{path}[{index}]"))
        return errors
    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def asset_content_payload(kind: str, readback: dict[str, Any]) -> dict[str, Any]:
    """Return the persisted user-authored fields for one MCP asset readback."""

    if kind == "character" and isinstance(readback.get("data"), dict):
        return readback["data"]
    return readback


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def durable_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact(event), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def evidence_axis(
    evaluated: bool,
    failures: list[str] | tuple[str, ...] = (),
    *,
    passed: bool | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    normalized_failures = [str(value) for value in failures]
    if not evaluated:
        resolved_passed = None
    elif passed is None:
        resolved_passed = not normalized_failures
    else:
        resolved_passed = bool(passed)
    return {
        "evaluated": bool(evaluated),
        "passed": resolved_passed,
        "failures": normalized_failures,
        **metadata,
    }


def direct_runtime_axis(
    components: list[dict[str, Any]],
    failures: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    normalized_failures = [str(value) for value in failures]
    evaluated = bool(components or normalized_failures)
    component_failures = [
        f"{item.get('component')}: direct component reported passed=false"
        for item in components
        if item.get("passed") is False
    ]
    return evidence_axis(
        evaluated,
        [*normalized_failures, *component_failures],
        components=components,
    )


def persist_direct_runtime_axis(step_dir: Path, axis: dict[str, Any]) -> None:
    durable_json(step_dir / "direct-runtime-axis.json", {"schemaVersion": "1.1.0", **axis})


def load_direct_runtime_axis(step_dir: Path) -> dict[str, Any]:
    path = step_dir / "direct-runtime-axis.json"
    if not path.exists():
        return direct_runtime_axis([])
    value = load_json(path)
    return evidence_axis(
        bool(value.get("evaluated")),
        list(value.get("failures") or []),
        passed=value.get("passed") if isinstance(value.get("passed"), bool) else None,
        components=list(value.get("components") or []),
    )


def run_direct_component(
    step_dir: Path,
    components: list[dict[str, Any]],
    component: str,
    callback: Callable[[], Any],
) -> Any:
    try:
        result = callback()
        if isinstance(result, dict) and result.get("passed") is False:
            raise RuntimeError(f"{component} returned passed=false")
    except RunnerTransportFailure:
        raise
    except Exception as exc:
        failure = f"{component}: {exc!r}"
        axis = direct_runtime_axis(components, [failure])
        persist_direct_runtime_axis(step_dir, axis)
        raise DirectRuntimeBehaviorFailure(component, exc, axis) from exc
    record = {
        "component": component,
        "passed": True,
        "result": result if isinstance(result, dict) else {"value": result},
    }
    components.append(record)
    persist_direct_runtime_axis(step_dir, direct_runtime_axis(components))
    return result


def mcp_tool(
    client: TavoMcp,
    output: Path,
    name: str,
    arguments: dict[str, Any],
    timeout: int = 180,
) -> dict[str, Any]:
    try:
        response = client.tool(name, arguments, timeout=timeout)
    except Exception as exc:
        durable_json(
            output.with_name(output.stem + "-exception.json"),
            {"tool": name, "arguments": arguments, "error": repr(exc), "traceback": traceback.format_exc()},
        )
        raise RunnerTransportFailure(f"MCP tool transport failed for {name}: {exc}") from exc
    durable_json(output, response)
    return response


def mcp_rpc(
    client: TavoMcp,
    output: Path,
    method: str,
    params: dict[str, Any],
    timeout: int = 180,
) -> dict[str, Any]:
    try:
        response = client.rpc(method, params, timeout=timeout)
    except Exception as exc:
        durable_json(
            output.with_name(output.stem + "-exception.json"),
            {"method": method, "params": params, "error": repr(exc), "traceback": traceback.format_exc()},
        )
        raise RunnerTransportFailure(f"MCP RPC transport failed for {method}: {exc}") from exc
    durable_json(output, response)
    return response


def object_id(response: dict[str, Any]) -> int:
    payload = response_payload(response)
    candidates: list[Any] = [payload.get("id")]
    for key in ("character", "chat", "lorebook", "preset", "regex", "message"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("id"))
    for candidate in candidates:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
        if isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
            return int(candidate)
    return 0


def marker(run_id: str, key: str) -> str:
    run_part = re.sub(r"[^A-Za-z0-9]", "", run_id).upper()[-18:]
    key_part = re.sub(r"[^A-Za-z0-9]", "_", key).upper()[:28]
    digest = hashlib.sha256(f"{run_id}:{key}".encode("utf-8")).hexdigest()[:10].upper()
    return f"CFM_{run_part}_{key_part}_{digest}"


def trigger(run_id: str, key: str) -> str:
    digest = hashlib.sha256(f"trigger:{run_id}:{key}".encode("utf-8")).hexdigest()[:12].upper()
    return f"gate-{safe_name(key)}-{digest}"


def nonce_for(run_id: str, ordinal: int, key: str) -> str:
    digest = hashlib.sha256(f"nonce:{run_id}:{ordinal}:{key}".encode("utf-8")).hexdigest()[:16].upper()
    return f"CFM_NONCE_{ordinal:02d}_{digest}"


def nonce_prompt(nonce: str, request: str) -> str:
    return (
        f"The first visible line of your reply must be exactly {nonce}.\n"
        f"{request}\n"
        "Use only supplied context. Do not invent or normalize evidence codes."
    )


def evidence_request(subject: str) -> str:
    return (
        f"Find the exact CFM evidence code supplied by {subject}. "
        "Write that exact code on the second line, then briefly identify its source."
    )


def absent_request(subject: str, sentinel: str) -> str:
    return (
        f"Check whether {subject} supplied a CFM evidence code for this turn. "
        f"If it did not, write exactly {sentinel} on the second line. Do not copy codes from unrelated history."
    )


def all_markers(run_id: str, allow_deletes: bool) -> dict[str, str]:
    keys = (
        "regex-raw",
        "regex-transformed",
        "constant",
        "keyword",
        "secondary",
        "probability-100",
        "probability-0",
        "scan-depth",
        "sticky-a",
        "sticky-b",
        "cooldown-a",
        "cooldown-b",
        "delay",
        "position-before",
        "position-after",
        "position-top-example",
        "position-bottom-example",
        "position-depth-system",
        "position-depth-assistant",
        "greeting-first",
        "greeting-alt-a",
        "greeting-alt-b",
        "message-example",
        "preset-depth-0",
        "preset-depth-3",
        "input-challenge",
        "message-original",
        "message-updated",
        "message-delete-retained",
        "message-delete-confirmed",
        "crud-created",
        "crud-updated",
        "crud-tombstone",
        "crud-delete-confirmed",
        "thread-a",
        "thread-b",
        "thread-summary",
    )
    values = {key: marker(run_id, key) for key in keys}
    values["message-delete-final"] = values[
        "message-delete-confirmed" if allow_deletes else "message-delete-retained"
    ]
    values["crud-delete-final"] = values[
        "crud-delete-confirmed" if allow_deletes else "crud-tombstone"
    ]
    return values


def lorebook_entry(
    run_id: str,
    key: str,
    content_marker: str,
    *,
    strategy: str = "keyword",
    keywords: list[str] | None = None,
    secondary_keywords: list[str] | None = None,
    secondary_strategy: str = "none",
    scan_depth: int = 10,
    probability: int = 100,
    sticky: int = 0,
    cooldown: int = 0,
    delay: int = 0,
    position: str = "lorebookBefore",
    depth: int = 0,
    role: str = "system",
) -> dict[str, Any]:
    return {
        "identifier": f"cfm-{safe_name(run_id)}-{safe_name(key)}",
        "name": f"CFM {key}",
        "content": (
            f"Cross-feature evidence code: {content_marker}. "
            "When asked for the current matrix evidence code, reproduce it exactly."
        ),
        "strategy": strategy,
        "injectionPosition": position,
        "injectionDepth": depth,
        "injectionRole": role,
        "keywords": keywords or [],
        "secondaryKeywords": secondary_keywords or [],
        "secondaryKeywordStrategy": secondary_strategy,
        "scanDepth": scan_depth,
        "caseSensitive": False,
        "matchWholeWord": False,
        "probability": probability,
        "sticky": sticky,
        "cooldown": cooldown,
        "delay": delay,
        "enabled": True,
    }


def lorebook_definitions(run_id: str, markers: dict[str, str]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}

    def add(key: str, entry: dict[str, Any]) -> None:
        definitions[key] = {
            "name": f"Codex CFM {run_id} Lore {key}",
            "entries": [entry],
        }

    add(
        "regex",
        lorebook_entry(
            run_id,
            "regex",
            markers["regex-raw"],
            keywords=[trigger(run_id, "regex")],
        ),
    )
    add("constant", lorebook_entry(run_id, "constant", markers["constant"], strategy="constant"))
    add(
        "keyword",
        lorebook_entry(
            run_id,
            "keyword",
            markers["keyword"],
            keywords=[trigger(run_id, "keyword")],
        ),
    )
    add(
        "secondary",
        lorebook_entry(
            run_id,
            "secondary",
            markers["secondary"],
            keywords=[trigger(run_id, "secondary-main")],
            secondary_keywords=[trigger(run_id, "secondary-a"), trigger(run_id, "secondary-b")],
            secondary_strategy="andAny",
        ),
    )
    add(
        "probability-100",
        lorebook_entry(
            run_id,
            "probability-100",
            markers["probability-100"],
            keywords=[trigger(run_id, "probability-100")],
            probability=100,
        ),
    )
    add(
        "probability-0",
        lorebook_entry(
            run_id,
            "probability-0",
            markers["probability-0"],
            keywords=[trigger(run_id, "probability-0")],
            probability=0,
        ),
    )
    add(
        "scan",
        lorebook_entry(
            run_id,
            "scan",
            markers["scan-depth"],
            keywords=[trigger(run_id, "scan")],
            scan_depth=2,
        ),
    )
    add(
        "sticky",
        lorebook_entry(
            run_id,
            "sticky",
            markers["sticky-a"],
            keywords=[trigger(run_id, "sticky")],
            scan_depth=2,
            sticky=6,
        ),
    )
    add(
        "cooldown",
        lorebook_entry(
            run_id,
            "cooldown",
            markers["cooldown-a"],
            keywords=[trigger(run_id, "cooldown")],
            cooldown=2,
        ),
    )
    add(
        "delay",
        lorebook_entry(
            run_id,
            "delay",
            markers["delay"],
            keywords=[trigger(run_id, "delay")],
            delay=1,
        ),
    )
    position_specs = (
        ("position-before", "lorebookBefore", 0, "system"),
        ("position-after", "lorebookAfter", 0, "system"),
        ("position-top", "topOfExampleMessages", 0, "system"),
        ("position-bottom", "bottomOfExampleMessages", 0, "system"),
        ("position-depth-system", "atDepth", 3, "system"),
        ("position-depth-assistant", "atDepth", 1, "assistant"),
    )
    marker_keys = {
        "position-top": "position-top-example",
        "position-bottom": "position-bottom-example",
    }
    for key, position, depth, role in position_specs:
        marker_key = marker_keys.get(key, key)
        add(
            key,
            lorebook_entry(
                run_id,
                key,
                markers[marker_key],
                strategy="constant",
                position=position,
                depth=depth,
                role=role,
            ),
        )
    return definitions


def regex_definitions(run_id: str, markers: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        "lorebook-transform": {
            "name": f"Codex CFM {run_id} Regex Lorebook Transform",
            "entries": [
                {
                    "identifier": f"cfm-{safe_name(run_id)}-regex-lorebook-transform",
                    "name": "Transform retained lorebook evidence before model send",
                    "findRegex": markers["regex-raw"],
                    "replaceString": markers["regex-transformed"],
                    "trimStrings": [],
                    "placements": ["lorebook"],
                    "timing": "send",
                    "substitution": "none",
                    "minDepth": None,
                    "maxDepth": None,
                    "enabled": True,
                }
            ],
        }
    }


def base_preset(run_id: str) -> dict[str, Any]:
    marker_entries = [
        ("worldInfoBefore", "Lorebook Before"),
        ("personaDescription", "Persona Description"),
        ("charDescription", "Character Description"),
        ("charPersonality", "Character Personality"),
        ("scenario", "Scenario"),
        ("worldInfoAfter", "Lorebook After"),
        ("dialogueExamples", "Dialogue Examples"),
        ("chatHistory", "Chat History"),
    ]
    entries: list[dict[str, Any]] = [
        {
            "identifier": f"cfm-main-{safe_name(run_id)}",
            "name": "CFM Main",
            "content": (
                "Answer the current request directly. Preserve exact literal ASCII evidence codes when they are "
                "present in supplied context. Never invent a CFM code that is absent from context."
            ),
            "enabled": True,
            "active": True,
            "type": "custom",
            "role": "system",
            "injectionPosition": "relative",
            "injectionDepth": 0,
            "forbidOverrides": True,
        }
    ]
    entries.extend(
        {
            "identifier": identifier,
            "name": name,
            "enabled": True,
            "active": True,
            "type": "marker",
        }
        for identifier, name in marker_entries
    )
    return {
        "name": f"Codex CFM {run_id} Preset Base",
        "active": False,
        "official": False,
        "basicPrompts": {
            "persona": "{{persona}}",
            "description": "{{description}}",
            "personality": "{{personality}}",
            "scenario": "{{scenario}}",
            "exampleMessageStart": "[Example dialogue]",
            "chatStart": "[Start of current chat]",
            "groupChatStart": "[Start of current group chat: {{group}}]",
            "groupNudge": "[Write the next reply only as {{char}}.]",
            "continueNudge": "[Continue without repeating.]",
            "impersonation": "[Write from {{user}}'s point of view.]",
            "lorebook": "{0}",
        },
        "entries": entries,
    }


def preset_definitions(run_id: str, markers: dict[str, str]) -> dict[str, dict[str, Any]]:
    base = base_preset(run_id)
    definitions = {"base": base}
    for key, depth, marker_key in (
        ("absolute-0", 0, "preset-depth-0"),
        ("absolute-3", 3, "preset-depth-3"),
    ):
        payload = json.loads(json.dumps(base, ensure_ascii=False))
        payload["name"] = f"Codex CFM {run_id} Preset {key}"
        payload["entries"].append(
            {
                "identifier": f"cfm-{safe_name(run_id)}-{key}",
                "name": f"CFM {key}",
                "content": (
                    f"Absolute-depth evidence code: {markers[marker_key]}. "
                    "Reproduce this code exactly when the user asks for preset evidence."
                ),
                "enabled": True,
                "active": True,
                "type": "custom",
                "role": "system",
                "injectionPosition": "absolute",
                "injectionDepth": depth,
                "forbidOverrides": True,
            }
        )
        definitions[key] = payload
    return definitions


def character_definition(run_id: str, markers: dict[str, str]) -> dict[str, Any]:
    return {
        "name": f"Codex CFM Character {run_id}",
        "description": (
            "{{char}} is a careful evidence auditor. The character separates observations from guesses and "
            "preserves exact machine-readable codes when asked."
        ),
        "first_mes": f"The audit desk is ready. Greeting evidence: {markers['greeting-first']}",
        "personality": "Precise, calm, concise, and unwilling to invent evidence.",
        "scenario": "{{char}} and {{user}} are validating independent Tavo feature paths on a retained test chat.",
        "mes_example": (
            "<START>\n"
            "{{user}}: Which code proves the example-message path?\n"
            f"{{{{char}}}}: {markers['message-example']}\n"
            "<START>\n"
            "{{user}}: What should happen if evidence is absent?\n"
            "{{char}}: Say that it is absent; do not manufacture a code."
        ),
        "alternate_greetings": [
            f"Alternate greeting A evidence: {markers['greeting-alt-a']}",
            f"Alternate greeting B evidence: {markers['greeting-alt-b']}",
        ],
        "creator_notes": f"Retained cross-feature real-phone evidence for {run_id}.",
        "system_prompt": "Stay in character and preserve exact CFM evidence codes from supplied context.",
        "post_history_instructions": "Honor the current nonce instruction and answer in no more than five lines.",
        "tags": ["codex", "cross-feature-matrix", "retained-evidence"],
        "creator": "Codex",
        "character_version": "1.0.0",
        "extensions": {},
    }


def build_cases(run_id: str, allow_deletes: bool) -> list[CaseSpec]:
    m = all_markers(run_id, allow_deletes)
    cases: list[CaseSpec] = []

    def add(
        key: str,
        family: str,
        chat_key: str,
        request: str,
        expected: tuple[str, ...],
        *,
        forbidden: tuple[str, ...] = (),
        lorebook_key: str | None = None,
        regex_key: str | None = None,
        preset_key: str = "base",
        input_mode: str = "standard",
        prelude: str = "",
        greeting_marker: str | None = None,
        capture_ui: bool = False,
        notes: str = "",
    ) -> None:
        ordinal = len(cases) + 1
        nonce = nonce_for(run_id, ordinal, key)
        cases.append(
            CaseSpec(
                ordinal=ordinal,
                key=key,
                family=family,
                chat_key=chat_key,
                nonce=nonce,
                prompt=nonce_prompt(nonce, request),
                expected=expected,
                forbidden=forbidden,
                lorebook_key=lorebook_key,
                regex_key=regex_key,
                preset_key=preset_key,
                input_mode=input_mode,
                prelude=prelude,
                greeting_marker=greeting_marker,
                capture_ui=capture_ui,
                notes=notes,
            )
        )

    add(
        "regex-lorebook-enabled",
        "regex-worldbook",
        "regex-on",
        f"The phrase {trigger(run_id, 'regex')} activates a worldbook entry. "
        + evidence_request("the transformed worldbook injection"),
        (m["regex-transformed"],),
        forbidden=(m["regex-raw"],),
        lorebook_key="regex",
        regex_key="lorebook-transform",
        notes="Regex placement=lorebook, timing=send must transform the injected worldbook content.",
    )
    add(
        "regex-lorebook-control",
        "regex-worldbook",
        "regex-off",
        f"The phrase {trigger(run_id, 'regex')} activates a worldbook entry. "
        + evidence_request("the untransformed worldbook injection"),
        (m["regex-raw"],),
        forbidden=(m["regex-transformed"],),
        lorebook_key="regex",
        notes="Same worldbook without regex binding is the non-transforming control.",
    )
    add(
        "worldbook-constant",
        "worldbook-activation",
        "constant",
        evidence_request("the constant worldbook entry"),
        (m["constant"],),
        lorebook_key="constant",
    )
    add(
        "worldbook-keyword-hit",
        "worldbook-activation",
        "keyword-hit",
        f"Keyword for this request: {trigger(run_id, 'keyword')}. " + evidence_request("the keyword worldbook entry"),
        (m["keyword"],),
        lorebook_key="keyword",
    )
    keyword_absent = marker(run_id, "keyword-absent")
    add(
        "worldbook-keyword-miss",
        "worldbook-activation",
        "keyword-miss",
        absent_request("the keyword worldbook entry", keyword_absent),
        (keyword_absent,),
        forbidden=(m["keyword"],),
        lorebook_key="keyword",
    )
    add(
        "worldbook-secondary-any-hit",
        "worldbook-activation",
        "secondary-hit",
        (
            f"Use {trigger(run_id, 'secondary-main')} together with {trigger(run_id, 'secondary-b')}. "
            + evidence_request("the main-plus-secondary worldbook rule")
        ),
        (m["secondary"],),
        lorebook_key="secondary",
    )
    secondary_absent = marker(run_id, "secondary-absent")
    add(
        "worldbook-secondary-any-miss",
        "worldbook-activation",
        "secondary-miss",
        (
            f"Use only {trigger(run_id, 'secondary-main')} without any secondary key. "
            + absent_request("the main-plus-secondary worldbook rule", secondary_absent)
        ),
        (secondary_absent,),
        forbidden=(m["secondary"],),
        lorebook_key="secondary",
    )
    add(
        "worldbook-probability-100",
        "worldbook-activation",
        "probability-100",
        f"Keyword: {trigger(run_id, 'probability-100')}. " + evidence_request("the probability-100 entry"),
        (m["probability-100"],),
        lorebook_key="probability-100",
    )
    probability_absent = marker(run_id, "probability-zero-absent")
    add(
        "worldbook-probability-0",
        "worldbook-activation",
        "probability-0",
        f"Keyword: {trigger(run_id, 'probability-0')}. "
        + absent_request("the probability-zero entry", probability_absent),
        (probability_absent,),
        forbidden=(m["probability-0"],),
        lorebook_key="probability-0",
    )
    add(
        "worldbook-scan-depth-in-window",
        "worldbook-activation",
        "scan-in",
        evidence_request("a trigger still inside the configured two-message scan window"),
        (m["scan-depth"],),
        lorebook_key="scan",
        prelude="scan-in",
    )
    scan_absent = marker(run_id, "scan-outside-absent")
    add(
        "worldbook-scan-depth-outside-window",
        "worldbook-activation",
        "scan-out",
        absent_request("a trigger older than the configured two-message scan window", scan_absent),
        (scan_absent,),
        forbidden=(m["scan-depth"],),
        lorebook_key="scan",
        prelude="scan-out",
    )
    add(
        "worldbook-sticky-trigger",
        "worldbook-lifecycle",
        "sticky",
        f"Keyword: {trigger(run_id, 'sticky')}. " + evidence_request("the newly activated sticky entry"),
        (m["sticky-a"],),
        lorebook_key="sticky",
    )
    add(
        "worldbook-sticky-carry",
        "worldbook-lifecycle",
        "sticky",
        evidence_request("the still-active sticky entry after its content was rotated without repeating the key"),
        (m["sticky-b"],),
        forbidden=(m["sticky-a"],),
        lorebook_key="sticky",
        prelude="sticky-rotate",
        notes="Content rotation reduces contamination from the first reply; a reset caused by update is a valid failure.",
    )
    sticky_control_absent = marker(run_id, "sticky-unactivated-control")
    add(
        "worldbook-sticky-unactivated-control",
        "worldbook-lifecycle",
        "sticky-control",
        absent_request("the rotated sticky entry in a chat where it was never activated", sticky_control_absent),
        (sticky_control_absent,),
        forbidden=(m["sticky-b"],),
        lorebook_key="sticky",
        notes="Control proving that content rotation alone does not activate the keyword entry in a fresh chat.",
    )
    add(
        "worldbook-cooldown-trigger",
        "worldbook-lifecycle",
        "cooldown",
        f"Keyword: {trigger(run_id, 'cooldown')}. " + evidence_request("the newly activated cooldown entry"),
        (m["cooldown-a"],),
        lorebook_key="cooldown",
    )
    cooldown_absent = marker(run_id, "cooldown-blocked")
    add(
        "worldbook-cooldown-blocked",
        "worldbook-lifecycle",
        "cooldown",
        f"Repeat keyword: {trigger(run_id, 'cooldown')}. "
        + absent_request("the rotated entry while its cooldown is active", cooldown_absent),
        (cooldown_absent,),
        forbidden=(m["cooldown-b"],),
        lorebook_key="cooldown",
        prelude="cooldown-rotate",
    )
    add(
        "worldbook-cooldown-expired",
        "worldbook-lifecycle",
        "cooldown",
        f"Repeat keyword after the configured cooldown: {trigger(run_id, 'cooldown')}. "
        + evidence_request("the rotated entry after cooldown expiry"),
        (m["cooldown-b"],),
        forbidden=(m["cooldown-a"],),
        lorebook_key="cooldown",
        prelude="cooldown-advance",
        notes="Neutral retained messages advance the cooldown before this positive control.",
    )
    delay_absent = marker(run_id, "delay-before-threshold")
    add(
        "worldbook-delay-before-threshold",
        "worldbook-lifecycle",
        "delay",
        f"Keyword: {trigger(run_id, 'delay')}. "
        + absent_request("the delayed entry before one full message step", delay_absent),
        (delay_absent,),
        forbidden=(m["delay"],),
        lorebook_key="delay",
    )
    add(
        "worldbook-delay-after-threshold",
        "worldbook-lifecycle",
        "delay",
        evidence_request("the delayed entry after the prior trigger turn"),
        (m["delay"],),
        lorebook_key="delay",
    )
    position_cases = (
        ("worldbook-position-before", "position-before", "position-before", "lorebookBefore/system"),
        ("worldbook-position-after", "position-after", "position-after", "lorebookAfter/system"),
        ("worldbook-position-top-example", "position-top", "position-top-example", "topOfExampleMessages/system"),
        ("worldbook-position-bottom-example", "position-bottom", "position-bottom-example", "bottomOfExampleMessages/system"),
        ("worldbook-position-depth-system", "position-depth-system", "position-depth-system", "atDepth=3/system"),
        (
            "worldbook-position-depth-assistant",
            "position-depth-assistant",
            "position-depth-assistant",
            "atDepth=1/assistant",
        ),
    )
    for case_key, lorebook_key, marker_key, subject in position_cases:
        add(
            case_key,
            "worldbook-position",
            case_key,
            evidence_request(f"the constant worldbook entry injected at {subject}"),
            (m[marker_key],),
            lorebook_key=lorebook_key,
            notes=(
                f"Claim boundary: exact readback proves the configured {subject} fields; "
                "the model result proves injection under that configuration, not exact prompt ordering."
            ),
        )
    add(
        "character-first-message",
        "character-greetings",
        "greeting-first",
        evidence_request("the selected first message in chat history"),
        (m["greeting-first"],),
        greeting_marker=m["greeting-first"],
        capture_ui=True,
    )
    add(
        "character-alternate-greeting-a",
        "character-greetings",
        "greeting-alt-a",
        evidence_request("the selected alternate greeting A in chat history"),
        (m["greeting-alt-a"],),
        greeting_marker=m["greeting-alt-a"],
        capture_ui=True,
    )
    add(
        "character-alternate-greeting-b",
        "character-greetings",
        "greeting-alt-b",
        evidence_request("the selected alternate greeting B in chat history"),
        (m["greeting-alt-b"],),
        greeting_marker=m["greeting-alt-b"],
        capture_ui=True,
    )
    add(
        "character-message-example",
        "character-greetings",
        "message-example",
        evidence_request("the character's example-message section"),
        (m["message-example"],),
    )
    add(
        "preset-absolute-depth-0",
        "preset-depth",
        "preset-absolute-0",
        evidence_request("the active preset's absolute-depth-zero custom entry"),
        (m["preset-depth-0"],),
        preset_key="absolute-0",
        notes="Claim boundary: preset depth fields are read back and injection is observed; exact prompt ordering is not claimed.",
    )
    add(
        "preset-absolute-depth-3",
        "preset-depth",
        "preset-absolute-3",
        evidence_request("the active preset's absolute-depth-three custom entry"),
        (m["preset-depth-3"],),
        preset_key="absolute-3",
        prelude="depth-history",
        notes="Claim boundary: preset depth fields are read back and injection is observed; exact prompt ordering is not claimed.",
    )
    add(
        "input-clear-set-append-send",
        "input-transport",
        "input-pipeline",
        (
            f"This transport-only challenge code is {m['input-challenge']}. "
            "Write the challenge code on the second line, then say INPUT_PIPELINE_OK."
        ),
        (m["input-challenge"], "INPUT_PIPELINE_OK"),
        input_mode="clear-set-append-send",
        capture_ui=True,
        notes="The challenge is intentionally in the prompt; proof comes from exact clear/set/append/get/send readbacks.",
    )
    add(
        "message-append-update-delete",
        "message-ops",
        "message-ops",
        evidence_request("the latest retained message-operation audit record in chat history"),
        (m["message-delete-final"],),
        forbidden=(m["message-original"], m["message-updated"]),
        prelude="message-ops",
        capture_ui=True,
    )
    add(
        "plugin-tavojs-lorebook-crud",
        "plugin-tavojs-lorebook",
        "plugin-crud",
        evidence_request("the plugin/TavoJS lorebook CRUD audit message in chat history"),
        (m["crud-delete-final"],),
        prelude="plugin-crud",
        capture_ui=True,
    )
    add(
        "thread-switch-tavojs-readback",
        "thread-tavojs-readback",
        "thread-a",
        evidence_request("the final TavoJS chat-scoped thread readback audit message"),
        (m["thread-summary"], m["thread-a"]),
        forbidden=(m["thread-b"],),
        prelude="thread-roundtrip",
        capture_ui=True,
    )
    validate_case_plan(cases)
    return cases


def validate_case_plan(cases: list[CaseSpec]) -> None:
    errors: list[str] = []
    if len(cases) != PLANNED_MODEL_CALLS:
        errors.append(f"planned {len(cases)} model calls, expected {PLANNED_MODEL_CALLS}")
    if len(cases) < MIN_MODEL_CALLS:
        errors.append(f"planned model calls are below minimum {MIN_MODEL_CALLS}")
    ordinals = [case.ordinal for case in cases]
    if ordinals != list(range(1, len(cases) + 1)):
        errors.append("case ordinals are not contiguous")
    keys = [case.key for case in cases]
    if len(keys) != len(set(keys)):
        errors.append("case keys are not unique")
    nonces = [case.nonce for case in cases]
    if len(nonces) != len(set(nonces)):
        errors.append("model nonces are not unique")
    for case in cases:
        if case.prompt.count(case.nonce) != 1:
            errors.append(f"{case.key} prompt does not contain its nonce exactly once")
        if not case.expected:
            errors.append(f"{case.key} has no semantic assertion")
        if case.family not in MODEL_FAMILIES:
            errors.append(f"{case.key} has unknown family {case.family}")
        if set(case.expected) & set(case.forbidden):
            errors.append(f"{case.key} has overlapping expected and forbidden markers")
    covered = {case.family for case in cases}
    missing_families = sorted(set(MODEL_FAMILIES) - covered)
    if missing_families:
        errors.append(f"missing model families: {missing_families}")
    if errors:
        raise RuntimeError("Invalid cross-feature model plan: " + "; ".join(errors))


def resolve_case_selection(cases: list[CaseSpec], raw_keys: str) -> tuple[list[CaseSpec], dict[str, Any]]:
    if not raw_keys.strip():
        keys = [case.key for case in cases]
        return cases, {
            "mode": "all",
            "requestedCaseKeys": keys,
            "selectedCaseKeys": keys,
            "autoExpandedCaseKeys": [],
            "dependencyGroupsApplied": [],
        }
    requested = [value.strip() for value in raw_keys.split(",") if value.strip()]
    if not requested:
        raise RuntimeError("--case-keys did not contain any case key")
    if len(requested) != len(set(requested)):
        raise RuntimeError("--case-keys contains duplicates")
    available = {case.key for case in cases}
    unknown = sorted(set(requested) - available)
    if unknown:
        raise RuntimeError(f"Unknown --case-keys: {unknown}")
    wanted = set(requested)
    applied: list[dict[str, Any]] = []
    changed = True
    while changed:
        changed = False
        for group in CASE_DEPENDENCY_GROUPS:
            selected_members = sorted(wanted.intersection(group))
            if not selected_members:
                continue
            added = [key for key in group if key not in wanted]
            if added:
                wanted.update(added)
                changed = True
                applied.append(
                    {
                        "triggeredBy": selected_members,
                        "expandedGroup": list(group),
                        "addedCaseKeys": added,
                    }
                )
    selected = [case for case in cases if case.key in wanted]
    selected_keys = [case.key for case in selected]
    return selected, {
        "mode": "dependency-expanded" if set(selected_keys) != set(requested) else "explicit",
        "requestedCaseKeys": requested,
        "selectedCaseKeys": selected_keys,
        "autoExpandedCaseKeys": [key for key in selected_keys if key not in set(requested)],
        "dependencyGroupsApplied": applied,
    }


def select_cases(cases: list[CaseSpec], raw_keys: str) -> list[CaseSpec]:
    selected, _ = resolve_case_selection(cases, raw_keys)
    return selected


def split_input_for_append(text: str) -> tuple[str, str]:
    """Split on an existing ASCII space and verify the runtime's observed separator."""

    midpoint = max(1, len(text) // 2)
    before = text.rfind(" ", 1, midpoint + 1)
    after = text.find(" ", midpoint)
    pivot = before if before > 0 else after
    if pivot <= 0 or pivot >= len(text) - 1:
        raise RuntimeError("Input transport prompt has no safe append boundary")
    first, second = text[:pivot], text[pivot + 1 :]
    if first + " " + second != text:
        raise RuntimeError("Input append split did not preserve the immutable prompt")
    return first, second


def input_append_proof(first: str, second: str, observed: str, expected: str) -> dict[str, Any]:
    separator: str | None = None
    if observed.startswith(first) and observed.endswith(second):
        suffix_start = len(observed) - len(second)
        if suffix_start >= len(first):
            separator = observed[len(first) : suffix_start]
    return {
        "mode": "clear-set-append-send",
        "firstSha256": hashlib.sha256(first.encode("utf-8")).hexdigest(),
        "secondSha256": hashlib.sha256(second.encode("utf-8")).hexdigest(),
        "combinedSha256": hashlib.sha256(observed.encode("utf-8")).hexdigest(),
        "expectedSha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "autoInsertedSeparator": separator,
        "autoInsertedSeparatorObserved": separator not in (None, ""),
        "exactTextMatched": observed == expected,
        "passed": observed == expected,
    }


def chat_profiles(cases: list[CaseSpec]) -> dict[str, ChatProfile]:
    profiles: dict[str, ChatProfile] = {}
    for case in cases:
        candidate = ChatProfile(
            key=case.chat_key,
            lorebook_key=case.lorebook_key,
            regex_key=case.regex_key,
            preset_key=case.preset_key,
        )
        previous = profiles.get(case.chat_key)
        if previous is not None and previous != candidate:
            raise RuntimeError(f"Chat profile {case.chat_key} has conflicting bindings.")
        profiles[case.chat_key] = candidate
    profiles["thread-b"] = ChatProfile(key="thread-b", preset_key="base")
    return profiles


def case_record(case: CaseSpec) -> dict[str, Any]:
    record = asdict(case)
    record["specHash"] = stable_hash(record)
    return record


def plan_record(
    run_id: str,
    allow_deletes: bool,
    cases: list[CaseSpec],
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = [case_record(case) for case in cases]
    plan = {
        "schemaVersion": "1.1.0",
        "case": "tavo-real-phone-cross-feature-matrix",
        "runId": run_id,
        "plannedModelCalls": len(cases),
        "minimumRequiredModelCalls": MIN_MODEL_CALLS,
        "families": list(MODEL_FAMILIES),
        "selection": selection
        or {
            "mode": "direct",
            "requestedCaseKeys": [case.key for case in cases],
            "selectedCaseKeys": [case.key for case in cases],
            "autoExpandedCaseKeys": [],
            "dependencyGroupsApplied": [],
        },
        "safety": {
            "executeRequiresFlag": True,
            "phoneObjectsRetainedByDefault": True,
            "phoneFilesDeleted": False,
            "runnerOwnedDeletesEnabled": allow_deletes,
            "actualDeleteScope": (
                "Only ledger-owned temporary messages and the one plugin-created runner lorebook."
                if allow_deletes
                else "None. Delete tools use dry-run and retained tombstone substitutes."
            ),
            "existingUserPayloadsEdited": False,
            "temporaryRuntimeMutations": ["current chat", "active preset", "input text", "plugin enabled states"],
            "restore": [
                "current chat and original message hash",
                "active preset and original preset payload hashes",
                "input text when readable",
                "existing plugin enabled states, payload hashes, and runtime contribution hash",
            ],
        },
        "countingContract": (
            "A model call counts only when its exact nonce-bearing prompt has one new persistent user id, one new "
            "persistent assistant id, a successful input-send response, successful before/after readbacks, exact nonce "
            "prefix, all expected assertions, and no forbidden markers. Direct-runtime, model-format, model-semantic, "
            "and runner/transport outcomes are retained as separate axes; any failed axis counts as zero."
        ),
        "cases": records,
    }
    plan["planHash"] = stable_hash(plan)
    return plan


class OwnershipLedger:
    """Durable proof that any optionally deleted object belongs to this run."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        if path.exists():
            data = load_json(path)
            if data.get("runId") != run_id:
                raise RuntimeError("Ownership ledger belongs to a different run.")
            self.data = data
        else:
            self.data = {
                "schemaVersion": "1.0.0",
                "runId": run_id,
                "createdAt": now_utc(),
                "objects": {
                    "character": [],
                    "lorebook": [],
                    "regex": [],
                    "preset": [],
                    "chat": [],
                    "message": [],
                    "plugin": [],
                },
            }
            self.save()

    def save(self) -> None:
        self.data["updatedAt"] = now_utc()
        durable_json(self.path, self.data)

    def claim(self, kind: str, identity: int | str, **metadata: Any) -> None:
        if kind not in self.data["objects"]:
            raise RuntimeError(f"Unsupported ledger kind: {kind}")
        records = self.data["objects"][kind]
        id_key = "pluginId" if kind == "plugin" else "id"
        matches = [record for record in records if record.get(id_key) == identity]
        candidate = {id_key: identity, **metadata}
        if matches:
            merged = {**matches[0], **candidate}
            records[records.index(matches[0])] = merged
        else:
            records.append(candidate)
        self.save()

    def owns(self, kind: str, identity: int | str) -> bool:
        id_key = "pluginId" if kind == "plugin" else "id"
        return any(record.get(id_key) == identity for record in self.data["objects"].get(kind, []))

    def require_owned(self, kind: str, identity: int | str) -> dict[str, Any]:
        id_key = "pluginId" if kind == "plugin" else "id"
        matches = [
            record
            for record in self.data["objects"].get(kind, [])
            if record.get(id_key) == identity
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Refusing destructive action: {kind} {identity!r} is not uniquely ledger-owned.")
        return matches[0]


def durable_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def adb(device: str, arguments: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    command = ["adb"] + (["-s", device] if device else []) + arguments
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerTransportFailure(f"ADB transport failed for {arguments!r}: {exc}") from exc


def run_ui_tool(arguments: list[str], output: Path) -> tuple[int, dict[str, Any]]:
    try:
        proc = subprocess.run(
            [sys.executable, str(UI_TOOL), *arguments],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerTransportFailure(f"UI helper transport failed for {arguments!r}: {exc}") from exc
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "rawOutput": proc.stdout, "exitCode": proc.returncode}
    durable_json(output, payload)
    return proc.returncode, payload


def capture_screen(device: str, output_dir: Path, name: str) -> None:
    target = output_dir / name
    target.mkdir(parents=True, exist_ok=True)
    command = ["adb"] + (["-s", device] if device else []) + ["exec-out", "screencap", "-p"]
    try:
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerTransportFailure(f"Screen-capture transport failed for {name}: {exc}") from exc
    passed = proc.returncode == 0 and proc.stdout.startswith(b"\x89PNG") and len(proc.stdout) >= 1024
    if passed:
        durable_bytes(target / "screen.png", proc.stdout)
    durable_json(
        target / "capture.json",
        {
            "command": command,
            "returncode": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="replace"),
            "bytes": len(proc.stdout),
            "passed": passed,
            "capturedAt": now_utc(),
        },
    )
    if not passed:
        raise RuntimeError(f"Could not capture phone screen for {name}.")


def require_device_identity(device: str) -> dict[str, Any]:
    if not device:
        raise RuntimeError("--device is required for real plugin actions and greeting selection.")
    state = adb(device, ["get-state"])
    if state.returncode != 0 or state.stdout.strip() != "device":
        raise RuntimeError(f"ADB device {device!r} is unavailable: {state.stdout.strip()}")
    model = adb(device, ["shell", "getprop", "ro.product.model"])
    android = adb(device, ["shell", "getprop", "ro.build.version.release"])
    package = adb(device, ["shell", "dumpsys", "package", "app.bitbear.tav"], timeout=60)
    version_name = re.search(r"\bversionName=([^\s]+)", package.stdout)
    version_code = re.search(r"\bversionCode=(\d+)", package.stdout)
    if (
        model.returncode != 0
        or android.returncode != 0
        or package.returncode != 0
        or version_name is None
        or version_code is None
    ):
        raise RuntimeError("Could not prove the connected Tavo phone/app identity.")
    return {
        "serial": device,
        "model": model.stdout.strip(),
        "androidVersion": android.stdout.strip(),
        "package": "app.bitbear.tav",
        "versionName": version_name.group(1),
        "versionCode": int(version_code.group(1)),
    }


def acquire_phone_lock(device: str) -> tuple[Any, str]:
    identity = hashlib.sha256(f"tavo-device|{device.strip().lower()}".encode("utf-8")).hexdigest()
    path = Path("/tmp") / f"tavo-phone-runtime-{identity[:24]}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(f"Another Tavo runner already holds the hard lock for device {device!r}.")
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} identity={identity} acquired={now_utc()}\n")
    handle.flush()
    os.fsync(handle.fileno())
    return handle, identity


def foreground_tavo(device: str, step_dir: Path, settle_seconds: float = 3.0) -> None:
    proc = adb(
        device,
        ["shell", "monkey", "-p", "app.bitbear.tav", "-c", "android.intent.category.LAUNCHER", "1"],
        timeout=30,
    )
    durable_json(
        step_dir / "foreground.json",
        {"returncode": proc.returncode, "output": proc.stdout, "settleSeconds": settle_seconds},
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not foreground Tavo.")
    time.sleep(settle_seconds)


def dismiss_greeting(device: str, step_dir: Path) -> None:
    code, payload = run_ui_tool(
        ["tap", "--device", device, "--content-desc", "取消", "--class", "android.widget.Button"],
        step_dir / "dismiss-greeting.json",
    )
    if code not in (0, 4):
        raise RuntimeError(f"Could not safely dismiss the greeting selector: {payload}")


def open_plus_menu(device: str, step_dir: Path) -> None:
    code, dump = run_ui_tool(
        ["dump", "--device", device, "--output", str(step_dir / "ui-before-plus.xml")],
        step_dir / "ui-before-plus.json",
    )
    if code != 0:
        raise RuntimeError("Could not dump UI before opening the plus menu.")
    nodes = dump.get("nodes") if isinstance(dump.get("nodes"), list) else []
    candidates: list[dict[str, Any]] = []
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
        durable_json(step_dir / "plus-candidates.json", {"candidates": candidates})
        raise RuntimeError(f"Expected one bottom-left plus control, found {len(candidates)}.")
    center = candidates[0]["bounds"]["center"]
    proc = adb(device, ["shell", "input", "tap", str(center["x"]), str(center["y"])])
    durable_json(
        step_dir / "plus-tap.json",
        {"target": candidates[0], "returncode": proc.returncode, "output": proc.stdout},
    )
    if proc.returncode != 0:
        raise RuntimeError("ADB tap failed while opening the plus menu.")


def tap_plugin_action(device: str, label: str, step_dir: Path) -> None:
    open_plus_menu(device, step_dir)
    time.sleep(1.2)
    for attempt in range(1, 13):
        code, payload = run_ui_tool(
            ["dump", "--device", device, "--output", str(step_dir / f"ui-plugin-{attempt}.xml")],
            step_dir / f"ui-plugin-{attempt}.json",
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
            durable_json(step_dir / f"ambiguous-{attempt}.json", {"matches": matches})
            raise RuntimeError(f"Plugin action {label!r} is ambiguous.")
        if len(matches) == 1:
            center = matches[0]["bounds"].get("center") or {}
            x = int(center.get("x") or 0)
            y = int(center.get("y") or 0)
            if 0 < x < 1200 and 120 <= y <= 2470:
                capture_screen(device, step_dir, f"menu-ready-{attempt}")
                proc = adb(device, ["shell", "input", "tap", str(x), str(y)])
                durable_json(
                    step_dir / "tap-action.json",
                    {"target": matches[0], "attempt": attempt, "returncode": proc.returncode, "output": proc.stdout},
                )
                if proc.returncode != 0:
                    raise RuntimeError(f"ADB tap failed for plugin action {label!r}.")
                return
        if attempt in (4, 8):
            closed = adb(device, ["shell", "input", "keyevent", "4"])
            durable_json(
                step_dir / f"menu-restart-{attempt}.json",
                {"returncode": closed.returncode, "output": closed.stdout},
            )
            time.sleep(0.8)
            open_plus_menu(device, step_dir / f"restart-{attempt}")
            time.sleep(1.2)
            continue
        swipe = adb(device, ["shell", "input", "swipe", "600", "2200", "600", "1100", "450"])
        durable_json(
            step_dir / f"menu-scroll-{attempt}.json",
            {"returncode": swipe.returncode, "output": swipe.stdout},
        )
        if swipe.returncode != 0:
            raise RuntimeError(f"Could not scroll while locating plugin action {label!r}.")
        time.sleep(0.8)
    raise RuntimeError(f"Plugin action {label!r} was not found after menu retries.")


def evaluate_greeting_materialization(
    initial_messages: list[dict[str, Any]],
    final_messages: list[dict[str, Any]],
    greeting_marker: str,
    other_greeting_markers: tuple[str, ...] | list[str],
    source: str,
) -> dict[str, Any]:
    target_matches = [item for item in final_messages if greeting_marker in str(item.get("content") or "")]
    selected = target_matches[0] if len(target_matches) == 1 else None
    selected_index = selected.get("index") if isinstance(selected, dict) else None
    supplied_other_markers = sorted({value for value in other_greeting_markers if value and value != greeting_marker})
    other_matches = [
        {
            "marker": value,
            "messageIds": [
                item.get("id") for item in final_messages if value in str(item.get("content") or "")
            ],
        }
        for value in supplied_other_markers
        if any(value in str(item.get("content") or "") for item in final_messages)
    ]
    assertions = {
        "initialZeroMessages": len(initial_messages) == 0,
        "exactlyOneTargetGreeting": len(target_matches) == 1,
        "selectedRoleAssistant": bool(selected and selected.get("role") == "assistant"),
        "selectedIndexZero": selected_index == 0,
        "otherGreetingMarkersProvided": bool(supplied_other_markers),
        "otherGreetingMarkersAbsent": bool(supplied_other_markers) and not other_matches,
    }
    basic_persistence = (
        assertions["exactlyOneTargetGreeting"]
        and assertions["selectedRoleAssistant"]
        and isinstance(selected.get("id") if selected else None, int)
        and int(selected.get("id") or 0) > 0
    )
    exact_materialization = basic_persistence and all(
        assertions[key]
        for key in (
            "initialZeroMessages",
            "selectedIndexZero",
            "otherGreetingMarkersProvided",
            "otherGreetingMarkersAbsent",
        )
    )
    proof_failures = [key for key, passed in assertions.items() if passed is False]
    if exact_materialization:
        evidence_level = "live-verified"
    elif basic_persistence:
        evidence_level = "semantic-pass-observation"
    else:
        evidence_level = "semantic-mixed"
    return {
        "greetingMarker": greeting_marker,
        "source": source,
        "initialMessageCount": len(initial_messages),
        "finalMessageCount": len(final_messages),
        "matchingMessageIds": [item.get("id") for item in target_matches],
        "selectedMessageId": selected.get("id") if selected else None,
        "selectedIndex": selected_index,
        "otherGreetingMatches": other_matches,
        "assertions": assertions,
        "proofFailures": proof_failures,
        "exactMaterializationProved": exact_materialization,
        "evidenceLevel": evidence_level,
        "passed": basic_persistence,
    }


def select_greeting(
    client: TavoMcp,
    device: str,
    chat_id: int,
    greeting_marker: str,
    step_dir: Path,
    request_scope: str,
    other_greeting_markers: tuple[str, ...] | list[str] = (),
) -> int:
    existing = all_messages(client, chat_id, step_dir / "existing", "messages.json")
    existing_matches = [item for item in existing if greeting_marker in str(item.get("content") or "")]
    if existing_matches:
        result = evaluate_greeting_materialization(
            existing,
            existing,
            greeting_marker,
            other_greeting_markers,
            "automatic-message-in-new-ledger-owned-chat",
        )
        durable_json(step_dir / "selection-result.json", result)
        if not result["passed"]:
            raise RuntimeError("Automatic greeting readback was ambiguous or invalid.")
        return int(result["selectedMessageId"])
    set_current_chat(client, step_dir / "set-chat", chat_id, request_scope)
    foreground_tavo(device, step_dir / "foreground", settle_seconds=2.5)
    capture_phone(device, step_dir, "before-greeting-selection")
    code, payload = run_ui_tool(
        ["tap", "--device", device, "--content-desc", greeting_marker, "--contains"],
        step_dir / "tap-greeting.json",
    )
    if code != 0:
        raise RuntimeError(f"Could not select greeting marker {greeting_marker!r}: {payload}")
    code, payload = run_ui_tool(
        ["tap", "--device", device, "--content-desc", "确定", "--class", "android.widget.Button"],
        step_dir / "confirm-greeting.json",
    )
    if code != 0:
        raise RuntimeError(f"Could not confirm greeting selection: {payload}")
    time.sleep(1.2)
    capture_phone(device, step_dir, "after-greeting-selection")
    messages = all_messages(client, chat_id, step_dir / "after", "messages.json")
    result = evaluate_greeting_materialization(
        existing,
        messages,
        greeting_marker,
        other_greeting_markers,
        "ui-greeting-selection",
    )
    durable_json(step_dir / "selection-result.json", result)
    if not result["passed"]:
        raise RuntimeError("Greeting selection did not persist exactly one matching assistant message.")
    return int(result["selectedMessageId"])


def ensure_default_greeting(context: RuntimeContext, chat_id: int, step_dir: Path) -> None:
    marker_value = str(context.registry["markers"]["greeting-first"])
    existing = all_messages(context.client, chat_id, step_dir / "existing", "messages.json")
    matching = [
        item
        for item in existing
        if item.get("role") == "assistant" and marker_value in str(item.get("content") or "")
    ]
    if len(matching) > 1:
        raise RuntimeError("Runner chat contains duplicate default greeting evidence.")
    if matching:
        durable_json(
            step_dir / "result.json",
            {"selected": False, "alreadyMaterialized": True, "messageId": matching[0].get("id")},
        )
        return
    select_greeting(
        context.client,
        context.device,
        chat_id,
        marker_value,
        step_dir / "select",
        f"{context.run_id}-default-greeting",
        tuple(
            str(context.registry["markers"][key])
            for key in ("greeting-alt-a", "greeting-alt-b")
            if context.registry["markers"].get(key)
        ),
    )
    durable_json(step_dir / "result.json", {"selected": True, "alreadyMaterialized": False})


def resource_text(response: dict[str, Any]) -> str:
    contents = (response.get("result") or {}).get("contents") if isinstance(response, dict) else None
    if not isinstance(contents, list):
        return ""
    return "\n".join(str(item.get("text") or "") for item in contents if isinstance(item, dict))


def missing_tavojs_doc_contracts(tavojs: str) -> list[str]:
    missing = [
        value
        for value in ("tavo.chat.current", "tavo.input.get/set/append/clear/send")
        if value not in tavojs
    ]
    lorebook_methods = (
        "tavo.lorebook.create",
        "tavo.lorebook.get",
        "tavo.lorebook.update",
        "tavo.lorebook.delete",
    )
    if "tavo.lorebook.*" not in tavojs:
        missing.extend(value for value in lorebook_methods if value not in tavojs)
    return missing


def read_mcp_identity(client: TavoMcp, artifact_dir: Path) -> tuple[dict[str, Any], str]:
    preflight = artifact_dir / "preflight"
    initialize = client.initialize()
    durable_json(preflight / "initialize.json", initialize)
    tools_list = mcp_rpc(client, preflight / "tools-list.json", "tools/list", {})
    resources_list = mcp_rpc(client, preflight / "resources-list.json", "resources/list", {})
    tools = (tools_list.get("result") or {}).get("tools") if isinstance(tools_list, dict) else None
    resources = (resources_list.get("result") or {}).get("resources") if isinstance(resources_list, dict) else None
    server_info = (initialize.get("result") or {}).get("serverInfo") if isinstance(initialize, dict) else None
    if not isinstance(server_info, dict) or not isinstance(tools, list) or not isinstance(resources, list):
        raise RuntimeError("MCP initialize/tools/resources did not return a usable identity.")
    names = {str(item.get("name") or "") for item in tools if isinstance(item, dict)}
    missing = sorted(REQUIRED_TOOLS - names)
    if missing:
        raise RuntimeError(f"Current Tavo MCP surface is missing required tools: {missing}")
    schemas = {str(item.get("name")): item.get("inputSchema") for item in tools if isinstance(item, dict)}
    for destructive_tool in ("tavo_message_delete", "tavo_lorebook_delete"):
        schema = schemas.get(destructive_tool)
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict) or "dryRun" not in properties:
            raise RuntimeError(f"{destructive_tool} no longer exposes a dryRun safety contract.")
    resource_reads: dict[str, Any] = {}
    for uri in REQUIRED_RESOURCE_URIS:
        response = mcp_rpc(
            client,
            preflight / "resources" / f"{safe_name(uri)}.json",
            "resources/read",
            {"uri": uri},
        )
        text = resource_text(response)
        if not text:
            raise RuntimeError(f"Required MCP resource {uri} returned no text.")
        resource_reads[uri] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))}
    tavojs = resource_text(
        load_json(preflight / "resources" / f"{safe_name('tavo://docs/tavojs')}.json")
    )
    missing_docs = missing_tavojs_doc_contracts(tavojs)
    if missing_docs:
        raise RuntimeError(f"Current TavoJS runtime docs are missing required APIs: {missing_docs}")
    identity = {
        "serverInfo": server_info,
        "toolNames": sorted(names),
        "toolSchemasHash": stable_hash(schemas),
        "resourceUris": sorted(str(item.get("uri") or "") for item in resources if isinstance(item, dict)),
        "resourceReads": resource_reads,
    }
    identity_hash = stable_hash(identity)
    durable_json(preflight / "identity.json", {**identity, "identityHash": identity_hash})
    return identity, identity_hash


def search_items(
    client: TavoMcp,
    tool: str,
    output_dir: Path,
    *,
    query: str = "",
    match: str | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_cursors: set[int] = set()
    cursor: int | None = None
    page = 1
    while True:
        arguments: dict[str, Any] = {"limit": 100}
        if query:
            arguments["query"] = query
        if match:
            arguments["match"] = match
        if cursor is not None:
            arguments["cursor"] = cursor
        response = mcp_tool(client, output_dir / f"page-{page:03d}.json", tool, arguments)
        if not ok_response(response):
            raise RuntimeError(f"{tool} failed while enumerating assets.")
        payload = response_payload(response)
        page_items = payload.get("items")
        if not isinstance(page_items, list) or any(not isinstance(item, dict) for item in page_items):
            raise RuntimeError(f"{tool} returned an invalid items payload.")
        items.extend(page_items)
        next_cursor = payload.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, int) or next_cursor < 0 or next_cursor in seen_cursors:
            raise RuntimeError(f"{tool} returned an invalid or repeated cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        page += 1
    return items


def exact_search(client: TavoMcp, step_dir: Path, kind: str, value: str) -> list[dict[str, Any]]:
    tool = f"tavo_{kind}_search"
    matches = search_items(client, tool, step_dir, query=value, match="exact")
    if kind == "plugin":
        return [item for item in matches if str(item.get("pluginId") or "") == value]
    return [item for item in matches if str(item.get("name") or item.get("title") or "") == value]


def message_count(client: TavoMcp, chat_id: int, output: Path) -> int:
    response = mcp_tool(client, output, "tavo_message_count", {"chatId": chat_id}, timeout=60)
    payload = response_payload(response)
    count = payload.get("count")
    if not ok_response(response) or not isinstance(count, int) or count < 0:
        raise RuntimeError(f"Could not count messages in chat {chat_id}.")
    return count


def all_messages(client: TavoMcp, chat_id: int, step_dir: Path, filename: str) -> list[dict[str, Any]]:
    count = message_count(client, chat_id, step_dir / f"{Path(filename).stem}-count.json")
    response = mcp_tool(
        client,
        step_dir / filename,
        "tavo_message_find",
        {"chatId": chat_id, "range": [0, max(1, count + 1)]},
        timeout=60,
    )
    if not ok_response(response):
        raise RuntimeError(f"Could not read messages in chat {chat_id}.")
    items = response_items(response)
    if len(items) != count:
        raise RuntimeError(f"Message count/find mismatch for chat {chat_id}: {count} vs {len(items)}.")
    return sorted(items, key=lambda item: (int(item.get("index") or 0), int(item.get("id") or 0)))


def message_payload_snapshot(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("id", "index", "role", "content", "reasoning", "hidden", "speakerName")
    return [{key: message.get(key) for key in fields} for message in messages]


def set_current_chat(client: TavoMcp, step_dir: Path, chat_id: int, request_scope: str) -> None:
    before = mcp_tool(client, step_dir / "before.json", "tavo_current_chat_get", {})
    before_chat = response_payload(before).get("chat")
    before_id = int(before_chat.get("id") or 0) if isinstance(before_chat, dict) else 0
    if before_id != chat_id:
        arguments = {
            "id": chat_id,
            "dryRun": True,
            "clientRequestId": f"cfm-{safe_name(request_scope)}-chat-{chat_id}-dry",
        }
        dry = mcp_tool(client, step_dir / "dry-run.json", "tavo_current_chat_set", arguments)
        after_dry = mcp_tool(client, step_dir / "after-dry-run.json", "tavo_current_chat_get", {})
        after_dry_chat = response_payload(after_dry).get("chat")
        after_dry_id = int(after_dry_chat.get("id") or 0) if isinstance(after_dry_chat, dict) else 0
        if not ok_response(dry) or after_dry_id != before_id:
            raise RuntimeError("Current-chat dry-run changed runtime state.")
        arguments["dryRun"] = False
        arguments["clientRequestId"] = f"cfm-{safe_name(request_scope)}-chat-{chat_id}-actual"
        actual = mcp_tool(client, step_dir / "actual.json", "tavo_current_chat_set", arguments)
        if not ok_response(actual):
            raise RuntimeError(f"Could not set current chat {chat_id}.")
    final = mcp_tool(client, step_dir / "final.json", "tavo_current_chat_get", {})
    final_chat = response_payload(final).get("chat")
    final_id = int(final_chat.get("id") or 0) if isinstance(final_chat, dict) else 0
    poll = 0
    deadline = time.time() + 5
    while ok_response(final) and final_id != chat_id and time.time() < deadline:
        time.sleep(0.5)
        final = mcp_tool(client, step_dir / f"final-poll-{poll:02d}.json", "tavo_current_chat_get", {})
        final_chat = response_payload(final).get("chat")
        final_id = int(final_chat.get("id") or 0) if isinstance(final_chat, dict) else 0
        poll += 1
    if not ok_response(final) or final_id != chat_id:
        raise RuntimeError(f"Current-chat readback did not match {chat_id}.")


def list_presets(client: TavoMcp, output_dir: Path) -> list[dict[str, Any]]:
    summaries = search_items(client, "tavo_preset_search", output_dir / "search")
    ids = [int(item.get("id") or 0) for item in summaries]
    if any(value < 1 for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Preset search returned missing or duplicate ids.")
    records: list[dict[str, Any]] = []
    for preset_id in sorted(ids):
        response = mcp_tool(
            client,
            output_dir / "presets" / str(preset_id) / "readback.json",
            "tavo_preset_get",
            {"id": preset_id},
        )
        payload = response_payload(response)
        if not ok_response(response) or not isinstance(payload.get("active"), bool):
            raise RuntimeError(f"Could not read active state for preset {preset_id}.")
        records.append(
            {
                "id": preset_id,
                "name": payload.get("name"),
                "active": bool(payload["active"]),
                "revision": payload.get("revision"),
                "payloadHash": stable_content_hash(payload, ("active", "revision", "updatedAt")),
            }
        )
    return records


def activate_preset(client: TavoMcp, step_dir: Path, preset_id: int, request_scope: str) -> None:
    before = mcp_tool(client, step_dir / "before.json", "tavo_preset_get", {"id": preset_id})
    before_payload = response_payload(before)
    if not ok_response(before) or int(before_payload.get("id") or 0) != preset_id:
        raise RuntimeError(f"Could not read preset {preset_id} before activation.")
    if before_payload.get("active") is not True:
        arguments: dict[str, Any] = {
            "id": preset_id,
            "dryRun": True,
            "clientRequestId": f"cfm-{safe_name(request_scope)}-preset-{preset_id}-dry",
        }
        revision = before_payload.get("revision")
        if isinstance(revision, str) and revision:
            arguments["expectedRevision"] = revision
        dry = mcp_tool(client, step_dir / "dry-run.json", "tavo_preset_set_active", arguments)
        after_dry = mcp_tool(client, step_dir / "after-dry-run.json", "tavo_preset_get", {"id": preset_id})
        if not ok_response(dry) or stable_hash(response_payload(after_dry)) != stable_hash(before_payload):
            raise RuntimeError("Preset activation dry-run changed state.")
        arguments["dryRun"] = False
        arguments["clientRequestId"] = f"cfm-{safe_name(request_scope)}-preset-{preset_id}-actual"
        actual = mcp_tool(client, step_dir / "actual.json", "tavo_preset_set_active", arguments)
        if not ok_response(actual):
            raise RuntimeError(f"Could not activate preset {preset_id}.")
    final = mcp_tool(client, step_dir / "final.json", "tavo_preset_get", {"id": preset_id})
    if not ok_response(final) or response_payload(final).get("active") is not True:
        raise RuntimeError(f"Preset {preset_id} was not active on final readback.")


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


def list_plugins(client: TavoMcp, output_dir: Path) -> list[dict[str, Any]]:
    summaries = search_items(client, "tavo_plugin_search", output_dir / "search")
    ids = [str(item.get("pluginId") or "") for item in summaries]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Plugin search returned missing or duplicate ids.")
    records: list[dict[str, Any]] = []
    for plugin_id in sorted(ids):
        response = mcp_tool(
            client,
            output_dir / "plugins" / safe_name(plugin_id) / "readback.json",
            "tavo_plugin_get",
            {"pluginId": plugin_id},
        )
        payload = response_payload(response)
        if (
            not ok_response(response)
            or payload.get("pluginId") != plugin_id
            or not isinstance(payload.get("enabled"), bool)
        ):
            raise RuntimeError(f"Could not read plugin {plugin_id}.")
        records.append(
            {
                "pluginId": plugin_id,
                "name": payload.get("name"),
                "enabled": bool(payload["enabled"]),
                "payloadHash": stable_content_hash(payload, ("enabled", "revision", "updatedAt")),
            }
        )
    return records


def set_plugin_enabled(
    client: TavoMcp,
    step_dir: Path,
    plugin_id: str,
    enabled: bool,
) -> None:
    before = mcp_tool(client, step_dir / "before.json", "tavo_plugin_get", {"pluginId": plugin_id})
    before_payload = response_payload(before)
    if not ok_response(before) or not isinstance(before_payload.get("enabled"), bool):
        raise RuntimeError(f"Could not read plugin {plugin_id} before enabled-state change.")
    if before_payload["enabled"] is not enabled:
        dry = mcp_tool(
            client,
            step_dir / "dry-run.json",
            "tavo_plugin_set_enabled",
            {"pluginId": plugin_id, "enabled": enabled, "dryRun": True},
        )
        after_dry = mcp_tool(client, step_dir / "after-dry-run.json", "tavo_plugin_get", {"pluginId": plugin_id})
        if not ok_response(dry) or stable_hash(response_payload(after_dry)) != stable_hash(before_payload):
            raise RuntimeError(f"Plugin {plugin_id} dry-run changed state.")
        actual = mcp_tool(
            client,
            step_dir / "actual.json",
            "tavo_plugin_set_enabled",
            {"pluginId": plugin_id, "enabled": enabled, "dryRun": False},
        )
        if not ok_response(actual):
            raise RuntimeError(f"Could not set plugin {plugin_id} enabled={enabled}.")
    final = mcp_tool(client, step_dir / "final.json", "tavo_plugin_get", {"pluginId": plugin_id})
    if not ok_response(final) or response_payload(final).get("enabled") is not enabled:
        raise RuntimeError(f"Plugin {plugin_id} enabled-state readback failed.")


def plugin_identity(run_id: str) -> str:
    return "codex.crossmatrix." + re.sub(r"[^a-z0-9]", "", run_id.lower())


def capture_runtime_snapshot(
    client: TavoMcp,
    artifact_dir: Path,
    run_id: str,
    device_identity: dict[str, Any],
    mcp_identity: dict[str, Any],
    mcp_identity_hash: str,
) -> dict[str, Any]:
    path = artifact_dir / "runtime-state" / "snapshot.json"
    if path.exists():
        snapshot = load_json(path)
        expected_identity = {
            "runId": run_id,
            "deviceIdentityHash": stable_hash(device_identity),
            "mcpIdentityHash": mcp_identity_hash,
        }
        mismatches = {
            key: {"expected": value, "actual": snapshot.get(key)}
            for key, value in expected_identity.items()
            if snapshot.get(key) != value
        }
        if mismatches:
            raise RuntimeError(f"Runtime snapshot identity mismatch: {mismatches}")
        return snapshot
    root = artifact_dir / "runtime-state" / "snapshot"
    current = mcp_tool(client, root / "current-chat.json", "tavo_current_chat_get", {})
    current_chat = response_payload(current).get("chat")
    if not ok_response(current) or not isinstance(current_chat, dict) or int(current_chat.get("id") or 0) < 1:
        raise RuntimeError("A real current chat is required so the runner can restore it exactly.")
    current_chat_id = int(current_chat["id"])
    current_chat_readback = mcp_tool(
        client,
        root / "current-chat-payload.json",
        "tavo_chat_get",
        {"id": current_chat_id, "includeMessages": False},
    )
    current_chat_payload = response_payload(current_chat_readback)
    if not ok_response(current_chat_readback) or int(current_chat_payload.get("id") or 0) != current_chat_id:
        raise RuntimeError("Could not snapshot the original current-chat payload.")
    current_messages = all_messages(client, current_chat_id, root / "current-chat-messages", "messages.json")
    current_message_snapshot = message_payload_snapshot(current_messages)
    input_response = mcp_tool(client, root / "input.json", "tavo_input_get", {})
    input_payload = response_payload(input_response)
    input_readable = ok_response(input_response) and isinstance(input_payload.get("text"), str)
    presets = list_presets(client, root / "presets")
    active_ids = [int(item["id"]) for item in presets if item["active"]]
    if len(active_ids) != 1:
        raise RuntimeError(f"Expected exactly one active preset before mutation, found {active_ids}.")
    plugins = list_plugins(client, root / "plugins")
    runtime = mcp_tool(
        client,
        root / "plugin-runtime.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    runtime_payload = response_payload(runtime)
    if not ok_response(runtime):
        raise RuntimeError("Could not snapshot plugin runtime contributions.")
    snapshot = {
        "schemaVersion": "1.0.0",
        "runId": run_id,
        "capturedAt": now_utc(),
        "deviceIdentity": device_identity,
        "deviceIdentityHash": stable_hash(device_identity),
        "mcpIdentity": mcp_identity,
        "mcpIdentityHash": mcp_identity_hash,
        "currentChatId": current_chat_id,
        "currentChatHash": stable_content_hash(current_chat_payload, ("revision", "updatedAt")),
        "currentChatFullHash": stable_hash(current_chat_payload),
        "currentChatPayload": current_chat_payload,
        "currentMessageIds": [item.get("id") for item in current_message_snapshot],
        "currentMessagesHash": stable_hash(current_message_snapshot),
        "currentMessagesFullHash": stable_hash(current_messages),
        "inputReadable": input_readable,
        "inputText": str(input_payload.get("text") or "") if input_readable else None,
        "activePresetId": active_ids[0],
        "presets": presets,
        "presetIdsHash": stable_hash([item["id"] for item in presets]),
        "plugins": plugins,
        "pluginIdsHash": stable_hash([item["pluginId"] for item in plugins]),
        "pluginRuntimeHash": stable_hash(runtime_payload),
        "pluginRuntimeIds": sorted(runtime_plugin_ids(runtime_payload)),
    }
    durable_json(path, snapshot)
    return snapshot


def restore_runtime(
    client: TavoMcp,
    artifact_dir: Path,
    snapshot: dict[str, Any],
    run_id: str,
    reason: str,
) -> bool:
    root = artifact_dir / "runtime-state" / f"restore-{safe_name(reason)}"
    root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    runner_plugin = plugin_identity(run_id)
    try:
        current_plugins = list_plugins(client, root / "plugin-inventory-before")
        current_ids = {item["pluginId"] for item in current_plugins}
        if runner_plugin in current_ids:
            set_plugin_enabled(client, root / "runner-plugin", runner_plugin, False)
        for record in snapshot.get("plugins", []):
            plugin_id = str(record["pluginId"])
            if plugin_id not in current_ids:
                errors.append(f"original plugin disappeared: {plugin_id}")
                continue
            try:
                set_plugin_enabled(
                    client,
                    root / "plugins" / safe_name(plugin_id),
                    plugin_id,
                    bool(record["enabled"]),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"plugin restore failed for {plugin_id}: {exc!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"plugin inventory/restore failed: {exc!r}")
    try:
        activate_preset(
            client,
            root / "preset",
            int(snapshot["activePresetId"]),
            f"{run_id}-{reason}-restore",
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"preset restore failed: {exc!r}")
    try:
        set_current_chat(
            client,
            root / "chat",
            int(snapshot["currentChatId"]),
            f"{run_id}-{reason}-restore",
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"chat restore failed: {exc!r}")
    if snapshot.get("inputReadable") is True:
        try:
            before = mcp_tool(client, root / "input-before.json", "tavo_input_get", {})
            expected = str(snapshot.get("inputText") or "")
            if not ok_response(before):
                raise RuntimeError("original input became unreadable")
            if str(response_payload(before).get("text") or "") != expected:
                set_response = mcp_tool(
                    client,
                    root / "input-set.json",
                    "tavo_input_set",
                    {"text": expected},
                )
                if not ok_response(set_response):
                    raise RuntimeError("input set failed")
            final_input = mcp_tool(client, root / "input-final.json", "tavo_input_get", {})
            if not ok_response(final_input) or str(response_payload(final_input).get("text") or "") != expected:
                raise RuntimeError("input final readback mismatch")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"input restore failed: {exc!r}")
    try:
        current = mcp_tool(client, root / "verify-current-chat.json", "tavo_current_chat_get", {})
        current_chat = response_payload(current).get("chat")
        if not isinstance(current_chat, dict) or int(current_chat.get("id") or 0) != int(snapshot["currentChatId"]):
            errors.append("final current-chat id does not match snapshot")
        chat_readback = mcp_tool(
            client,
            root / "verify-current-chat-payload.json",
            "tavo_chat_get",
            {"id": int(snapshot["currentChatId"]), "includeMessages": False},
        )
        chat_payload = response_payload(chat_readback)
        if (
            not ok_response(chat_readback)
            or stable_content_hash(chat_payload, ("revision", "updatedAt")) != snapshot.get("currentChatHash")
        ):
            errors.append("original current-chat payload hash changed")
        if stable_hash(chat_payload) != snapshot.get("currentChatFullHash"):
            errors.append("original current-chat full payload hash changed")
        messages = all_messages(
            client,
            int(snapshot["currentChatId"]),
            root / "verify-current-chat-messages",
            "messages.json",
        )
        if stable_hash(message_payload_snapshot(messages)) != snapshot.get("currentMessagesHash"):
            errors.append("original current-chat message payload hash changed")
        if stable_hash(messages) != snapshot.get("currentMessagesFullHash"):
            errors.append("original current-chat full message readback hash changed")
        presets = list_presets(client, root / "verify-presets")
        active_ids = [int(item["id"]) for item in presets if item["active"]]
        if active_ids != [int(snapshot["activePresetId"])]:
            errors.append(f"final active preset mismatch: {active_ids}")
        expected_presets = {int(item["id"]): item.get("payloadHash") for item in snapshot.get("presets", [])}
        actual_presets = {int(item["id"]): item.get("payloadHash") for item in presets}
        for preset_id, payload_hash in expected_presets.items():
            if actual_presets.get(preset_id) != payload_hash:
                errors.append(f"original preset payload hash changed: {preset_id}")
        plugins = list_plugins(client, root / "verify-plugins")
        enabled = {item["pluginId"]: item["enabled"] for item in plugins}
        payload_hashes = {item["pluginId"]: item.get("payloadHash") for item in plugins}
        for record in snapshot.get("plugins", []):
            if enabled.get(record["pluginId"]) is not bool(record["enabled"]):
                errors.append(f"final plugin enabled-state mismatch: {record['pluginId']}")
            if payload_hashes.get(record["pluginId"]) != record.get("payloadHash"):
                errors.append(f"original plugin payload hash changed: {record['pluginId']}")
        if runner_plugin in enabled and enabled[runner_plugin] is not False:
            errors.append("runner plugin remained enabled")
        runtime = mcp_tool(
            client,
            root / "verify-plugin-runtime.json",
            "tavo_plugin_get_runtime_contributions",
            {},
        )
        runtime_payload = response_payload(runtime)
        if not ok_response(runtime) or stable_hash(runtime_payload) != snapshot.get("pluginRuntimeHash"):
            errors.append("plugin runtime contributions did not return to the original hash")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"final restore verification failed: {exc!r}")
    passed = not errors
    durable_json(
        root / "result.json",
        {"reason": reason, "finishedAt": now_utc(), "errors": errors, "passed": passed},
    )
    return passed


def isolate_plugin_runtime(
    client: TavoMcp,
    artifact_dir: Path,
    snapshot: dict[str, Any],
    run_id: str,
    device: str,
) -> None:
    root = artifact_dir / "runtime-state" / "plugin-isolation"
    runner_plugin = plugin_identity(run_id)
    records = list_plugins(client, root / "inventory-before")
    current_ids = {item["pluginId"] for item in records}
    expected_ids = {str(item["pluginId"]) for item in snapshot.get("plugins", [])} | {runner_plugin}
    if current_ids != expected_ids:
        raise RuntimeError(
            "Plugin inventory drifted after the original snapshot; refusing to toggle an unknown concurrent plugin."
        )
    for record in snapshot.get("plugins", []):
        set_plugin_enabled(
            client,
            root / "disable-originals" / safe_name(str(record["pluginId"])),
            str(record["pluginId"]),
            False,
        )
    set_plugin_enabled(client, root / "enable-runner", runner_plugin, True)
    time.sleep(8)
    foreground_tavo(device, root / "foreground", settle_seconds=3)
    runtime = mcp_tool(
        client,
        root / "runtime.json",
        "tavo_plugin_get_runtime_contributions",
        {},
    )
    payload = response_payload(runtime)
    ids = runtime_plugin_ids(payload)
    passed = ok_response(runtime) and ids == {runner_plugin}
    durable_json(
        root / "result.json",
        {"runnerPluginId": runner_plugin, "runtimePluginIds": sorted(ids), "passed": passed},
    )
    if not passed:
        raise RuntimeError("Plugin isolation did not leave exactly the runner plugin active.")


ASSET_TOOLS = {
    "character": ("tavo_character_search", "tavo_character_create", "tavo_character_get", "character"),
    "lorebook": ("tavo_lorebook_search", "tavo_lorebook_create", "tavo_lorebook_get", "lorebook"),
    "regex": ("tavo_regex_search", "tavo_regex_create", "tavo_regex_get", "regex"),
    "preset": ("tavo_preset_search", "tavo_preset_create", "tavo_preset_get", "preset"),
}


def ensure_asset(
    client: TavoMcp,
    artifact_dir: Path,
    ledger: OwnershipLedger,
    run_id: str,
    kind: str,
    key: str,
    payload: dict[str, Any],
    required_strings: list[str],
) -> dict[str, Any]:
    if kind not in ASSET_TOOLS:
        raise RuntimeError(f"Unsupported asset kind: {kind}")
    _, create_tool, get_tool, argument_key = ASSET_TOOLS[kind]
    name = str(payload["name"])
    root = artifact_dir / "setup" / kind / safe_name(key)
    before = exact_search(client, root / "search-before", kind, name)
    if len(before) > 1:
        raise RuntimeError(f"Multiple exact {kind} objects exist for {name}.")
    if before:
        raise RuntimeError(f"Collision: exact {kind} object already exists for {name}; refusing reuse.")
    dry_arguments = {
        argument_key: payload,
        "dryRun": True,
        "clientRequestId": f"cfm-{safe_name(run_id)}-{kind}-{safe_name(key)}-dry",
    }
    dry = mcp_tool(client, root / "create-dry-run.json", create_tool, dry_arguments)
    after_dry = exact_search(client, root / "search-after-dry-run", kind, name)
    if not ok_response(dry) or after_dry:
        raise RuntimeError(f"{kind} create dry-run changed state for {name}.")
    actual_arguments = {**dry_arguments, "dryRun": False}
    actual_arguments["clientRequestId"] = f"cfm-{safe_name(run_id)}-{kind}-{safe_name(key)}-actual"
    actual = mcp_tool(client, root / "create-actual.json", create_tool, actual_arguments)
    asset_id = object_id(actual)
    if not ok_response(actual) or asset_id < 1:
        raise RuntimeError(f"Could not create {kind} {name}.")
    readback = mcp_tool(client, root / "readback.json", get_tool, {"id": asset_id})
    parsed = response_payload(readback)
    rendered = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    failures = [value for value in [name, *required_strings] if value not in rendered]
    field_failures = payload_mismatches(payload, asset_content_payload(kind, parsed))
    if not ok_response(readback) or int(parsed.get("id") or 0) != asset_id or failures or field_failures:
        durable_json(
            root / "readback-failure.json",
            {"missingStrings": failures, "fieldMismatches": field_failures, "payload": parsed},
        )
        raise RuntimeError(f"{kind} {name} failed exact readback validation.")
    final_matches = exact_search(client, root / "search-after-actual", kind, name)
    if len(final_matches) != 1 or int(final_matches[0].get("id") or 0) != asset_id:
        raise RuntimeError(f"{kind} {name} is not uniquely searchable after creation.")
    if kind == "preset" and parsed.get("active") is not False:
        raise RuntimeError(f"New/reconciled runner preset {name} unexpectedly became active during setup.")
    ledger.claim(
        kind,
        asset_id,
        key=key,
        name=name,
        retained=True,
        createdByThisInvocation=True,
        expectedPayload=payload,
        payloadHash=stable_hash(parsed),
    )
    return {
        "id": asset_id,
        "key": key,
        "name": name,
        "payloadHash": stable_hash(parsed),
        "expectedPayload": payload,
        "reconciled": False,
    }


def ensure_chat(
    client: TavoMcp,
    artifact_dir: Path,
    ledger: OwnershipLedger,
    run_id: str,
    profile: ChatProfile,
    character_id: int,
    preset_id: int,
    lorebook_id: int | None,
    regex_id: int | None,
) -> dict[str, Any]:
    name = f"Codex CFM {run_id} Chat {profile.key}"
    root = artifact_dir / "setup" / "chat" / safe_name(profile.key)
    payload: dict[str, Any] = {
        "title": name,
        "characterIds": [character_id],
        "presetId": preset_id,
        "lorebookIds": [lorebook_id] if lorebook_id else [],
        "regexIds": [regex_id] if regex_id else [],
    }
    before = exact_search(client, root / "search-before", "chat", name)
    if len(before) > 1:
        raise RuntimeError(f"Multiple exact runner chats exist for {name}.")
    if before:
        raise RuntimeError(f"Collision: exact runner chat already exists for {name}; refusing reuse.")
    dry_args = {
        "chat": payload,
        "dryRun": True,
        "clientRequestId": f"cfm-{safe_name(run_id)}-chat-{safe_name(profile.key)}-dry",
    }
    dry = mcp_tool(client, root / "create-dry-run.json", "tavo_chat_create", dry_args)
    after_dry = exact_search(client, root / "search-after-dry-run", "chat", name)
    if not ok_response(dry) or after_dry:
        raise RuntimeError(f"Chat create dry-run changed state for {name}.")
    actual_args = {**dry_args, "dryRun": False}
    actual_args["clientRequestId"] = f"cfm-{safe_name(run_id)}-chat-{safe_name(profile.key)}-actual"
    actual = mcp_tool(client, root / "create-actual.json", "tavo_chat_create", actual_args)
    chat_id = object_id(actual)
    if not ok_response(actual) or chat_id < 1:
        raise RuntimeError(f"Could not create runner chat {name}.")
    readback = mcp_tool(
        client,
        root / "readback.json",
        "tavo_chat_get",
        {"id": chat_id, "includeMessages": False},
    )
    parsed = response_payload(readback)
    binding_failures = {
        key: {"expected": expected, "actual": parsed.get(key)}
        for key, expected in payload.items()
        if parsed.get(key) != expected
    }
    if not ok_response(readback) or int(parsed.get("id") or 0) != chat_id or binding_failures:
        durable_json(root / "binding-failure.json", {"failures": binding_failures, "readback": parsed})
        raise RuntimeError(f"Runner chat {name} failed binding readback.")
    final_matches = exact_search(client, root / "search-after-actual", "chat", name)
    if len(final_matches) != 1 or int(final_matches[0].get("id") or 0) != chat_id:
        raise RuntimeError(f"Runner chat {name} is not uniquely searchable after creation.")
    ledger.claim(
        "chat",
        chat_id,
        key=profile.key,
        name=name,
        retained=True,
        createdByThisInvocation=True,
        bindingHash=stable_hash(payload),
        expectedPayload=payload,
    )
    return {
        "id": chat_id,
        "key": profile.key,
        "name": name,
        "payload": payload,
        "payloadHash": stable_hash(parsed),
        "reconciled": False,
    }


def plugin_action_labels(run_id: str) -> dict[str, str]:
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:6].upper()
    return {
        "lore-create": f"CFM {suffix} Lore Create",
        "lore-read": f"CFM {suffix} Lore Read",
        "lore-update": f"CFM {suffix} Lore Update",
        "lore-delete": f"CFM {suffix} Lore Delete Probe",
        "thread-write-a": f"CFM {suffix} Thread Write A",
        "thread-write-b": f"CFM {suffix} Thread Write B",
        "thread-read": f"CFM {suffix} Thread Read",
    }


def plugin_source(run_id: str, allow_deletes: bool, markers: dict[str, str]) -> tuple[dict[str, Any], str]:
    plugin_id = plugin_identity(run_id)
    labels = plugin_action_labels(run_id)
    config = {
        "runId": run_id,
        "allowDeletes": allow_deletes,
        "variableKey": f"cfm_lore_id_{safe_name(run_id)}",
        "threadVariableKey": f"cfm_thread_value_{safe_name(run_id)}",
        "threadAuditVariableKey": f"cfm_thread_audit_id_{safe_name(run_id)}",
        "loreName": f"Codex CFM {run_id} TavoJS Lore",
        "loreUpdatedName": f"Codex CFM {run_id} TavoJS Lore Updated",
        "loreTombstoneName": f"Codex CFM {run_id} TavoJS Lore Retained Tombstone",
        "entryIdentifier": f"cfm-{safe_name(run_id)}-tavojs-entry",
        "markers": markers,
    }
    action_items = [{"id": action_id, "label": label} for action_id, label in labels.items()]
    manifest = {
        "id": plugin_id,
        "name": f"Codex Cross Feature Matrix {run_id}",
        "version": "1.0.0",
        "specVersion": 1,
        "entry": "entry.js",
        "author": "Codex",
        "description": "Retained real-phone cross-feature TavoJS evidence plugin.",
        "permissions": ["input", "message", "variable"],
        "contributes": {"inputActions": action_items},
    }
    template = r'''const C = __CONFIG__;

function emit(kind, value) {
  tavo.input.set(`[CFM:${C.runId}:${kind}]${JSON.stringify(value)}`);
}

function fail(kind, error) {
  emit(kind, { ok: false, error: String(error && error.message ? error.message : error) });
}

function loreId() {
  return Number(tavo.get(C.variableKey, 'chat') || 0);
}

function assertBook(book, expectedName, expectedMarker) {
  if (!book || Number(book.id || 0) !== loreId()) throw new Error('runner lorebook identity mismatch');
  if (book.name !== expectedName) throw new Error('runner lorebook name mismatch');
  if (!Array.isArray(book.entries) || book.entries.length !== 1) throw new Error('runner lorebook entry count mismatch');
  const entry = book.entries[0];
  if (!entry || entry.identifier !== C.entryIdentifier) throw new Error('runner lorebook entry identifier mismatch');
  if (!String(entry.content || '').includes(expectedMarker)) throw new Error('runner lorebook marker mismatch');
  return entry;
}

function makeEntry(content) {
  return {
    identifier: C.entryIdentifier,
    name: 'CFM TavoJS CRUD entry',
    content,
    strategy: 'constant',
    injectionPosition: 'lorebookBefore',
    injectionDepth: 0,
    injectionRole: 'system',
    keywords: [],
    secondaryKeywords: [],
    secondaryKeywordStrategy: 'none',
    scanDepth: 10,
    caseSensitive: false,
    matchWholeWord: false,
    probability: 100,
    sticky: 0,
    cooldown: 0,
    delay: 0,
    enabled: true,
  };
}

tavo.plugin.onInputAction('lore-create', async () => {
  try {
    const chat = await tavo.chat.current();
    const id = await tavo.lorebook.create({
      name: C.loreName,
      entries: [makeEntry(`TavoJS create evidence: ${C.markers['crud-created']}`)],
    });
    tavo.set(C.variableKey, id, 'chat');
    const readback = await tavo.lorebook.get(id);
    assertBook(readback, C.loreName, C.markers['crud-created']);
    emit('lore-create', { ok: Boolean(id && readback), id, chatId: chat && chat.id, name: readback.name, identifier: readback.entries[0].identifier });
  } catch (error) { fail('lore-create', error); }
});

tavo.plugin.onInputAction('lore-read', async () => {
  try {
    const id = loreId();
    const readback = await tavo.lorebook.get(id);
    assertBook(readback, C.loreName, C.markers['crud-created']);
    emit('lore-read', { ok: true, id, name: readback.name, entries: readback.entries.length, identifier: readback.entries[0].identifier });
  } catch (error) { fail('lore-read', error); }
});

tavo.plugin.onInputAction('lore-update', async () => {
  try {
    const id = loreId();
    const book = await tavo.lorebook.get(id);
    assertBook(book, C.loreName, C.markers['crud-created']);
    book.name = C.loreUpdatedName;
    book.entries = [makeEntry(`TavoJS update evidence: ${C.markers['crud-updated']}`)];
    const updateReturn = await tavo.lorebook.update(book);
    const readback = await tavo.lorebook.get(id);
    assertBook(readback, C.loreUpdatedName, C.markers['crud-updated']);
    emit('lore-update', {
      ok: true,
      id,
      updateReturn: updateReturn ?? null,
      successAuthority: 'stable-readback',
      name: readback.name,
      identifier: readback.entries[0].identifier,
    });
  } catch (error) { fail('lore-update', error); }
});

tavo.plugin.onInputAction('lore-delete', async () => {
  try {
    const id = loreId();
    let finalMarker = C.markers['crud-tombstone'];
    let deleted = false;
    let deleteReturn = null;
    const before = await tavo.lorebook.get(id);
    assertBook(before, C.loreUpdatedName, C.markers['crud-updated']);
    if (C.allowDeletes) {
      deleteReturn = await tavo.lorebook.delete(id);
      let absent = null;
      try { absent = await tavo.lorebook.get(id); } catch (_) { absent = null; }
      if (absent) throw new Error('TavoJS deleted lorebook still readable');
      deleted = true;
      finalMarker = C.markers['crud-delete-confirmed'];
    } else {
      const book = before;
      book.name = C.loreTombstoneName;
      const entry = makeEntry(`Retained delete substitute evidence: ${finalMarker}`);
      entry.enabled = false;
      book.entries = [entry];
      await tavo.lorebook.update(book);
      const retained = await tavo.lorebook.get(id);
      assertBook(retained, C.loreTombstoneName, finalMarker);
    }
    const auditMessageId = await tavo.message.append({ role: 'assistant', content: finalMarker, hidden: false });
    emit('lore-delete', {
      ok: Boolean(auditMessageId),
      id,
      deleted,
      deleteReturn: deleteReturn ?? null,
      successAuthority: deleted ? 'stable-not-found-readback' : 'stable-tombstone-readback',
      finalMarker,
      auditMessageId,
    });
  } catch (error) { fail('lore-delete', error); }
});

async function writeThread(value, kind) {
  try {
    const chat = await tavo.chat.current();
    tavo.set(C.threadVariableKey, value, 'chat');
    emit(kind, { ok: true, chatId: chat && chat.id, value, readback: tavo.get(C.threadVariableKey, 'chat') });
  } catch (error) { fail(kind, error); }
}

tavo.plugin.onInputAction('thread-write-a', async () => writeThread(C.markers['thread-a'], 'thread-write-a'));
tavo.plugin.onInputAction('thread-write-b', async () => writeThread(C.markers['thread-b'], 'thread-write-b'));

tavo.plugin.onInputAction('thread-read', async () => {
  try {
    const chat = await tavo.chat.current();
    const value = tavo.get(C.threadVariableKey, 'chat') ?? null;
    let auditMessageId = Number(tavo.get(C.threadAuditVariableKey, 'chat') || 0) || null;
    if (value === C.markers['thread-a'] && !auditMessageId) {
      auditMessageId = await tavo.message.append({
        role: 'assistant',
        content: `${C.markers['thread-summary']} value=${value} chat=${chat && chat.id}`,
        hidden: false,
      });
      tavo.set(C.threadAuditVariableKey, auditMessageId, 'chat');
    }
    emit('thread-read', { ok: true, chatId: chat && chat.id, value, auditMessageId });
  } catch (error) { fail('thread-read', error); }
});
'''
    actions = template.replace("__CONFIG__", json.dumps(config, ensure_ascii=False, separators=(",", ":")))
    return manifest, actions


def ensure_plugin(
    client: TavoMcp,
    artifact_dir: Path,
    ledger: OwnershipLedger,
    run_id: str,
    allow_deletes: bool,
    markers: dict[str, str],
) -> dict[str, Any]:
    root = artifact_dir / "setup" / "plugin"
    source_dir = artifact_dir / "sources" / "plugin"
    plugin_id = plugin_identity(run_id)
    manifest, actions = plugin_source(run_id, allow_deletes, markers)
    durable_text(source_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    durable_text(source_dir / "entry.js", actions)
    source_hash = stable_hash({"manifest": manifest, "entry": actions})
    matches = exact_search(client, root / "search-before", "plugin", plugin_id)
    if len(matches) > 1:
        raise RuntimeError(f"Multiple installed plugins have id {plugin_id}.")
    if matches:
        raise RuntimeError(f"Collision: plugin id {plugin_id} is already installed; refusing reuse.")
    validate = mcp_tool(
        client,
        root / "validate-manifest.json",
        "tavo_plugin_validate_manifest",
        {"manifest": manifest},
    )
    files = [
        {"path": "manifest.json", "text": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"},
        {"path": "entry.js", "text": actions},
    ]
    package_dry = mcp_tool(
        client,
        root / "package-dry-run.json",
        "tavo_plugin_package",
        {"files": files, "includeZipBase64": True, "dryRun": True},
    )
    package_actual = mcp_tool(
        client,
        root / "package-actual.json",
        "tavo_plugin_package",
        {"files": files, "includeZipBase64": True, "dryRun": False},
    )
    zip_base64 = response_payload(package_actual).get("zipBase64")
    if (
        not ok_response(validate)
        or not ok_response(package_dry)
        or not ok_response(package_actual)
        or not isinstance(zip_base64, str)
    ):
        raise RuntimeError("Could not validate/package the cross-feature runner plugin.")
    package_bytes = base64.b64decode(zip_base64)
    durable_bytes(source_dir / "plugin.tpg", package_bytes)
    install_dry = mcp_tool(
        client,
        root / "install-dry-run.json",
        "tavo_plugin_install",
        {"zipBase64": zip_base64, "dryRun": True},
    )
    after_dry = exact_search(client, root / "search-after-install-dry-run", "plugin", plugin_id)
    if not ok_response(install_dry) or after_dry:
        raise RuntimeError("Plugin install dry-run changed installed inventory.")
    install_actual = mcp_tool(
        client,
        root / "install-actual.json",
        "tavo_plugin_install",
        {"zipBase64": zip_base64, "dryRun": False},
    )
    if not ok_response(install_actual):
        raise RuntimeError("Could not install the cross-feature runner plugin.")
    readback = mcp_tool(client, root / "readback.json", "tavo_plugin_get", {"pluginId": plugin_id})
    parsed = response_payload(readback)
    rendered = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    missing_labels = [label for label in plugin_action_labels(run_id).values() if label not in rendered]
    missing_action_ids = [action_id for action_id in plugin_action_labels(run_id) if action_id not in rendered]
    critical_failures = payload_mismatches(
        {"pluginId": plugin_id, "name": manifest["name"]},
        parsed,
    )
    if not ok_response(readback) or missing_labels or missing_action_ids or critical_failures:
        durable_json(
            root / "plugin-readback-failure.json",
            {
                "missingLabels": missing_labels,
                "missingActionIds": missing_action_ids,
                "criticalFieldMismatches": critical_failures,
                "payload": parsed,
            },
        )
        raise RuntimeError("Runner plugin failed exact identity/action readback.")
    final_matches = exact_search(client, root / "search-after-install", "plugin", plugin_id)
    if len(final_matches) != 1:
        raise RuntimeError("Runner plugin is not uniquely searchable after install.")
    set_plugin_enabled(client, root / "disable-after-setup", plugin_id, False)
    ledger.claim(
        "plugin",
        plugin_id,
        name=manifest["name"],
        retained=True,
        enabledAfterRun=False,
        sourceHash=source_hash,
        packageSha256=hashlib.sha256(package_bytes).hexdigest(),
        createdByThisInvocation=True,
    )
    return {
        "pluginId": plugin_id,
        "name": manifest["name"],
        "sourceHash": source_hash,
        "packageSha256": hashlib.sha256(package_bytes).hexdigest(),
        "manifestHash": stable_hash(manifest),
        "actionLabels": plugin_action_labels(run_id),
        "reconciled": False,
    }


def prepare_registry(
    client: TavoMcp,
    artifact_dir: Path,
    ledger: OwnershipLedger,
    run_id: str,
    allow_deletes: bool,
    cases: list[CaseSpec],
) -> dict[str, Any]:
    markers = all_markers(run_id, allow_deletes)
    character_payload = character_definition(run_id, markers)
    character = ensure_asset(
        client,
        artifact_dir,
        ledger,
        run_id,
        "character",
        "matrix-character",
        character_payload,
        [
            markers["greeting-first"],
            markers["greeting-alt-a"],
            markers["greeting-alt-b"],
            markers["message-example"],
        ],
    )
    lorebooks: dict[str, Any] = {}
    for key, payload in lorebook_definitions(run_id, markers).items():
        required = [str(entry["content"]).split("Cross-feature evidence code: ", 1)[-1].split(".", 1)[0] for entry in payload["entries"]]
        lorebooks[key] = ensure_asset(
            client,
            artifact_dir,
            ledger,
            run_id,
            "lorebook",
            key,
            payload,
            required,
        )
    regexes: dict[str, Any] = {}
    for key, payload in regex_definitions(run_id, markers).items():
        regexes[key] = ensure_asset(
            client,
            artifact_dir,
            ledger,
            run_id,
            "regex",
            key,
            payload,
            [markers["regex-raw"], markers["regex-transformed"]],
        )
    presets: dict[str, Any] = {}
    for key, payload in preset_definitions(run_id, markers).items():
        required = [f"cfm-main-{safe_name(run_id)}"]
        if key == "absolute-0":
            required.append(markers["preset-depth-0"])
        if key == "absolute-3":
            required.append(markers["preset-depth-3"])
        presets[key] = ensure_asset(
            client,
            artifact_dir,
            ledger,
            run_id,
            "preset",
            key,
            payload,
            required,
        )
    plugin = ensure_plugin(client, artifact_dir, ledger, run_id, allow_deletes, markers)
    chats: dict[str, Any] = {}
    for key, profile in sorted(chat_profiles(cases).items()):
        chats[key] = ensure_chat(
            client,
            artifact_dir,
            ledger,
            run_id,
            profile,
            int(character["id"]),
            int(presets[profile.preset_key]["id"]),
            int(lorebooks[profile.lorebook_key]["id"]) if profile.lorebook_key else None,
            int(regexes[profile.regex_key]["id"]) if profile.regex_key else None,
        )
    registry = {
        "schemaVersion": "1.0.0",
        "runId": run_id,
        "preparedAt": now_utc(),
        "allowRunnerOwnedDeletes": allow_deletes,
        "markers": markers,
        "character": character,
        "lorebooks": lorebooks,
        "regexes": regexes,
        "presets": presets,
        "plugin": plugin,
        "chats": chats,
    }
    registry["registryHash"] = stable_hash(registry)
    durable_json(artifact_dir / "registry.json", registry)
    return registry


def ledger_record(ledger: OwnershipLedger, kind: str, identity: int | str) -> dict[str, Any]:
    return ledger.require_owned(kind, identity)


def read_owned_object(
    context: RuntimeContext,
    kind: str,
    identity: int | str,
    step_dir: Path,
) -> dict[str, Any]:
    record = ledger_record(context.ledger, kind, identity)
    if kind == "plugin":
        response = mcp_tool(
            context.client,
            step_dir / "owned-plugin-readback.json",
            "tavo_plugin_get",
            {"pluginId": str(identity)},
        )
        payload = response_payload(response)
        if not ok_response(response) or payload.get("pluginId") != identity:
            raise RuntimeError(f"Owned plugin {identity!r} failed pre-mutation readback.")
        if record.get("name") and payload.get("name") != record.get("name"):
            raise RuntimeError(f"Owned plugin {identity!r} changed name before mutation.")
        return payload
    get_tools = {
        "character": "tavo_character_get",
        "lorebook": "tavo_lorebook_get",
        "regex": "tavo_regex_get",
        "preset": "tavo_preset_get",
        "chat": "tavo_chat_get",
    }
    if kind not in get_tools:
        raise RuntimeError(f"Unsupported owned-object readback kind: {kind}")
    arguments: dict[str, Any] = {"id": int(identity)}
    if kind == "chat":
        arguments["includeMessages"] = False
    response = mcp_tool(
        context.client,
        step_dir / f"owned-{kind}-readback.json",
        get_tools[kind],
        arguments,
    )
    payload = response_payload(response)
    if not ok_response(response) or int(payload.get("id") or 0) != int(identity):
        raise RuntimeError(f"Owned {kind} {identity!r} failed pre-mutation readback.")
    expected_payload = record.get("expectedPayload")
    if isinstance(expected_payload, dict):
        ignored = {"revision", "updatedAt"}
        if kind == "preset":
            ignored.add("active")
        comparable_expected = {key: value for key, value in expected_payload.items() if key not in ignored}
        comparable_payload = {key: value for key, value in payload.items() if key not in ignored}
        failures = payload_mismatches(comparable_expected, comparable_payload)
        if failures:
            durable_json(step_dir / f"owned-{kind}-payload-mismatch.json", {"mismatches": failures, "payload": payload})
            raise RuntimeError(f"Owned {kind} {identity!r} payload drifted before mutation.")
    return payload


def verify_case_assets(context: RuntimeContext, case: CaseSpec, step_dir: Path) -> None:
    chat = context.registry["chats"][case.chat_key]
    read_owned_object(context, "chat", int(chat["id"]), step_dir / "chat")
    preset = context.registry["presets"][case.preset_key]
    read_owned_object(context, "preset", int(preset["id"]), step_dir / "preset")
    if case.lorebook_key:
        lorebook = context.registry["lorebooks"][case.lorebook_key]
        read_owned_object(context, "lorebook", int(lorebook["id"]), step_dir / "lorebook")
    if case.regex_key:
        regex = context.registry["regexes"][case.regex_key]
        read_owned_object(context, "regex", int(regex["id"]), step_dir / "regex")


def append_owned_message(
    context: RuntimeContext,
    chat_id: int,
    message: dict[str, Any],
    step_dir: Path,
    request_key: str,
) -> dict[str, Any]:
    read_owned_object(context, "chat", chat_id, step_dir / "chat-precondition")
    before = all_messages(context.client, chat_id, step_dir / "before", "messages.json")
    request_id = f"cfm-{safe_name(context.run_id)}-{safe_name(request_key)}"
    dry = mcp_tool(
        context.client,
        step_dir / "append-dry-run.json",
        "tavo_message_append",
        {"chatId": chat_id, "message": message, "dryRun": True, "clientRequestId": request_id + "-dry"},
    )
    after_dry = all_messages(context.client, chat_id, step_dir / "after-dry", "messages.json")
    if not ok_response(dry) or stable_hash(message_payload_snapshot(after_dry)) != stable_hash(message_payload_snapshot(before)):
        raise RuntimeError("Message append dry-run changed chat history.")
    actual = mcp_tool(
        context.client,
        step_dir / "append-actual.json",
        "tavo_message_append",
        {"chatId": chat_id, "message": message, "dryRun": False, "clientRequestId": request_id + "-actual"},
    )
    parsed = response_payload(actual)
    message_id = int(parsed.get("id") or 0)
    if not ok_response(actual) or message_id < 1:
        raise RuntimeError("Message append did not return a persistent id.")
    readback = mcp_tool(
        context.client,
        step_dir / "message-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": message_id},
    )
    payload = response_payload(readback)
    mismatches = payload_mismatches({"id": message_id, **message}, payload)
    after = all_messages(context.client, chat_id, step_dir / "after", "messages.json")
    new_ids = {int(item.get("id") or 0) for item in after} - {int(item.get("id") or 0) for item in before}
    if not ok_response(readback) or mismatches or len(after) != len(before) + 1 or new_ids != {message_id}:
        durable_json(step_dir / "append-validation-failure.json", {"mismatches": mismatches, "newIds": sorted(new_ids)})
        raise RuntimeError("Message append did not persist exactly one full payload.")
    context.ledger.claim(
        "message",
        message_id,
        chatId=chat_id,
        requestKey=request_key,
        expectedPayload={"id": message_id, **message},
        payloadHash=stable_hash(payload),
        retained=True,
    )
    return payload


def read_owned_message(context: RuntimeContext, chat_id: int, message_id: int, step_dir: Path) -> dict[str, Any]:
    record = ledger_record(context.ledger, "message", message_id)
    if int(record.get("chatId") or 0) != chat_id:
        raise RuntimeError("Owned message ledger chat id mismatch.")
    read_owned_object(context, "chat", chat_id, step_dir / "chat-precondition")
    response = mcp_tool(
        context.client,
        step_dir / "message-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": message_id},
    )
    payload = response_payload(response)
    expected = record.get("expectedPayload")
    mismatches = payload_mismatches(expected, payload) if isinstance(expected, dict) else []
    if not ok_response(response) or int(payload.get("id") or 0) != message_id or mismatches:
        durable_json(step_dir / "owned-message-mismatch.json", {"mismatches": mismatches, "payload": payload})
        raise RuntimeError("Owned message failed pre-mutation readback.")
    return payload


def update_owned_message(
    context: RuntimeContext,
    chat_id: int,
    message_id: int,
    changes: dict[str, Any],
    step_dir: Path,
    request_key: str,
) -> dict[str, Any]:
    before = read_owned_message(context, chat_id, message_id, step_dir / "precondition")
    expected = {**before, **changes, "id": message_id}
    message_payload = {"id": message_id, **changes}
    base = {
        "chatId": chat_id,
        "message": message_payload,
        "dryRun": True,
        "clientRequestId": f"cfm-{safe_name(context.run_id)}-{safe_name(request_key)}-dry",
    }
    if isinstance(before.get("revision"), str) and before["revision"]:
        base["expectedRevision"] = before["revision"]
    dry = mcp_tool(context.client, step_dir / "update-dry-run.json", "tavo_message_update", base)
    after_dry = mcp_tool(
        context.client,
        step_dir / "after-dry-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": message_id},
    )
    if not ok_response(dry) or stable_hash(response_payload(after_dry)) != stable_hash(before):
        raise RuntimeError("Message update dry-run changed the stored message.")
    actual_arguments = {**base, "dryRun": False}
    actual_arguments["clientRequestId"] = f"cfm-{safe_name(context.run_id)}-{safe_name(request_key)}-actual"
    actual = mcp_tool(context.client, step_dir / "update-actual.json", "tavo_message_update", actual_arguments)
    final = mcp_tool(
        context.client,
        step_dir / "final-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": message_id},
    )
    payload = response_payload(final)
    required = {
        key: value
        for key, value in expected.items()
        if key not in {"revision", "updatedAt"}
    }
    mismatches = payload_mismatches(required, payload)
    if not ok_response(actual) or not ok_response(final) or mismatches:
        durable_json(step_dir / "update-validation-failure.json", {"mismatches": mismatches, "payload": payload})
        raise RuntimeError("Message update full readback failed.")
    context.ledger.claim(
        "message",
        message_id,
        chatId=chat_id,
        requestKey=request_key,
        expectedPayload=payload,
        payloadHash=stable_hash(payload),
        retained=True,
    )
    return payload


def delete_owned_message(
    context: RuntimeContext,
    chat_id: int,
    message_id: int,
    retained_marker: str,
    step_dir: Path,
) -> dict[str, Any]:
    before = read_owned_message(context, chat_id, message_id, step_dir / "precondition")
    base: dict[str, Any] = {"chatId": chat_id, "id": message_id, "dryRun": True}
    if isinstance(before.get("revision"), str) and before["revision"]:
        base["expectedRevision"] = before["revision"]
    base["clientRequestId"] = f"cfm-{safe_name(context.run_id)}-message-delete-{message_id}-dry"
    dry = mcp_tool(context.client, step_dir / "delete-dry-run.json", "tavo_message_delete", base)
    after_dry = read_owned_message(context, chat_id, message_id, step_dir / "after-dry")
    if not ok_response(dry) or stable_hash(after_dry) != stable_hash(before):
        raise RuntimeError("Message delete dry-run changed the stored message.")
    if not context.allow_deletes:
        retained = update_owned_message(
            context,
            chat_id,
            message_id,
            {"content": retained_marker, "hidden": False},
            step_dir / "retained-substitute",
            "message-delete-retained",
        )
        return {"deleted": False, "retained": True, "readback": retained}
    ledger_record(context.ledger, "message", message_id)
    actual_arguments = {**base, "dryRun": False}
    actual_arguments["clientRequestId"] = f"cfm-{safe_name(context.run_id)}-message-delete-{message_id}-actual"
    actual = mcp_tool(context.client, step_dir / "delete-actual.json", "tavo_message_delete", actual_arguments)
    absent = mcp_tool(
        context.client,
        step_dir / "not-found-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": message_id},
    )
    messages = all_messages(context.client, chat_id, step_dir / "after-delete", "messages.json")
    still_present = [item for item in messages if int(item.get("id") or 0) == message_id]
    absent_payload = response_payload(absent)
    still_readable = ok_response(absent) and int(absent_payload.get("id") or 0) == message_id
    if not ok_response(actual) or still_readable or still_present:
        raise RuntimeError("Runner-owned message delete lacked a not-found/full-history readback.")
    context.ledger.claim("message", message_id, deleted=True, retained=False, deletedAt=now_utc())
    return {"deleted": True, "retained": False, "notFoundReadback": response_payload(absent)}


def update_owned_lorebook_entry(
    context: RuntimeContext,
    lorebook_key: str,
    entry: dict[str, Any],
    step_dir: Path,
    request_key: str,
) -> dict[str, Any]:
    lorebook_id = int(context.registry["lorebooks"][lorebook_key]["id"])
    before = read_owned_object(context, "lorebook", lorebook_id, step_dir / "precondition")
    current_entries = before.get("entries") if isinstance(before.get("entries"), list) else []
    identifiers = [item.get("identifier") for item in current_entries if isinstance(item, dict)]
    if entry.get("identifier") not in identifiers:
        raise RuntimeError("Lorebook entry mutation identifier is not present in the owned book.")
    base: dict[str, Any] = {
        "lorebookId": lorebook_id,
        "entry": entry,
        "dryRun": True,
        "clientRequestId": f"cfm-{safe_name(context.run_id)}-{safe_name(request_key)}-dry",
    }
    if isinstance(before.get("revision"), str) and before["revision"]:
        base["expectedRevision"] = before["revision"]
    dry = mcp_tool(context.client, step_dir / "upsert-dry-run.json", "tavo_lorebook_entry_upsert", base)
    after_dry = mcp_tool(
        context.client,
        step_dir / "after-dry-readback.json",
        "tavo_lorebook_get",
        {"id": lorebook_id},
    )
    if not ok_response(dry) or stable_hash(response_payload(after_dry)) != stable_hash(before):
        raise RuntimeError("Lorebook entry upsert dry-run changed the book.")
    actual_arguments = {**base, "dryRun": False}
    actual_arguments["clientRequestId"] = f"cfm-{safe_name(context.run_id)}-{safe_name(request_key)}-actual"
    actual = mcp_tool(context.client, step_dir / "upsert-actual.json", "tavo_lorebook_entry_upsert", actual_arguments)
    final = mcp_tool(context.client, step_dir / "final-readback.json", "tavo_lorebook_get", {"id": lorebook_id})
    payload = response_payload(final)
    matches = [
        item
        for item in (payload.get("entries") or [])
        if isinstance(item, dict) and item.get("identifier") == entry.get("identifier")
    ]
    mismatches = payload_mismatches(entry, matches[0]) if len(matches) == 1 else ["entry missing or duplicated"]
    if not ok_response(actual) or not ok_response(final) or mismatches:
        durable_json(step_dir / "upsert-validation-failure.json", {"mismatches": mismatches, "payload": payload})
        raise RuntimeError("Lorebook entry upsert failed full readback.")
    context.ledger.claim(
        "lorebook",
        lorebook_id,
        expectedPayload=payload,
        payloadHash=stable_hash(payload),
        lastMutation=request_key,
    )
    return payload


def append_neutral_window(
    context: RuntimeContext,
    chat_id: int,
    step_dir: Path,
    key: str,
    exchanges: int = 2,
) -> list[int]:
    ids: list[int] = []
    for index in range(1, exchanges + 1):
        for role, suffix in (("user", "question"), ("assistant", "answer")):
            payload = append_owned_message(
                context,
                chat_id,
                {
                    "role": role,
                    "content": f"Neutral lifecycle window {key} {index} {suffix}; no evidence code is supplied.",
                    "hidden": False,
                },
                step_dir / f"{index:02d}-{role}",
                f"{key}-{index}-{role}",
            )
            ids.append(int(payload["id"]))
    return ids


def parse_plugin_action_output(text: str, run_id: str, action_id: str) -> dict[str, Any]:
    prefix = f"[CFM:{run_id}:{action_id}]"
    if not text.startswith(prefix):
        raise RuntimeError(f"Plugin action {action_id!r} returned an unexpected input prefix.")
    try:
        value = json.loads(text[len(prefix) :])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Plugin action {action_id!r} returned invalid JSON.") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeError(f"Plugin action {action_id!r} reported failure: {value!r}")
    return value


def plugin_permission_fragment(action_id: str, allow_deletes: bool) -> str | None:
    if action_id == "lore-create":
        return "是否允许创建世界书"
    if action_id == "lore-update":
        return "是否允许修改世界书"
    if action_id == "lore-delete":
        return "是否允许删除世界书" if allow_deletes else "是否允许修改世界书"
    return None


def permission_observation_record(
    action_id: str,
    expected_fragment: str | None,
    *,
    observed: bool,
    confirmed: bool,
    description: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    if observed and confirmed:
        observation = "prompt-observed-and-confirmed"
    elif observed:
        observation = "prompt-observed-not-confirmed"
    elif expected_fragment is None:
        observation = "not-applicable"
    else:
        observation = "prompt-not-observed"
    return {
        "actionId": action_id,
        "expected": expected_fragment is not None,
        "expectedPromptFragment": expected_fragment,
        "observed": observed,
        "confirmed": confirmed,
        "description": description,
        "attempt": attempt,
        "promptAbsent": bool(expected_fragment is not None and not observed),
        "observation": observation,
        "permissionGateVerified": False,
        "claimBoundary": (
            "This artifact records only whether one prompt was observed and confirmed. Prompt absence is not a "
            "permission-gate pass, and no denial/cancellation path was tested."
        ),
    }


def confirm_expected_plugin_permission(
    context: RuntimeContext,
    action_id: str,
    step_dir: Path,
) -> dict[str, Any]:
    expected = plugin_permission_fragment(action_id, context.allow_deletes)
    if expected is None:
        result = permission_observation_record(
            action_id,
            expected,
            observed=False,
            confirmed=False,
        )
        durable_json(step_dir / "result.json", result)
        return result
    deadline = time.time() + 6
    attempt = 0
    while time.time() < deadline:
        code, dump = run_ui_tool(
            ["dump", "--device", context.device, "--output", str(step_dir / f"ui-permission-{attempt}.xml")],
            step_dir / f"ui-permission-{attempt}.json",
        )
        if code != 0:
            raise RuntimeError("Could not inspect the expected plugin permission prompt.")
        nodes = dump.get("nodes") if isinstance(dump.get("nodes"), list) else []
        prompts = [
            node
            for node in nodes
            if isinstance(node, dict) and str(node.get("content-desc") or "").startswith("是否允许")
        ]
        if prompts:
            if len(prompts) != 1:
                raise RuntimeError("Plugin action exposed multiple permission prompts.")
            description = str(prompts[0].get("content-desc") or "")
            if expected not in description or context.run_id not in description:
                raise RuntimeError(f"Refusing unexpected plugin permission prompt: {description!r}")
            capture_phone(context.device, step_dir / f"prompt-{attempt}", "permission-before-confirm")
            tap_code, tap_payload = run_ui_tool(
                ["tap", "--device", context.device, "--content-desc", "确定", "--class", "android.widget.Button"],
                step_dir / "confirm-permission.json",
            )
            if tap_code != 0:
                raise RuntimeError(f"Could not confirm the expected plugin permission: {tap_payload}")
            result = permission_observation_record(
                action_id,
                expected,
                observed=True,
                confirmed=True,
                description=description,
                attempt=attempt,
            )
            durable_json(step_dir / "result.json", result)
            time.sleep(1.0)
            return result
        time.sleep(0.5)
        attempt += 1
    result = permission_observation_record(
        action_id,
        expected,
        observed=False,
        confirmed=False,
    )
    durable_json(step_dir / "result.json", result)
    return result


def invoke_plugin_action(
    context: RuntimeContext,
    chat_id: int,
    action_id: str,
    step_dir: Path,
) -> dict[str, Any]:
    plugin_id = str(context.registry["plugin"]["pluginId"])
    read_owned_object(context, "chat", chat_id, step_dir / "chat-precondition")
    read_owned_object(context, "plugin", plugin_id, step_dir / "plugin-precondition")
    if (step_dir / "action-intent.json").exists():
        raise RuntimeError("Unresolved non-idempotent plugin action intent exists; refusing to click again.")
    set_current_chat(context.client, step_dir / "set-chat", chat_id, f"{context.run_id}-{action_id}")
    ensure_default_greeting(context, chat_id, step_dir / "ensure-default-greeting")
    foreground_tavo(context.device, step_dir / "foreground", settle_seconds=2.5)
    before_input = mcp_tool(context.client, step_dir / "input-before.json", "tavo_input_get", {})
    if not ok_response(before_input):
        raise RuntimeError("Could not read input before plugin action.")
    cleared = mcp_tool(context.client, step_dir / "input-clear.json", "tavo_input_clear", {})
    blank = mcp_tool(context.client, step_dir / "input-clear-readback.json", "tavo_input_get", {})
    if not ok_response(cleared) or not ok_response(blank) or str(response_payload(blank).get("text") or ""):
        raise RuntimeError("Could not prove blank input before plugin action.")
    label = str(context.registry["plugin"]["actionLabels"][action_id])
    intent = {
        "runId": context.run_id,
        "planHash": context.plan_hash,
        "scriptHash": context.script_hash,
        "pluginId": plugin_id,
        "chatId": chat_id,
        "actionId": action_id,
        "label": label,
        "status": "prepared-before-non-idempotent-ui-action",
        "preparedAt": now_utc(),
    }
    durable_json(step_dir / "action-intent.json", intent)
    tap_plugin_action(context.device, label, step_dir / "ui-action")
    permission_observation = confirm_expected_plugin_permission(context, action_id, step_dir / "permission")
    deadline = time.time() + 20
    output_text = ""
    poll = 0
    while time.time() < deadline:
        time.sleep(0.8)
        readback = mcp_tool(
            context.client,
            step_dir / f"input-poll-{poll:03d}.json",
            "tavo_input_get",
            {},
        )
        poll += 1
        if ok_response(readback):
            output_text = str(response_payload(readback).get("text") or "")
            if output_text.startswith(f"[CFM:{context.run_id}:{action_id}]"):
                break
    value = parse_plugin_action_output(output_text, context.run_id, action_id)
    durable_json(
        step_dir / "action-result.json",
        {
            **intent,
            "status": "completed",
            "output": value,
            "permissionObservation": permission_observation,
            "completedAt": now_utc(),
        },
    )
    return {**value, "permissionObservation": permission_observation}


def assert_tavojs_lorebook(
    context: RuntimeContext,
    lorebook_id: int,
    expected_name: str,
    expected_marker: str,
    step_dir: Path,
) -> dict[str, Any]:
    ledger_record(context.ledger, "lorebook", lorebook_id)
    response = mcp_tool(context.client, step_dir / "readback.json", "tavo_lorebook_get", {"id": lorebook_id})
    payload = response_payload(response)
    failures = tavojs_lorebook_payload_failures(
        payload,
        lorebook_id,
        expected_name,
        expected_marker,
        context.run_id,
    )
    if not ok_response(response) or failures:
        durable_json(step_dir / "payload-failure.json", {"failures": failures, "payload": payload})
        raise RuntimeError("TavoJS lorebook readback lost its run-specific name, identifier, or marker.")
    return payload


def tavojs_lorebook_payload_failures(
    payload: dict[str, Any],
    lorebook_id: int,
    expected_name: str,
    expected_marker: str,
    run_id: str,
) -> list[str]:
    expected_identifier = f"cfm-{safe_name(run_id)}-tavojs-entry"
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    matches = [item for item in entries if isinstance(item, dict) and item.get("identifier") == expected_identifier]
    failures: list[str] = []
    if int(payload.get("id") or 0) != lorebook_id:
        failures.append("id mismatch")
    if payload.get("name") != expected_name:
        failures.append("name mismatch")
    if len(entries) != 1 or len(matches) != 1:
        failures.append("entry count/identifier mismatch")
    elif expected_marker not in str(matches[0].get("content") or ""):
        failures.append("marker mismatch")
    return failures


def run_message_crud_prelude(context: RuntimeContext, chat_id: int, step_dir: Path) -> dict[str, Any]:
    markers = context.registry["markers"]
    created = append_owned_message(
        context,
        chat_id,
        {"role": "assistant", "content": markers["message-original"], "hidden": False},
        step_dir / "create",
        "message-crud-create",
    )
    message_id = int(created["id"])
    read_created = read_owned_message(context, chat_id, message_id, step_dir / "read-created")
    updated = update_owned_message(
        context,
        chat_id,
        message_id,
        {"content": markers["message-updated"], "hidden": False},
        step_dir / "update",
        "message-crud-update",
    )
    read_updated = read_owned_message(context, chat_id, message_id, step_dir / "read-updated")
    deleted = delete_owned_message(
        context,
        chat_id,
        message_id,
        markers["message-delete-retained"],
        step_dir / "delete",
    )
    if context.allow_deletes:
        audit = append_owned_message(
            context,
            chat_id,
            {"role": "assistant", "content": markers["message-delete-confirmed"], "hidden": False},
            step_dir / "delete-audit",
            "message-crud-delete-audit",
        )
    else:
        audit = deleted["readback"]
    result = {
        "messageId": message_id,
        "createReadHash": stable_hash(read_created),
        "updateReadHash": stable_hash(read_updated),
        "delete": deleted,
        "auditMessageId": int(audit["id"]),
        "passed": True,
    }
    durable_json(step_dir / "crud-result.json", result)
    return result


def run_plugin_crud_prelude(context: RuntimeContext, chat_id: int, step_dir: Path) -> dict[str, Any]:
    config = {
        "createdName": f"Codex CFM {context.run_id} TavoJS Lore",
        "updatedName": f"Codex CFM {context.run_id} TavoJS Lore Updated",
        "tombstoneName": f"Codex CFM {context.run_id} TavoJS Lore Retained Tombstone",
    }
    for label, name in config.items():
        collisions = exact_search(context.client, step_dir / "collision-check" / label, "lorebook", name)
        if collisions:
            raise RuntimeError(f"Collision: TavoJS CRUD lorebook name already exists: {name}")
    created_output = invoke_plugin_action(context, chat_id, "lore-create", step_dir / "create")
    lorebook_id = int(created_output.get("id") or 0)
    if lorebook_id < 1:
        raise RuntimeError("TavoJS lore create returned no persistent id.")
    created_response = mcp_tool(
        context.client,
        step_dir / "create" / "host-readback-before-claim.json",
        "tavo_lorebook_get",
        {"id": lorebook_id},
    )
    created_payload = response_payload(created_response)
    if not ok_response(created_response):
        raise RuntimeError("Host could not read the TavoJS-created lorebook.")
    created_failures = tavojs_lorebook_payload_failures(
        created_payload,
        lorebook_id,
        config["createdName"],
        context.registry["markers"]["crud-created"],
        context.run_id,
    )
    if created_failures:
        durable_json(
            step_dir / "create" / "host-readback-before-claim-failure.json",
            {"failures": created_failures, "payload": created_payload},
        )
        raise RuntimeError("Refusing to claim a TavoJS-created lorebook without run-specific payload proof.")
    context.ledger.claim(
        "lorebook",
        lorebook_id,
        key="plugin-tavojs-crud",
        name=config["createdName"],
        expectedPayload=created_payload,
        payloadHash=stable_hash(created_payload),
        createdByThisInvocation=True,
        retained=not context.allow_deletes,
    )
    created = assert_tavojs_lorebook(
        context,
        lorebook_id,
        config["createdName"],
        context.registry["markers"]["crud-created"],
        step_dir / "create" / "host-assert",
    )
    read_owned_object(context, "lorebook", lorebook_id, step_dir / "read" / "mutation-precondition")
    read_output = invoke_plugin_action(context, chat_id, "lore-read", step_dir / "read")
    if int(read_output.get("id") or 0) != lorebook_id:
        raise RuntimeError("TavoJS lore read returned a different id.")
    read_owned_object(context, "lorebook", lorebook_id, step_dir / "update" / "mutation-precondition")
    update_output = invoke_plugin_action(context, chat_id, "lore-update", step_dir / "update")
    if int(update_output.get("id") or 0) != lorebook_id:
        raise RuntimeError("TavoJS lore update returned a different id.")
    updated = assert_tavojs_lorebook(
        context,
        lorebook_id,
        config["updatedName"],
        context.registry["markers"]["crud-updated"],
        step_dir / "update" / "host-assert",
    )
    context.ledger.claim(
        "lorebook",
        lorebook_id,
        name=config["updatedName"],
        expectedPayload=updated,
        payloadHash=stable_hash(updated),
    )
    read_owned_object(context, "lorebook", lorebook_id, step_dir / "delete" / "mutation-precondition")
    delete_output = invoke_plugin_action(context, chat_id, "lore-delete", step_dir / "delete")
    if int(delete_output.get("id") or 0) != lorebook_id:
        raise RuntimeError("TavoJS lore delete/tombstone returned a different id.")
    if context.allow_deletes:
        ledger_record(context.ledger, "lorebook", lorebook_id)
        absent = mcp_tool(
            context.client,
            step_dir / "delete" / "host-not-found-readback.json",
            "tavo_lorebook_get",
            {"id": lorebook_id},
        )
        absent_payload = response_payload(absent)
        if ok_response(absent) and int(absent_payload.get("id") or 0) == lorebook_id:
            raise RuntimeError("TavoJS-deleted runner lorebook is still readable.")
        remaining = exact_search(context.client, step_dir / "delete" / "host-search-after", "lorebook", config["updatedName"])
        if remaining:
            raise RuntimeError("TavoJS-deleted runner lorebook remains searchable.")
        context.ledger.claim("lorebook", lorebook_id, deleted=True, retained=False, deletedAt=now_utc())
        final_lore = None
    else:
        final_lore = assert_tavojs_lorebook(
            context,
            lorebook_id,
            config["tombstoneName"],
            context.registry["markers"]["crud-tombstone"],
            step_dir / "delete" / "host-retained-readback",
        )
        context.ledger.claim(
            "lorebook",
            lorebook_id,
            name=config["tombstoneName"],
            expectedPayload=final_lore,
            payloadHash=stable_hash(final_lore),
            retained=True,
        )
    audit_message_id = int(delete_output.get("auditMessageId") or 0)
    if audit_message_id < 1:
        raise RuntimeError("TavoJS lore delete action returned no audit message id.")
    audit = mcp_tool(
        context.client,
        step_dir / "delete" / "audit-message-readback.json",
        "tavo_message_get",
        {"chatId": chat_id, "id": audit_message_id},
    )
    audit_payload = response_payload(audit)
    expected_marker = context.registry["markers"]["crud-delete-final"]
    if not ok_response(audit) or audit_payload.get("content") != expected_marker:
        raise RuntimeError("TavoJS lore delete audit message did not exactly match the final marker.")
    context.ledger.claim(
        "message",
        audit_message_id,
        chatId=chat_id,
        expectedPayload=audit_payload,
        payloadHash=stable_hash(audit_payload),
        retained=True,
    )
    result = {
        "lorebookId": lorebook_id,
        "createdHash": stable_hash(created),
        "updatedHash": stable_hash(updated),
        "finalHash": stable_hash(final_lore) if final_lore else None,
        "deleted": context.allow_deletes,
        "auditMessageId": audit_message_id,
        "permissionObservations": {
            "create": created_output.get("permissionObservation"),
            "read": read_output.get("permissionObservation"),
            "update": update_output.get("permissionObservation"),
            "delete": delete_output.get("permissionObservation"),
        },
        "passed": True,
    }
    durable_json(step_dir / "crud-result.json", result)
    return result


def run_thread_roundtrip_prelude(context: RuntimeContext, chat_a: int, chat_b: int, step_dir: Path) -> dict[str, Any]:
    markers = context.registry["markers"]

    def action(chat_id: int, action_id: str, name: str) -> dict[str, Any]:
        read_owned_object(context, "chat", chat_id, step_dir / name / "mutation-precondition")
        value = invoke_plugin_action(context, chat_id, action_id, step_dir / name)
        if int(value.get("chatId") or 0) != chat_id:
            raise RuntimeError(f"Thread action {name} returned the wrong chat id.")
        return value

    write_a = action(chat_a, "thread-write-a", "01-write-a")
    if write_a.get("value") != markers["thread-a"] or write_a.get("readback") != markers["thread-a"]:
        raise RuntimeError("Thread A write/readback failed.")
    write_b = action(chat_b, "thread-write-b", "02-write-b")
    if write_b.get("value") != markers["thread-b"] or write_b.get("readback") != markers["thread-b"]:
        raise RuntimeError("Thread B write/readback failed.")
    read_b_first = action(chat_b, "thread-read", "03-read-b-first")
    if read_b_first.get("value") != markers["thread-b"]:
        raise RuntimeError("Thread B first readback leaked another chat scope.")
    read_a = action(chat_a, "thread-read", "04-read-a")
    if read_a.get("value") != markers["thread-a"]:
        raise RuntimeError("Thread A readback leaked another chat scope.")
    audit_message_id = int(read_a.get("auditMessageId") or 0)
    if audit_message_id < 1:
        raise RuntimeError("Thread A readback created no audit message.")
    audit = mcp_tool(
        context.client,
        step_dir / "04-read-a" / "audit-message.json",
        "tavo_message_get",
        {"chatId": chat_a, "id": audit_message_id},
    )
    audit_payload = response_payload(audit)
    if (
        not ok_response(audit)
        or markers["thread-summary"] not in str(audit_payload.get("content") or "")
        or markers["thread-a"] not in str(audit_payload.get("content") or "")
    ):
        raise RuntimeError("Thread A audit message readback failed.")
    context.ledger.claim(
        "message",
        audit_message_id,
        chatId=chat_a,
        expectedPayload=audit_payload,
        payloadHash=stable_hash(audit_payload),
        retained=True,
    )
    read_b_second = action(chat_b, "thread-read", "05-read-b-second")
    if read_b_second.get("value") != markers["thread-b"]:
        raise RuntimeError("Thread B second readback changed after returning from A.")
    final_a = action(chat_a, "thread-read", "06-read-a-final")
    if final_a.get("value") != markers["thread-a"]:
        raise RuntimeError("Thread A final readback changed after second B visit.")
    if int(final_a.get("auditMessageId") or 0) != audit_message_id:
        raise RuntimeError("Thread A final read created or returned a different audit message.")
    set_current_chat(context.client, step_dir / "07-final-chat-a", chat_a, f"{context.run_id}-thread-final-a")
    result = {
        "chatA": chat_a,
        "chatB": chat_b,
        "writeA": write_a,
        "writeB": write_b,
        "readBFirst": read_b_first,
        "readA": read_a,
        "readBSecond": read_b_second,
        "readAFinal": final_a,
        "auditMessageId": audit_message_id,
        "passed": True,
    }
    durable_json(step_dir / "thread-roundtrip-result.json", result)
    return result


def activate_owned_preset(context: RuntimeContext, preset_id: int, step_dir: Path, request_key: str) -> None:
    read_owned_object(context, "preset", preset_id, step_dir / "precondition")
    activate_preset(context.client, step_dir / "activate", preset_id, request_key)
    final = mcp_tool(context.client, step_dir / "final-readback.json", "tavo_preset_get", {"id": preset_id})
    payload = response_payload(final)
    if not ok_response(final) or payload.get("active") is not True:
        raise RuntimeError("Owned preset activation lacked exact final readback.")
    record = ledger_record(context.ledger, "preset", preset_id)
    context.ledger.claim(
        "preset",
        preset_id,
        **{
            key: value
            for key, value in record.items()
            if key not in {"id", "expectedPayload", "payloadHash"}
        },
        expectedPayload=payload,
        payloadHash=stable_content_hash(payload, ("active", "revision", "updatedAt")),
    )


def run_case_prelude(context: RuntimeContext, case: CaseSpec, chat_id: int, step_dir: Path) -> dict[str, Any] | None:
    if not case.prelude:
        return None
    markers = context.registry["markers"]
    result: dict[str, Any]
    if case.prelude == "scan-in":
        trigger_message = append_owned_message(
            context,
            chat_id,
            {
                "role": "user",
                "content": f"Prior in-window trigger: {trigger(context.run_id, 'scan')}",
                "hidden": False,
            },
            step_dir / "trigger",
            "scan-in-trigger",
        )
        result = {"triggerMessageId": int(trigger_message["id"]), "window": "inside", "passed": True}
    elif case.prelude == "scan-out":
        scan_entry = lorebook_definitions(context.run_id, markers)["scan"]["entries"][0]
        trigger_message = append_owned_message(
            context,
            chat_id,
            {
                "role": "user",
                "content": f"Prior out-of-window trigger: {trigger(context.run_id, 'scan')}",
                "hidden": False,
            },
            step_dir / "trigger",
            "scan-out-trigger",
        )
        filler_ids = append_neutral_window(context, chat_id, step_dir / "window", "scan-out", exchanges=2)
        result = {
            "triggerMessageId": int(trigger_message["id"]),
            "fillerMessageIds": filler_ids,
            "configuredScanDepth": int(scan_entry["scanDepth"]),
            "configuredSticky": int(scan_entry["sticky"]),
            "window": "outside",
            "passed": len(filler_ids) > 2,
        }
    elif case.prelude == "sticky-rotate":
        entry = lorebook_definitions(context.run_id, markers)["sticky"]["entries"][0]
        entry = {**entry, "content": f"Cross-feature evidence code: {markers['sticky-b']}. Sticky carry readback."}
        updated = update_owned_lorebook_entry(context, "sticky", entry, step_dir / "rotate", "sticky-rotate")
        filler_ids = append_neutral_window(context, chat_id, step_dir / "window", "sticky", exchanges=2)
        result = {
            "lorebookHash": stable_hash(updated),
            "fillerMessageIds": filler_ids,
            "configuredScanDepth": 2,
            "triggerMovedOutsideWindow": len(filler_ids) > 2,
            "passed": len(filler_ids) > 2,
        }
    elif case.prelude == "cooldown-rotate":
        entry = lorebook_definitions(context.run_id, markers)["cooldown"]["entries"][0]
        entry = {**entry, "content": f"Cross-feature evidence code: {markers['cooldown-b']}. Cooldown rotated readback."}
        updated = update_owned_lorebook_entry(context, "cooldown", entry, step_dir / "rotate", "cooldown-rotate")
        result = {"lorebookHash": stable_hash(updated), "passed": True}
    elif case.prelude == "cooldown-advance":
        filler_ids = append_neutral_window(context, chat_id, step_dir / "window", "cooldown-expiry", exchanges=2)
        result = {"fillerMessageIds": filler_ids, "configuredCooldown": 2, "passed": len(filler_ids) >= 4}
    elif case.prelude == "depth-history":
        filler_ids = append_neutral_window(context, chat_id, step_dir / "history", "preset-depth", exchanges=2)
        result = {"historyMessageIds": filler_ids, "passed": len(filler_ids) == 4}
    elif case.prelude == "message-ops":
        result = run_message_crud_prelude(context, chat_id, step_dir / "message-crud")
    elif case.prelude == "plugin-crud":
        result = run_plugin_crud_prelude(context, chat_id, step_dir / "plugin-crud")
    elif case.prelude == "thread-roundtrip":
        chat_b = int(context.registry["chats"]["thread-b"]["id"])
        result = run_thread_roundtrip_prelude(context, chat_id, chat_b, step_dir / "thread-roundtrip")
    else:
        raise RuntimeError(f"Unknown case prelude: {case.prelude}")
    if result.get("passed") is not True:
        raise RuntimeError(f"Prelude {case.prelude!r} did not pass its own readback checks.")
    durable_json(step_dir / "prelude-result.json", {"prelude": case.prelude, **result})
    return result


def set_case_input(context: RuntimeContext, case: CaseSpec, step_dir: Path) -> dict[str, Any]:
    before = mcp_tool(context.client, step_dir / "input-before.json", "tavo_input_get", {})
    if not ok_response(before) or not isinstance(response_payload(before).get("text"), str):
        raise RuntimeError("Case input was not readable before preparation.")
    if case.input_mode == "standard":
        set_response = mcp_tool(
            context.client,
            step_dir / "input-set.json",
            "tavo_input_set",
            {"text": case.prompt},
        )
        if not ok_response(set_response):
            raise RuntimeError("Input set failed.")
        first = second = None
    elif case.input_mode == "clear-set-append-send":
        cleared = mcp_tool(context.client, step_dir / "input-clear.json", "tavo_input_clear", {})
        cleared_readback = mcp_tool(context.client, step_dir / "input-clear-readback.json", "tavo_input_get", {})
        if (
            not ok_response(cleared)
            or not ok_response(cleared_readback)
            or str(response_payload(cleared_readback).get("text") or "")
        ):
            raise RuntimeError("Input clear did not produce an exact blank readback.")
        first, second = split_input_for_append(case.prompt)
        set_response = mcp_tool(context.client, step_dir / "input-set.json", "tavo_input_set", {"text": first})
        append_response = mcp_tool(
            context.client,
            step_dir / "input-append.json",
            "tavo_input_append",
            {"text": second},
        )
        if not ok_response(set_response) or not ok_response(append_response):
            raise RuntimeError("Input clear/set/append pipeline failed.")
    else:
        raise RuntimeError(f"Unknown input mode: {case.input_mode}")
    final = mcp_tool(context.client, step_dir / "input-final.json", "tavo_input_get", {})
    observed = response_payload(final).get("text")
    if case.input_mode == "clear-set-append-send" and isinstance(first, str) and isinstance(second, str):
        proof = input_append_proof(first, second, str(observed or ""), case.prompt)
        durable_json(step_dir / "input-transport-proof.json", proof)
    else:
        proof = {
            "mode": case.input_mode,
            "exactTextMatched": observed == case.prompt,
            "passed": observed == case.prompt,
        }
    if not ok_response(final) or observed != case.prompt:
        raise RuntimeError("Prepared input did not exactly equal the immutable case prompt.")
    return proof


def validate_case_exchange_axes(
    case: CaseSpec,
    messages_before: list[dict[str, Any]],
    messages_after: list[dict[str, Any]],
    send_ok: bool,
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    before_ids = {int(item.get("id") or 0) for item in messages_before if int(item.get("id") or 0) > 0}
    new_messages = [item for item in messages_after if int(item.get("id") or 0) not in before_ids]
    infrastructure: list[str] = []
    model_format: list[str] = []
    model_semantic: list[str] = []
    if not send_ok:
        infrastructure.append("tavo_input_send did not return a successful response")
    if len(messages_after) != len(messages_before) + 2:
        infrastructure.append(
            f"message count changed from {len(messages_before)} to {len(messages_after)}; expected exactly two"
        )
    if len(new_messages) != 2:
        infrastructure.append(f"new persistent message id count was {len(new_messages)}; expected two")
    user_candidates = [
        item for item in new_messages if item.get("role") == "user" and item.get("content") == case.prompt
    ]
    assistant_candidates = [item for item in new_messages if item.get("role") == "assistant"]
    user = user_candidates[0] if len(user_candidates) == 1 else None
    assistant = assistant_candidates[0] if len(assistant_candidates) == 1 else None
    if user is None:
        infrastructure.append("exactly one fresh persistent user message did not match the immutable prompt")
    if assistant is None:
        infrastructure.append("exactly one fresh persistent assistant message was not found")
    if user and assistant:
        user_index_raw = user.get("index")
        assistant_index_raw = assistant.get("index")
        if user_index_raw is None or assistant_index_raw is None:
            infrastructure.append("fresh exchange messages did not expose stable indexes")
        elif int(assistant_index_raw) != int(user_index_raw) + 1:
            infrastructure.append("fresh assistant message did not immediately follow the fresh user message")
    content = str(assistant.get("content") or "") if assistant else ""
    visible_lines = [line.strip() for line in content.replace("\r\n", "\n").split("\n") if line.strip()]
    if assistant and (not visible_lines or visible_lines[0] != case.nonce):
        model_format.append("assistant first visible line did not exactly equal the case nonce")
    if assistant:
        for expected in case.expected:
            if expected not in content:
                model_semantic.append(f"assistant omitted expected marker: {expected}")
        for forbidden in case.forbidden:
            if forbidden in content:
                model_semantic.append(f"assistant included forbidden marker: {forbidden}")
    exchange = {
        "beforeMessageIds": sorted(before_ids),
        "afterMessageIds": sorted(int(item.get("id") or 0) for item in messages_after),
        "newMessageIds": sorted(int(item.get("id") or 0) for item in new_messages),
        "userMessageId": int(user.get("id") or 0) if user else None,
        "assistantMessageId": int(assistant.get("id") or 0) if assistant else None,
        "assistantContent": content if assistant else None,
        "modelOutputEvaluated": assistant is not None,
        "exchangeComplete": not infrastructure and user is not None and assistant is not None,
    }
    return exchange, infrastructure, model_format, model_semantic


def validate_case_exchange(
    case: CaseSpec,
    messages_before: list[dict[str, Any]],
    messages_after: list[dict[str, Any]],
    send_ok: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Backward-compatible wrapper returning the former combined product list."""

    exchange, infrastructure, model_format, model_semantic = validate_case_exchange_axes(
        case,
        messages_before,
        messages_after,
        send_ok,
    )
    return exchange, infrastructure, [*model_format, *model_semantic]


def build_case_evidence_axes(
    direct_axis: dict[str, Any],
    runner_transport_failures: list[str],
    model_format_failures: list[str],
    model_semantic_failures: list[str],
    *,
    model_output_evaluated: bool,
    runner_transport_evaluated: bool = True,
) -> dict[str, dict[str, Any]]:
    return {
        "runnerTransportInfra": evidence_axis(runner_transport_evaluated, runner_transport_failures),
        "directRuntimeBehavior": direct_axis,
        "modelFormat": evidence_axis(model_output_evaluated, model_format_failures),
        "modelSemantic": evidence_axis(model_output_evaluated, model_semantic_failures),
    }


def failed_axis_names(axes: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, axis in axes.items() if axis.get("evaluated") is True and axis.get("passed") is False]


def case_failure_result(
    context: RuntimeContext,
    case: CaseSpec,
    step_dir: Path,
    *,
    direct_axis: dict[str, Any],
    runner_transport_failures: list[str],
    direct_runtime_failures: list[str],
    traceback_text: str,
) -> dict[str, Any]:
    axes = build_case_evidence_axes(
        direct_axis,
        runner_transport_failures,
        [],
        [],
        model_output_evaluated=False,
        runner_transport_evaluated=True,
    )
    failures = failed_axis_names(axes)
    legacy_failure_class = "runner_or_infrastructure" if runner_transport_failures else "product_behavior"
    return {
        "schemaVersion": "1.1.0",
        "runId": context.run_id,
        "planHash": context.plan_hash,
        "scriptHash": context.script_hash,
        "specHash": case_record(case)["specHash"],
        "ordinal": case.ordinal,
        "key": case.key,
        "family": case.family,
        "passed": False,
        "countsTowardKpi": False,
        "usableAsEvidence": bool(direct_axis.get("evaluated")),
        "failureClass": legacy_failure_class,
        "failureAxes": failures,
        "primaryFailureAxis": failures[0] if failures else None,
        "evidenceAxes": axes,
        "modelFormatFailures": [],
        "modelSemanticFailures": [],
        "directRuntimeBehaviorFailures": direct_runtime_failures,
        "runnerTransportInfrastructureFailures": runner_transport_failures,
        "productBehaviorFailures": direct_runtime_failures,
        "runnerInfrastructureFailures": runner_transport_failures,
        "directRuntimePassed": direct_axis.get("passed"),
        "modelFormatPassed": None,
        "modelSemanticPassed": None,
        "modelRequestSent": (step_dir / "send-start.json").exists(),
        "traceback": traceback_text,
        "finishedAt": now_utc(),
    }


def execute_case(context: RuntimeContext, case: CaseSpec) -> dict[str, Any]:
    step_dir = context.artifact_dir / "model-calls" / case.family / case.step_name
    step_dir.mkdir(parents=True, exist_ok=False)
    start = {
        "runId": context.run_id,
        "planHash": context.plan_hash,
        "scriptHash": context.script_hash,
        "specHash": case_record(case)["specHash"],
        "ordinal": case.ordinal,
        "key": case.key,
        "startedAt": now_utc(),
    }
    durable_json(step_dir / "start.json", start)
    chat_id = int(context.registry["chats"][case.chat_key]["id"])
    verify_case_assets(context, case, step_dir / "asset-preflight")
    set_current_chat(context.client, step_dir / "set-current-chat", chat_id, f"{context.run_id}-{case.key}")
    preset_id = int(context.registry["presets"][case.preset_key]["id"])
    activate_owned_preset(context, preset_id, step_dir / "activate-preset", f"{context.run_id}-{case.key}")
    direct_components: list[dict[str, Any]] = []
    if case.greeting_marker:
        def greeting_component() -> dict[str, Any]:
            read_owned_object(context, "chat", chat_id, step_dir / "greeting" / "mutation-precondition")
            other_markers = tuple(
                str(context.registry["markers"][key])
                for key in ("greeting-first", "greeting-alt-a", "greeting-alt-b")
                if context.registry["markers"].get(key) != case.greeting_marker
            )
            greeting_message_id = select_greeting(
                context.client,
                context.device,
                chat_id,
                case.greeting_marker,
                step_dir / "greeting",
                f"{context.run_id}-{case.key}",
                other_markers,
            )
            greeting_readback = mcp_tool(
                context.client,
                step_dir / "greeting" / "host-message-readback.json",
                "tavo_message_get",
                {"chatId": chat_id, "id": greeting_message_id},
            )
            greeting_payload = response_payload(greeting_readback)
            if (
                not ok_response(greeting_readback)
                or greeting_payload.get("role") != "assistant"
                or case.greeting_marker not in str(greeting_payload.get("content") or "")
            ):
                raise RuntimeError("Selected greeting failed host-side full message readback.")
            context.ledger.claim(
                "message",
                greeting_message_id,
                chatId=chat_id,
                expectedPayload=greeting_payload,
                payloadHash=stable_hash(greeting_payload),
                retained=True,
                source="greeting-selection",
            )
            selection = load_json(step_dir / "greeting" / "selection-result.json")
            return {
                "passed": True,
                "messageId": greeting_message_id,
                "selectedIndex": greeting_payload.get("index"),
                "exactMaterializationProved": selection.get("exactMaterializationProved") is True,
                "evidenceLevel": selection.get("evidenceLevel"),
                "assertions": selection.get("assertions"),
                "proofFailures": selection.get("proofFailures") or [],
            }

        run_direct_component(step_dir, direct_components, "greeting-selection", greeting_component)
    prelude = None
    if case.prelude:
        prelude = run_direct_component(
            step_dir,
            direct_components,
            f"prelude:{case.prelude}",
            lambda: run_case_prelude(context, case, chat_id, step_dir / "prelude"),
        )

    def confirm_current_chat() -> dict[str, Any]:
        set_current_chat(
            context.client,
            step_dir / "confirm-current-chat",
            chat_id,
            f"{context.run_id}-{case.key}-confirm",
        )
        return {"passed": True, "chatId": chat_id}

    if case.prelude == "thread-roundtrip":
        run_direct_component(
            step_dir,
            direct_components,
            "current-chat-set-post-thread-roundtrip",
            confirm_current_chat,
        )
    else:
        confirm_current_chat()
    if case.input_mode == "clear-set-append-send":
        input_proof = run_direct_component(
            step_dir,
            direct_components,
            "input-clear-set-append",
            lambda: set_case_input(context, case, step_dir / "input"),
        )
    else:
        input_proof = set_case_input(context, case, step_dir / "input")
    messages_before = all_messages(context.client, chat_id, step_dir / "baseline-a", "messages.json")
    messages_before_confirm = all_messages(context.client, chat_id, step_dir / "baseline-b", "messages.json")
    if stable_hash(message_payload_snapshot(messages_before)) != stable_hash(message_payload_snapshot(messages_before_confirm)):
        raise RuntimeError("Pre-send chat baseline changed between two read-only snapshots.")
    if any(item.get("role") == "user" and item.get("content") == case.prompt for item in messages_before_confirm):
        raise RuntimeError("Exact case prompt already exists without a terminal result; refusing duplicate send.")
    intent_path = step_dir / "send-intent.json"
    if intent_path.exists():
        raise RuntimeError("Unresolved send intent exists; refusing non-idempotent resend.")
    intent = {
        **start,
        "chatId": chat_id,
        "activePresetId": preset_id,
        "nonce": case.nonce,
        "prompt": case.prompt,
        "promptSha256": hashlib.sha256(case.prompt.encode("utf-8")).hexdigest(),
        "beforeCount": len(messages_before_confirm),
        "beforeMessageIds": [int(item.get("id") or 0) for item in messages_before_confirm],
        "beforeMessagesHash": stable_hash(message_payload_snapshot(messages_before_confirm)),
        "status": "prepared-before-non-idempotent-send",
        "preparedAt": now_utc(),
    }
    durable_json(intent_path, intent)
    durable_json(
        step_dir / "send-start.json",
        {**{key: intent[key] for key in ("runId", "specHash", "chatId", "promptSha256")}, "startedAt": now_utc()},
    )
    send = mcp_tool(
        context.client,
        step_dir / "input-send.json",
        "tavo_input_send",
        {},
        timeout=context.timeout,
    )
    send_ok = ok_response(send)
    deadline = time.time() + context.timeout
    after_count = message_count(context.client, chat_id, step_dir / "poll-000.json")
    poll = 1
    while after_count < len(messages_before_confirm) + 2 and time.time() < deadline:
        time.sleep(2)
        after_count = message_count(context.client, chat_id, step_dir / f"poll-{poll:03d}.json")
        poll += 1
    messages_after = all_messages(context.client, chat_id, step_dir / "after", "messages.json")
    exchange, infrastructure_failures, model_format_failures, model_semantic_failures = validate_case_exchange_axes(
        case,
        messages_before_confirm,
        messages_after,
        send_ok,
    )
    ui_capture: dict[str, Any] | None = None
    if case.capture_ui:
        try:
            foreground_tavo(context.device, step_dir / "ui" / "foreground", settle_seconds=2.5)
            dismiss_greeting(context.device, step_dir / "ui" / "dismiss-greeting")
            capture_code = capture_phone(context.device, step_dir / "ui", "after-case")
            ui_capture = {"returnCode": capture_code, "passed": capture_code == 0}
            if capture_code != 0:
                infrastructure_failures.append("required UI capture failed")
        except Exception as exc:  # noqa: BLE001
            ui_capture = {"passed": False, "error": repr(exc)}
            infrastructure_failures.append(f"required UI capture raised: {exc!r}")
    direct_axis = direct_runtime_axis(direct_components)
    if direct_axis.get("evaluated"):
        persist_direct_runtime_axis(step_dir, direct_axis)
    axes = build_case_evidence_axes(
        direct_axis,
        infrastructure_failures,
        model_format_failures,
        model_semantic_failures,
        model_output_evaluated=bool(exchange.get("modelOutputEvaluated")),
    )
    product_failures = [*model_format_failures, *model_semantic_failures]
    if infrastructure_failures:
        failure_class = "runner_or_infrastructure"
    elif product_failures:
        failure_class = "product_behavior"
    else:
        failure_class = None
    failure_axes = failed_axis_names(axes)
    passed = not failure_axes
    result = {
        "schemaVersion": "1.1.0",
        **start,
        "finishedAt": now_utc(),
        "family": case.family,
        "chatId": chat_id,
        "presetId": preset_id,
        "nonce": case.nonce,
        "promptSha256": intent["promptSha256"],
        "beforeMessagesHash": intent["beforeMessagesHash"],
        "afterMessagesHash": stable_hash(message_payload_snapshot(messages_after)),
        "expected": list(case.expected),
        "forbidden": list(case.forbidden),
        "inputMode": case.input_mode,
        "inputProof": input_proof,
        "prelude": prelude,
        "notes": case.notes,
        "sendResponseOk": send_ok,
        **exchange,
        "uiCapture": ui_capture,
        "evidenceAxes": axes,
        "failureAxes": failure_axes,
        "primaryFailureAxis": failure_axes[0] if failure_axes else None,
        "modelFormatFailures": model_format_failures,
        "modelSemanticFailures": model_semantic_failures,
        "directRuntimeBehaviorFailures": list(direct_axis.get("failures") or []),
        "runnerTransportInfrastructureFailures": infrastructure_failures,
        "productBehaviorFailures": product_failures,
        "runnerInfrastructureFailures": infrastructure_failures,
        "failureClass": failure_class,
        "directRuntimePassed": direct_axis.get("passed"),
        "modelFormatPassed": axes["modelFormat"].get("passed"),
        "modelSemanticPassed": axes["modelSemantic"].get("passed"),
        "modelRequestSent": True,
        "usableAsEvidence": bool(direct_axis.get("evaluated") or (exchange["exchangeComplete"] and not infrastructure_failures)),
        "passed": passed,
        "countsTowardKpi": passed,
        "positionClaimBoundary": (
            "Configured fields were read back and injection occurred under that configuration; exact ordering is not claimed."
            if case.family in {"worldbook-position", "preset-depth"}
            else None
        ),
    }
    durable_json(step_dir / "result.json", result)
    return result


def summarize_results(results: list[dict[str, Any]], planned: int) -> dict[str, Any]:
    families: dict[str, dict[str, int]] = {}
    for result in results:
        family = str(result.get("family") or "unknown")
        row = families.setdefault(
            family,
            {
                "executed": 0,
                "passed": 0,
                "productFailed": 0,
                "infrastructureFailed": 0,
                "modelFormatFailed": 0,
                "modelSemanticFailed": 0,
                "directRuntimeFailed": 0,
                "runnerTransportInfraFailed": 0,
                "directRuntimePassed": 0,
            },
        )
        row["executed"] += 1
        if result.get("passed") is True:
            row["passed"] += 1
        elif result.get("failureClass") == "product_behavior":
            row["productFailed"] += 1
        else:
            row["infrastructureFailed"] += 1
        axes = result.get("evidenceAxes") if isinstance(result.get("evidenceAxes"), dict) else {}
        for axis_name, counter in (
            ("modelFormat", "modelFormatFailed"),
            ("modelSemantic", "modelSemanticFailed"),
            ("directRuntimeBehavior", "directRuntimeFailed"),
            ("runnerTransportInfra", "runnerTransportInfraFailed"),
        ):
            axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else {}
            if axis.get("evaluated") is True and axis.get("passed") is False:
                row[counter] += 1
        direct_axis = axes.get("directRuntimeBehavior") if isinstance(axes.get("directRuntimeBehavior"), dict) else {}
        if direct_axis.get("evaluated") is True and direct_axis.get("passed") is True:
            row["directRuntimePassed"] += 1
    exchange_ids = [
        int(message_id)
        for result in results
        for message_id in (result.get("userMessageId"), result.get("assistantMessageId"))
        if isinstance(message_id, int) and message_id > 0
    ]
    duplicate_exchange_ids = sorted({message_id for message_id in exchange_ids if exchange_ids.count(message_id) > 1})
    return {
        "planned": planned,
        "executed": len(results),
        "passed": sum(item.get("passed") is True for item in results),
        "productBehaviorFailed": sum(item.get("failureClass") == "product_behavior" for item in results),
        "runnerInfrastructureFailed": sum(item.get("failureClass") == "runner_or_infrastructure" for item in results),
        "modelFormatFailed": sum(bool(item.get("modelFormatFailures")) for item in results),
        "modelSemanticFailed": sum(bool(item.get("modelSemanticFailures")) for item in results),
        "directRuntimeBehaviorFailed": sum(bool(item.get("directRuntimeBehaviorFailures")) for item in results),
        "runnerTransportInfrastructureFailed": sum(
            bool(item.get("runnerTransportInfrastructureFailures") or item.get("runnerInfrastructureFailures"))
            for item in results
        ),
        "directRuntimePassed": sum(item.get("directRuntimePassed") is True for item in results),
        "persistentExchangeMessageIds": len(exchange_ids),
        "uniquePersistentExchangeMessageIds": len(set(exchange_ids)),
        "duplicatePersistentExchangeMessageIds": duplicate_exchange_ids,
        "families": families,
    }


def offline_self_check() -> dict[str, Any]:
    run_a = "CFM-OFFLINE-A-001"
    run_b = "CFM-OFFLINE-B-002"
    cases_a = build_cases(run_a, False)
    cases_b = build_cases(run_b, False)
    plan_a = plan_record(run_a, False, cases_a)
    plan_b = plan_record(run_b, False, cases_b)
    manifest, source = plugin_source(run_a, False, all_markers(run_a, False))
    expanded_cases, expanded_selection = resolve_case_selection(cases_a, "worldbook-cooldown-expired")
    preludes = {case.prelude for case in cases_a if case.prelude}
    implemented_preludes = {
        "scan-in",
        "scan-out",
        "sticky-rotate",
        "cooldown-rotate",
        "cooldown-advance",
        "depth-history",
        "message-ops",
        "plugin-crud",
        "thread-roundtrip",
    }
    checks = {
        "plannedAtLeast33": len(cases_a) >= 33,
        "plannedExactContract": len(cases_a) == PLANNED_MODEL_CALLS,
        "uniqueCaseKeys": len({case.key for case in cases_a}) == len(cases_a),
        "uniqueNonces": len({case.nonce for case in cases_a}) == len(cases_a),
        "crossRunNoncesDisjoint": not ({case.nonce for case in cases_a} & {case.nonce for case in cases_b}),
        "crossRunPlansDistinct": plan_a["planHash"] != plan_b["planHash"],
        "executeRequiresFlag": plan_a["safety"]["executeRequiresFlag"] is True,
        "deletesDisabledByDefault": plan_a["safety"]["runnerOwnedDeletesEnabled"] is False,
        "defaultMessageDeleteRetained": all_markers(run_a, False)["message-delete-final"]
        == all_markers(run_a, False)["message-delete-retained"],
        "defaultLoreDeleteRetained": all_markers(run_a, False)["crud-delete-final"]
        == all_markers(run_a, False)["crud-tombstone"],
        "allPreludesImplemented": preludes <= implemented_preludes,
        "dependentSelectionExpanded": {
            "worldbook-cooldown-trigger",
            "worldbook-cooldown-blocked",
            "worldbook-cooldown-expired",
        }
        == {case.key for case in expanded_cases}
        and expanded_selection["mode"] == "dependency-expanded",
        "stickyWindowDeconfounded": any(
            case.key == "worldbook-sticky-carry" and case.prelude == "sticky-rotate" for case in cases_a
        ),
        "stickyFreshChatControlPlanned": any(
            case.key == "worldbook-sticky-unactivated-control" and case.chat_key == "sticky-control"
            for case in cases_a
        ),
        "cooldownExpiryPlanned": any(case.key == "worldbook-cooldown-expired" for case in cases_a),
        "delayPositiveNegativePairPlanned": {
            "worldbook-delay-before-threshold",
            "worldbook-delay-after-threshold",
        }
        <= {case.key for case in cases_a},
        "inputPipelineModePlanned": any(case.input_mode == "clear-set-append-send" for case in cases_a),
        "greetingUiCasesPlanned": sum(case.greeting_marker is not None and case.capture_ui for case in cases_a) == 3,
        "positionClaimsBounded": all(
            "exact prompt ordering" in case.notes
            for case in cases_a
            if case.family in {"worldbook-position", "preset-depth"}
        ),
        "pluginRunSpecificId": manifest["id"] == plugin_identity(run_a),
        "pluginUpdateDeleteGuards": all(
            token in source
            for token in (
                "assertBook(book, C.loreName, C.markers['crud-created'])",
                "assertBook(before, C.loreUpdatedName, C.markers['crud-updated'])",
                "entry.identifier !== C.entryIdentifier",
                "TavoJS deleted lorebook still readable",
                "successAuthority: 'stable-readback'",
                "successAuthority: deleted ? 'stable-not-found-readback'",
            )
        )
        and "Boolean(updatedId)" not in source
        and "delete did not return the runner-owned id" not in source,
        "inputAppendProofHashesExactFinalText": (
            input_append_proof("left", "right", "left right", "left right")["combinedSha256"]
            == hashlib.sha256(b"left right").hexdigest()
        ),
        "payloadReadbackComparator": not payload_mismatches(
            {"a": 1, "b": [2, {"c": "x"}]}, {"a": 1, "b": [2, {"c": "x"}], "extra": True}
        ),
        "payloadMismatchDetected": bool(payload_mismatches({"a": 1}, {"a": 2})),
        "outerRestoreFinallyPresent": "finally:\n        if snapshot is not None:" in SCRIPT_PATH.read_text(encoding="utf-8"),
    }
    failures = sorted(key for key, passed in checks.items() if not passed)
    return {
        "case": "cross-feature-runner-offline-self-check",
        "checkedAt": now_utc(),
        "plannedModelCalls": len(cases_a),
        "families": sorted({case.family for case in cases_a}),
        "preludes": sorted(preludes),
        "checks": checks,
        "failures": failures,
        "passed": not failures,
    }


def create_artifact_lock(artifact_dir: Path) -> Any:
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise RuntimeError("Artifact directory already exists and is non-empty; every execution requires a new run.")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    handle = (artifact_dir / ".run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another process holds this artifact directory lock.")
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} acquired={now_utc()}\n")
    handle.flush()
    os.fsync(handle.fileno())
    return handle


def execute_live(args: argparse.Namespace) -> int:
    run_stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_id = f"CFM{run_stamp.replace('-', '')}{secrets.token_hex(5).upper()}"
    artifact_dir = (
        Path(args.artifact_dir).expanduser().resolve()
        if args.artifact_dir
        else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{run_stamp}-cross-feature-matrix"
    )
    artifact_lock = create_artifact_lock(artifact_dir)
    phone_lock: Any | None = None
    snapshot: dict[str, Any] | None = None
    client: TavoMcp | None = None
    restoration_passed = False
    restoration_attempted = False
    results: list[dict[str, Any]] = []
    infrastructure_error: BaseException | None = None
    all_cases = build_cases(run_id, bool(args.allow_runner_owned_deletes))
    cases, selection = resolve_case_selection(all_cases, str(getattr(args, "case_keys", "") or ""))
    full_matrix_selection = len(cases) == len(all_cases)
    plan = plan_record(run_id, bool(args.allow_runner_owned_deletes), cases, selection)
    script_hash = sha256_file(SCRIPT_PATH)
    manifest_path = artifact_dir / "run-manifest.json"
    manifest: dict[str, Any] = {
        "schemaVersion": "1.1.0",
        "case": "tavo-real-phone-cross-feature-matrix",
        "runId": run_id,
        "status": "starting",
        "startedAt": now_utc(),
        "artifactDir": str(artifact_dir),
        "scriptHash": script_hash,
        "planHash": plan["planHash"],
        "allowRunnerOwnedDeletes": bool(args.allow_runner_owned_deletes),
        "requestedCaseKeys": selection["requestedCaseKeys"],
        "selectedCaseKeys": [case.key for case in cases],
        "autoExpandedCaseKeys": selection["autoExpandedCaseKeys"],
        "caseSelection": selection,
        "fullMatrixSelection": full_matrix_selection,
        "countsTowardKpi": False,
    }
    durable_json(artifact_dir / "plan.json", plan)
    durable_json(manifest_path, manifest)
    try:
        endpoint = load_endpoint(args.endpoint_json)
        url = args.url or str(endpoint.get("url") or "")
        auth = args.auth or str(endpoint.get("auth") or "")
        if not url:
            raise RuntimeError("No Tavo MCP URL was supplied.")
        phone_lock, phone_lock_identity = acquire_phone_lock(args.device)
        device_identity = require_device_identity(args.device)
        client = TavoMcp(url, auth)
        mcp_identity, mcp_identity_hash = read_mcp_identity(client, artifact_dir)
        snapshot = capture_runtime_snapshot(
            client,
            artifact_dir,
            run_id,
            device_identity,
            mcp_identity,
            mcp_identity_hash,
        )
        manifest.update(
            {
                "status": "running",
                "deviceIdentity": device_identity,
                "deviceIdentityHash": stable_hash(device_identity),
                "mcpIdentityHash": mcp_identity_hash,
                "phoneLockIdentity": phone_lock_identity,
                "snapshotHash": stable_hash(snapshot),
            }
        )
        durable_json(manifest_path, manifest)
        ledger = OwnershipLedger(artifact_dir / "ownership-ledger.json", run_id)
        registry = prepare_registry(
            client,
            artifact_dir,
            ledger,
            run_id,
            bool(args.allow_runner_owned_deletes),
            cases,
        )
        context = RuntimeContext(
            client=client,
            artifact_dir=artifact_dir,
            device=args.device,
            run_id=run_id,
            allow_deletes=bool(args.allow_runner_owned_deletes),
            timeout=int(args.per_call_timeout),
            registry=registry,
            plan_hash=str(plan["planHash"]),
            script_hash=script_hash,
            ledger=ledger,
        )
        isolate_plugin_runtime(client, artifact_dir, snapshot, run_id, args.device)
        manifest.update(
            {
                "setupComplete": True,
                "registryHash": registry["registryHash"],
                "status": "executing",
            }
        )
        durable_json(manifest_path, manifest)
        for case in cases:
            append_event(
                artifact_dir / "events.jsonl",
                {"event": "case-start", "ordinal": case.ordinal, "key": case.key, "at": now_utc()},
            )
            try:
                result = execute_case(context, case)
            except DirectRuntimeBehaviorFailure as exc:
                step_dir = artifact_dir / "model-calls" / case.family / case.step_name
                failure = case_failure_result(
                    context,
                    case,
                    step_dir,
                    direct_axis=exc.axis,
                    runner_transport_failures=[],
                    direct_runtime_failures=list(exc.axis.get("failures") or [str(exc)]),
                    traceback_text=traceback.format_exc(),
                )
                durable_json(step_dir / "result.json", failure)
                results.append(failure)
                append_event(
                    artifact_dir / "events.jsonl",
                    {
                        "event": "case-direct-runtime-behavior-failure",
                        "ordinal": case.ordinal,
                        "key": case.key,
                        "component": exc.component,
                        "error": repr(exc),
                        "at": now_utc(),
                    },
                )
                manifest["progress"] = summarize_results(results, len(cases))
                durable_json(manifest_path, manifest)
                break
            except BaseException as exc:  # noqa: BLE001
                step_dir = artifact_dir / "model-calls" / case.family / case.step_name
                direct_axis = load_direct_runtime_axis(step_dir)
                failure = case_failure_result(
                    context,
                    case,
                    step_dir,
                    direct_axis=direct_axis,
                    runner_transport_failures=[repr(exc)],
                    direct_runtime_failures=list(direct_axis.get("failures") or []),
                    traceback_text=traceback.format_exc(),
                )
                failure_path = step_dir / "infrastructure-failure.json"
                durable_json(failure_path, failure)
                results.append(failure)
                infrastructure_error = exc
                append_event(
                    artifact_dir / "events.jsonl",
                    {"event": "case-infrastructure-failure", "ordinal": case.ordinal, "key": case.key, "error": repr(exc), "at": now_utc()},
                )
                manifest["progress"] = summarize_results(results, len(cases))
                durable_json(manifest_path, manifest)
                break
            results.append(result)
            append_event(
                artifact_dir / "events.jsonl",
                {
                    "event": "case-finish",
                    "ordinal": case.ordinal,
                    "key": case.key,
                    "passed": result["passed"],
                    "failureClass": result["failureClass"],
                    "at": now_utc(),
                },
            )
            manifest["progress"] = summarize_results(results, len(cases))
            durable_json(manifest_path, manifest)
            if result.get("failureClass") == "runner_or_infrastructure":
                infrastructure_error = RuntimeError(f"Infrastructure failure in case {case.key}")
                break
    except BaseException as exc:  # noqa: BLE001
        infrastructure_error = exc
        manifest["executionException"] = repr(exc)
        manifest["executionTraceback"] = traceback.format_exc()
    finally:
        if snapshot is not None:
            restoration_attempted = True
            if client is None:
                restoration_passed = False
            else:
                try:
                    restoration_passed = restore_runtime(client, artifact_dir, snapshot, run_id, "final")
                except BaseException as restore_exc:  # noqa: BLE001
                    restoration_passed = False
                    manifest["restorationException"] = repr(restore_exc)
                    manifest["restorationTraceback"] = traceback.format_exc()
        summary = summarize_results(results, int(plan["plannedModelCalls"]))
        product_failures = [item.get("key") for item in results if item.get("failureClass") == "product_behavior"]
        runner_failures = [item.get("key") for item in results if item.get("failureClass") == "runner_or_infrastructure"]
        model_format_failures = [item.get("key") for item in results if item.get("modelFormatFailures")]
        model_semantic_failures = [item.get("key") for item in results if item.get("modelSemanticFailures")]
        direct_runtime_failures = [item.get("key") for item in results if item.get("directRuntimeBehaviorFailures")]
        runner_transport_failures = [
            item.get("key")
            for item in results
            if item.get("runnerTransportInfrastructureFailures") or item.get("runnerInfrastructureFailures")
        ]
        if summary["duplicatePersistentExchangeMessageIds"]:
            runner_failures.append("suite:duplicate-persistent-exchange-message-ids")
        complete_execution = len(results) == int(plan["plannedModelCalls"])
        passed = (
            infrastructure_error is None
            and restoration_attempted
            and restoration_passed
            and complete_execution
            and not product_failures
            and not runner_failures
            and all(item.get("passed") is True for item in results)
        )
        if passed:
            status = "passed"
        elif infrastructure_error is not None or not restoration_passed or runner_failures:
            status = "failed_runner_or_infrastructure"
        else:
            status = "failed_product_behavior"
        counts_toward_kpi = passed and full_matrix_selection
        manifest.update(
            {
                "status": status,
                "finishedAt": now_utc(),
                "summary": summary,
                "productBehaviorFailures": product_failures,
                "runnerInfrastructureFailures": runner_failures,
                "modelFormatFailures": model_format_failures,
                "modelSemanticFailures": model_semantic_failures,
                "directRuntimeBehaviorFailures": direct_runtime_failures,
                "runnerTransportInfrastructureFailures": runner_transport_failures,
                "infrastructureError": repr(infrastructure_error) if infrastructure_error else None,
                "restorationAttempted": restoration_attempted,
                "restorationPassed": restoration_passed,
                "completeExecution": complete_execution,
                "countsTowardKpi": counts_toward_kpi,
                "partialEvidenceUsable": bool(
                    restoration_passed
                    and complete_execution
                    and not runner_failures
                    and all(item.get("usableAsEvidence") is True for item in results)
                ),
                "evidencePolicy": (
                    "Model format, model semantic markers, direct-runtime behavior, and runner/transport infrastructure "
                    "are independent axes. A later infrastructure failure does not erase already persisted direct-runtime "
                    "components. Only an all-axis pass in a fully restored full matrix counts toward KPI."
                ),
                "positionDepthClaimBoundary": (
                    "Readback proves configured position/depth/role and the cases test injection under each configuration; "
                    "the matrix does not claim exact prompt ordering without request-body evidence."
                ),
            }
        )
        durable_json(manifest_path, manifest)
        if phone_lock is not None:
            phone_lock.close()
        artifact_lock.close()
    print(json.dumps({"artifactDir": str(artifact_dir), "runId": run_id, "status": manifest["status"], "countsTowardKpi": manifest["countsTowardKpi"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "passed" else 1


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a fail-closed 35-call retained Tavo cross-feature matrix.",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--self-check", action="store_true", help="Run offline structural and safety checks only.")
    actions.add_argument("--print-plan", action="store_true", help="Print a fresh offline plan; never contact the phone.")
    actions.add_argument("--execute", action="store_true", help="Explicitly authorize real-phone execution.")
    parser.add_argument("--endpoint-json", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument(
        "--case-keys",
        default="",
        help=(
            "Comma-separated case keys for a partial evidence run. Paired/lifecycle dependency groups are expanded "
            "fail-closed and recorded in plan/manifest; partial runs never count as the full matrix KPI."
        ),
    )
    parser.add_argument("--per-call-timeout", type=int, default=240)
    parser.add_argument(
        "--allow-runner-owned-deletes",
        action="store_true",
        help="Allow actual deletes only for objects uniquely proven in this run's ownership ledger.",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.per_call_timeout < 30:
        parser.error("--per-call-timeout must be at least 30 seconds")
    if args.self_check:
        report = offline_self_check()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    if args.print_plan:
        run_id = f"CFM-PLAN-{secrets.token_hex(8).upper()}"
        plan = plan_record(run_id, bool(args.allow_runner_owned_deletes), build_cases(run_id, bool(args.allow_runner_owned_deletes)))
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.device:
        parser.error("--execute requires an explicit --device serial")
    try:
        return execute_live(args)
    except Exception as exc:  # noqa: BLE001
        print(f"cross-feature runner refused execution: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    pass


# --- WebView / plugin retained matrix scaffold ---
# Offline bundle planning only. Its WebView-prefixed API must not replace the
# real-phone 35-case runner above or count prepared placeholders as live evidence.

WORKSPACE_ROOT = ROOT.parent.parent.parent
MATRIX_NAME = "webview-plugin-retained-matrix"
SETUP_ARTIFACTS = ("state.json",)
VISUAL_ARTIFACTS = ("screen.png", "ui.xml", "marker.txt", "input.json", "readback.json")
PERSISTENT_ARTIFACTS = ("stable-id.txt", "stable-hash.json", "readback.json")
SENSITIVE_KEY_PARTS = ("authorization", "auth", "token", "bearer", "api_key", "apikey", "secret", "password", "session", "cookie")


@dataclass(frozen=True)
class WebViewCaseSpec:
    key: str
    family: str
    kind: str
    dependencies: tuple[str, ...] = ()
    requires_execute: bool = True
    persistent: bool = False
    retain_objects: bool = True
    no_resend: bool = True
    hidden: bool = False
    notes: str = ""
    marker_hint: str = ""
    artifact_requirements: tuple[str, ...] = ()


@dataclass
class WebViewRuntimeContext:
    client: Any | None
    artifact_dir: Path
    device: str
    run_id: str
    allow_deletes: bool
    timeout: int
    registry: dict[str, Any]
    plan_hash: str
    script_hash: str
    ledger: "WebViewOwnershipLedger"
    cases: list[WebViewCaseSpec] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in SENSITIVE_KEY_PARTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower().startswith("bearer "):
            return "Bearer <redacted>"
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(redact_sensitive(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def matrix_artifacts(case: WebViewCaseSpec) -> tuple[str, ...]:
    if not case.requires_execute:
        return SETUP_ARTIFACTS
    if case.persistent:
        return (*VISUAL_ARTIFACTS, *PERSISTENT_ARTIFACTS)
    return VISUAL_ARTIFACTS


def stable_case_identity(run_id: str, case: WebViewCaseSpec) -> tuple[str, str]:
    digest = stable_hash(
        {
            "runId": run_id,
            "key": case.key,
            "family": case.family,
            "kind": case.kind,
            "deps": list(case.dependencies),
            "retained": case.retain_objects,
            "artifactRequirements": list(case.artifact_requirements),
        }
    )
    stable_id = f"{safe_name(run_id)}-{safe_name(case.key)}-{digest[:16]}"
    return stable_id, digest


def webview_case_record(run_id: str, case: WebViewCaseSpec) -> dict[str, Any]:
    record: dict[str, Any] = {
        "key": case.key,
        "family": case.family,
        "kind": case.kind,
        "dependencies": list(case.dependencies),
        "requiresExecute": case.requires_execute,
        "persistent": case.persistent,
        "retainObjects": case.retain_objects,
        "noResend": case.no_resend,
        "hidden": case.hidden,
        "notes": case.notes,
        "markerHint": case.marker_hint,
        "artifactRequirements": list(case.artifact_requirements),
    }
    if case.persistent:
        stable_id, stable_hash_value = stable_case_identity(run_id, case)
        record["stableId"] = stable_id
        record["stableHash"] = stable_hash_value
    record["caseHash"] = stable_hash({key: value for key, value in record.items() if key not in {"caseHash"}})
    return record


def _case(
    key: str,
    family: str,
    kind: str,
    *,
    dependencies: tuple[str, ...] = (),
    persistent: bool = False,
    hidden: bool = False,
    notes: str = "",
    marker_hint: str = "",
) -> WebViewCaseSpec:
    requires_execute = kind != "setup"
    return WebViewCaseSpec(
        key=key,
        family=family,
        kind=kind,
        dependencies=dependencies,
        requires_execute=requires_execute,
        persistent=persistent,
        retain_objects=True,
        no_resend=True,
        hidden=hidden,
        notes=notes,
        marker_hint=marker_hint,
        artifact_requirements=matrix_artifacts(
            WebViewCaseSpec(
                key=key,
                family=family,
                kind=kind,
                dependencies=dependencies,
                requires_execute=requires_execute,
                persistent=persistent,
                retain_objects=True,
                no_resend=True,
                hidden=hidden,
                notes=notes,
                marker_hint=marker_hint,
            )
        ),
    )


def build_webview_cases(run_id: str, allow_deletes: bool = False) -> list[WebViewCaseSpec]:
    _ = allow_deletes
    cases: list[WebViewCaseSpec] = [
        _case("bootstrap-runtime", "setup", "setup", hidden=True, notes="Capture plan hash, redaction policy, and baseline retention settings."),
        _case(
            "prepare-ar-webview",
            "setup",
            "setup",
            dependencies=("bootstrap-runtime",),
            hidden=True,
            notes="Prepare the Advanced Rendering/WebView surface and JS support state without touching user data.",
        ),
        _case(
            "seed-retained-chat",
            "setup",
            "setup",
            dependencies=("bootstrap-runtime", "prepare-ar-webview",),
            hidden=True,
            notes="Snapshot the current chat, preset, and plugin state for later restoration checks.",
        ),
        _case(
            "install-fixture-plugin",
            "setup",
            "setup",
            dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat"),
            hidden=True,
            notes="Record the retained fixture plugin state used by the HTML fragment and sidebar cases.",
        ),
    ]

    for key, notes, marker_hint in [
        ("webview-bubble-floating-button", "Floating button inside a chat bubble must remain visible above the bubble chrome.", "bubble-floating"),
        ("webview-bubble-fixed-button", "Fixed-position button must stay pinned while the bubble scrolls.", "bubble-fixed"),
        ("webview-bubble-sticky-button", "Sticky-position button must keep its stickiness while the bubble scrolls.", "bubble-sticky"),
        ("webview-bubble-absolute-button", "Absolute-position button must stay anchored within the bubble layout.", "bubble-absolute"),
        ("webview-bubble-overflow-zindex-scroll", "Overflow, z-index, and scroll layering must be visible in the same bubble.", "bubble-overflow"),
    ]:
        cases.append(
            _case(
                key,
                "webview-bubble",
                "visual",
                dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat"),
                notes=notes,
                marker_hint=marker_hint,
            )
        )

    for key, notes, marker_hint in [
        ("sanitizer-tag-allowed", "Allowed tags should survive sanitizer filtering.", "sanitize-tag-allow"),
        ("sanitizer-tag-blocked", "Blocked tags should be stripped from the rendered WebView.", "sanitize-tag-block"),
        ("sanitizer-attr-allowed", "Allowed attributes should remain on permitted elements.", "sanitize-attr-allow"),
        ("sanitizer-attr-blocked", "Blocked attributes should be stripped from the rendered element.", "sanitize-attr-block"),
        ("sanitizer-script-blocked", "Script tags must be blocked or neutralized by the sanitizer.", "sanitize-script-block"),
        ("sanitizer-url-allowed", "Allowed URL schemes should render or navigate as documented.", "sanitize-url-allow"),
        ("sanitizer-url-blocked", "Blocked URL schemes should be rejected or neutralized.", "sanitize-url-block"),
    ]:
        cases.append(
            _case(
                key,
                "sanitizer",
                "visual",
                dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat"),
                notes=notes,
                marker_hint=marker_hint,
            )
        )

    for key, notes, marker_hint in [
        ("js-load-counter", "A visible counter must increment during the initial JS load lifecycle.", "js-load"),
        ("js-rerender-counter", "A visible counter must increment on rerender without losing retained state.", "js-rerender"),
        ("js-message-update-counter", "A visible counter must survive message update and show the update step.", "js-message-update"),
        ("js-chat-switch-counter", "A visible counter must survive chat switching and restore in the target chat.", "js-chat-switch"),
        ("js-app-restart-counter", "A visible counter must survive app restart and restore from retained storage.", "js-app-restart"),
    ]:
        cases.append(
            _case(
                key,
                "lifecycle",
                "persistent",
                dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat"),
                persistent=True,
                notes=notes,
                marker_hint=marker_hint,
            )
        )

    for key, notes, marker_hint in [
        ("ejs-html-escape", "EJS output should preserve HTML escaping when rendered into the AR surface.", "ejs-html"),
        ("ejs-js-escape", "EJS output should preserve JavaScript escaping without breaking the WebView.", "ejs-js"),
        ("ejs-json-escape", "EJS output should preserve JSON escaping in the rendered artifact.", "ejs-json"),
        ("ejs-regex-escape", "EJS output should preserve regex escaping in the rendered artifact.", "ejs-regex"),
    ]:
        cases.append(
            _case(
                key,
                "ejs",
                "visual",
                dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat"),
                notes=notes,
                marker_hint=marker_hint,
            )
        )

    for key, notes, marker_hint, persistent in [
        ("tpg-htmlfragment-button", "HTML fragment buttons must stay strictly separate from native action buttons.", "tpg-fragment", False),
        ("tpg-native-action-separation", "Native actions must remain distinct from htmlFragment button controls.", "tpg-native", False),
        ("tpg-sidebar-action", "Sidebar actions must be reachable from the plugin sidebar entry point.", "tpg-sidebar", False),
        ("tpg-reload-error", "Reload and error surfaces must still report the retained plugin state.", "tpg-reload-error", False),
        ("tpg-state-persistence", "Plugin state and data must survive retained reloads and app restarts.", "tpg-state-persistence", True),
    ]:
        cases.append(
            _case(
                key,
                "tpg",
                "persistent" if persistent else "visual",
                dependencies=("bootstrap-runtime", "prepare-ar-webview", "seed-retained-chat", "install-fixture-plugin"),
                persistent=persistent,
                notes=notes,
                marker_hint=marker_hint,
            )
        )

    validate_webview_case_plan(cases)
    return cases


def validate_webview_case_plan(cases: list[WebViewCaseSpec]) -> None:
    errors: list[str] = []
    if len(cases) < 20:
        errors.append(f"planned case count too small: {len(cases)}")
    keys = [case.key for case in cases]
    if len(keys) != len(set(keys)):
        errors.append("case keys are not unique")
    index = {case.key: position for position, case in enumerate(cases)}
    for case in cases:
        if case.kind == "setup" and case.requires_execute:
            errors.append(f"setup case {case.key} must not require execute")
        if case.requires_execute and not case.artifact_requirements:
            errors.append(f"case {case.key} is missing required artifact requirements")
        if case.requires_execute and not {"screen.png", "ui.xml", "marker.txt", "input.json", "readback.json"}.issubset(case.artifact_requirements):
            errors.append(f"visual proof artifacts missing for {case.key}")
        if case.persistent and not {"stable-id.txt", "stable-hash.json"}.issubset(case.artifact_requirements):
            errors.append(f"persistent case {case.key} missing stable identity artifacts")
        for dependency in case.dependencies:
            if dependency not in index:
                errors.append(f"{case.key} depends on unknown case {dependency}")
            elif index[dependency] >= index[case.key]:
                errors.append(f"{case.key} is ordered before dependency {dependency}")
        if case.persistent and case.kind != "persistent":
            errors.append(f"persistent case {case.key} must use persistent kind")
    if errors:
        raise RuntimeError("Invalid retained matrix plan: " + "; ".join(errors))


def expand_webview_case_keys(cases: list[WebViewCaseSpec], requested: set[str]) -> list[WebViewCaseSpec]:
    if not requested:
        requested = {case.key for case in cases if case.requires_execute}
    registry = {case.key: case for case in cases}
    unknown = sorted(requested - registry.keys())
    if unknown:
        raise RuntimeError(f"Unknown case keys: {unknown}")

    closure: set[str] = set()
    visiting: set[str] = set()

    def visit(key: str) -> None:
        if key in closure:
            return
        if key in visiting:
            raise RuntimeError(f"Dependency cycle detected at {key!r}")
        visiting.add(key)
        case = registry[key]
        for dependency in case.dependencies:
            visit(dependency)
        visiting.remove(key)
        closure.add(key)

    for key in sorted(requested):
        visit(key)
    return [case for case in cases if case.key in closure]


def select_webview_cases(cases: list[WebViewCaseSpec], raw_keys: str) -> list[WebViewCaseSpec]:
    if not raw_keys.strip():
        return expand_webview_case_keys(cases, {case.key for case in cases if case.requires_execute})
    requested = [item.strip() for item in raw_keys.split(",") if item.strip()]
    if not requested:
        raise RuntimeError("--case-keys did not contain any case key")
    if len(requested) != len(set(requested)):
        raise RuntimeError("--case-keys contains duplicates")
    if any(item in {"*", "all"} for item in requested):
        if len(requested) != 1:
            raise RuntimeError("--case-keys may use all/* only by itself")
        return expand_webview_case_keys(cases, {case.key for case in cases if case.requires_execute})
    return expand_webview_case_keys(cases, set(requested))


def webview_plan_record(run_id: str, allow_deletes: bool, cases: list[WebViewCaseSpec]) -> dict[str, Any]:
    records = [webview_case_record(run_id, case) for case in cases]
    plan = {
        "schemaVersion": "1.0.0",
        "matrix": MATRIX_NAME,
        "runId": run_id,
        "plannedCaseCount": len(cases),
        "plannedModelCalls": len([case for case in cases if case.requires_execute]),
        "publicCaseKeys": [case.key for case in cases if case.requires_execute],
        "expandedCaseKeys": [case.key for case in cases],
        "persistentCaseKeys": [case.key for case in cases if case.persistent],
        "families": sorted({case.family for case in cases}),
        "safety": {
            "executeRequiresFlag": True,
            "retainObjectsByDefault": True,
            "noDeleteDefault": True,
            "allowRunnerOwnedDeletes": allow_deletes,
            "ownership": "only run-owned objects may be registered in the ledger",
            "noResend": "send-intent files are exclusive and refuse duplicates",
            "restoreTargets": ["current chat", "active preset", "plugin states", "retained objects"],
        },
        "artifactRequirements": {
            "visual": list(VISUAL_ARTIFACTS),
            "persistent": list((*VISUAL_ARTIFACTS, *PERSISTENT_ARTIFACTS)),
            "setup": list(SETUP_ARTIFACTS),
        },
        "caseRecords": records,
    }
    plan["planHash"] = stable_hash(plan)
    return plan


class WebViewOwnershipLedger:
    """Track run-owned objects and their retained identities."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        if path.exists():
            data = load_json(path)
            if data.get("runId") != run_id:
                raise RuntimeError("Ownership ledger belongs to a different run.")
            self.data = data
        else:
            self.data = {
                "schemaVersion": "1.0.0",
                "runId": run_id,
                "createdAt": now_utc(),
                "objects": {"chat": [], "preset": [], "plugin": [], "message": [], "asset": []},
            }
            self.save()

    def save(self) -> None:
        self.data["updatedAt"] = now_utc()
        atomic_json(self.path, self.data)

    def claim(self, kind: str, identity: int | str, **metadata: Any) -> None:
        objects = self.data["objects"].setdefault(kind, [])
        key = "pluginId" if kind == "plugin" else "id"
        payload = {key: identity, **metadata}
        for index, record in enumerate(objects):
            if record.get(key) == identity:
                objects[index] = {**record, **payload}
                self.save()
                return
        objects.append(payload)
        self.save()

    def owns(self, kind: str, identity: int | str) -> bool:
        key = "pluginId" if kind == "plugin" else "id"
        return any(record.get(key) == identity for record in self.data.get("objects", {}).get(kind, []))

    def require_owned(self, kind: str, identity: int | str) -> dict[str, Any]:
        key = "pluginId" if kind == "plugin" else "id"
        matches = [record for record in self.data.get("objects", {}).get(kind, []) if record.get(key) == identity]
        if len(matches) != 1:
            raise RuntimeError(f"Refusing destructive action: {kind} {identity!r} is not uniquely ledger-owned.")
        return matches[0]


def reserve_webview_case_intent(
    case_dir: Path,
    case: WebViewCaseSpec,
    run_id: str,
    *,
    stable_id: str | None = None,
    stable_hash_value: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": "1.0.0",
        "runId": run_id,
        "caseKey": case.key,
        "family": case.family,
        "kind": case.kind,
        "status": "reserved",
        "requiresExecute": case.requires_execute,
        "retainObjects": case.retain_objects,
        "noResend": case.no_resend,
        "dependencies": list(case.dependencies),
        "artifactRequirements": list(case.artifact_requirements),
        "notes": case.notes,
    }
    if stable_id is not None:
        payload["stableId"] = stable_id
    if stable_hash_value is not None:
        payload["stableHash"] = stable_hash_value
    path = case_dir / "send-intent.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(redact_sensitive(payload), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return payload


def summarize_webview_results(results: list[dict[str, Any]], planned: int) -> dict[str, Any]:
    stable_ids = [item.get("stableId") for item in results if item.get("stableId")]
    duplicate_stable_ids = sorted({item for item in stable_ids if stable_ids.count(item) > 1})
    return {
        "planned": planned,
        "executed": len(results),
        "passed": len([item for item in results if item.get("passed")]),
        "failed": len([item for item in results if not item.get("passed")]),
        "duplicateStableIds": duplicate_stable_ids,
    }


def write_matrix_bundle(artifact_dir: Path, plan: dict[str, Any], *, allow_deletes: bool) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(artifact_dir / "matrix-plan.json", plan)
    manifest = {
        "schemaVersion": "1.0.0",
        "matrix": MATRIX_NAME,
        "runId": plan["runId"],
        "status": "prepared_offline",
        "mode": "execute",
        "retainObjectsByDefault": True,
        "noDeleteDefault": True,
        "allowRunnerOwnedDeletes": allow_deletes,
        "caseCount": plan["plannedCaseCount"],
        "modelCallCount": plan["plannedModelCalls"],
        "planHash": plan["planHash"],
        "redactionPolicy": {
            "keys": list(SENSITIVE_KEY_PARTS),
            "replacement": "<redacted>",
        },
        "restoreTargets": plan["safety"]["restoreTargets"],
    }
    atomic_json(artifact_dir / "run-manifest.json", manifest)
    return manifest


def write_webview_case_bundle(
    root: Path,
    run_id: str,
    case: WebViewCaseSpec,
    plan_case: dict[str, Any],
    ledger: WebViewOwnershipLedger,
) -> dict[str, Any]:
    case_dir = root / "cases" / f"{plan_case['key']}"
    case_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(case_dir / "case.json", plan_case)
    if case.persistent:
        atomic_text(case_dir / "stable-id.txt", str(plan_case["stableId"]))
        atomic_json(case_dir / "stable-hash.json", {"stableHash": plan_case["stableHash"]})
        ledger.claim(
            "asset",
            str(plan_case["stableId"]),
            caseKind=case.kind,
            key=case.key,
            stableHash=plan_case["stableHash"],
            retained=True,
        )
    if case.requires_execute:
        reserve_webview_case_intent(
            case_dir,
            case,
            run_id,
            stable_id=str(plan_case.get("stableId")) if plan_case.get("stableId") else None,
            stable_hash_value=str(plan_case.get("stableHash")) if plan_case.get("stableHash") else None,
        )
    else:
        atomic_json(case_dir / "state.json", {"status": "setup-only", "retained": True, "caseKey": case.key})
    atomic_json(case_dir / "artifacts.json", {"required": list(case.artifact_requirements)})
    return {
        "caseKey": case.key,
        "caseDir": str(case_dir),
        "persistent": case.persistent,
        "requiresExecute": case.requires_execute,
    }


def webview_offline_self_check() -> dict[str, Any]:
    run_id = f"SELF-CHECK-{secrets.token_hex(6).upper()}"
    cases = build_webview_cases(run_id)
    plan = webview_plan_record(run_id, False, cases)
    subset = select_webview_cases(cases, "tpg-state-persistence,ejs-json-escape")
    redacted = redact_sensitive(
        {
            "authorization": "Bearer abc",
            "nested": {"secret": "x", "keep": "ok"},
            "notes": "retained",
        }
    )
    ledger = WebViewOwnershipLedger(Path("/tmp") / f"tavo-webview-matrix-{run_id}.json", run_id)
    probe_dir = Path("/tmp") / f"tavo-webview-matrix-probe-{run_id}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    intent_one = reserve_webview_case_intent(probe_dir, subset[-1], run_id)
    duplicate_refused = False
    try:
        reserve_webview_case_intent(probe_dir, subset[-1], run_id)
    except FileExistsError:
        duplicate_refused = True
    return {
        "passed": bool(
            plan["plannedCaseCount"] == len(cases)
            and plan["plannedModelCalls"] == len([case for case in cases if case.requires_execute])
            and any(case.persistent for case in cases)
            and duplicate_refused
        ),
        "runId": run_id,
        "planHash": plan["planHash"],
        "caseCount": len(cases),
        "modelCallCount": plan["plannedModelCalls"],
        "subsetExpansion": [case.key for case in subset],
        "stableIds": [record["stableId"] for record in plan["caseRecords"] if "stableId" in record],
        "redactedSample": redacted,
        "intentPreview": intent_one,
        "ledgerPath": str(ledger.path),
    }


def _default_artifact_dir(run_id: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return WORKSPACE_ROOT / "artifacts" / "tavo-validation" / f"{stamp}-{safe_name(run_id)}"


def prepare_webview_matrix_bundle(args: argparse.Namespace) -> int:
    run_id = str(getattr(args, "run_id", "") or f"WEBVIEW-PLUGIN-{secrets.token_hex(6).upper()}")
    cases = build_webview_cases(run_id, bool(getattr(args, "allow_runner_owned_deletes", False)))
    selected = select_webview_cases(cases, str(getattr(args, "case_keys", "") or ""))
    plan = webview_plan_record(run_id, bool(getattr(args, "allow_runner_owned_deletes", False)), selected)
    artifact_dir = Path(getattr(args, "artifact_dir", "") or _default_artifact_dir(run_id)).expanduser()
    ledger = WebViewOwnershipLedger(artifact_dir / "ownership-ledger.json", run_id)
    manifest = write_matrix_bundle(artifact_dir, plan, allow_deletes=bool(getattr(args, "allow_runner_owned_deletes", False)))
    results: list[dict[str, Any]] = []
    for case in selected:
        record = webview_case_record(run_id, case)
        result = write_webview_case_bundle(artifact_dir, run_id, case, record, ledger)
        results.append(result)
    atomic_json(artifact_dir / "results.json", summarize_webview_results(results, len(selected)))
    atomic_json(
        artifact_dir / "restoration-plan.json",
        {
            "currentChat": "retained",
            "activePreset": "retained",
            "pluginStates": "retained",
            "retainByDefault": True,
            "noDeleteDefault": True,
        },
    )
    atomic_json(
        artifact_dir / "run-manifest.json",
        {
            **manifest,
            "status": "prepared_offline",
            "finishedAt": now_utc(),
            "selectedCaseKeys": [case.key for case in selected if case.requires_execute],
            "expandedCaseKeys": [case.key for case in selected],
            "artifactDir": str(artifact_dir),
        },
    )
    print(json.dumps({"artifactDir": str(artifact_dir), "planHash": plan["planHash"], "caseCount": len(selected)}, ensure_ascii=False, indent=2))
    return 0


def build_webview_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retained WebView/plugin test matrix for Tavo.")
    parser.add_argument("--self-check", action="store_true", help="Validate the retained matrix offline and print JSON.")
    parser.add_argument("--print-plan", action="store_true", help="Print the retained matrix plan JSON without writing artifacts.")
    parser.add_argument("--execute", action="store_true", help="Write the retained matrix bundle to disk.")
    parser.add_argument("--case-keys", default="", help="Comma-separated subset of case keys; dependencies are auto-expanded.")
    parser.add_argument("--run-id", default="", help="Stable run identifier used in hashes and retained IDs.")
    parser.add_argument("--artifact-dir", default="", help="Override the output artifact directory.")
    parser.add_argument("--allow-runner-owned-deletes", action="store_true", default=False, help="Opt into runner-owned delete paths; default retains everything.")
    parser.add_argument("--device", default="", help="Reserved for future live phone wiring; currently recorded only.")
    parser.add_argument("--endpoint-json", default="", help="Reserved for future live phone wiring; currently recorded only.")
    parser.add_argument("--url", default="", help="Reserved for future live phone wiring; currently recorded only.")
    parser.add_argument("--auth", default="", help="Reserved for future live phone wiring; currently recorded only.")
    return parser


def webview_main() -> int:
    parser = build_webview_argument_parser()
    args = parser.parse_args()
    if not any((args.self_check, args.print_plan, args.execute)):
        parser.error("choose --self-check, --print-plan, or --execute")
    if args.self_check:
        print(json.dumps(webview_offline_self_check(), ensure_ascii=False, indent=2))
        return 0
    run_id = str(args.run_id or f"WEBVIEW-PLUGIN-{secrets.token_hex(6).upper()}")
    cases = build_webview_cases(run_id, bool(args.allow_runner_owned_deletes))
    selected = select_webview_cases(cases, str(args.case_keys or ""))
    plan = webview_plan_record(run_id, bool(args.allow_runner_owned_deletes), selected)
    if args.print_plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    return prepare_webview_matrix_bundle(args)


if __name__ == "__main__":
    raise SystemExit(main())
