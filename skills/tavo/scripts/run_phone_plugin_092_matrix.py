#!/usr/bin/env python3
"""Prepare and safely stage the Tavo 0.92 plugin/runtime phone matrix.

Offline modes never contact ADB or MCP. ``--execute`` is intentionally a
fail-closed *staging-only* operation: it requires an isolated current chat,
requires explicit protected-chat IDs, installs uniquely named fixtures disabled,
and never sends input or writes a message. It emits mechanically derived staging
assertions only; it does not run any F01-F11 runtime assertion. Runtime triggers
and their retained evidence are evaluated separately; missing evidence is
``blocked``, never a pass.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROTECTED_CHAT_IDS: frozenset[int] = frozenset()
CONFIRMATION = "TEST_CHAT_ONLY"
DEFAULT_ENDPOINT = Path("/tmp/tavo_mcp_endpoint.json")
CONSOLE_SENTINEL = "TAVO092_EVIDENCE_V1"
DUMP_SENTINEL = "TAVO092_EVIDENCE_DUMP_V1"
INSPECTOR_CASE_KEY = "INSPECTOR"
MAX_EVIDENCE_ROWS = 256
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
SECRET_PATTERN = re.compile(
    r"(?i)(?:\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b|\btavo-cap-[A-Za-z0-9_-]{8,}\b)"
)
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "key",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)
REQUIRED_LIVE_TOOLS = frozenset(
    {
        "tavo_status",
        "tavo_current_chat_get",
        "tavo_input_get",
        "tavo_plugin_get",
        "tavo_plugin_install",
        "tavo_plugin_set_enabled",
    }
)

F09_DELAY_SCENARIOS: dict[str, dict[str, Any]] = {
    "before-first": {
        "description": "Hold the stream before its first token so cancellation deterministically yields partial=false.",
        "fixtureScenario": "slow_stream",
        "delayBeforeFirstMs": 2500,
        "delayAfterFirstMs": 0,
    },
    "after-first": {
        "description": "Emit one token, then hold the stream so cancellation deterministically yields partial=true.",
        "fixtureScenario": "slow_stream",
        "delayBeforeFirstMs": 0,
        "delayAfterFirstMs": 2500,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_]", "_", key.lower()).strip("_")
    return bool(
        normalized in SENSITIVE_KEYS
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
        or normalized.endswith("_credential")
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if re.match(r"^(?:bearer|basic)\s+", value, re.IGNORECASE):
            return value.split(" ", 1)[0] + " <redacted>"
        return SECRET_PATTERN.sub("<redacted-secret>", value)
    return value


def atomic_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


@dataclass(frozen=True)
class AssertionSpec:
    key: str
    description: str
    evidence_kind: str
    required: bool = True


@dataclass(frozen=True)
class CaseSpec:
    key: str
    title: str
    surface: str
    dependencies: tuple[str, ...]
    requires_model_fixture: bool
    live_mutations: tuple[str, ...]
    assertions: tuple[AssertionSpec, ...]


def a(key: str, description: str, kind: str = "runtime-log") -> AssertionSpec:
    return AssertionSpec(key, description, kind)


def build_cases() -> tuple[CaseSpec, ...]:
    return (
        CaseSpec(
            "F01",
            "entry-only plugin without UI contributions",
            "plugin-entry",
            (),
            False,
            ("install disposable plugin", "enable in isolated chat runtime", "disable and retain"),
            (
                a("entry_started_once", "entry marker exists exactly once"),
                a("no_contribution_required", "plugin starts with no contribution object", "mcp-readback"),
                a("no_runtime_error", "no plugin bootstrap error", "logcat"),
            ),
        ),
        CaseSpec(
            "F02",
            "legacy scripts.actions compatibility",
            "plugin-entry",
            (),
            False,
            ("install disposable legacy plugin", "invoke isolated input action", "disable and retain"),
            (
                a("legacy_handler_started", "legacy action handler registered and ran"),
                a("legacy_marker_once", "legacy marker exists exactly once"),
                a("no_runtime_error", "no plugin action failure", "logcat"),
            ),
        ),
        CaseSpec(
            "F03",
            "entry precedence over scripts.actions",
            "plugin-entry",
            ("F01", "F02"),
            False,
            ("install dual-entry plugin", "invoke isolated input action", "disable and retain"),
            (
                a("entry_marker_once", "entry.js marker exists exactly once"),
                a("legacy_marker_absent", "legacy marker is absent"),
                a("single_dispatch", "action dispatched exactly once"),
            ),
        ),
        CaseSpec(
            "F04",
            "plugin config default/override/copy isolation",
            "plugin-config",
            ("F01",),
            False,
            ("install config fixture", "set disposable config override", "disable and retain"),
            (
                a("default_value_seen", "config.get returns schema default"),
                a("override_value_seen", "saved override wins over default"),
                a("all_returns_effective_copy", "config.all returns effective values"),
                a("mutating_copy_not_persisted", "mutating config.all result does not save"),
            ),
        ),
        CaseSpec(
            "F05",
            "chat and persistent-message notification ordering",
            "notification-hooks",
            ("F01",),
            True,
            ("enable hook fixture in isolated chat", "create/update/delete disposable messages", "disable and retain"),
            (
                a("chat_events_fields", "chat events contain type/pluginId/at/chatId"),
                a("chat_changed_alias_normalized", "chat:changed handler receives chat:updated"),
                a("message_specific_before_changed", "specific message event precedes message:changed"),
                a("stream_intermediate_not_added", "streaming intermediate states do not emit message:added"),
                a("handler_error_isolated", "one failing handler does not block later handlers"),
            ),
        ),
        CaseSpec(
            "F06",
            "input interception across mcp/tavojs/ui",
            "input-hooks",
            ("F05",),
            True,
            ("send ASCII-only disposable prompts in isolated chat", "exercise cancel/error/invalid/timeout", "clear input"),
            (
                a("sources_all_seen", "source allowlist contains mcp, tavojs, and ui"),
                a("rewrite_committed", "normal rewrite reaches accepted input"),
                a("cancel_preserves_input", "explicit cancel preserves the latest committed input"),
                AssertionSpec(
                    "cancel_preserves_attachments_if_exposed",
                    "when the runtime exposes safe attachment metadata, explicit cancel preserves its count",
                    "runtime-log",
                    False,
                ),
                a("second_handler_isolated", "a later canary handler still runs after throw, invalid text, or timeout"),
                a("throw_fail_open", "throw rolls back only its handler"),
                a("invalid_fail_open", "non-string text rolls back only its handler"),
                a("timeout_fail_open", "five-second timeout rolls back only its handler"),
                a("after_send_acceptance_only", "afterSend occurs on acceptance before model completion"),
            ),
        ),
        CaseSpec(
            "F07",
            "generation prepare model-only rewrite",
            "generation-hooks",
            ("F05",),
            True,
            ("temporary fixture API on isolated chat", "one deterministic generation", "restore original API"),
            (
                a("prepare_source_reply", "prepare source is reply"),
                a("captured_last_user_rewritten", "fixture capture contains rewritten final user request" , "request-capture"),
                a("persistent_user_original", "saved user message remains original", "mcp-readback"),
                a("stable_plugin_order", "multiple prepare handlers run in stable order"),
            ),
        ),
        CaseSpec(
            "F08",
            "generation success rewrite and rollback",
            "generation-hooks",
            ("F07",),
            True,
            ("deterministic JSON and SSE generations", "read saved assistant messages", "restore original API"),
            (
                a("success_before_save", "valid success rewrite appears in saved character message"),
                a("empty_rewrite_discarded", "empty success rewrite is discarded"),
                a("throw_rewrite_discarded", "throwing success handler fails open"),
                a("timeout_rewrite_discarded", "timed-out success handler fails open"),
            ),
        ),
        CaseSpec(
            "F09",
            "generation terminal/source/cancellation matrix",
            "generation-hooks",
            ("F07", "F08"),
            True,
            ("fixture HTTP/protocol/slow-stream cases", "cancel disposable generation", "restore original API"),
            (
                a("source_allowlist", "reply/regeneration/continuation/othersContinuation are observed"),
                a("error_sanitized", "error exposes only sanitized code and message"),
                a("cancel_partial_saved", "partial=true saves one partial character message"),
                a("cancel_empty_not_saved", "partial=false saves no character message"),
                a("one_terminal_event", "each generation has exactly one terminal event"),
                a("auxiliary_paths_excluded", "independent/image/speech/summary paths do not trigger hooks"),
            ),
        ),
        CaseSpec(
            "F10",
            "tavo.input.send result contract",
            "tavojs-input",
            ("F06",),
            True,
            ("invoke disposable input action in isolated chat", "exercise accepted and cancelled send", "clear input"),
            (
                a("success_shape", "success is {ok:true,text}"),
                a("failure_shape", "failure is {ok:false,reason,text}"),
                a("reason_allowlist", "reason is cancelled, busy, or rejected"),
                a("resolves_before_generation", "promise resolves before downstream generation finishes"),
            ),
        ),
        CaseSpec(
            "F11",
            "plugin TTS explicit speaker and shared stop",
            "tts",
            ("F01",),
            False,
            ("invoke short disposable TTS task", "stop shared current-chat queue", "restore voice rules"),
            (
                a("missing_voice_rejected", "plugin TTS rejects missing voice"),
                a("exactly_one_voice_accepted", "exactly one character/persona voice is accepted"),
                a("both_voices_rejected", "character plus persona is rejected"),
                a("stop_clears_queue", "stop clears the current chat shared queue"),
                a("human_audio_check", "human confirms correct audible voice", "human"),
            ),
        ),
    )


def expand_cases(cases: tuple[CaseSpec, ...], requested: str | None) -> tuple[CaseSpec, ...]:
    by_key = {case.key: case for case in cases}
    if not requested:
        return cases
    keys = [item.strip().upper() for item in requested.split(",") if item.strip()]
    if len(keys) != len(set(keys)):
        raise RuntimeError("--cases contains duplicates")
    unknown = sorted(set(keys) - set(by_key))
    if unknown:
        raise RuntimeError(f"Unknown case key: {unknown[0]}")
    selected: set[str] = set()

    def add(key: str) -> None:
        for dependency in by_key[key].dependencies:
            add(dependency)
        selected.add(key)

    for key in keys:
        add(key)
    return tuple(case for case in cases if case.key in selected)


def validate_catalog(cases: tuple[CaseSpec, ...]) -> list[str]:
    failures: list[str] = []
    keys = [case.key for case in cases]
    if keys != [f"F{index:02d}" for index in range(1, 12)]:
        failures.append("case keys must be exactly F01-F11")
    if len(keys) != len(set(keys)):
        failures.append("case keys are not unique")
    known = set(keys)
    assertion_keys: set[str] = set()
    for case in cases:
        if any(dep not in known for dep in case.dependencies):
            failures.append(f"{case.key} has an unknown dependency")
        if case.key in case.dependencies:
            failures.append(f"{case.key} depends on itself")
        if not case.assertions:
            failures.append(f"{case.key} has no assertions")
        for assertion in case.assertions:
            scoped = f"{case.key}.{assertion.key}"
            if scoped in assertion_keys:
                failures.append(f"duplicate assertion: {scoped}")
            assertion_keys.add(scoped)
    return failures


def plan_record(run_id: str, cases: tuple[CaseSpec, ...]) -> dict[str, Any]:
    # ``atomic_json`` deliberately redacts values under generic secret-shaped
    # keys such as ``key``.  Plan identifiers are structural, not credentials,
    # so serialize them under unambiguous names.  This also ensures the stored
    # plan bytes still hash to ``planHash`` after the artifact redaction pass.
    plan_cases = [
        {
            "caseKey": case.key,
            "title": case.title,
            "surface": case.surface,
            "dependencies": list(case.dependencies),
            "requires_model_fixture": case.requires_model_fixture,
            "live_mutations": list(case.live_mutations),
            "assertions": [
                {
                    "assertionKey": assertion.key,
                    "description": assertion.description,
                    "evidence_kind": assertion.evidence_kind,
                    "required": assertion.required,
                }
                for assertion in case.assertions
            ],
        }
        for case in cases
    ]
    payload = {
        "schemaVersion": 1,
        "runId": run_id,
        "appVersion": "0.92.0",
        "cases": plan_cases,
        "protectedChatIds": sorted(PROTECTED_CHAT_IDS),
        "evidenceInspector": {
            "separatePlugin": True,
            "pluginId": plugin_id(run_id, INSPECTOR_CASE_KEY),
            "dumpSentinel": DUMP_SENTINEL,
            "actions": {
                case.key: [f"dump-{case.key.lower()}", f"clear-{case.key.lower()}"]
                for case in cases
            },
        },
        "modelFixtureScenarios": {"F09": F09_DELAY_SCENARIOS},
        "safety": {
            "offlineModesContactPhone": False,
            "executeRequiresConfirmation": CONFIRMATION,
            "executeRequiresIsolatedCurrentChat": True,
            "executeSendsMessages": False,
            "executeInstallsFixturesDisabled": True,
            "executeRunsRuntimeAssertions": False,
            "secretsStoredInArtifacts": False,
            "missingEvidenceClassification": "blocked",
        },
    }
    payload["planHash"] = canonical_hash(payload)
    return payload


def evaluate_case(case: CaseSpec, evidence: dict[str, Any] | None) -> dict[str, Any]:
    observations = evidence.get("assertions", {}) if isinstance(evidence, dict) else {}
    if not isinstance(observations, dict):
        observations = {}
    missing: list[str] = []
    failed: list[str] = []
    passed: list[str] = []
    for assertion in case.assertions:
        value = observations.get(assertion.key)
        if value is True:
            passed.append(assertion.key)
        elif value is False:
            failed.append(assertion.key)
        elif assertion.required:
            missing.append(assertion.key)
    if failed:
        status = "failed"
    elif missing:
        status = "blocked"
    else:
        status = "passed"
    return {"case": case.key, "status": status, "passed": passed, "failed": failed, "missing": missing}


def evaluate_matrix(cases: tuple[CaseSpec, ...], evidence: dict[str, Any]) -> dict[str, Any]:
    per_case = evidence.get("cases", evidence) if isinstance(evidence, dict) else {}
    if not isinstance(per_case, dict):
        per_case = {}
    results = [evaluate_case(case, per_case.get(case.key)) for case in cases]
    counts = {status: sum(item["status"] == status for item in results) for status in ("passed", "failed", "blocked")}
    return {"schemaVersion": 1, "results": results, "counts": counts, "ok": counts["failed"] == 0 and counts["blocked"] == 0}


def normalized_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError("run id must be 3-64 ASCII letters, digits, underscore, or hyphen")
    return run_id


def plugin_id(run_id: str, case_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", run_id.lower()).strip("-")
    return f"dev.tavo.validation.v092.{slug}.{case_key.lower()}"


def evidence_key(run_id: str, case_key: str) -> str:
    safe_run = re.sub(r"[^A-Za-z0-9_]", "_", run_id)
    safe_case = re.sub(r"[^A-Za-z0-9_]", "_", case_key)
    return f"__tavo092_{safe_run}_{safe_case}"


def record_helper(run_id: str, case_key: str) -> str:
    variable = evidence_key(run_id, case_key)
    safe_keys = [
        "action",
        "after",
        "all",
        "at",
        "attachmentMeta",
        "before",
        "cancelledBy",
        "change",
        "chatId",
        "code",
        "count",
        "delayMs",
        "enabled",
        "elapsedMs",
        "error",
        "exposed",
        "field",
        "fields",
        "first",
        "flag",
        "generationId",
        "hidden",
        "id",
        "index",
        "isUser",
        "marker",
        "message",
        "mode",
        "name",
        "ok",
        "partial",
        "phase",
        "pluginId",
        "reason",
        "result",
        "role",
        "second",
        "source",
        "text",
        "type",
    ]
    return f"""const EVIDENCE_SCHEMA_VERSION = 1;
