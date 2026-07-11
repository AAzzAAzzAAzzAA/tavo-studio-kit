#!/usr/bin/env python3
"""Build one immutable evidence index from several retained cross-feature runs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED_CASES = 35
AXIS_NAMES = (
    "runnerTransportInfra",
    "directRuntimeBehavior",
    "modelFormat",
    "modelSemantic",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def durable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class Candidate:
    key: str
    family: str
    ordinal: int
    run_dir: Path
    run_manifest: dict[str, Any]
    result_path: Path
    result: dict[str, Any]
    action_results: tuple[Path, ...]
    direct_proofs: tuple[Path, ...]
    permission_results: tuple[Path, ...]
    evidence_axes: dict[str, dict[str, Any]]
    direct_components: tuple[dict[str, Any], ...]
    model_request_sent: bool
    exchange_complete: bool
    score: int
    source_order: int


def normalized_axis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"evaluated": False, "passed": None, "failures": []}
    evaluated = value.get("evaluated") is True
    passed = value.get("passed") if isinstance(value.get("passed"), bool) else None
    if not evaluated:
        passed = None
    return {
        "evaluated": evaluated,
        "passed": passed,
        "failures": [str(item) for item in (value.get("failures") or [])],
        **({"components": list(value.get("components") or [])} if "components" in value else {}),
    }


def infer_direct_axis(
    action_results: tuple[Path, ...],
    direct_proofs: tuple[Path, ...],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    axis_paths = [path for path in direct_proofs if path.name == "direct-runtime-axis.json"]
    if axis_paths:
        axis = normalized_axis(load_json(axis_paths[-1]))
        return axis, tuple(item for item in axis.get("components", []) if isinstance(item, dict))

    components: list[dict[str, Any]] = []
    explicit_passes: list[bool] = []
    failures: list[str] = []
    for path in (*action_results, *direct_proofs):
        payload = load_json(path)
        passed: bool | None = None
        if path.name == "action-result.json":
            output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
            passed = payload.get("status") == "completed" and output.get("ok") is True
        elif isinstance(payload.get("passed"), bool):
            passed = bool(payload["passed"])
        elif isinstance(payload.get("exactTextMatched"), bool):
            passed = bool(payload["exactTextMatched"])
        component = {
            "component": f"legacy-proof:{path.parent.name}/{path.name}",
            "passed": passed,
            "source": str(path),
        }
        components.append(component)
        if passed is not None:
            explicit_passes.append(passed)
            if not passed:
                failures.append(f"legacy direct proof reported passed=false: {path}")
    evaluated = bool(components)
    if not evaluated:
        passed_value: bool | None = None
    elif failures:
        passed_value = False
    elif explicit_passes:
        passed_value = True
    else:
        passed_value = None
    axis = {
        "evaluated": evaluated,
        "passed": passed_value,
        "failures": failures,
        "components": components,
    }
    return axis, tuple(components)


def derive_evidence_axes(
    result: dict[str, Any],
    action_results: tuple[Path, ...],
    direct_proofs: tuple[Path, ...],
) -> tuple[dict[str, dict[str, Any]], tuple[dict[str, Any], ...]]:
    direct_axis, direct_components = infer_direct_axis(action_results, direct_proofs)
    raw_axes = result.get("evidenceAxes") if isinstance(result.get("evidenceAxes"), dict) else None
    if raw_axes is not None:
        axes = {name: normalized_axis(raw_axes.get(name)) for name in AXIS_NAMES}
        if axes["directRuntimeBehavior"].get("evaluated") is not True and direct_axis.get("evaluated") is True:
            axes["directRuntimeBehavior"] = direct_axis
        else:
            direct_components = tuple(
                item
                for item in axes["directRuntimeBehavior"].get("components", [])
                if isinstance(item, dict)
            ) or direct_components
    else:
        legacy_failure = str(result.get("failureClass") or "")
        runner_failures = [str(item) for item in (result.get("runnerInfrastructureFailures") or [])]
        exchange_complete = result.get("exchangeComplete") is True
        model_evaluated = exchange_complete or isinstance(result.get("assistantContent"), str) or isinstance(
            result.get("assistantMessageId"), int
        )
        product_failures = [str(item) for item in (result.get("productBehaviorFailures") or [])]
        format_failures = [
            item for item in product_failures if "first visible line" in item or "nonce" in item.lower()
        ]
        semantic_failures = [item for item in product_failures if item not in format_failures]
        if legacy_failure == "product_behavior" and not format_failures and not semantic_failures:
            semantic_failures = ["legacy product_behavior failure lacked an atomic subtype"]
        runner_evaluated = bool(legacy_failure or exchange_complete or result.get("passed") is True)
        axes = {
            "runnerTransportInfra": {
                "evaluated": runner_evaluated,
                "passed": None
                if not runner_evaluated
                else legacy_failure != "runner_or_infrastructure",
                "failures": runner_failures,
            },
            "directRuntimeBehavior": direct_axis,
            "modelFormat": {
                "evaluated": model_evaluated,
                "passed": None if not model_evaluated else not format_failures,
                "failures": format_failures,
            },
            "modelSemantic": {
                "evaluated": model_evaluated,
                "passed": None if not model_evaluated else not semantic_failures,
                "failures": semantic_failures,
            },
        }

    failure_text = json.dumps(
        {
            "runner": result.get("runnerInfrastructureFailures") or [],
            "traceback": result.get("traceback") or "",
        },
        ensure_ascii=False,
    )
    if "Current-chat readback did not match" in failure_text and axes["directRuntimeBehavior"].get("evaluated") is True:
        regression = {
            "component": "current-chat-set-after-direct-runtime",
            "passed": False,
            "source": "legacy-infrastructure-label-reinterpreted-as-direct-runtime-regression",
        }
        components = [*direct_components, regression]
        failures = [
            *[str(item) for item in axes["directRuntimeBehavior"].get("failures", [])],
            "current_chat_set readback regressed after completed direct-runtime components",
        ]
        axes["directRuntimeBehavior"] = {
            "evaluated": True,
            "passed": False,
            "failures": failures,
            "components": components,
        }
        direct_components = tuple(components)
    return axes, direct_components


def failed_axes(axes: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name in AXIS_NAMES if axes[name].get("evaluated") is True and axes[name].get("passed") is False]


def interpreted_failure_class(axes: dict[str, dict[str, Any]]) -> str | None:
    failures = failed_axes(axes)
    if not failures:
        return None
    if len(failures) > 1:
        return "multi_axis"
    return {
        "runnerTransportInfra": "runner_or_transport_infrastructure",
        "directRuntimeBehavior": "direct_runtime_behavior",
        "modelFormat": "model_format",
        "modelSemantic": "model_semantic",
    }[failures[0]]


def candidate_score(
    result: dict[str, Any],
    axes: dict[str, dict[str, Any]],
    action_count: int,
    direct_proof_count: int,
    restored: bool,
) -> int:
    score = 0
    if result.get("passed") is True:
        score += 600
    elif (
        axes["directRuntimeBehavior"].get("evaluated") is True
        and axes["directRuntimeBehavior"].get("passed") is False
    ):
        score += 560
    elif axes["modelSemantic"].get("evaluated") is True:
        score += 520
    elif axes["directRuntimeBehavior"].get("evaluated") is True:
        score += 500
    elif result.get("exchangeComplete") is True:
        score += 460
    elif action_count or direct_proof_count:
        score += 300 + action_count * 10 + direct_proof_count * 5
    else:
        score += 100
    if restored:
        score += 20
    return score


def discover_candidates(run_dir: Path, source_order: int) -> list[Candidate]:
    manifest_path = run_dir / "run-manifest.json"
    plan_path = run_dir / "plan.json"
    if not manifest_path.exists() or not plan_path.exists():
        raise RuntimeError(f"Run is missing manifest or plan: {run_dir}")
    manifest = load_json(manifest_path)
    restored = manifest.get("restorationPassed") is True
    candidates: list[Candidate] = []
    result_paths = sorted((run_dir / "model-calls").glob("*/*/result.json"))
    result_paths += sorted((run_dir / "model-calls").glob("*/*/infrastructure-failure.json"))
    seen_paths: set[Path] = set()
    for result_path in result_paths:
        if result_path in seen_paths:
            continue
        seen_paths.add(result_path)
        result = load_json(result_path)
        key = str(result.get("key") or "")
        family = str(result.get("family") or "")
        ordinal = int(result.get("ordinal") or 0)
        if not key or not family or ordinal < 1:
            continue
        step_dir = result_path.parent
        action_results = tuple(sorted(step_dir.rglob("action-result.json")))
        direct_names = {
            "crud-result.json",
            "direct-runtime-axis.json",
            "thread-roundtrip-result.json",
            "input-transport-proof.json",
            "selection-result.json",
            "audit-message-readback.json",
        }
        direct_proofs = tuple(
            sorted(path for path in step_dir.rglob("*.json") if path.name in direct_names)
        )
        permission_results = tuple(sorted(step_dir.rglob("permission/result.json")))
        exchange_complete = result.get("exchangeComplete") is True
        axes, direct_components = derive_evidence_axes(result, action_results, direct_proofs)
        candidates.append(
            Candidate(
                key=key,
                family=family,
                ordinal=ordinal,
                run_dir=run_dir,
                run_manifest=manifest,
                result_path=result_path,
                result=result,
                action_results=action_results,
                direct_proofs=direct_proofs,
                permission_results=permission_results,
                evidence_axes=axes,
                direct_components=direct_components,
                model_request_sent=(step_dir / "send-start.json").exists(),
                exchange_complete=exchange_complete,
                score=candidate_score(result, axes, len(action_results), len(direct_proofs), restored),
                source_order=source_order,
            )
        )
    return candidates


def canonical_plan(run_dirs: list[Path]) -> list[dict[str, Any]]:
    plans = [load_json(path / "plan.json") for path in run_dirs]
    full = [plan for plan in plans if int(plan.get("plannedModelCalls") or 0) == EXPECTED_CASES]
    if not full:
        raise RuntimeError("No supplied run contains the canonical 35-case plan")
    cases = full[0].get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASES:
        raise RuntimeError("Canonical plan has an invalid cases array")
    keys = [str(item.get("key") or "") for item in cases if isinstance(item, dict)]
    if len(keys) != EXPECTED_CASES or len(keys) != len(set(keys)):
        raise RuntimeError("Canonical plan case keys are missing or duplicated")
    return cases


def relative_or_absolute(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def build_aggregate(run_dirs: list[Path], output_dir: Path, workspace_root: Path) -> dict[str, Any]:
    plan_cases = canonical_plan(run_dirs)
    expected = {str(item["key"]): item for item in plan_cases}
    candidates: dict[str, list[Candidate]] = {key: [] for key in expected}
    for source_order, run_dir in enumerate(run_dirs):
        for candidate in discover_candidates(run_dir, source_order):
            if candidate.key in candidates:
                candidates[candidate.key].append(candidate)
    missing = sorted(key for key, values in candidates.items() if not values)
    if missing:
        raise RuntimeError(f"No result candidate exists for cases: {missing}")
    selected: list[Candidate] = []
    for case in plan_cases:
        key = str(case["key"])
        selected.append(max(candidates[key], key=lambda item: (item.score, item.source_order)))

    message_ids: list[int] = []
    case_rows: list[dict[str, Any]] = []
    for candidate in selected:
        result = candidate.result
        ids = [
            int(value)
            for value in (result.get("userMessageId"), result.get("assistantMessageId"))
            if isinstance(value, int) and value > 0
        ]
        message_ids.extend(ids)
        axes = candidate.evidence_axes
        direct_axis = axes["directRuntimeBehavior"]
        direct_runtime = direct_axis.get("evaluated") is True
        source_failure = str(result.get("failureClass") or "") or None
        interpreted = interpreted_failure_class(axes)
        behavior_evidence = bool(
            direct_runtime
            or axes["modelFormat"].get("evaluated") is True
            or axes["modelSemantic"].get("evaluated") is True
        )
        usable = behavior_evidence or result.get("passed") is True
        case_rows.append(
            {
                "ordinal": candidate.ordinal,
                "key": candidate.key,
                "family": candidate.family,
                "sourceRun": relative_or_absolute(candidate.run_dir, workspace_root),
                "sourceResult": relative_or_absolute(candidate.result_path, workspace_root),
                "sourceResultSha256": sha256_file(candidate.result_path),
                "sourceRunStatus": candidate.run_manifest.get("status"),
                "sourceRestorationPassed": candidate.run_manifest.get("restorationPassed"),
                "sourceFailureClass": source_failure,
                "interpretedFailureClass": interpreted,
                "interpretedFailureAxes": failed_axes(axes),
                "evidenceAxes": axes,
                "passed": result.get("passed") is True,
                "exchangeComplete": candidate.exchange_complete,
                "modelRequestSent": candidate.model_request_sent,
                "userMessageId": result.get("userMessageId"),
                "assistantMessageId": result.get("assistantMessageId"),
                "productBehaviorFailures": result.get("productBehaviorFailures") or [],
                "runnerInfrastructureFailures": result.get("runnerInfrastructureFailures") or [],
                "modelFormatFailures": axes["modelFormat"].get("failures") or [],
                "modelSemanticFailures": axes["modelSemantic"].get("failures") or [],
                "directRuntimeBehaviorFailures": direct_axis.get("failures") or [],
                "runnerTransportInfrastructureFailures": axes["runnerTransportInfra"].get("failures") or [],
                "modelFormatPassed": axes["modelFormat"].get("passed"),
                "modelSemanticPassed": axes["modelSemantic"].get("passed"),
                "directRuntimePassed": direct_axis.get("passed"),
                "runnerTransportInfraPassed": axes["runnerTransportInfra"].get("passed"),
                "directRuntimeEvidence": direct_runtime,
                "directRuntimeSubresults": list(candidate.direct_components),
                "actionResultCount": len(candidate.action_results),
                "directProofCount": len(candidate.direct_proofs),
                "directEvidencePaths": [
                    relative_or_absolute(path, workspace_root)
                    for path in (*candidate.action_results, *candidate.direct_proofs)
                ],
                "permissionObservationPaths": [
                    relative_or_absolute(path, workspace_root) for path in candidate.permission_results
                ],
                "behaviorEvidenceAvailable": behavior_evidence,
                "usableAsScopedEvidence": usable,
                "selectionScore": candidate.score,
            }
        )

    duplicates = sorted({value for value in message_ids if message_ids.count(value) > 1})
    coverage_complete = len(case_rows) == EXPECTED_CASES and all(row["usableAsScopedEvidence"] for row in case_rows)
    source_artifacts = [relative_or_absolute(path, workspace_root) for path in run_dirs]
    aggregate = {
        "schemaVersion": "1.1.0",
        "case": "tavo-cross-feature-matrix-aggregate",
        "status": "failed_product_behavior",
        "startedAt": min(str(load_json(path / "run-manifest.json").get("startedAt") or "") for path in run_dirs),
        "finishedAt": now_utc(),
        "evidenceLevel": "semantic-mixed",
        "countsTowardKpi": False,
        "artifacts": source_artifacts,
        "selectionPolicy": (
            "Choose one strongest retained result per canonical case using atomic evidence axes: all-axis pass, "
            "model semantic/format observation, then direct-runtime pass or regression. Prefer later supplied runs "
            "only when evidence strength ties."
        ),
        "coverage": {
            "plannedCases": EXPECTED_CASES,
            "selectedCases": len(case_rows),
            "coverageComplete": coverage_complete,
            "passedCases": sum(row["passed"] for row in case_rows),
            "completeModelExchanges": sum(row["exchangeComplete"] for row in case_rows),
            "selectedModelRequestsSent": sum(row["modelRequestSent"] for row in case_rows),
            "directRuntimeEvidenceCases": sum(row["directRuntimeEvidence"] for row in case_rows),
            "directRuntimePassedCases": sum(row["directRuntimePassed"] is True for row in case_rows),
            "directRuntimeFailedCases": sum(row["directRuntimePassed"] is False for row in case_rows),
            "modelFormatFailedCases": sum(row["modelFormatPassed"] is False for row in case_rows),
            "modelSemanticFailedCases": sum(row["modelSemanticPassed"] is False for row in case_rows),
            "runnerTransportInfraFailedCases": sum(
                row["runnerTransportInfraPassed"] is False for row in case_rows
            ),
            "behaviorEvidenceCases": sum(row["behaviorEvidenceAvailable"] for row in case_rows),
            "persistentExchangeMessageIds": len(message_ids),
            "uniquePersistentExchangeMessageIds": len(set(message_ids)),
            "duplicatePersistentExchangeMessageIds": duplicates,
            "allSourceRunsRestored": all(row["sourceRestorationPassed"] is True for row in case_rows),
        },
        "claimBoundary": (
            "This stitched aggregate is a coverage index, not one green epoch. Source legacy failureClass values are "
            "retained but do not override atomic axes. Completed direct-runtime components remain scoped behavior "
            "evidence even when a later runner/transport or current_chat_set step fails; direct success is never "
            "rewritten as model-semantic success."
        ),
        "cases": sorted(case_rows, key=lambda item: int(item["ordinal"])),
    }
    if not coverage_complete or duplicates:
        raise RuntimeError("Aggregate coverage or persistent message identity contract failed")
    durable_json(output_dir / "aggregate-manifest.json", aggregate)
    durable_json(
        output_dir / "source-manifests.json",
        {
            "generatedAt": now_utc(),
            "sources": [
                {
                    "path": relative_or_absolute(path / "run-manifest.json", workspace_root),
                    "sha256": sha256_file(path / "run-manifest.json"),
                }
                for path in run_dirs
            ],
        },
    )
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate retained Tavo cross-feature matrix runs.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("output directory must be absent or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate = build_aggregate(
        [Path(value).expanduser().resolve() for value in args.runs],
        output_dir,
        Path(args.workspace_root).expanduser().resolve(),
    )
    print(f"aggregate={output_dir / 'aggregate-manifest.json'}")
    print(json.dumps(aggregate["coverage"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
