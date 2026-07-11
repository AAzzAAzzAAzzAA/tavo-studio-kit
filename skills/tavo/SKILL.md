---
name: tavo
description: Comprehensive Tavo encyclopedia and creation workflow skill. Use when Codex needs to answer what Tavo can do; explain or compare Tavo features; create, audit, or validate Tavo or SillyTavern character cards, worldbooks, presets, regexes, EJS templates, TavoJS, Advanced Rendering HTML/CSS/JS, plugins, image or voice workflows, app settings, or MCP workflows; or plan live Android/MCP verification against the current Tavo version.
---

# Tavo

Use this skill as the single entry point for Tavo capability answers and Tavo creation workflows. It is intentionally reference-heavy: load only the reference files required by the user's task, then cite the evidence tier used for any current-product claim.

## Evidence Priority

Use two separate judgments instead of one flat ranking:

1. **Declared surface:** fresh official documentation, then the current MCP runtime surface and schemas, then historical material.
2. **Observed reliability:** fresh Android/MCP experiments on the current app version. A reproducible live failure or mixed result controls any claim that a documented feature works reliably; official support text must not erase a current runtime regression.

Do not treat old skill references as current Tavo facts. When current sources conflict, report the conflict and its exact scope. Use `mixed` or `blocked` for reliability instead of selecting whichever source is more convenient.

## Evidence Labels

- `official-current`: Found in the latest official docs crawl.
- `mcp-runtime`: Found through the current MCP server surface or runtime docs.
- `live-verified`: Proved on the connected Android app during this run.
- `historical`: Useful material from older skills that still needs current confirmation.
- `deprecated`: Old claim known to be removed, unsafe, or contradicted by newer evidence.
- `creative-guidance`: Authoring advice that improves cards, worldbooks, regexes, prompts, plugins, or rendering, but is not itself a product API guarantee.
- `historical-derived`: Non-conflicting reusable material from old skills, kept with a validation boundary until current docs/MCP/live tests support stronger claims.

Use validation levels separately from source labels: `schema-seen`, `dry-run-pass`, `roundtrip-pass`, `semantic-pass`, `semantic-pass-observation`, `ui-pass`, `live-verified`, `live-verified-regression`, and `semantic-mixed`. Semantic, visual, persistence, and import proof are orthogonal; never promote one into another without the matching evidence.

## Task Routing

| User task | Read first | Then read |
| --- | --- | --- |
| "Tavo 能干嘛", feature comparison, unusual capability questions | `references/02-capabilities-overview.md`, `references/16-capability-answer-playbook.md` | `references/00-source-of-truth.md`, `references/14-evidence-registry.md`, `references/01-official-url-map.md` |
| Character cards, personas, greetings, examples, PNG cards, SillyTavern compatibility | `references/03-characters-cards-personas.md`, `references/24-character-opening-and-examples.md`, `references/17-authoring-blueprints.md` | `scripts/validate_tavo_artifact.py`, `scripts/embed_st_card_png.mjs`, `scripts/extract_st_card_png.mjs`, `scripts/worldbook_to_character_book.mjs` |
| Card/worldbook creative quality, role design, gameplay-mode planning | `references/13-creation-craft-workflows.md`, `references/17-authoring-blueprints.md` | `references/03-characters-cards-personas.md`, `references/05-prompt-authoring.md` |
| Chat pages, group chat, shortcuts, translation, history workflows | `references/04-chat-workflows.md` | `references/11-mcp-runtime.md` when automation or import/export is involved |
| Presets and prompt injection depth/order | `references/22-preset-prompt-injection.md`, `references/05-prompt-authoring.md` | `references/12-validation-matrix.md` |
| Worldbooks, keywords, secondary logic, depth, probability, timing | `references/21-worldbook-entry-semantics.md`, `references/05-prompt-authoring.md` | `references/12-validation-matrix.md` |
| Regex timing, scope, substitution, display/send/persistence pipeline | `references/23-regex-execution-pipeline.md`, `references/05-prompt-authoring.md` | `references/12-validation-matrix.md`, `scripts/run_regex_fixtures.py` |
| Macros and EJS authoring | `references/06-macros-ejs.md`, `references/25-ejs-tavojs-plugin-boundaries.md` | `references/12-validation-matrix.md` |
| Advanced Rendering, CSS/JS, TavoJS, WebView behavior | `references/07-rendering-tavojs.md`, `references/18-ar-tavojs-plugin-patterns.md`, `references/25-ejs-tavojs-plugin-boundaries.md` | `references/12-validation-matrix.md`, `references/15-phone-validation-runbook.md` |
| TPG plugins, plugin packaging, plugin UI/actions | `references/08-plugins-tpg.md`, `references/18-ar-tavojs-plugin-patterns.md`, `references/25-ejs-tavojs-plugin-boundaries.md` | `references/11-mcp-runtime.md`, `scripts/validate_tpg_package.py` |
| Image sending, image generation, voice, TTS/STT | `references/09-media-voice-image.md` | `references/10-app-settings-data.md` |
| App settings, API keys, model providers, backup/storage/data | `references/10-app-settings-data.md` | `references/01-official-url-map.md` |
| MCP operation, read-only inspection, import validation | `references/11-mcp-runtime.md`, `references/15-phone-validation-runbook.md` | `scripts/dump_mcp_surface.py`, `scripts/tavo_mcp_client.py` |
| Proving "can this be done?" or designing new experiments | `references/16-capability-answer-playbook.md`, `references/12-validation-matrix.md` | `references/14-evidence-registry.md`, `references/15-phone-validation-runbook.md`, the feature-specific reference above |
| Reconciling old skills or suspicious old APIs | `references/historical/deprecated-claims.md`, `references/19-debugging-pitfalls.md` | `references/00-source-of-truth.md` |
| Forward-testing this skill with subagents | `references/20-forward-testing.md` | `references/14-evidence-registry.md` |