const EVIDENCE_KEY = {json.dumps(variable)};
const EVIDENCE_RUN_ID = {json.dumps(run_id)};
const EVIDENCE_CASE = {json.dumps(case_key)};
const EVIDENCE_CONSOLE_SENTINEL = {json.dumps(CONSOLE_SENTINEL)};
const EVIDENCE_RUNTIME_ID = `${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 10)}}`;
const EVIDENCE_SAFE_KEYS = new Set({json.dumps(safe_keys)});
const EVIDENCE_SECRET_PATTERN = /(?:(?:sk|rk|pk)-[A-Za-z0-9_-]{{12,}}|tavo-cap-[A-Za-z0-9_-]{{8,}})/gi;
const EVIDENCE_AUTH_PATTERN = /\\b(Bearer|Basic)\\s+[A-Za-z0-9._~+/=-]+/gi;
const EVIDENCE_CREDENTIAL_PATTERN = /\\b(authorization|token|secret|password|api[-_ ]?key)\\s*[:=]\\s*\\S+/gi;
function evidenceProject(value, key = '', depth = 0) {{
  if (depth > 4) return '[depth-limit]';
  if (value === null || typeof value === 'boolean' || typeof value === 'number') return value;
  if (typeof value === 'string') {{
    const clean = value
      .replace(EVIDENCE_SECRET_PATTERN, '<redacted-secret>')
      .replace(EVIDENCE_AUTH_PATTERN, '$1 <redacted>')
      .replace(EVIDENCE_CREDENTIAL_PATTERN, '$1=<redacted>');
    if (key === 'text') {{
      const markers = clean.match(/\\[(?:F[0-9]{{2}}_[A-Z0-9_-]+|TAVO_FIXTURE_[A-Z0-9:_-]+)\\]/g) || [];
      return {{ length: clean.length, markers: markers.slice(0, 16) }};
    }}
    return clean.slice(0, 256);
  }}
  if (Array.isArray(value)) return value.slice(0, 32).map(item => evidenceProject(item, key, depth + 1));
  if (typeof value === 'object') {{
    const projected = {{}};
    for (const [childKey, childValue] of Object.entries(value)) {{
      if (EVIDENCE_SAFE_KEYS.has(childKey)) projected[childKey] = evidenceProject(childValue, childKey, depth + 1);
    }}
    return projected;
  }}
  return String(value).slice(0, 128);
}}
function record(kind, payload = {{}}) {{
  const prior = tavo.get(EVIDENCE_KEY, 'global');
  const existing = Array.isArray(prior) ? prior : [];
  const previousSeq = Number(existing[existing.length - 1]?.seq || 0);
  const row = {{
    schemaVersion: EVIDENCE_SCHEMA_VERSION,
    runId: EVIDENCE_RUN_ID,
    case: EVIDENCE_CASE,
    pluginId: String(tavo.plugin?.pluginId || ''),
    runtimeId: EVIDENCE_RUNTIME_ID,
    seq: previousSeq + 1,
    kind: String(kind).slice(0, 96),
    payload: evidenceProject(payload),
    at: new Date().toISOString(),
  }};
  const rows = existing.slice(-{MAX_EVIDENCE_ROWS - 1});
  rows.push(row);
  tavo.set(EVIDENCE_KEY, rows, 'global');
  console.log(`${{EVIDENCE_CONSOLE_SENTINEL}}|${{EVIDENCE_RUN_ID}}|${{EVIDENCE_CASE}}|${{JSON.stringify(row)}}`);
}}
"""


def evidence_inspector_files(run_id: str, cases: tuple[CaseSpec, ...]) -> dict[str, bytes]:
    pid = plugin_id(run_id, INSPECTOR_CASE_KEY)
    actions: list[dict[str, str]] = []
    entry = f"""const EVIDENCE_DUMP_SENTINEL = {json.dumps(DUMP_SENTINEL)};
