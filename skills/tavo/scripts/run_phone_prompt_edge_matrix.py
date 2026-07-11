#!/usr/bin/env python3
"""Plan and validate a prompt-edge Tavo matrix.

This runner is intentionally fail-closed and offline-friendly in this turn:

* it builds a real model prompt-edge plan with unique nonces, expected and
  forbidden markers, stable message-id placeholders, and dependency closure;
* it emits a verifiable manifest shape for future live execution;
* it preserves secret redaction and explicit ``--execute`` gating;
* it does not touch a phone unless a future live executor is wired in.

The case set is intentionally distinct from the existing 35-case cross-feature
matrix. This file focuses on prompt edges: secondary strategies, case
sensitivity, whole-word matching, multi-main-word OR behavior, constant-vs-
keyword precedence, preset ordering/role/depth, and regex placement/timing/
depth/substitution/capture-group behavior.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "/tmp/tavo_mcp_endpoint.json"
TARGET_MODEL_CALLS = 34
MIN_MODEL_CALLS = 24
MODEL_FAMILIES = (
    "worldbook-precedence",
    "worldbook-secondary",
    "keyword-shape",
    "preset-edges",
    "regex-edges",
)

sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_kpi_batch import TavoMcp, load_endpoint, ok_response, redact  # noqa: E402


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
    requires: tuple[str, ...] = ()
    input_mode: str = "standard"
    prelude: str = ""
    notes: str = ""

    @property
    def stable_message_ids(self) -> dict[str, str]:
        base = f"{safe_name(self.key)}-{self.ordinal:02d}"
        return {
            "user": f"pe-{base}-user",
            "assistant": f"pe-{base}-assistant",
        }

    @property
    def step_name(self) -> str:
        return f"{self.ordinal:02d}-{safe_name(self.key)}"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


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


def marker(run_id: str, key: str) -> str:
    run_part = re.sub(r"[^A-Za-z0-9]", "", run_id).upper()[-18:]
    key_part = re.sub(r"[^A-Za-z0-9]", "_", key).upper()[:28]
    digest = hashlib.sha256(f"{run_id}:{key}".encode("utf-8")).hexdigest()[:10].upper()
    return f"PE_{run_part}_{key_part}_{digest}"


def trigger(run_id: str, key: str) -> str:
    digest = hashlib.sha256(f"trigger:{run_id}:{key}".encode("utf-8")).hexdigest()[:12].upper()
    return f"edge-{safe_name(key)}-{digest}"


def nonce_for(run_id: str, ordinal: int, key: str) -> str:
    digest = hashlib.sha256(f"nonce:{run_id}:{ordinal}:{key}".encode("utf-8")).hexdigest()[:16].upper()
    return f"PE_NONCE_{ordinal:02d}_{digest}"


def nonce_prompt(nonce: str, request: str) -> str:
    return (
        f"The first visible line of your reply must be exactly {nonce}.\n"
        f"{request}\n"
        "Use only supplied context. Do not invent or normalize evidence codes."
    )


def evidence_request(subject: str) -> str:
    return (
        f"Find the exact prompt-edge evidence code supplied by {subject}. "
        "Write that exact code on the second line, then briefly identify its source."
    )


def absent_request(subject: str, sentinel: str) -> str:
    return (
        f"Check whether {subject} supplied a prompt-edge evidence code for this turn. "
        f"If it did not, write exactly {sentinel} on the second line. Do not copy codes from unrelated history."
    )


def case_markers(run_id: str) -> dict[str, str]:
    keys = (
        "precedence-baseline-constant",
        "precedence-baseline-keyword",
        "precedence-order-reversed-constant",
        "precedence-order-reversed-keyword",
        "precedence-keyword-control",
        "precedence-keyword-control-keyword",
        "precedence-keyword-control-absent",
        "secondary-none-hit",
        "secondary-none-miss",
        "secondary-andAny-hit",
        "secondary-andAny-miss",
        "secondary-andAll-hit",
        "secondary-andAll-miss",
        "secondary-notAny-hit",
        "secondary-notAny-miss",
        "secondary-notAll-hit",
        "secondary-notAll-miss",
        "case-sensitive-ascii-hit",
        "case-sensitive-ascii-miss",
        "whole-word-ascii-hit",
        "whole-word-ascii-miss",
        "whole-word-chinese-hit",
        "whole-word-chinese-miss",
        "multi-mainword-hit",
        "multi-mainword-miss",
        "preset-relative-forward-a",
        "preset-relative-forward-b",
        "preset-relative-forward-c",
        "preset-relative-reverse-a",
        "preset-relative-reverse-b",
        "preset-relative-reverse-c",
        "preset-absolute-system",
        "preset-absolute-user",
        "preset-absolute-assistant",
        "regex-capture-hit",
        "regex-capture-miss",
        "regex-markdown-hit",
        "regex-markdown-miss",
        "regex-substitution-raw-hit",
        "regex-substitution-raw-miss",
        "regex-placement-depth-hit",
        "regex-placement-depth-miss",
    )
    return {key: marker(run_id, key) for key in keys}


def append_case(
    cases: list[CaseSpec],
    run_id: str,
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
    requires: tuple[str, ...] = (),
    input_mode: str = "standard",
    prelude: str = "",
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
            requires=requires,
            input_mode=input_mode,
            prelude=prelude,
            notes=notes,
        )
    )


def build_cases(run_id: str, allow_deletes: bool) -> list[CaseSpec]:
    m = case_markers(run_id)
    cases: list[CaseSpec] = []

    baseline_requires: tuple[str, ...] = ()
    dependent_requires = ("worldbook-precedence-baseline",)

    append_case(
        cases,
        run_id,
        "worldbook-precedence-baseline",
        "worldbook-precedence",
        "precedence-baseline",
        (
            f"Two rival worldbook facts are available. Prefer the constant fact when both are present. "
            f"Constant gate: {trigger(run_id, 'precedence-baseline-constant')}. "
            f"Keyword gate: {trigger(run_id, 'precedence-baseline-keyword')}. "
            + evidence_request("the precedence baseline constant fact")
        ),
        (m["precedence-baseline-constant"],),
        forbidden=(m["precedence-baseline-keyword"],),
        lorebook_key="precedence-baseline",
        notes="Constant must win when the keyword rival is also visible.",
        requires=baseline_requires,
    )
    append_case(
        cases,
        run_id,
        "worldbook-precedence-order-reversed",
        "worldbook-precedence",
        "precedence-order-reversed",
        (
            f"The same constant fact should win even when the keyword competitor is ordered first. "
            f"Keyword gate: {trigger(run_id, 'precedence-order-reversed-keyword')}. "
            f"Constant gate: {trigger(run_id, 'precedence-order-reversed-constant')}. "
            + evidence_request("the reversed-order constant fact")
        ),
        (m["precedence-order-reversed-constant"],),
        forbidden=(m["precedence-order-reversed-keyword"],),
        lorebook_key="precedence-order-reversed",
        notes="Ordering changes must not demote constant precedence.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "worldbook-precedence-keyword-control",
        "worldbook-precedence",
        "precedence-keyword-control",
        (
            f"Only the keyword fact is visible here: {trigger(run_id, 'precedence-keyword-control-keyword')}. "
            + absent_request("the constant precedence fact", m["precedence-keyword-control-absent"])
        ),
        (m["precedence-keyword-control-keyword"],),
        forbidden=(m["precedence-keyword-control-absent"],),
        lorebook_key="precedence-keyword-control",
        notes="Control proving that the competitor keyword still works when constant is absent.",
        requires=dependent_requires,
    )

    secondary_specs = (
        (
            "secondary-none",
            "none",
            "Primary keyword + secondary clues should still fire when the secondary strategy is none.",
            f"Primary gate {trigger(run_id, 'secondary-none-primary')}; secondary hints {trigger(run_id, 'secondary-none-a')} and {trigger(run_id, 'secondary-none-b')}. "
            + evidence_request("the none-strategy secondary worldbook"),
            (m["secondary-none-hit"],),
            (m["secondary-none-miss"],),
            "only secondary hints and no primary gate",
        ),
        (
            "secondary-andAny",
            "andAny",
            "Primary keyword plus any single secondary clue should fire.",
            f"Primary gate {trigger(run_id, 'secondary-andAny-primary')}; one secondary hint {trigger(run_id, 'secondary-andAny-a')}. "
            + evidence_request("the andAny secondary worldbook"),
            (m["secondary-andAny-hit"],),
            (m["secondary-andAny-miss"],),
            "primary gate but no secondary hints",
        ),
        (
            "secondary-andAll",
            "andAll",
            "Primary keyword plus both secondary clues should fire.",
            f"Primary gate {trigger(run_id, 'secondary-andAll-primary')}; both secondary hints {trigger(run_id, 'secondary-andAll-a')} and {trigger(run_id, 'secondary-andAll-b')}. "
            + evidence_request("the andAll secondary worldbook"),
            (m["secondary-andAll-hit"],),
            (m["secondary-andAll-miss"],),
            "primary gate plus only one secondary hint",
        ),
        (
            "secondary-notAny",
            "notAny",
            "Primary keyword should fire only when no secondary clue is present.",
            f"Primary gate {trigger(run_id, 'secondary-notAny-primary')}. "
            + evidence_request("the notAny secondary worldbook"),
            (m["secondary-notAny-hit"],),
            (m["secondary-notAny-miss"],),
            "primary gate plus a secondary hint",
        ),
        (
            "secondary-notAll",
            "notAll",
            "Primary keyword should fire when the secondary set is not complete.",
            f"Primary gate {trigger(run_id, 'secondary-notAll-primary')}; one secondary hint {trigger(run_id, 'secondary-notAll-a')}. "
            + evidence_request("the notAll secondary worldbook"),
            (m["secondary-notAll-hit"],),
            (m["secondary-notAll-miss"],),
            "primary gate plus both secondary hints",
        ),
    )
    for key, strategy, description, positive_request, positive_expected, negative_expected, negative_subject in secondary_specs:
        append_case(
            cases,
            run_id,
            f"{key}-hit",
            "worldbook-secondary",
            key,
            positive_request,
            positive_expected,
            lorebook_key=key,
            notes=description,
            requires=dependent_requires,
        )
        append_case(
            cases,
            run_id,
            f"{key}-miss",
            "worldbook-secondary",
            key,
            absent_request(negative_subject, negative_expected[0]),
            negative_expected,
            forbidden=positive_expected,
            lorebook_key=key,
            notes=f"Negative control for secondary strategy {strategy}.",
            requires=dependent_requires,
        )

    append_case(
        cases,
        run_id,
        "keyword-case-sensitive-ascii-hit",
        "keyword-shape",
        "case-sensitive-ascii",
        f"Exact ASCII trigger required: {trigger(run_id, 'CaseSensitiveAscii')}. " + evidence_request("the case-sensitive ASCII worldbook"),
        (m["case-sensitive-ascii-hit"],),
        lorebook_key="case-sensitive-ascii",
        notes="Upper/lower case differences should matter when caseSensitive is true.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-case-sensitive-ascii-miss",
        "keyword-shape",
        "case-sensitive-ascii",
        absent_request(
            f"the same ASCII trigger in the wrong case {trigger(run_id, 'casesensitiveascii').upper()}",
            m["case-sensitive-ascii-miss"],
        ),
        (m["case-sensitive-ascii-miss"],),
        forbidden=(m["case-sensitive-ascii-hit"],),
        lorebook_key="case-sensitive-ascii",
        notes="Wrong-case ASCII should not trigger when caseSensitive is true.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-whole-word-ascii-hit",
        "keyword-shape",
        "whole-word-ascii",
        f"Standalone token required: {trigger(run_id, 'whole-word-ascii')} . " + evidence_request("the ASCII whole-word worldbook"),
        (m["whole-word-ascii-hit"],),
        lorebook_key="whole-word-ascii",
        notes="ASCII whole-word positive control.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-whole-word-ascii-miss",
        "keyword-shape",
        "whole-word-ascii",
        absent_request(
            f"the same token embedded in a longer token pre{trigger(run_id, 'whole-word-ascii')}post",
            m["whole-word-ascii-miss"],
        ),
        (m["whole-word-ascii-miss"],),
        forbidden=(m["whole-word-ascii-hit"],),
        lorebook_key="whole-word-ascii",
        notes="Embedded ASCII should not trigger when matchWholeWord is true.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-whole-word-chinese-hit",
        "keyword-shape",
        "whole-word-chinese",
        f"中文词边界应命中：{trigger(run_id, 'whole-word-chinese')}。 " + evidence_request("the Chinese whole-word worldbook"),
        (m["whole-word-chinese-hit"],),
        lorebook_key="whole-word-chinese",
        notes="Chinese token separated by punctuation should be accepted.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-whole-word-chinese-miss",
        "keyword-shape",
        "whole-word-chinese",
        absent_request(
            f"the same Chinese token embedded in a longer compound 前缀{trigger(run_id, 'whole-word-chinese')}后缀",
            m["whole-word-chinese-miss"],
        ),
        (m["whole-word-chinese-miss"],),
        forbidden=(m["whole-word-chinese-hit"],),
        lorebook_key="whole-word-chinese",
        notes="Chinese embedded text should not trigger when matchWholeWord is true.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-multi-mainword-hit",
        "keyword-shape",
        "multi-mainword",
        f"Any one main keyword should suffice: {trigger(run_id, 'multi-mainword-a')}. " + evidence_request("the multi-main-word worldbook"),
        (m["multi-mainword-hit"],),
        lorebook_key="multi-mainword",
        notes="Multiple primary keywords should behave as OR, not AND.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "keyword-multi-mainword-miss",
        "keyword-shape",
        "multi-mainword",
        absent_request(
            "the multi-main-word worldbook with neither primary keyword present",
            m["multi-mainword-miss"],
        ),
        (m["multi-mainword-miss"],),
        forbidden=(m["multi-mainword-hit"],),
        lorebook_key="multi-mainword",
        notes="A prompt missing both main keywords should remain cold.",
        requires=dependent_requires,
    )

    append_case(
        cases,
        run_id,
        "preset-relative-forward",
        "preset-edges",
        "preset-relative-forward",
        (
            "There are three relative custom entries. Report the markers in the same order as the entry list: "
            f"{m['preset-relative-forward-a']} then {m['preset-relative-forward-b']} then {m['preset-relative-forward-c']}. "
            + evidence_request("the forward relative preset ordering")
        ),
        (
            m["preset-relative-forward-a"],
            m["preset-relative-forward-b"],
            m["preset-relative-forward-c"],
        ),
        preset_key="preset-relative-forward",
        notes="Relative order should follow the entry array.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "preset-relative-reverse",
        "preset-edges",
        "preset-relative-reverse",
        (
            "The same three relative entries are reversed. Report the markers in reverse order: "
            f"{m['preset-relative-reverse-c']} then {m['preset-relative-reverse-b']} then {m['preset-relative-reverse-a']}. "
            + evidence_request("the reversed relative preset ordering")
        ),
        (
            m["preset-relative-reverse-c"],
            m["preset-relative-reverse-b"],
            m["preset-relative-reverse-a"],
        ),
        preset_key="preset-relative-reverse",
        notes="Reordered relative entries should surface in the reordered sequence.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "preset-absolute-system-depth",
        "preset-edges",
        "preset-absolute-system",
        (
            "An absolute custom entry is injected as system at depth 0. "
            + evidence_request("the system/depth-zero absolute preset entry")
        ),
        (m["preset-absolute-system"],),
        preset_key="preset-absolute-system",
        notes="System role plus absolute depth 0 should be observable in the prompt path.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "preset-absolute-user-depth",
        "preset-edges",
        "preset-absolute-user",
        (
            "An absolute custom entry is injected as user at depth 1. "
            + evidence_request("the user/depth-one absolute preset entry")
        ),
        (m["preset-absolute-user"],),
        preset_key="preset-absolute-user",
        notes="User role plus absolute depth 1 should be observable in the prompt path.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "preset-absolute-assistant-depth",
        "preset-edges",
        "preset-absolute-assistant",
        (
            "An absolute custom entry is injected as assistant at depth 2. "
            + evidence_request("the assistant/depth-two absolute preset entry")
        ),
        (m["preset-absolute-assistant"],),
        preset_key="preset-absolute-assistant",
        notes="Assistant role plus absolute depth 2 should be observable in the prompt path.",
        requires=dependent_requires,
    )

    append_case(
        cases,
        run_id,
        "regex-capture-code-fence-hit",
        "regex-edges",
        "regex-capture",
        (
            f"Capture group plus code fence should preserve the exact captured token {trigger(run_id, 'regex-capture-token')}. "
            + evidence_request("the capture-group code-fence regex")
        ),
        (m["regex-capture-hit"],),
        regex_key="regex-capture",
        input_mode="regex",
        notes="Capturing groups should survive into a fenced replacement.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-capture-code-fence-miss",
        "regex-edges",
        "regex-capture",
        absent_request(
            f"the capture-group code-fence regex when the fence is absent around {trigger(run_id, 'regex-capture-token')}",
            m["regex-capture-miss"],
        ),
        (m["regex-capture-miss"],),
        forbidden=(m["regex-capture-hit"],),
        regex_key="regex-capture",
        input_mode="regex",
        notes="Negative control for fenced capture replacement.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-markdown-display-hit",
        "regex-edges",
        "regex-markdown",
        (
            f"Markdown display replacement should keep emphasis and the token {trigger(run_id, 'regex-markdown-token')}. "
            + evidence_request("the markdown display regex")
        ),
        (m["regex-markdown-hit"],),
        regex_key="regex-markdown",
        input_mode="regex",
        notes="Display timing should preserve markdown-shaped replacement text.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-markdown-display-miss",
        "regex-edges",
        "regex-markdown",
        absent_request(
            f"the markdown display regex when the display-only marker is not in scope {trigger(run_id, 'regex-markdown-token')}",
            m["regex-markdown-miss"],
        ),
        (m["regex-markdown-miss"],),
        forbidden=(m["regex-markdown-hit"],),
        regex_key="regex-markdown",
        input_mode="regex",
        notes="Display-only negative control for markdown regex replacement.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-substitution-raw-hit",
        "regex-edges",
        "regex-substitution-raw",
        (
            f"Raw substitution should leave the captured macro-like text intact: {trigger(run_id, 'regex-substitution-raw-token')}. "
            + evidence_request("the raw substitution regex")
        ),
        (m["regex-substitution-raw-hit"],),
        regex_key="regex-substitution-raw",
        input_mode="regex",
        notes="Substitution mode raw should not collapse captured text into a different shape.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-substitution-raw-miss",
        "regex-edges",
        "regex-substitution-raw",
        absent_request(
            f"the raw substitution regex when escaped substitution is expected instead {trigger(run_id, 'regex-substitution-raw-token')}",
            m["regex-substitution-raw-miss"],
        ),
        (m["regex-substitution-raw-miss"],),
        forbidden=(m["regex-substitution-raw-hit"],),
        regex_key="regex-substitution-raw",
        input_mode="regex",
        notes="Negative control for raw substitution behavior.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-placement-depth-hit",
        "regex-edges",
        "regex-placement-depth",
        (
            f"Placement, timing, and depth all matter here. The right path is char/send at depth 1 with token {trigger(run_id, 'regex-placement-depth-token')}. "
            + evidence_request("the placement/timing/depth regex")
        ),
        (m["regex-placement-depth-hit"],),
        regex_key="regex-placement-depth",
        input_mode="regex",
        notes="Single edge case covering placement, timing, and depth together.",
        requires=dependent_requires,
    )
    append_case(
        cases,
        run_id,
        "regex-placement-depth-miss",
        "regex-edges",
        "regex-placement-depth",
        absent_request(
            f"the placement/timing/depth regex when user/display/outside-depth rules are used instead {trigger(run_id, 'regex-placement-depth-token')}",
            m["regex-placement-depth-miss"],
        ),
        (m["regex-placement-depth-miss"],),
        forbidden=(m["regex-placement-depth-hit"],),
        regex_key="regex-placement-depth",
        input_mode="regex",
        notes="Negative control for placement/timing/depth behavior.",
        requires=dependent_requires,
    )

    validate_case_plan(cases)
    return cases


def validate_case_plan(cases: list[CaseSpec]) -> None:
    errors: list[str] = []
    if len(cases) != TARGET_MODEL_CALLS:
        errors.append(f"planned {len(cases)} model calls, expected {TARGET_MODEL_CALLS}")
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
        errors.append("case nonces are not unique")

    expected_markers: list[str] = []
    forbidden_markers: list[str] = []
    known_keys = set(keys)
    for case in cases:
        if case.prompt.count(case.nonce) != 1:
            errors.append(f"{case.key} prompt does not contain its nonce exactly once")
        if not case.expected:
            errors.append(f"{case.key} has no semantic assertion")
        if case.family not in MODEL_FAMILIES:
            errors.append(f"{case.key} has unknown family {case.family}")
        if set(case.expected) & set(case.forbidden):
            errors.append(f"{case.key} has overlapping expected and forbidden markers")
        expected_markers.extend(case.expected)
        forbidden_markers.extend(case.forbidden)
        for required in case.requires:
            if required not in known_keys:
                errors.append(f"{case.key} requires missing case {required}")
    if len(expected_markers) != len(set(expected_markers)):
        errors.append("expected markers are not unique")
    if len(forbidden_markers) != len(set(forbidden_markers)):
        errors.append("forbidden markers are not unique")
    if not set(MODEL_FAMILIES).issubset({case.family for case in cases}):
        errors.append(f"missing model families: {sorted(set(MODEL_FAMILIES) - {case.family for case in cases})}")

    if errors:
        raise RuntimeError("Invalid prompt-edge model plan: " + "; ".join(errors))


def stable_message_ids(case: CaseSpec) -> dict[str, str]:
    return case.stable_message_ids


def case_record(case: CaseSpec) -> dict[str, Any]:
    record = asdict(case)
    record["messageIds"] = stable_message_ids(case)
    record["specHash"] = stable_hash(record)
    return record


def plan_record(run_id: str, allow_deletes: bool, cases: list[CaseSpec]) -> dict[str, Any]:
    records = [case_record(case) for case in cases]
    plan = {
        "schemaVersion": "1.0.0",
        "case": "tavo-prompt-edge-matrix",
        "runId": run_id,
        "plannedModelCalls": len(cases),
        "minimumRequiredModelCalls": MIN_MODEL_CALLS,
        "families": list(MODEL_FAMILIES),
        "safety": {
            "executeRequiresFlag": True,
            "phoneObjectsRetainedByDefault": True,
            "phoneFilesDeleted": False,
            "runnerOwnedDeletesEnabled": allow_deletes,
            "actualDeleteScope": "None in this offline build. Live executor is intentionally not wired here.",
            "existingUserPayloadsEdited": False,
            "temporaryRuntimeMutations": ["current chat", "active preset", "input text", "plugin enabled states"],
            "restore": [
                "current chat and original message hash",
                "active preset and original preset payload hashes",
                "input text when readable",
                "existing plugin enabled states, payload hashes, and runtime contribution hash",
            ],
            "secretRedaction": True,
        },
        "countingContract": (
            "A model call counts only when its exact nonce-bearing prompt has one new persistent user id, one new "
            "persistent assistant id, successful pre/post readbacks, exact nonce prefix, all expected assertions, and "
            "no forbidden markers. Failures and ambiguous sends count as zero."
        ),
        "messageIdTemplate": "pe-<safe_case_key>-<ordinal>-<role>",
        "cases": records,
    }
    plan["planHash"] = stable_hash(plan)
    return plan


def expand_case_dependencies(cases: list[CaseSpec], raw_keys: str) -> tuple[list[CaseSpec], list[str]]:
    if not raw_keys.strip():
        return cases, [case.key for case in cases]
    requested = [value.strip() for value in raw_keys.split(",") if value.strip()]
    if not requested:
        raise RuntimeError("--case-keys did not contain any case key")
    if len(requested) != len(set(requested)):
        raise RuntimeError("--case-keys contains duplicates")
    lookup = {case.key: case for case in cases}
    unknown = sorted(set(requested) - set(lookup))
    if unknown:
        raise RuntimeError(f"Unknown --case-keys: {unknown}")
    wanted: set[str] = set()
    stack = list(requested)
    while stack:
        key = stack.pop()
        if key in wanted:
            continue
        wanted.add(key)
        stack.extend(lookup[key].requires)
    selected = [case for case in cases if case.key in wanted]
    return selected, [case.key for case in selected]


def redact_manifest_payload(value: Any) -> Any:
    return redact(value)


def execute_live(args: argparse.Namespace) -> int:
    raise RuntimeError("Prompt-edge live execution is not wired in this offline-only turn.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan a prompt-edge Tavo model matrix.")
    parser.add_argument("--endpoint-json", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--case-keys", default="")
    parser.add_argument("--allow-runner-owned-deletes", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Explicitly opt into live execution.")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--print-plan", action="store_true")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    run_id = args.run_id or f"prompt-edge-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cases = build_cases(run_id, bool(args.allow_runner_owned_deletes))
    selected_cases, selected_keys = expand_case_dependencies(cases, args.case_keys)
    plan = plan_record(run_id, bool(args.allow_runner_owned_deletes), selected_cases)
    plan["selectedCaseKeys"] = selected_keys
    plan["expandedFromSubset"] = bool(args.case_keys.strip())
    plan["expandedCaseCount"] = len(selected_cases)
    plan["selectedPlanHash"] = stable_hash({"runId": run_id, "keys": selected_keys, "planHash": plan["planHash"]})

    if args.self_check:
        print(
            json.dumps(
                {
                    "ok": True,
                    "runId": run_id,
                    "caseCount": len(selected_cases),
                    "planHash": plan["planHash"],
                    "selectedCaseKeys": selected_keys,
                    "secretRedaction": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.print_plan:
        print(json.dumps(redact_manifest_payload(plan), ensure_ascii=False, indent=2))
        return 0

    if not args.execute:
        print("Refusing to run live prompt-edge execution without --execute.", file=sys.stderr)
        return 2

    if not args.url and not load_endpoint(args.endpoint_json).get("url"):
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2

    if args.artifact_dir:
        artifact_dir = Path(args.artifact_dir).expanduser()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        durable_json(artifact_dir / "run-manifest.json", plan)

    return execute_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