## Subagent Rules

Use subagents for independent review when expanding or validating this skill:

- Official docs agent: refresh the current official information architecture and URL list from the live docs site.
- Historical audit agent: inspect old Tavo-family skills and report only recyclable material, deprecated claims, and migration risks.
- Skill engineering agent: check `SKILL.md`, `agents/openai.yaml`, reference routing, script indexing, and skill-creator compliance.
- Creation coverage agent: look for gaps in cards, worldbooks, regexes, EJS, TavoJS, Advanced Rendering, and plugins.
- Runtime validation agent: review the Android/MCP test matrix before live writes or UI experiments.

Keep delegated work bounded. Subagents should not move, delete, or edit old Tavo skills during the skeleton phase.

## Scripts

- `scripts/fetch_official_docs.py`: crawl the current official docs site into a timestamped local evidence folder and emit `url_map.json`.
- `scripts/normalize_official_docs.py`: turn a docs crawl into a durable manifest with topic, hash, line count, and reference routing metadata.
- `scripts/dump_mcp_surface.py`: read/list the connected Tavo MCP server surface and redact authorization values in saved output.
- `scripts/test_dump_mcp_surface.py`: verify the strict MCP gate requires all five top-level reads, every selected runtime document, and a successful read-only `tavo_status` call.
- `scripts/normalize_mcp_surface.py`: turn a redacted MCP dump into a compact tools/resources/templates index with risk labels.
- `scripts/tavo_mcp_client.py`: call Tavo MCP JSON-RPC methods and tools through the correct `tools/call` path with redacted output by default.
- `scripts/tavo_phone_capture.py`: capture ADB device state, Tavo package/window state, UIAutomator XML, and screenshot evidence.
- `scripts/tavo_phone_validate.py`: create validation artifact directories and run repeatable phone/MCP cases while retaining real-phone evidence by default.
- `scripts/run_phone_kpi_batch.py`: execute large retained real-phone validation batches, including at least 50 imported test assets and at least 50 real model API sends when required.
- `scripts/run_phone_semantic_kpi.py`: run the strict ten-family, 50-primary-call semantic epoch with retained attempts, negative controls, runtime isolation, screenshots, and exact restoration.
- `scripts/run_phone_semantic_ui_preflight.py`: prove all AR, TavoJS, plugin, and EJS UI actions on the real phone without consuming model-call KPI credit.
- `scripts/run_phone_cross_feature_matrix.py`: run the retained cross-feature matrix for lorebook, regex, preset, character, message, input, TavoJS, and plugin interactions.
- `scripts/aggregate_cross_feature_matrix.py`: select one strongest retained result per canonical cross-feature case and emit a coverage-complete stitched evidence manifest without pretending it was one green epoch.
- `scripts/run_phone_prompt_edge_matrix.py`: run gap-driven prompt edge cases for worldbook activation, preset role/depth/order, and regex placement/timing; do not use it to repeat already-settled baseline facts.
- `scripts/test_run_phone_prompt_edge_matrix.py`: validate the prompt-edge case catalog, dependency graph, fail-closed state, and offline result classification without touching the phone.
- `scripts/run_phone_asset_roundtrip_matrix.py`: run retained native/CCv2/CCv3/PNG character and persona import/export/readback cases when exact asset compatibility needs current proof.
- `scripts/test_run_phone_asset_roundtrip_matrix.py`: validate asset-roundtrip case ownership, resume behavior, and structured blocked outcomes offline.
- `scripts/run_phone_media_provider_matrix.py`: enumerate and test only currently exposed media/provider paths, requiring concrete readback/audio/transcript semantics and emitting structured blocked evidence for deferred or UI-only surfaces.
- `scripts/test_run_phone_media_provider_matrix.py`: validate the media matrix, semantic result assertions, and fail-closed unsupported-surface behavior offline.
- `scripts/run_phone_plugin_092_matrix.py`: prepare the F01-F11 Tavo 0.92 plugin matrix, build deterministic fixtures, evaluate retained assertions, and safely stage disabled fixtures only in an explicitly isolated test chat.
- `scripts/test_run_phone_plugin_092_matrix.py`: verify the 0.92 matrix catalog, dependency closure, deterministic packages, protected-chat refusal, redaction, evidence evaluation, and no-send staging contract offline.
- `scripts/tavo_generation_hook_fixture.py`: run a deterministic, source-allowlisted OpenAI-compatible LAN fixture for JSON, SSE, slow-stream, HTTP 500, and protocol-error generation-hook tests with private redacted captures.
- `scripts/test_tavo_generation_hook_fixture.py`: verify fixture authentication, allowlisting, deterministic responses, faults, streaming, secret-file rules, and capture redaction offline.
- `scripts/tavo_request_capture_gateway.py`: run a short-lived, credential-redacting OpenAI-compatible LAN relay when exact final model requests must be inspected; use source allowlists and stop it after capture.
- `scripts/test_tavo_request_capture_gateway.py`: verify gateway auth, redaction, private artifacts, redirect blocking, upstream errors, and incremental SSE relay offline.
- `scripts/test_run_phone_semantic_kpi_faults.py`: inject offline transaction faults and verify resume does not silently resend or overwrite terminal evidence.
- `scripts/test_run_phone_cross_feature_matrix.py`: exercise cross-feature ownership, no-resend, failure classification, and restoration paths without touching the phone.
- `scripts/run_phone_import_kpi.py`: retained historical import-volume runner; use the strict import artifact as its terminal evidence and prefer newer fail-closed runners for future epochs.
- `scripts/run_phone_coverage_kpi.py`: retained coverage probe used to enumerate phone-side capability paths; do not confuse its case count with semantic proof.
- `scripts/run_phone_ejs_runtime_diagnostic.py`: targeted EJS runtime seed/probe diagnostic with real chat evidence.
- `scripts/run_phone_preset_hidden_seed_diagnostic.py`: targeted preset-hidden-seed diagnostic for prompt-path isolation.
- `scripts/tavo_ui_tree.py`: semantic UIAutomator locator and ADB tap helper used by phone runners.
- `scripts/audit_skill_skeleton.py`: verify reference/script indexing, absence of initialization remnants, and old-skill isolation.
- `scripts/audit_tavo_skill.py`: full local audit for reference indexing, required assets, scripts, evidence registry, and secret checks.
- `scripts/validate_tavo_artifact.py`: validate local cards, worldbooks, regex fixtures, plugin manifests, MCP dumps, and evidence registry files.
- `scripts/generate_from_template.py`: render `{{variable}}` template variables into concrete artifacts.
- `scripts/run_regex_fixtures.py`: run before/after regex fixtures with deterministic local checks.
- `scripts/validate_tpg_package.py`: validate plugin package structure, manifest fields, path safety, and optional requirements such as input actions, HTML fragments, and marker text.
- `scripts/test_validate_tpg_package.py`: verify root/nested manifest selection, `entry` precedence, legacy fallback, hook-only packages, and path/symlink/ambiguity rejection offline.
- `scripts/scan_deprecated_tavojs.py`: scan generated artifacts and old snippets for deprecated or risky TavoJS patterns.
- `scripts/compare_roundtrip_export.py`: compare submitted JSON with imported/readback/exported JSON to detect normalization or field loss.
- `scripts/record_validation_artifact.py`: append or update evidence registry rows after local, MCP, or phone validation.
- `scripts/png-card-lib.mjs`: shared PNG text-chunk helper used by the ST PNG tools.
- `scripts/embed_st_card_png.mjs`: embed a SillyTavern character JSON payload into a PNG.
- `scripts/extract_st_card_png.mjs`: extract embedded SillyTavern card data from a PNG.
- `scripts/worldbook_to_character_book.mjs`: convert compatible worldbook/lorebook data into a `character_book` payload.

