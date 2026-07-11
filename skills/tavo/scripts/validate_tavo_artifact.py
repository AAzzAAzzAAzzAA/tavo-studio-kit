#!/usr/bin/env python3
"""Validate local Tavo skill artifacts with deterministic stdlib checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SECRET_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]{4,}|sk-[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{20,}|api[_-]?key['\"]?\s*[:=]\s*['\"][^'\"]{8,})",
    re.IGNORECASE,
)

REGISTRY_SCHEMA_VERSIONS = {"1.0.0"}
REGISTRY_VERDICTS = {
    "verified",
    "mixed",
    "official-only",
    "runtime-only",
    "probable",
    "workaround",
    "blocked",
    "deprecated",
}
EVIDENCE_TIERS = {
    "official-current",
    "mcp-runtime",
    "schema-seen",
    "dry-run-pass",
    "roundtrip-pass",
    "semantic-pass",
    "semantic-pass-observation",
    "ui-pass",
    "live-verified",
    "live-verified-regression",
    "semantic-mixed",
    "historical-derived",
    "deprecated",
}
LIVE_EVIDENCE_TIERS = {
    "dry-run-pass",
    "roundtrip-pass",
    "semantic-pass",
    "semantic-pass-observation",
    "ui-pass",
    "live-verified",
    "live-verified-regression",
    "semantic-mixed",
}
MANIFEST_STATUSES = {
    "planned",
    "prepared",
    "running",
    "passed",
    "failed",
    "blocked",
    "failed_runner_or_infrastructure",
    "failed_product_behavior",
}
CLAIM_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PACKAGE_URI_OR_DRIVE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_card(data: dict[str, Any], errors: list[str]) -> None:
    require(data.get("spec") == "chara_card_v2", "card spec must be chara_card_v2", errors)
    require(str(data.get("spec_version", "")).startswith("2."), "card spec_version must start with 2.", errors)
    card = data.get("data")
    require(isinstance(card, dict), "card data must be an object", errors)
    if not isinstance(card, dict):
        return
    for key in ["name", "description", "first_mes"]:
        require(isinstance(card.get(key), str) and bool(card.get(key).strip()), f"card data.{key} must be a non-empty string", errors)
    if "character_book" in card:
        validate_character_book(card["character_book"], errors)


def validate_character_book(data: Any, errors: list[str]) -> None:
    require(isinstance(data, dict), "character_book must be an object", errors)
    if not isinstance(data, dict):
        return
    entries = data.get("entries")
    require(isinstance(entries, list), "character_book.entries must be an array", errors)
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            require(isinstance(entry, dict), f"character_book.entries[{index}] must be an object", errors)
            if isinstance(entry, dict):
                require(isinstance(entry.get("content"), str) and bool(entry["content"].strip()), f"character_book.entries[{index}].content must be non-empty", errors)


def validate_worldbook(data: dict[str, Any], errors: list[str]) -> None:
    require(isinstance(data.get("name"), str) and bool(data["name"].strip()), "worldbook name must be non-empty", errors)
    entries = data.get("entries")
    require(isinstance(entries, (list, dict)), "worldbook entries must be an array or object", errors)
    iterable = entries if isinstance(entries, list) else list(entries.values()) if isinstance(entries, dict) else []
    require(bool(iterable), "worldbook must contain at least one entry", errors)
    for index, entry in enumerate(iterable):
        require(isinstance(entry, dict), f"worldbook entry {index} must be an object", errors)
        if isinstance(entry, dict):
            require(isinstance(entry.get("content"), str) and bool(entry["content"].strip()), f"worldbook entry {index} content must be non-empty", errors)


def validate_regex_fixture(data: dict[str, Any], errors: list[str]) -> None:
    require(isinstance(data.get("rules"), list) and bool(data["rules"]), "regex fixture rules must be a non-empty array", errors)
    require(isinstance(data.get("cases"), list) and bool(data["cases"]), "regex fixture cases must be a non-empty array", errors)
    for rule in data.get("rules", []):
        if not isinstance(rule, dict):
            errors.append("regex rule must be an object")
            continue
        require(isinstance(rule.get("id"), str) and bool(rule["id"]), "regex rule id is required", errors)
        require(isinstance(rule.get("pattern"), str), f"regex rule {rule.get('id', '<unknown>')} pattern must be a string", errors)
        try:
            re.compile(rule.get("pattern", ""))
        except re.error as exc:
            errors.append(f"regex rule {rule.get('id', '<unknown>')} does not compile in Python fixture runner: {exc}")


def is_safe_package_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value or value.startswith("/") or PACKAGE_URI_OR_DRIVE_RE.match(value):
        return False
    return all(segment not in {"", ".", ".."} for segment in value.split("/"))


def resolve_tpg_entry(data: dict[str, Any]) -> tuple[str | None, Any]:
    """Resolve the 0.92 entry declaration, with the legacy alias as fallback."""

    if "entry" in data:
        return "entry", data.get("entry")
    scripts = data.get("scripts")
    if isinstance(scripts, dict) and "actions" in scripts:
        return "scripts.actions", scripts.get("actions")
    return None, None


def validate_tpg_manifest(data: dict[str, Any], errors: list[str]) -> None:
    plugin_id = data.get("id")
    require(isinstance(plugin_id, str) and bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", plugin_id)), "plugin id must be lowercase dotted/kebab identifier", errors)
    for key in ["name", "version"]:
        require(isinstance(data.get(key), str) and bool(data[key].strip()), f"plugin {key} must be non-empty", errors)

    if "entry" in data:
        require(is_safe_package_path(data.get("entry")), "plugin entry must be a safe package-relative path", errors)
    scripts = data.get("scripts")
    if scripts is not None:
        require(isinstance(scripts, dict), "plugin scripts must be an object", errors)
        actions = scripts.get("actions") if isinstance(scripts, dict) else None
        if actions is not None:
            require(is_safe_package_path(actions), "plugin scripts.actions must be a safe package-relative path", errors)

    if "cover" in data:
        require(is_safe_package_path(data.get("cover")), "plugin cover must be a safe package-relative path", errors)

    contributes_value = data.get("contributes", {})
    require(isinstance(contributes_value, dict), "plugin contributes must be an object", errors)
    contributes = contributes_value if isinstance(contributes_value, dict) else {}
    input_value = contributes.get("inputActions", [])
    sidebar_value = contributes.get("sidebar", [])
    fragments_value = contributes.get("htmlFragments", [])
    require(isinstance(input_value, list), "plugin contributes.inputActions must be an array", errors)
    require(isinstance(sidebar_value, list), "plugin contributes.sidebar must be an array", errors)
    require(isinstance(fragments_value, list), "plugin contributes.htmlFragments must be an array", errors)
    input_actions = input_value if isinstance(input_value, list) else []
    sidebar = sidebar_value if isinstance(sidebar_value, list) else []
    fragments = fragments_value if isinstance(fragments_value, list) else []

    source, _ = resolve_tpg_entry(data)
    if input_actions or sidebar:
        require(
            source is not None,
            "plugin entry is required for inputActions/sidebar (legacy scripts.actions is accepted)",
            errors,
        )

    for index, action in enumerate(input_actions):
        require(isinstance(action, dict), f"plugin inputActions[{index}] must be an object", errors)
        if isinstance(action, dict) and "icon" in action:
            require(
                is_safe_package_path(action.get("icon")),
                f"plugin inputActions[{index}].icon must be a safe package-relative path",
                errors,
            )
    for index, fragment in enumerate(fragments):
        require(isinstance(fragment, dict), f"plugin htmlFragments[{index}] must be an object", errors)
        if isinstance(fragment, dict):
            require(
                is_safe_package_path(fragment.get("src")),
                f"plugin htmlFragments[{index}].src must be a safe package-relative path",
                errors,
            )


def validate_registry(data: dict[str, Any], errors: list[str]) -> None:
    require(data.get("schemaVersion") in REGISTRY_SCHEMA_VERSIONS, "registry schemaVersion must be 1.0.0", errors)
    require(isinstance(data.get("sourcePolicy"), str) and bool(data["sourcePolicy"].strip()), "registry sourcePolicy is required", errors)
    claims = data.get("claims")
    require(isinstance(claims, list) and bool(claims), "registry claims must be a non-empty array", errors)
    required = [
        "claim_id",
        "topic",
        "verdict",
        "evidence_tier",
        "official_source",
        "mcp_source",
        "live_artifact",
        "app_version",
        "last_verified",
        "retention",
        "staleness_policy",
        "notes",
    ]
    seen_ids: set[str] = set()
    for index, claim in enumerate(claims or []):
        require(isinstance(claim, dict), f"registry claim {index} must be an object", errors)
        if isinstance(claim, dict):
            for key in required:
                require(isinstance(claim.get(key), str), f"registry claim {index} {key} must be a string", errors)
            claim_id = claim.get("claim_id", "")
            require(bool(CLAIM_ID_RE.fullmatch(claim_id)), f"registry claim {index} has invalid claim_id", errors)
            require(claim_id not in seen_ids, f"registry claim id is duplicated: {claim_id}", errors)
            seen_ids.add(claim_id)
            require(bool(str(claim.get("topic", "")).strip()), f"registry claim {index} topic is required", errors)
            require(claim.get("verdict") in REGISTRY_VERDICTS, f"registry claim {index} has unknown verdict {claim.get('verdict')!r}", errors)
            tier = claim.get("evidence_tier")
            require(tier in EVIDENCE_TIERS, f"registry claim {index} has unknown evidence_tier {tier!r}", errors)
            require(bool(str(claim.get("retention", "")).strip()), f"registry claim {index} retention is required", errors)
            require(bool(str(claim.get("staleness_policy", "")).strip()), f"registry claim {index} staleness_policy is required", errors)
            require(bool(str(claim.get("notes", "")).strip()), f"registry claim {index} notes are required", errors)
            sources = [claim.get("official_source", ""), claim.get("mcp_source", ""), claim.get("live_artifact", "")]
            require(any(isinstance(value, str) and value.strip() for value in sources), f"registry claim {index} has no evidence source", errors)
            if tier in LIVE_EVIDENCE_TIERS:
                require(bool(str(claim.get("app_version", "")).strip()), f"registry claim {index} live evidence requires app_version", errors)
                last_verified = str(claim.get("last_verified", ""))
                require(bool(ISO_DATE_RE.fullmatch(last_verified)), f"registry claim {index} live evidence requires ISO last_verified", errors)


def validate_validation_manifest(data: dict[str, Any], errors: list[str]) -> None:
    for key in ("case", "status", "startedAt"):
        require(isinstance(data.get(key), str) and bool(data[key].strip()), f"validation manifest {key} is required", errors)
    status = data.get("status")
    require(status in MANIFEST_STATUSES, f"validation manifest has unknown status {status!r}", errors)
    if "evidenceLevel" in data:
        require(data.get("evidenceLevel") in EVIDENCE_TIERS | {"claimed", "needs-live-verify"}, "validation manifest has unknown evidenceLevel", errors)
    else:
        require(isinstance(data.get("countsTowardKpi"), bool), "legacy validation manifest without evidenceLevel must include countsTowardKpi", errors)
    artifacts = data.get("artifacts")
    require(isinstance(artifacts, list) and bool(artifacts), "validation manifest artifacts must be a non-empty array", errors)
    if isinstance(artifacts, list):
        require(all(isinstance(item, str) and item.strip() for item in artifacts), "validation manifest artifacts must contain non-empty strings", errors)
    if status == "passed":
        require(isinstance(data.get("finishedAt"), str) and bool(data["finishedAt"].strip()), "passed validation manifest requires finishedAt", errors)
    if data.get("countsTowardKpi") is True:
        require(status == "passed", "countsTowardKpi=true requires status=passed", errors)
        require(isinstance(data.get("progress"), dict), "countsTowardKpi=true requires progress evidence", errors)


def validate_mcp_surface(data: dict[str, Any], errors: list[str]) -> None:
    for key in ["dumped_at", "endpoint", "calls"]:
        require(key in data, f"mcp surface missing {key}", errors)
    endpoint = data.get("endpoint", {})
    if isinstance(endpoint, dict):
        require(endpoint.get("auth") in {"", "<redacted>"}, "mcp endpoint auth must be empty or <redacted>", errors)


def scan_secret_text(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if SECRET_RE.search(text):
        errors.append(f"possible secret found in {path}")


def infer_kind(path: Path, data: Any) -> str:
    name = path.name.lower()
    if name.endswith("registry.json"):
        return "registry"
    if name == "mcp_surface.json":
        return "mcp-surface"
    if name == "run-manifest.json":
        return "validation-manifest"
    if "regex" in name:
        return "regex-fixture"
    if "worldbook" in name or "lorebook" in name:
        return "worldbook"
    if name in {"tavo-plugin.json", "plugin.json", "manifest.json"}:
        return "tpg-manifest"
    if isinstance(data, dict) and data.get("spec") == "chara_card_v2":
        return "card"
    return "json"


def validate(path: Path, kind: str | None) -> list[str]:
    errors: list[str] = []
    scan_secret_text(path, errors)
    data = load_json(path)
    selected = kind or infer_kind(path, data)
    require(isinstance(data, dict), f"{selected} must be a JSON object", errors)
    if not isinstance(data, dict):
        return errors
    if selected == "card":
        validate_card(data, errors)
    elif selected == "worldbook":
        validate_worldbook(data, errors)
    elif selected == "regex-fixture":
        validate_regex_fixture(data, errors)
    elif selected == "tpg-manifest":
        require(path.name == "manifest.json", "Tavo plugin manifest filename must be manifest.json", errors)
        validate_tpg_manifest(data, errors)
    elif selected == "registry":
        validate_registry(data, errors)
    elif selected == "mcp-surface":
        validate_mcp_surface(data, errors)
    elif selected == "validation-manifest":
        validate_validation_manifest(data, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local Tavo artifacts.")
    parser.add_argument("paths", nargs="+")
    parser.add_argument(
        "--kind",
        choices=["card", "worldbook", "regex-fixture", "tpg-manifest", "registry", "mcp-surface", "validation-manifest", "json"],
    )
    args = parser.parse_args()

    failures = 0
    for raw in args.paths:
        path = Path(raw).expanduser()
        try:
            errors = validate(path, args.kind)
        except Exception as exc:  # noqa: BLE001 - validator should report all bad inputs as failures
            errors = [str(exc)]
        if errors:
            failures += 1
            print(f"FAIL {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
