#!/usr/bin/env python3
"""Full local audit for the Tavo encyclopedia skill."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from validate_tavo_artifact import validate as validate_artifact
from validate_tpg_package import validate_package


FORBIDDEN_TEXT = re.compile(r"(TO" + r"DO|place" + r"holder|\[TO" + r"DO)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]{4,}|sk-[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{20,}|api[_-]?key['\"]?\s*[:=]\s*['\"][^'\"]{8,})",
    re.IGNORECASE,
)
TEXT_SCAN_SUFFIXES = {
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
KNOWN_TEST_SECRET_LITERALS = (
    "sk-1234567890abcdefghijklmnop",
    "Bearer secret-token",
    "Bearer secret-value",
    "Bearer hidden",
    "Bearer secret",
    "Bearer 123456",
    "Bearer token",
    "Bearer tokens",
    "Bearer requires",
    '"api_key": "body-secret"',
    'apiKey": "<redacted>"',
    'apiKey": "sk-live-123"',
)
SENSITIVE_JSON_KEYS = {
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "token",
    "access_token",
}
ALLOWED_REDACTED_VALUES = {"<redacted>", "<redacted-secret>"}

REQUIRED_REFERENCES = [
    "references/00-source-of-truth.md",
    "references/01-official-url-map.md",
    "references/02-capabilities-overview.md",
    "references/03-characters-cards-personas.md",
    "references/04-chat-workflows.md",
    "references/05-prompt-authoring.md",
    "references/06-macros-ejs.md",
    "references/07-rendering-tavojs.md",
    "references/08-plugins-tpg.md",
    "references/09-media-voice-image.md",
    "references/10-app-settings-data.md",
    "references/11-mcp-runtime.md",
    "references/12-validation-matrix.md",
    "references/13-creation-craft-workflows.md",
    "references/14-evidence-registry.md",
    "references/15-phone-validation-runbook.md",
    "references/16-capability-answer-playbook.md",
    "references/17-authoring-blueprints.md",
    "references/18-ar-tavojs-plugin-patterns.md",
    "references/19-debugging-pitfalls.md",
    "references/20-forward-testing.md",
    "references/21-worldbook-entry-semantics.md",
    "references/22-preset-prompt-injection.md",
    "references/23-regex-execution-pipeline.md",
    "references/24-character-opening-and-examples.md",
    "references/25-ejs-tavojs-plugin-boundaries.md",
    "references/historical/deprecated-claims.md",
]

REQUIRED_SCRIPTS = [
    "scripts/fetch_official_docs.py",
    "scripts/normalize_official_docs.py",
    "scripts/dump_mcp_surface.py",
    "scripts/test_dump_mcp_surface.py",
    "scripts/normalize_mcp_surface.py",
    "scripts/tavo_mcp_client.py",
    "scripts/tavo_phone_capture.py",
    "scripts/tavo_phone_validate.py",
    "scripts/run_phone_kpi_batch.py",
    "scripts/run_phone_coverage_kpi.py",
    "scripts/run_phone_ejs_runtime_diagnostic.py",
    "scripts/run_phone_import_kpi.py",
    "scripts/run_phone_preset_hidden_seed_diagnostic.py",
    "scripts/run_phone_semantic_kpi.py",
    "scripts/run_phone_semantic_ui_preflight.py",
    "scripts/run_phone_cross_feature_matrix.py",
    "scripts/aggregate_cross_feature_matrix.py",
    "scripts/run_phone_prompt_edge_matrix.py",
    "scripts/test_run_phone_prompt_edge_matrix.py",
    "scripts/run_phone_asset_roundtrip_matrix.py",
    "scripts/test_run_phone_asset_roundtrip_matrix.py",
    "scripts/run_phone_media_provider_matrix.py",
    "scripts/test_run_phone_media_provider_matrix.py",
    "scripts/run_phone_plugin_092_matrix.py",
    "scripts/test_run_phone_plugin_092_matrix.py",
    "scripts/tavo_generation_hook_fixture.py",
    "scripts/test_tavo_generation_hook_fixture.py",
    "scripts/tavo_request_capture_gateway.py",
    "scripts/test_tavo_request_capture_gateway.py",
    "scripts/test_run_phone_semantic_kpi_faults.py",
    "scripts/test_run_phone_cross_feature_matrix.py",
    "scripts/tavo_ui_tree.py",
    "scripts/audit_skill_skeleton.py",
    "scripts/audit_tavo_skill.py",
    "scripts/validate_tavo_artifact.py",
    "scripts/generate_from_template.py",
    "scripts/run_regex_fixtures.py",
    "scripts/validate_tpg_package.py",
    "scripts/test_validate_tpg_package.py",
    "scripts/scan_deprecated_tavojs.py",
    "scripts/compare_roundtrip_export.py",
    "scripts/record_validation_artifact.py",
    "scripts/png-card-lib.mjs",
    "scripts/embed_st_card_png.mjs",
    "scripts/extract_st_card_png.mjs",
    "scripts/worldbook_to_character_book.mjs",
]

REQUIRED_ASSETS = [
    "assets/official-docs/official_manifest.json",
    "assets/evidence/registry.json",
    "assets/fixtures/minimal-card.json",
    "assets/fixtures/worldbook-basic.json",
    "assets/fixtures/regex-cleanup-fixture.json",
    "assets/fixtures/plugin-minimal/manifest.json",
    "assets/fixtures/plugin-minimal/entry.js",
    "assets/fixtures/plugin-legacy/manifest.json",
    "assets/fixtures/plugin-legacy/legacy-actions.js",
    "assets/fixtures/plugin-dual/manifest.json",
    "assets/fixtures/plugin-dual/entry.js",
    "assets/fixtures/plugin-hook-only/manifest.json",
    "assets/fixtures/plugin-hook-only/entry.js",
    "assets/fixtures/plugin-dangerous-path/manifest.json",
    "assets/fixtures/plugin-nested/wrapper/manifest.json",
    "assets/fixtures/plugin-nested/wrapper/entry.js",
    "assets/fixtures/plugin-ambiguous/one/manifest.json",
    "assets/fixtures/plugin-ambiguous/two/manifest.json",
    "assets/fixtures/plugin-missing-entry/manifest.json",
    "assets/schemas/st-card-v2.schema.json",
    "assets/schemas/worldbook.schema.json",
    "assets/schemas/regex-fixture.schema.json",
    "assets/schemas/tpg-manifest.schema.json",
    "assets/schemas/mcp-surface.schema.json",
    "assets/schemas/mcp-surface-0.91.0-20260710.json",
    "assets/schemas/mcp-surface-index-0.91.0-20260710.json",
    "assets/schemas/mcp-surface-0.92.0-20260716.json",
    "assets/schemas/mcp-surface-index-0.92.0-20260716.json",
    "assets/schemas/validation-artifact.schema.json",
    "assets/schemas/evidence-registry.schema.json",
    "assets/evidence/0.92.0/20260716-gate.json",
    "assets/evidence/0.92.0/20260717-live-matrix.json",
    "assets/templates/character-card-minimal.json",
    "assets/templates/worldbook-minimal.json",
    "assets/templates/regex-fixture.json",
    "assets/templates/advanced-rendering-marker.html",
    "assets/templates/plugin-minimal/manifest.json",
    "assets/templates/plugin-minimal/entry.js",
    "assets/templates/plugin-minimal/ui/panel.html",
    "assets/templates/semantic-validation/plugin/manifest.json",
    "assets/templates/semantic-validation/plugin/entry.js",
    "assets/templates/semantic-validation/plugin/ui/panel.html",
]

VALID_TPG_PACKAGE_ASSETS = [
    "assets/templates/plugin-minimal",
    "assets/fixtures/plugin-minimal",
    "assets/fixtures/plugin-legacy",
    "assets/fixtures/plugin-dual",
    "assets/fixtures/plugin-hook-only",
    "assets/fixtures/plugin-nested",
]

INVALID_TPG_PACKAGE_ASSETS = [
    "assets/fixtures/plugin-dangerous-path",
    "assets/fixtures/plugin-ambiguous",
    "assets/fixtures/plugin-missing-entry",
]

TERMINAL_EVIDENCE_MANIFESTS = [
    "artifacts/tavo-validation/20260710-020132-strict-import-kpi/run-manifest.json",
    "artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/run-manifest.json",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def local_source_path(value: str) -> str:
    """Remove optional line/fragment selectors from a local evidence source."""

    without_fragment = value.partition("#")[0]
    return re.sub(r":\d+(?:-\d+)?$", "", without_fragment)


def scan_json_secret_values(value: object, rel: str, errors: list[str], path: str = "") -> None:
    """Reject non-empty credential values stored under explicit JSON secret keys."""

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = re.sub(r"[- ]", "_", str(key).lower())
            if normalized in SENSITIVE_JSON_KEYS and isinstance(child, str) and child and child not in ALLOWED_REDACTED_VALUES:
                errors.append(f"possible structured secret found in {rel}:{child_path}")
            scan_json_secret_values(child, rel, errors, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_json_secret_values(child, rel, errors, f"{path}[{index}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the Tavo skill.")
    parser.add_argument("skill_dir", nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = Path(args.skill_dir).expanduser().resolve()
    errors: list[str] = []

    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        errors.append("SKILL.md missing")
        print("\n".join(f"ERROR: {e}" for e in errors), file=sys.stderr)
        return 1
    skill_text = read(skill_md)
    url_map_text = read(root / "references/01-official-url-map.md") if (root / "references/01-official-url-map.md").exists() else ""
    for rel in REQUIRED_REFERENCES:
        path = root / rel
        if not path.exists():
            errors.append(f"missing required reference: {rel}")

    reference_paths = sorted((root / "references").rglob("*.md")) if (root / "references").is_dir() else []
    all_reference_text = skill_text
    for path in reference_paths:
        rel = path.relative_to(root).as_posix()
        text = read(path)
        all_reference_text += "\n" + text
        if rel not in skill_text and rel not in url_map_text:
            errors.append(f"reference not indexed in SKILL.md or official URL map: {rel}")
        if FORBIDDEN_TEXT.search(text):
            errors.append(f"initialization remnant found in {rel}")

    for rel in REQUIRED_SCRIPTS:
        path = root / rel
        if not path.exists():
            errors.append(f"missing required script: {rel}")

    script_paths = sorted(
        path
        for path in (root / "scripts").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    ) if (root / "scripts").is_dir() else []
    for path in script_paths:
        rel = path.relative_to(root).as_posix()
        if rel not in all_reference_text:
            errors.append(f"script not documented in SKILL.md/references: {rel}")
        if path.suffix == ".py":
            try:
                ast.parse(read(path), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"python syntax check failed for {rel}: {exc}")

    for rel in REQUIRED_ASSETS:
        if not (root / rel).exists():
            errors.append(f"missing required asset: {rel}")

    for rel in VALID_TPG_PACKAGE_ASSETS:
        path = root / rel
        if path.exists():
            result = validate_package(path)
            if result.errors:
                errors.append(f"valid TPG fixture failed {rel}: {'; '.join(result.errors)}")

    for rel in INVALID_TPG_PACKAGE_ASSETS:
        path = root / rel
        if path.exists() and not validate_package(path).errors:
            errors.append(f"negative TPG fixture unexpectedly passed: {rel}")

    for gitkeep in root.glob("assets/*/.gitkeep"):
        parent_files = [p for p in gitkeep.parent.iterdir() if p.name != ".gitkeep"]
        if not parent_files:
            errors.append(f"asset directory is still placeholder-only: {gitkeep.parent.relative_to(root)}")

    for path in (
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file()
        and candidate.suffix.lower() in TEXT_SCAN_SUFFIXES
        and "__pycache__" not in candidate.parts
    ):
        rel = path.relative_to(root).as_posix()
        text = read(path)
        scanned_text = text
        for literal in KNOWN_TEST_SECRET_LITERALS:
            scanned_text = re.sub(re.escape(literal), "<known-test-secret>", scanned_text, flags=re.IGNORECASE)
        if SECRET_RE.search(scanned_text):
            errors.append(f"possible secret found in {rel}")
        if path.suffix.lower() == ".json":
            try:
                scan_json_secret_values(json.loads(text), rel, errors)
            except json.JSONDecodeError:
                pass

    workspace_root = root.parents[2] if len(root.parents) > 2 else None
    registry_path = root / "assets/evidence/registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(read(registry_path))
            if len(registry.get("claims", [])) < 5:
                errors.append("evidence registry must contain at least five seed claims")
            errors.extend(f"registry: {error}" for error in validate_artifact(registry_path, "registry"))
            for index, claim in enumerate(registry.get("claims", [])):
                if not isinstance(claim, dict):
                    continue
                for field in ("official_source", "mcp_source", "live_artifact"):
                    value = claim.get(field, "")
                    if not isinstance(value, str) or not value or URL_RE.match(value):
                        continue
                    path_value = local_source_path(value)
                    # Raw phone captures are intentionally private and excluded from
                    # the public repository. Their redacted summaries remain under
                    # assets/evidence/, so do not require private artifact paths here.
                    if path_value.startswith("artifacts/"):
                        continue
                    candidate = root / path_value if path_value.startswith(("assets/", "references/", "scripts/")) else None
                    if candidate is None and workspace_root is not None:
                        candidate = workspace_root / path_value
                    if candidate is not None and not candidate.exists():
                        errors.append(f"registry claim {index} {field} does not exist: {value}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"registry JSON parse failed: {exc}")

    live_matrix_path = root / "assets/evidence/0.92.0/20260717-live-matrix.json"
    if live_matrix_path.exists():
        try:
            live_matrix = json.loads(read(live_matrix_path))
            if live_matrix.get("artifactType") != "tavo-live-atomic-evidence-summary":
                errors.append("0.92 live matrix has an unexpected artifactType")
            if live_matrix.get("appVersion") != "0.92.0":
                errors.append("0.92 live matrix has an unexpected appVersion")
            source_run = live_matrix.get("sourceRun")
            if not isinstance(source_run, str) or not source_run:
                errors.append("0.92 live matrix sourceRun is missing")
            for section_name in ("coreMatrix", "packageAndBackup", "supplemental"):
                section = live_matrix.get(section_name)
                if not isinstance(section, dict):
                    errors.append(f"0.92 live matrix section is missing: {section_name}")
                    continue
                sources = section.get("sourceArtifacts")
                if not isinstance(sources, list) or not sources:
                    errors.append(f"0.92 live matrix {section_name} sourceArtifacts must be a non-empty list")
                    continue
                for source in sources:
                    if not isinstance(source, str) or not source:
                        errors.append(f"0.92 live matrix {section_name} has an invalid source artifact")
                        continue
                    if re.search(r"(?:audit[-_.]?draft|provisional|draft)", Path(source).name, re.IGNORECASE):
                        errors.append(f"0.92 live matrix {section_name} points to a draft artifact: {source}")
            if workspace_root is not None:
                evaluation_path = workspace_root / "artifacts/tavo-validation/20260716-204923-tavo-092-live/matrix-evaluation.json"
                matrix_path = workspace_root / "artifacts/tavo-validation/20260716-204923-tavo-092-live/matrix-evidence.json"
                if evaluation_path.exists() and matrix_path.exists():
                    evaluation = json.loads(read(evaluation_path))
                    immutable_matrix = json.loads(read(matrix_path))
                    core = live_matrix.get("coreMatrix", {})
                    if core.get("overallStatus") != evaluation.get("overallStatus"):
                        errors.append("0.92 live matrix core overallStatus does not match immutable evaluation")
                    for key, value in core.get("caseTotals", {}).items():
                        source_key = key if key != "notApplicable" else "not-applicable"
                        if evaluation.get("caseTotals", {}).get(source_key) != value:
                            errors.append(f"0.92 live matrix core caseTotals.{key} does not match immutable evaluation")
                    assertion_key_map = {
                        "total": "total",
                        "passed": "passed",
                        "failedProductBehavior": "failed_product_behavior",
                        "blocked": "blocked",
                        "manual": "manual",
                        "notApplicable": "not-applicable",
                    }
                    for key, source_key in assertion_key_map.items():
                        if core.get("assertionTotals", {}).get(key) != evaluation.get("assertionTotals", {}).get(source_key):
                            errors.append(f"0.92 live matrix core assertionTotals.{key} does not match immutable evaluation")
                    immutable_cases = immutable_matrix.get("cases", {})
                    for case_id, case in core.get("cases", {}).items():
                        if case_id not in immutable_cases or case.get("status") != immutable_cases[case_id].get("status"):
                            errors.append(f"0.92 live matrix core {case_id} status does not match immutable matrix")
                        assertion_projection = case.get("assertionStatuses")
                        if assertion_projection is not None:
                            immutable_projection = {
                                assertion_id: assertion.get("status")
                                for assertion_id, assertion in immutable_cases.get(case_id, {}).get("assertions", {}).items()
                            }
                            if assertion_projection != immutable_projection:
                                errors.append(f"0.92 live matrix core {case_id} assertionStatuses do not match immutable matrix")
                    if not isinstance(core.get("cases", {}).get("F11", {}).get("assertionStatuses"), dict):
                        errors.append("0.92 live matrix core F11 requires immutable assertionStatuses")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"0.92 live matrix JSON parse failed: {exc}")

    gate_path = root / "assets/evidence/0.92.0/20260716-gate.json"
    if gate_path.exists():
        try:
            gate = json.loads(read(gate_path))
            device = gate.get("device", {})
            state = gate.get("preservedUserState", {})
            if device.get("serial") != "<redacted-device>":
                errors.append("0.92 reusable gate must redact the device serial")
            if "chatId" in state or "displayTitle" in state or state.get("privateChatIdentityIncluded") is not False:
                errors.append("0.92 reusable gate must omit private chat identity")
            if gate.get("mcp", {}).get("authorization") != "<redacted>":
                errors.append("0.92 reusable gate must redact MCP authorization")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"0.92 gate JSON parse failed: {exc}")

    if workspace_root is not None:
        for rel in TERMINAL_EVIDENCE_MANIFESTS:
            path = workspace_root / rel
            if not path.exists():
                continue
            errors.extend(f"{rel}: {error}" for error in validate_artifact(path, "validation-manifest"))

    openai_yaml = root / "agents/openai.yaml"
    if openai_yaml.exists():
        text = read(openai_yaml)
        if "$tavo" not in text:
            errors.append("agents/openai.yaml default_prompt must include $tavo")
        short_match = re.search(r"short_description:\s*['\"]?([^'\"]+)['\"]?", text)
        if short_match and len(short_match.group(1)) > 80:
            errors.append("agents/openai.yaml short_description is too long")
    else:
        errors.append("agents/openai.yaml missing")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("audit_tavo_skill_ok")
    print(f"references={len(reference_paths)}")
    print(f"scripts={len(script_paths)}")
    print(f"assets={len(REQUIRED_ASSETS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