## Reference Files

| File | Purpose |
| --- | --- |
| `references/00-source-of-truth.md` | Evidence hierarchy, source labels, stale-source policy, and old-skill quarantine rules. |
| `references/01-official-url-map.md` | Current official documentation IA and URL inventory from a fresh crawl. |
| `references/02-capabilities-overview.md` | Main entry for answering Tavo capability questions and inferring unusual feature boundaries. |
| `references/03-characters-cards-personas.md` | Character cards, personas, PNG cards, imports, exports, and compatibility boundaries. |
| `references/04-chat-workflows.md` | Chat, group chat, shortcuts, translation, history, and conversation operations. |
| `references/05-prompt-authoring.md` | Presets, worldbooks, regexes, long memory, and prompt construction workflows. |
| `references/06-macros-ejs.md` | Macro expansion, EJS templates, context variables, and escaping rules. |
| `references/07-rendering-tavojs.md` | Advanced Rendering, CSS/JS behavior, TavoJS APIs, and WebView verification. |
| `references/08-plugins-tpg.md` | TPG plugin structure, packaging, manifests, actions, and validation. |
| `references/09-media-voice-image.md` | Voice, image, media generation, image sending, and media provider setup. |
| `references/10-app-settings-data.md` | App settings, API/model providers, backup, storage, and data management. |
| `references/11-mcp-runtime.md` | MCP connection, tool/resource discovery, safety classes, and import checks. |
| `references/12-validation-matrix.md` | Test matrix for turning official/MCP claims into live Android evidence. |
| `references/13-creation-craft-workflows.md` | Historical-derived creative workflows from old Tavo Studio that do not conflict with current official docs. |
| `references/14-evidence-registry.md` | Claim registry rules, evidence promotion, and seed live-verified claims. |
| `references/15-phone-validation-runbook.md` | Proven real-phone validation workflow using MCP, UIAutomator, ADB fallback, screenshots, and retained evidence. |
| `references/16-capability-answer-playbook.md` | How to answer unusual "can Tavo do X?" questions without overclaiming. |
| `references/17-authoring-blueprints.md` | Repeatable creation workflows for cards, worldbooks, presets, regexes, EJS, rendering, plugins, and packages. |
| `references/18-ar-tavojs-plugin-patterns.md` | Evidence-bounded Advanced Rendering, TavoJS, floating UI, and plugin implementation patterns. |
| `references/19-debugging-pitfalls.md` | Common failures: import normalization, stale MCP, render proof, old APIs, secrets, and UI limits. |
| `references/20-forward-testing.md` | Subagent forward-testing prompts and scoring rules for this skill. |
| `references/21-worldbook-entry-semantics.md` | Native worldbook fields, constant/keyword activation, secondary logic, scan/depth/role, probability/timing, compatibility mappings, and evidence boundaries. |
| `references/22-preset-prompt-injection.md` | Preset object model, relative/absolute entries, depth/order/role, active-preset behavior, and validation workflow. |
| `references/23-regex-execution-pipeline.md` | Regex placements, timings, substitutions, depth, display/send/persistent-message distinctions, and A/B validation. |
| `references/24-character-opening-and-examples.md` | First messages, alternate greetings, dialogue examples, channel field mappings, imports, chat creation, and thread switching. |
| `references/25-ejs-tavojs-plugin-boundaries.md` | Macro, EJS, TavoJS, TPG, and MCP capability boundaries for variables, worldbooks, messages, input, permissions, and visual proof. |
| `references/historical/deprecated-claims.md` | Historical claims from old skills that must not silently enter new answers. |

## Skeleton Maintenance

Before accepting skeleton or reference edits, run:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/tavo
python3 skills/tavo/scripts/audit_skill_skeleton.py skills/tavo
python3 skills/tavo/scripts/audit_tavo_skill.py skills/tavo
```

For product facts, refresh official docs with fail-closed `scripts/fetch_official_docs.py`, normalize with `scripts/normalize_official_docs.py`, and reread MCP runtime state with `scripts/dump_mcp_surface.py --strict` when a connected phone is available.