const EVIDENCE_CONSOLE_SENTINEL = {json.dumps(CONSOLE_SENTINEL)};
function evidenceBase64(value) {{
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}}
"""
    for case in cases:
        lower = case.key.lower()
        key = evidence_key(run_id, case.key)
        actions.extend(
            [
                {"id": f"dump-{lower}", "label": f"T092 dump {case.key}"},
                {"id": f"clear-{lower}", "label": f"T092 clear {case.key}"},
            ]
        )
        entry += f"""tavo.plugin.onInputAction('dump-{lower}', async () => {{
  const raw = tavo.get({json.dumps(key)}, 'global');
  const rows = Array.isArray(raw) ? raw.slice(-{MAX_EVIDENCE_ROWS}) : [];
  const envelope = JSON.stringify({{ schemaVersion: 1, runId: {json.dumps(run_id)}, case: {json.dumps(case.key)}, rows }});
  await tavo.input.set(`${{EVIDENCE_DUMP_SENTINEL}}|{run_id}|{case.key}|${{evidenceBase64(envelope)}}`);
  console.log(`${{EVIDENCE_CONSOLE_SENTINEL}}|INSPECTOR|dump|{case.key}|${{rows.length}}`);
}});
tavo.plugin.onInputAction('clear-{lower}', async () => {{
  tavo.unset({json.dumps(key)}, 'global');
  console.log(`${{EVIDENCE_CONSOLE_SENTINEL}}|INSPECTOR|clear|{case.key}`);
}});
"""
    manifest = {
        "id": pid,
        "name": f"Tavo 0.92 Matrix {run_id} Evidence Inspector",
        "version": "0.92.0-test.1",
        "description": "Separate disposable evidence bridge; not part of any F01-F11 contribution assertion.",
        "author": "Codex validation",
        "entry": "entry.js",
        "permissions": ["input", "variable"],
        "contributes": {"inputActions": actions},
    }
    return {
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "entry.js": entry.encode("utf-8"),
    }


def fixture_files(run_id: str, case: CaseSpec) -> dict[str, bytes]:
    pid = plugin_id(run_id, case.key)
    manifest: dict[str, Any] = {
        "id": pid,
        "name": f"Tavo 0.92 Matrix {run_id} {case.key}",
        "version": "0.92.0-test.1",
        "description": f"Disposable retained fixture for {case.title}.",
        "author": "Codex validation",
    }
    helper = record_helper(run_id, case.key)
    entry = helper + f"record('entry', {{ marker: '{case.key}_ENTRY' }});\n"
    extra: dict[str, str] = {}

    if case.key == "F02":
        manifest["scripts"] = {"actions": "legacy.js"}
        manifest["contributes"] = {"inputActions": [{"id": "probe", "label": "F02 probe"}]}
        extra["legacy.js"] = helper + "record('legacy-loaded'); tavo.plugin.onInputAction('probe', async () => record('legacy-action'));\n"
        entry = ""
    elif case.key == "F03":
        manifest["entry"] = "entry.js"
        manifest["scripts"] = {"actions": "legacy.js"}
        manifest["contributes"] = {"inputActions": [{"id": "probe", "label": "F03 probe"}]}
        entry += "tavo.plugin.onInputAction('probe', async () => record('entry-action'));\n"
        extra["legacy.js"] = helper + "record('legacy-loaded'); tavo.plugin.onInputAction('probe', async () => record('legacy-action'));\n"
    elif case.key == "F04":
        manifest["entry"] = "entry.js"
        manifest["contributes"] = {
            "settings": {
                "schema": [
                    {"key": "mode", "type": "text", "label": "Mode", "default": "default-mode"},
                    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
                ]
            }
        }
        entry += "const first = tavo.plugin.config.all(); const before = tavo.plugin.config.get('mode'); first.mode = 'mutated-copy'; record('config', { before, after: tavo.plugin.config.get('mode'), all: tavo.plugin.config.all() });\n"
    elif case.key == "F05":
        manifest["entry"] = "entry.js"
        for name in ("chat:opened", "chat:updated", "chat:changed", "chat:closed", "message:added", "message:updated", "message:deleted", "message:changed"):
            entry += f"tavo.plugin.on('{name}', async (event) => record('{name}', event));\n"
        entry += "tavo.plugin.on('message:changed', async () => { throw new Error('F05 intentional handler isolation probe'); });\n"
        entry += "tavo.plugin.on('message:changed', async (event) => record('message:changed-after-throw', event));\n"
    elif case.key == "F06":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["input"]
        entry += """function f06SafeAttachmentMeta(event) {
  const fields = [];
  for (const field of ['attachments', 'files', 'images']) {
    const candidate = event?.[field];
    if (Array.isArray(candidate)) fields.push({ field, count: candidate.length });
  }
  for (const field of ['attachmentCount', 'fileCount', 'imageCount']) {
    const candidate = event?.[field];
    if (Number.isSafeInteger(candidate) && candidate >= 0) fields.push({ field, count: candidate });
  }
  for (const field of ['hasAttachments', 'hasFiles', 'hasImages']) {
    const candidate = event?.[field];
    if (typeof candidate === 'boolean') fields.push({ field, flag: candidate });
  }
  return fields.length > 0 ? { exposed: true, fields } : null;
}
function f06Evidence(event) {
  const payload = { source: event.source, text: event.text };
  const attachmentMeta = f06SafeAttachmentMeta(event);
  if (attachmentMeta) payload.attachmentMeta = attachmentMeta;
  return payload;
}
tavo.plugin.on('input:beforeSend', async (event) => {
  record('before', f06Evidence(event));
  if (event.text.includes('[F06_CANCEL]')) event.cancel('matrix-cancel');
  else if (event.text.includes('[F06_THROW]')) throw new Error('F06 intentional');
  else if (event.text.includes('[F06_INVALID]')) event.text = 42;
  else if (event.text.includes('[F06_TIMEOUT]')) await new Promise(resolve => setTimeout(resolve, 6000));
  else event.text = '[F06_REWRITE]' + event.text;
});
tavo.plugin.on('input:beforeSend', async (event) => record('before-canary', f06Evidence(event)));
tavo.plugin.on('input:afterSend', async (event) => record('after', f06Evidence(event)));
"""
    elif case.key == "F07":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["generate"]
        entry += "tavo.plugin.on('generation:prepare', async (event) => { record('prepare-before', event); event.text = '[F07_MODEL_ONLY]' + event.text; record('prepare-after', event); });\n"
    elif case.key == "F08":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["generate"]
        manifest["contributes"] = {
            "settings": {
                "schema": [
                    {
                        "key": "mode",
                        "type": "select",
                        "label": "F08 success mode",
                        "default": "append",
                        "options": ["append", "empty", "throw", "timeout"],
                    }
                ]
            }
        }
        entry += """tavo.plugin.on('generation:success', async (event) => {
  const mode = String(tavo.plugin.config.get('mode') || 'append');
  record('success-before', { type: event.type, pluginId: event.pluginId, at: event.at, chatId: event.chatId, generationId: event.generationId, source: event.source, text: event.text, mode });
  if (mode === 'empty') event.text = '';
  else if (mode === 'throw') throw new Error('F08 intentional');
  else if (mode === 'timeout') await new Promise(resolve => setTimeout(resolve, 6000));
  else event.text = event.text + '[F08_SAVED]';
});
"""
    elif case.key == "F09":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["generate"]
        manifest["contributes"] = {
            "settings": {
                "schema": [
                    {
                        "key": "cancelWindow",
                        "type": "select",
                        "label": "F09 deterministic cancellation window",
                        "default": "before-first",
                        "options": sorted(F09_DELAY_SCENARIOS),
                    },
                    {
                        "key": "delayMs",
                        "type": "slider",
                        "label": "Fixture delay milliseconds",
                        "min": 500,
                        "max": 10000,
                        "step": 100,
                        "default": 2500,
                    },
                ]
            }
        }
        extra["fixture-scenarios.json"] = json.dumps(
            {"schemaVersion": 1, "scenarios": F09_DELAY_SCENARIOS},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        entry += "record('cancel-window-config', { phase: tavo.plugin.config.get('cancelWindow'), delayMs: tavo.plugin.config.get('delayMs') });\n"
        for name in ("generation:prepare", "generation:success", "generation:error", "generation:cancelled"):
            entry += f"tavo.plugin.on('{name}', async (event) => record('{name}', event));\n"
    elif case.key == "F10":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["input"]
        manifest["contributes"] = {"inputActions": [{"id": "send-probe", "label": "F10 send probe"}]}
        entry += "tavo.plugin.onInputAction('send-probe', async () => { const started = Date.now(); const result = await tavo.input.send(); record('input-send-result', { result, elapsedMs: Date.now() - started }); });\n"
    elif case.key == "F11":
        manifest["entry"] = "entry.js"
        manifest["permissions"] = ["tts"]
        manifest["contributes"] = {
            "sidebar": [
                {"id": "missing", "label": "F11 missing voice"},
                {"id": "character", "label": "F11 character voice"},
                {"id": "user", "label": "F11 user voice"},
                {"id": "both", "label": "F11 both voices"},
                {"id": "queue", "label": "F11 queue voices"},
                {"id": "stop", "label": "F11 stop"},
            ]
        }
        entry += """async function f11VoiceTargets() {
  const chat = await tavo.chat.current();
  const character = chat?.character ?? chat?.characterId ?? chat?.characterIds?.[0] ?? chat?.characters?.[0] ?? null;
  const persona = chat?.persona ?? chat?.personaId ?? null;
  return { character, persona };
}
async function f11Play(action, voice, options = {}) {
  try {
    const result = await tavo.tts.play(`F11 ${action} voice`, { voice, ...options });
    record(result ? 'tts-accepted' : 'tts-rejected', { action, result: Boolean(result) });
    return Boolean(result);
  } catch (error) {
    record('tts-rejected', { action, result: false, name: error?.name, message: String(error?.message || error) });
    return false;
  }
}
"""
        entry += "tavo.plugin.onSidebarAction('missing', async () => { try { const result = await tavo.tts.play('F11'); record(result ? 'missing-unexpected-success' : 'missing-rejected', { result: Boolean(result) }); } catch (error) { record('missing-rejected', { result: false, name: error?.name, message: String(error?.message || error) }); } });\n"
        entry += "tavo.plugin.onSidebarAction('character', async () => { const { character } = await f11VoiceTargets(); await f11Play('character', { character }); });\n"
        entry += "tavo.plugin.onSidebarAction('user', async () => { const { persona } = await f11VoiceTargets(); await f11Play('user', { persona }); });\n"
        entry += "tavo.plugin.onSidebarAction('both', async () => { const { character, persona } = await f11VoiceTargets(); await f11Play('both', { character, persona }); });\n"
        entry += "tavo.plugin.onSidebarAction('queue', async () => { const { character } = await f11VoiceTargets(); const first = await f11Play('queue-first', { character }, { queue: false }); const second = first ? await f11Play('queue-second', { character }, { queue: true }) : false; record('queue-results', { first, second }); });\n"
        entry += "tavo.plugin.onSidebarAction('stop', async () => { await tavo.tts.stop(); record('stop-complete'); });\n"
    else:
        manifest["entry"] = "entry.js"

    files: dict[str, bytes] = {
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    }
    if entry:
        files["entry.js"] = entry.encode("utf-8")
    files.update({name: value.encode("utf-8") for name, value in extra.items()})
    return files


def deterministic_zip(files: dict[str, bytes]) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
                raise RuntimeError(f"Unsafe fixture path: {name}")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[name])
    return output.getvalue()


def prepare_bundle(output: Path, run_id: str, cases: tuple[CaseSpec, ...]) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.is_symlink():
        raise RuntimeError("output cannot be a symlink")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output must be absent or empty: {output}")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    plan = plan_record(run_id, cases)
    atomic_json(output / "plan.json", plan, exclusive=True)
    packages: list[dict[str, Any]] = []
    fixture_definitions = [
        (case.key, plugin_id(run_id, case.key), fixture_files(run_id, case))
        for case in cases
    ]
    fixture_definitions.append(
        (
            INSPECTOR_CASE_KEY,
            plugin_id(run_id, INSPECTOR_CASE_KEY),
            evidence_inspector_files(run_id, cases),
        )
    )
    for case_key, fixture_plugin_id, files in fixture_definitions:
        case_dir = output / "fixtures" / case_key
        case_dir.mkdir(mode=0o700, parents=True)
        for name, raw in files.items():
            destination = case_dir / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
        package = deterministic_zip(files)
        package_path = output / "packages" / f"{case_key}-{run_id}.tpg"
        package_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(package_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(package)
        packages.append(
            {
                "case": case_key,
                "pluginId": fixture_plugin_id,
                "package": str(package_path),
                "sha256": sha256_bytes(package),
                "bytes": len(package),
                "files": {name: sha256_bytes(raw) for name, raw in sorted(files.items())},
            }
        )
    summary = {"schemaVersion": 1, "runId": run_id, "planHash": plan["planHash"], "packages": packages}
    atomic_json(output / "prepared.json", summary, exclusive=True)
    return summary


def self_check(run_id: str) -> dict[str, Any]:
    cases = build_cases()
    failures = validate_catalog(cases)
    redacted = redact(
        {
            "authorization": "Bearer secret-value",
            "nested": {"apiKey": "hidden", "note": "sk-1234567890abcdefghijklmnop"},
        }
    )
    if redacted["authorization"] != "<redacted>":
        failures.append("authorization redaction failed")
    if redacted["nested"]["apiKey"] != "<redacted>":
        failures.append("nested secret redaction failed")
    if "sk-123456" in redacted["nested"]["note"]:
        failures.append("embedded secret redaction failed")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "bundle"
        summary = prepare_bundle(root, run_id, cases)
        for package in summary["packages"]:
            path = Path(package["package"])
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if names != sorted(names):
                    failures.append(f"{package['case']} zip order is not deterministic")
                if "manifest.json" not in names:
                    failures.append(f"{package['case']} lacks root manifest")
            first = path.read_bytes()
            if package["case"] == INSPECTOR_CASE_KEY:
                recreated_files = evidence_inspector_files(run_id, cases)
            else:
                recreated_files = fixture_files(
                    run_id,
                    next(case for case in cases if case.key == package["case"]),
                )
            recreated = deterministic_zip(recreated_files)
            if first != recreated:
                failures.append(f"{package['case']} package bytes are not deterministic")
    return {
        "ok": not failures,
        "caseCount": len(cases),
        "assertionCount": sum(len(case.assertions) for case in cases),
        "failures": failures,
        "protectedChatIds": sorted(PROTECTED_CHAT_IDS),
    }


def read_private_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError(f"private JSON cannot be a symlink: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise RuntimeError(f"private JSON must be a mode-0600 regular file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"private JSON must contain an object: {path}")
    return payload


class TavoMcp:
    def __init__(self, url: str, auth: str) -> None:
        self.url = url
        self.auth = auth
        self.next_id = 1

    def rpc(self, method: str, params: dict[str, Any] | None = None, *, timeout: int = 60) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = self.auth if self.auth.lower().startswith("bearer ") else f"Bearer {self.auth}"
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("MCP response must be an object")
        return result

    def initialize(self) -> dict[str, Any]:
        return self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "tavo-092-phone-matrix", "version": "1.0"},
            },
        )

    def tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": name, "arguments": arguments or {}})


def response_payload(response: dict[str, Any]) -> Any:
    try:
        text = response["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text


def response_ok(response: dict[str, Any]) -> bool:
    if "error" in response:
        return False
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return False
    payload = response_payload(response)
    return not (isinstance(payload, dict) and (payload.get("ok") is False or payload.get("success") is False))


def current_chat_id(response: dict[str, Any]) -> int | None:
    payload = response_payload(response)
    if not isinstance(payload, dict):
        return None
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else payload
    value = chat.get("id") if isinstance(chat, dict) else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def plugin_readback_record(payload: Any, expected_plugin_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    for key in ("plugin", "data", "item"):
        if isinstance(payload.get(key), dict):
            candidates.append(payload[key])
    for candidate in candidates:
        manifest = candidate.get("manifest") if isinstance(candidate.get("manifest"), dict) else {}
        observed_id = candidate.get("pluginId") or candidate.get("id") or manifest.get("id")
        if observed_id == expected_plugin_id:
            return candidate
    return None


def staging_assertions(
    package: dict[str, Any],
    dry_run: dict[str, Any],
    install: dict[str, Any],
    disable: dict[str, Any],
    readback: dict[str, Any],
) -> dict[str, bool | None]:
    expected_plugin_id = str(package.get("pluginId") or "")
    record = plugin_readback_record(response_payload(readback), expected_plugin_id)
    readback_enabled = record.get("enabled") if isinstance(record, dict) else None
    return {
        "packageSha256Recorded": bool(re.fullmatch(r"[0-9a-f]{64}", str(package.get("sha256") or ""))),
        "dryRunAccepted": response_ok(dry_run),
        "installAccepted": response_ok(install),
        "disableAccepted": response_ok(disable),
        "readbackAccepted": response_ok(readback),
        "readbackPluginIdMatches": record is not None if response_ok(readback) else False,
        "readbackDisabled": (readback_enabled is False) if isinstance(readback_enabled, bool) else None,
    }


def adb_gate(device: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["adb", "-s", device, "get-state"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "device":
        raise RuntimeError(f"ADB device is unavailable: {device}")
    return {"device": device, "state": "device"}


def reserve_intent(path: Path, payload: dict[str, Any]) -> None:
    atomic_json(path, {**payload, "status": "reserved", "reservedAt": utc_now()}, exclusive=True)


def execute_live(args: argparse.Namespace, cases: tuple[CaseSpec, ...]) -> dict[str, Any]:
    run_id = normalized_run_id(args.run_id)
    protected_chat_ids = frozenset(getattr(args, "protected_chat_ids", ()) or ())
    if args.confirm != CONFIRMATION:
        raise RuntimeError(f"--execute requires --confirm {CONFIRMATION}")
    if not protected_chat_ids or any(chat_id < 1 for chat_id in protected_chat_ids):
        raise RuntimeError("--execute requires at least one valid --protected-chat-id")
    if args.test_chat_id < 1 or args.test_chat_id in protected_chat_ids:
        raise RuntimeError(f"refusing protected or invalid test chat id: {args.test_chat_id}")
    if not args.device:
        raise RuntimeError("--execute requires --device or TAVO_DEVICE")
    if not args.fixture_base_url.startswith("http://") and not args.fixture_base_url.startswith("https://"):
        raise RuntimeError("--fixture-base-url must be an absolute HTTP(S) URL")
    artifact = args.output.expanduser().resolve()
    if artifact.exists() and any(artifact.iterdir()):
        raise RuntimeError("live output must be absent or empty")
    artifact.mkdir(mode=0o700, parents=True, exist_ok=True)
    artifact.chmod(0o700)
    endpoint = read_private_json(args.endpoint_file.expanduser())
    url = str(endpoint.get("url") or endpoint.get("lan_url") or "")
    auth = str(endpoint.get("auth") or endpoint.get("authorization") or endpoint.get("token") or "")
    if not url or not auth:
        raise RuntimeError("endpoint file must contain URL and authorization")
    gate = adb_gate(args.device)
    client = TavoMcp(url, auth)
    initialized = client.initialize()
    tools = client.rpc("tools/list")
    tool_items = tools.get("result", {}).get("tools", []) if isinstance(tools.get("result"), dict) else []
    names = {item.get("name") for item in tool_items if isinstance(item, dict)}
    missing_tools = sorted(REQUIRED_LIVE_TOOLS - names)
    if missing_tools:
        raise RuntimeError(f"MCP surface lacks required tools: {', '.join(missing_tools)}")
    before = client.tool("tavo_current_chat_get")
    before_id = current_chat_id(before)
    if not response_ok(before) or before_id != args.test_chat_id:
        raise RuntimeError(f"current chat must equal isolated --test-chat-id {args.test_chat_id}; got {before_id}")
    if before_id in protected_chat_ids:
        raise RuntimeError("protected chat is current; refusing all writes")
    input_state = client.tool("tavo_input_get")
    input_payload = response_payload(input_state)
    if not response_ok(input_state) or not isinstance(input_payload, dict):
        raise RuntimeError("could not prove current input state")
    if str(input_payload.get("text") or ""):
        raise RuntimeError("isolated test chat input must be empty before fixture installation")

    bundle = prepare_bundle(artifact / "bundle", run_id, cases)
    atomic_json(
        artifact / "preflight.json",
        {
            "adb": gate,
            "initialize": initialized,
            "toolCount": len(names),
            "currentChatId": before_id,
            "fixtureBaseUrl": args.fixture_base_url,
            "inputBlank": True,
        },
        exclusive=True,
    )
    outcomes: list[dict[str, Any]] = []
    for package in bundle["packages"]:
        case_key = str(package["case"])
        case_dir = artifact / "live" / case_key
        case_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        reserve_intent(
            case_dir / "intent.json",
            {
                "case": case_key,
                "operation": "install-disposable-fixture-disabled",
                "pluginId": package["pluginId"],
                "testChatId": args.test_chat_id,
            },
        )
        zip_base64 = base64.b64encode(Path(package["package"]).read_bytes()).decode("ascii")
        dry: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        disabled: dict[str, Any] = {}
        readback: dict[str, Any] = {}
        dry = client.tool("tavo_plugin_install", {"zipBase64": zip_base64, "dryRun": True})
        atomic_json(case_dir / "install-dry-run.json", dry, exclusive=True)
        if not response_ok(dry):
            assertions = staging_assertions(package, dry, actual, disabled, readback)
            atomic_json(case_dir / "staging-assertions.json", assertions, exclusive=True)
            outcomes.append(
                {
                    "case": case_key,
                    "status": "failed",
                    "reason": "install dry-run failed",
                    "stagingAssertions": assertions,
                }
            )
            break
        actual = client.tool("tavo_plugin_install", {"zipBase64": zip_base64, "dryRun": False})
        atomic_json(case_dir / "install.json", actual, exclusive=True)
        if not response_ok(actual):
            assertions = staging_assertions(package, dry, actual, disabled, readback)
            atomic_json(case_dir / "staging-assertions.json", assertions, exclusive=True)
            outcomes.append(
                {
                    "case": case_key,
                    "status": "failed",
                    "reason": "install failed",
                    "stagingAssertions": assertions,
                }
            )
            break
        disabled = client.tool(
            "tavo_plugin_set_enabled",
            {"pluginId": package["pluginId"], "enabled": False, "dryRun": False},
        )
        atomic_json(case_dir / "disable.json", disabled, exclusive=True)
        if not response_ok(disabled):
            assertions = staging_assertions(package, dry, actual, disabled, readback)
            atomic_json(case_dir / "staging-assertions.json", assertions, exclusive=True)
            outcomes.append(
                {
                    "case": case_key,
                    "status": "failed",
                    "reason": "could not leave fixture disabled",
                    "stagingAssertions": assertions,
                }
            )
            break
        readback = client.tool("tavo_plugin_get", {"pluginId": package["pluginId"]})
        atomic_json(case_dir / "readback.json", readback, exclusive=True)
        assertions = staging_assertions(package, dry, actual, disabled, readback)
        atomic_json(case_dir / "staging-assertions.json", assertions, exclusive=True)
        if not response_ok(readback):
            outcomes.append(
                {
                    "case": case_key,
                    "status": "failed",
                    "reason": "plugin readback failed",
                    "stagingAssertions": assertions,
                }
            )
            break
        outcomes.append(
            {
                "case": case_key,
                "status": "blocked",
                "reason": (
                    "evidence inspector installed disabled; use its explicit dump/clear actions during controlled runtime validation"
                    if case_key == INSPECTOR_CASE_KEY
                    else "fixture installed disabled; runtime assertions require controlled trigger evidence"
                ),
                "stagingAssertions": assertions,
            }
        )

    after = client.tool("tavo_current_chat_get")
    after_id = current_chat_id(after)
    if not response_ok(after) or after_id != before_id:
        raise RuntimeError("current chat changed during safe fixture staging")
    final = {
        "schemaVersion": 1,
        "runId": run_id,
        "executionMode": "staging-only",
        "liveAssertionsExecuted": 0,
        "stagingAssertionCount": sum(
            len(item.get("stagingAssertions", {})) for item in outcomes if isinstance(item, dict)
        ),
        "status": "staged" if all(item["status"] == "blocked" for item in outcomes) else "failed",
        "currentChatBefore": before_id,
        "currentChatAfter": after_id,
        "protectedChatUntouched": before_id not in protected_chat_ids and after_id not in protected_chat_ids,
        "messagesSent": 0,
        "outcomes": outcomes,
    }
    atomic_json(artifact / "live-summary.json", final, exclusive=True)
    return final


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--self-check", action="store_true")
    actions.add_argument("--print-plan", action="store_true")
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--evaluate-evidence", type=Path)
    actions.add_argument(
        "--execute",
        action="store_true",
        help="Stage fixtures disabled and emit staging assertions only; never executes F01-F11 runtime assertions.",
    )
    parser.add_argument("--run-id", default="T092-SELF-CHECK")
    parser.add_argument("--cases", help="Comma-separated case keys; dependencies are added in canonical order.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default=os.environ.get("TAVO_DEVICE", ""))
    parser.add_argument("--endpoint-file", type=Path, default=DEFAULT_ENDPOINT)
    parser.add_argument("--test-chat-id", type=int, default=0)
    parser.add_argument(
        "--protected-chat-id",
        dest="protected_chat_ids",
        type=int,
        action="append",
        default=[],
        help="Chat ID that live staging must never touch; repeat for multiple protected chats.",
    )
    parser.add_argument("--fixture-base-url", default="")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_id = normalized_run_id(args.run_id)
        cases = expand_cases(build_cases(), args.cases)
        if args.self_check:
            payload = self_check(run_id)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 1
        if args.print_plan:
            print(json.dumps(plan_record(run_id, cases), ensure_ascii=False, indent=2))
            return 0
        if args.evaluate_evidence:
            evidence = json.loads(args.evaluate_evidence.read_text(encoding="utf-8"))
            payload = evaluate_matrix(cases, evidence)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 1
        if not args.output:
            raise RuntimeError("--prepare and --execute require --output")
        if args.prepare:
            payload = prepare_bundle(args.output, run_id, cases)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        payload = execute_live(args, cases)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "staged" else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": redact(str(error))}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
