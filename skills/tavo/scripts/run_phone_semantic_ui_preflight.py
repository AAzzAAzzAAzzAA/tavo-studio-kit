#!/usr/bin/env python3
"""Preflight every UI action used by the strict semantic KPI epoch.

This script never sends a model request and never counts toward the API-call KPI.
It proves that the prepared epoch's AR/TavoJS buttons and plugin input actions can
be located through the live UI tree, clicked on the real phone, and read back
through MCP before the expensive semantic batch begins.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_import_kpi import atomic_json, load_json, now_utc, response_payload, tool_call  # noqa: E402
from run_phone_kpi_batch import TavoMcp, capture_phone, load_endpoint, ok_response  # noqa: E402
from run_phone_semantic_kpi import (  # noqa: E402
    adb,
    acquire_phone_runtime_lock,
    append_live_panel,
    assert_isolated_plugin_runtime,
    capture_screen_only,
    dismiss_greeting,
    isolate_plugin_runtime,
    read_mcp_surface_identity,
    reload_chat_ui,
    recover_plugin_runtime,
    restore_original_chat,
    run_ui_action_until_input_marker,
    runner_bundle_records,
    safe_name,
    set_current_chat,
    settle_plugin_runtime_ui,
    sha256,
    stable_hash,
    tap_ar_button,
    tap_plugin_action,
)


ACTION_NAMES = ["OBSERVE", "CLARIFY", "STATE", "PLAN", "EVIDENCE"]
AR_LABELS = ["AR 观察场景", "AR 澄清目标", "AR 核对状态", "AR 规划下一步", "AR 汇总证据"]


def foreground_tavo(device: str, output: Path) -> None:
    launched = adb(
        device,
        ["shell", "monkey", "-p", "app.bitbear.tav", "-c", "android.intent.category.LAUNCHER", "1"],
        timeout=30,
    )
    atomic_json(output, {"returncode": launched.returncode, "output": launched.stdout})
    if launched.returncode != 0:
        raise RuntimeError("Could not bring Tavo to the foreground for UI preflight.")
    time.sleep(1.5)


def clear_and_assert_blank(client: TavoMcp, step_dir: Path, suffix: str) -> None:
    cleared = tool_call(client, step_dir, f"input-clear-{suffix}.json", "tavo_input_clear", {})
    readback = tool_call(client, step_dir, f"input-clear-readback-{suffix}.json", "tavo_input_get", {})
    text = str(response_payload(readback).get("text") or "")
    if not ok_response(cleared) or not ok_response(readback) or text:
        raise RuntimeError(f"Input was not blank after clear ({suffix}).")


def verify_action_family(
    client: TavoMcp,
    semantic_artifact: Path,
    artifact_dir: Path,
    device: str,
    epoch_id: str,
    run_id: str,
    family: str,
    chat_ids: list[int],
    labels: list[str],
    marker_for: Callable[[str, int], str],
    tap: Callable[[str, str, Path], None],
    results: list[dict[str, Any]],
    panel_sources: list[dict[str, Any]] | None = None,
    reload_anchor_ids: list[int] | None = None,
) -> None:
    family_dir = artifact_dir / family
    family_dir.mkdir(parents=True, exist_ok=True)
    if len(chat_ids) != 5 or len(set(chat_ids)) != 5:
        raise RuntimeError(f"{family} preflight requires five distinct fresh chats.")
    if panel_sources is not None and len(panel_sources) != 5:
        raise RuntimeError(f"{family} preflight requires five immutable panel sources.")
    if panel_sources is not None and (
        reload_anchor_ids is None
        or len(reload_anchor_ids) != 5
        or len(set(reload_anchor_ids)) != 5
        or set(reload_anchor_ids) & set(chat_ids)
    ):
        raise RuntimeError(f"{family} preflight requires five distinct seed-only reload anchors.")

    for index, (label, action) in enumerate(zip(labels, ACTION_NAMES, strict=True), start=1):
        step_dir = family_dir / f"{index:02d}-{safe_name(action.lower())}"
        step_dir.mkdir(parents=True, exist_ok=True)
        chat_id = chat_ids[index - 1]
        set_current_chat(
            client,
            step_dir,
            chat_id,
            f"ui-preflight-{safe_name(epoch_id)}-{safe_name(family)}-{index:02d}-{chat_id}",
        )
        time.sleep(3)
        assert_isolated_plugin_runtime(
            client,
            step_dir,
            f"codex.semantic.{run_id.lower()}",
            "before-ui-action",
        )
        dismiss_greeting(device, step_dir)
        clear_and_assert_blank(client, step_dir, "before")
        panel_evidence: dict[str, Any] | None = None
        if panel_sources is not None:
            panel_source = panel_sources[index - 1]
            panel_evidence = append_live_panel(
                client,
                semantic_artifact,
                step_dir,
                chat_id,
                run_id,
                str(panel_source["variant"]),
                str(panel_source["sourceSha256"]),
                f"ui-preflight-{family}-{index:02d}",
            )
            atomic_json(step_dir / "live-panel-result.json", panel_evidence)
            reload_chat_ui(
                client,
                step_dir / "panel-ui-reload",
                device,
                chat_id,
                int(reload_anchor_ids[index - 1]),
                f"ui-preflight-{safe_name(epoch_id)}-{safe_name(family)}-{index:02d}-panel-reload",
                str(panel_evidence["marker"]),
            )
        if capture_screen_only(device, step_dir, "before-click") != 0:
            raise RuntimeError(f"Could not capture {family} action {index} before its click.")
        time.sleep(0.3)
        marker = marker_for(action, index)
        readback, text = run_ui_action_until_input_marker(
            client,
            device,
            step_dir / "ui-action",
            label,
            marker,
            tap,
        )
        passed = bool(ok_response(readback) and marker in text)
        if capture_phone(device, step_dir, "after-click") != 0:
            passed = False
        assert_isolated_plugin_runtime(
            client,
            step_dir,
            f"codex.semantic.{run_id.lower()}",
            "after-ui-action",
        )
        result = {
            "family": family,
            "ordinal": index,
            "label": label,
            "action": action,
            "chatId": chat_id,
            "expectedMarker": marker,
            "inputText": text,
            "panelEvidence": panel_evidence,
            "passed": passed,
            "finishedAt": now_utc(),
        }
        atomic_json(step_dir / "result.json", result)
        results.append(result)
        if not passed:
            raise RuntimeError(f"{family} action {label!r} did not write marker {marker!r}.")
        clear_and_assert_blank(client, step_dir, "after")


def verify_ejs_plugin_actions(
    client: TavoMcp,
    artifact_dir: Path,
    device: str,
    epoch_id: str,
    run_id: str,
    chat_id: int,
    results: list[dict[str, Any]],
) -> None:
    family_dir = artifact_dir / "ejs-plugin-runtime"
    seed_value = ""
    before_count = -1
    cases = [
        (1, "SEED", f"EJS 随机写入 {run_id}"),
        (2, "PROBE", f"EJS 状态回读 {run_id}"),
    ]
    for ordinal, action, label in cases:
        step_dir = family_dir / f"{ordinal:02d}-{action.lower()}"
        set_current_chat(
            client,
            step_dir,
            chat_id,
            f"ui-preflight-{safe_name(epoch_id)}-ejs-plugin-{ordinal:02d}-{chat_id}",
        )
        time.sleep(2)
        assert_isolated_plugin_runtime(
            client,
            step_dir,
            f"codex.semantic.{run_id.lower()}",
            "before-ui-action",
        )
        dismiss_greeting(device, step_dir)
        clear_and_assert_blank(client, step_dir, "before")
        if capture_screen_only(device, step_dir, "before-click") != 0:
            raise RuntimeError(f"Could not capture EJS plugin action {action} before its click.")
        tap_plugin_action(device, label, step_dir)
        time.sleep(1.0)
        readback = tool_call(client, step_dir, "input-readback.json", "tavo_input_get", {})
        text = str(response_payload(readback).get("text") or "")
        if action == "SEED":
            match = re.fullmatch(
                rf"\[EJS-SEED:{re.escape(run_id)}\] token=(EJS_RUNTIME_{re.escape(run_id)}_[A-Za-z0-9_]+);before=(\d+)",
                text,
            )
            passed = bool(ok_response(readback) and match is not None)
            if match is not None:
                seed_value = match.group(1)
                before_count = int(match.group(2))
            expected = f"[EJS-SEED:{run_id}]"
        else:
            match = re.fullmatch(
                rf"\[EJS-PROBE:{re.escape(run_id)}\] token=(EJS_RUNTIME_{re.escape(run_id)}_[A-Za-z0-9_]+);after=(\d+)",
                text,
            )
            passed = bool(
                ok_response(readback)
                and match is not None
                and match.group(1) == seed_value
                and int(match.group(2)) == before_count
            )
            expected = f"[EJS-PROBE:{run_id}]"
        if capture_phone(device, step_dir, "after-click") != 0:
            passed = False
        assert_isolated_plugin_runtime(
            client,
            step_dir,
            f"codex.semantic.{run_id.lower()}",
            "after-ui-action",
        )
        result = {
            "family": "ejs-plugin-runtime",
            "ordinal": ordinal,
            "label": label,
            "action": action,
            "chatId": chat_id,
            "expectedMarker": expected,
            "inputText": text,
            "runtimeValue": seed_value,
            "beforeRenderCount": before_count,
            "passed": passed,
            "finishedAt": now_utc(),
        }
        atomic_json(step_dir / "result.json", result)
        results.append(result)
        if not passed:
            raise RuntimeError(f"EJS plugin action {action} failed its input/variable round trip.")
        clear_and_assert_blank(client, step_dir, "after")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight prepared semantic KPI UI actions without model calls.")
    parser.add_argument("--semantic-artifact", required=True)
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    semantic_artifact = Path(args.semantic_artifact).expanduser().resolve()
    parent_manifest = load_json(semantic_artifact / "run-manifest.json")
    if parent_manifest.get("status") != "prepared" or parent_manifest.get("countsTowardKpi") is not False:
        print("--semantic-artifact must be an immutable prepared, non-counting semantic epoch.", file=sys.stderr)
        return 2
    current_bundle_hash = stable_hash(runner_bundle_records())
    if parent_manifest.get("scriptHash") != current_bundle_hash:
        print("The semantic runner bundle changed after preparation; start a new epoch.", file=sys.stderr)
        return 2

    registry = load_json(semantic_artifact / "context-registry.json")
    artifact_dir = semantic_artifact / "ui-preflight"
    manifest_path = artifact_dir / "run-manifest.json"
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        print("UI preflight artifact already exists; it is immutable.", file=sys.stderr)
        return 2
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "case": "semantic-ui-preflight",
        "status": "running",
        "startedAt": now_utc(),
        "semanticArtifact": str(semantic_artifact),
        "epochId": parent_manifest.get("epochId"),
        "semanticRunnerBundleHash": current_bundle_hash,
        "preflightScriptHash": sha256(Path(__file__).resolve()),
        "targetActions": 17,
        "modelRequestsSent": 0,
        "countsTowardKpi": False,
    }
    atomic_json(manifest_path, manifest)

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    client = TavoMcp(url, auth)
    global_lock_handle, global_lock_identity = acquire_phone_runtime_lock(args.device, url)
    manifest["globalRuntimeLockIdentity"] = global_lock_identity
    atomic_json(manifest_path, manifest)
    original_chat_id = int(parent_manifest["originalChatId"]) if parent_manifest.get("originalChatId") else None
    results: list[dict[str, Any]] = []
    plugin_isolation: dict[str, Any] | None = None
    try:
        foreground_tavo(args.device, artifact_dir / "foreground-tavo.json")
        _surface_identity, surface_hash = read_mcp_surface_identity(client, artifact_dir)
        if surface_hash != parent_manifest.get("mcpSurfaceHash"):
            raise RuntimeError("MCP surface changed after semantic epoch preparation.")

        run_id = str(registry["runId"])
        chats = registry["preflightChats"]
        plugin_isolation = isolate_plugin_runtime(
            client,
            artifact_dir / "plugin-isolation",
            str(registry["semanticPluginId"]),
            str(parent_manifest["epochId"]) + "-ui-preflight",
            str(registry["semanticPlugin"]["readbackHash"]),
        )
        manifest.update(
            {
                "pluginIsolationPassed": True,
                "isolatedPluginCount": plugin_isolation["result"]["pluginCount"],
                "disabledPluginCount": plugin_isolation["result"]["disabledCount"],
            }
        )
        atomic_json(manifest_path, manifest)
        settle_plugin_runtime_ui(
            args.device,
            artifact_dir / "plugin-isolation" / "webview-settle",
            "ui-preflight",
        )
        verify_action_family(
            client,
            semantic_artifact,
            artifact_dir,
            args.device,
            str(parent_manifest["epochId"]),
            run_id,
            "tavojs-variable",
            [int(chat["id"]) for chat in chats["tavojs-variable"]],
            AR_LABELS,
            lambda action, index: f"AR_{run_id}PJS{index:02d}_{action} state=clicked",
            tap_ar_button,
            results,
            registry["preflightPanelSources"]["tavojs-variable"],
            [int(group[0]["id"]) for group in registry["uiReloadAnchors"]["tavojs-variable"]],
        )
        verify_action_family(
            client,
            semantic_artifact,
            artifact_dir,
            args.device,
            str(parent_manifest["epochId"]),
            run_id,
            "advanced-rendering",
            [int(chat["id"]) for chat in chats["advanced-rendering"]],
            AR_LABELS,
            lambda action, index: f"AR_{run_id}PAR{index:02d}_{action} state=clicked",
            tap_ar_button,
            results,
            registry["preflightPanelSources"]["advanced-rendering"],
            [int(group[0]["id"]) for group in registry["uiReloadAnchors"]["advanced-rendering"]],
        )
        verify_action_family(
            client,
            semantic_artifact,
            artifact_dir,
            args.device,
            str(parent_manifest["epochId"]),
            run_id,
            "plugin-action-panel",
            [int(chat["id"]) for chat in chats["plugin-action-panel"]],
            [
                f"观察场景 {run_id}",
                f"澄清目标 {run_id}",
                f"核对状态 {run_id}",
                f"规划下一步 {run_id}",
                f"汇总证据 {run_id}",
            ],
            lambda action, _index: f"TPG_{run_id}_{action} state=clicked",
            tap_plugin_action,
            results,
        )
        verify_ejs_plugin_actions(
            client,
            artifact_dir,
            args.device,
            str(parent_manifest["epochId"]),
            run_id,
            int(registry["ejsPluginPreflightChat"]["id"]),
            results,
        )
        plugins_restored = recover_plugin_runtime(
            client, Path(str(plugin_isolation["root"])), "preflight-complete"
        )
        if plugins_restored:
            plugin_isolation = None
        restored = restore_original_chat(client, artifact_dir, original_chat_id, str(parent_manifest["epochId"]) + "-ui-preflight")
        passed = (
            len(results) == 17
            and all(result.get("passed") for result in results)
            and plugins_restored
            and restored
        )
        atomic_json(artifact_dir / "results.json", results)
        manifest.update(
            {
                "status": "passed" if passed else "failed",
                "finishedAt": now_utc(),
                "actionsPassed": sum(1 for result in results if result.get("passed")),
                "pluginsRestored": plugins_restored,
                "restoredOriginalChat": restored,
                "countsTowardKpi": False,
            }
        )
        atomic_json(manifest_path, manifest)
        print(f"artifact_dir={artifact_dir}")
        print(f"status={manifest['status']}")
        print(f"actions_passed={manifest['actionsPassed']}/17")
        return 0 if passed else 1
    except Exception as exc:  # noqa: BLE001
        plugins_restored_after_failure: bool | None = None
        if plugin_isolation is not None:
            try:
                plugins_restored_after_failure = recover_plugin_runtime(
                    client, Path(str(plugin_isolation["root"])), "preflight-failure"
                )
            except Exception:  # noqa: BLE001
                plugins_restored_after_failure = False
        restored = False
        try:
            restored = restore_original_chat(client, artifact_dir, original_chat_id, str(parent_manifest.get("epochId")) + "-ui-preflight-failure")
        except Exception:  # noqa: BLE001
            pass
        atomic_json(artifact_dir / "results.json", results)
        atomic_json(artifact_dir / "fatal-exception.json", {"error": repr(exc), "traceback": traceback.format_exc()})
        manifest.update(
            {
                "status": "failed",
                "failedAt": now_utc(),
                "failure": repr(exc),
                "actionsPassed": sum(1 for result in results if result.get("passed")),
                "pluginsRestoredAfterFailure": plugins_restored_after_failure,
                "restoredOriginalChat": restored,
                "countsTowardKpi": False,
            }
        )
        atomic_json(manifest_path, manifest)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
