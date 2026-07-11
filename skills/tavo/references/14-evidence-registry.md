# Evidence Registry

Use the evidence registry to keep Tavo answers tied to proof instead of memory, old skills, or plausible guesses.

## Registry Contract

Every non-trivial product claim should have a registry row when it is used repeatedly or when it answers a boundary question such as "can Tavo do X?".

Required fields:

- `claim_id`: stable kebab-case identifier.
- `topic`: capability area such as `cards`, `worldbooks`, `regex`, `ejs`, `rendering`, `tavojs`, `plugins`, `media`, `mcp`, or `settings`.
- `verdict`: one of `verified`, `mixed`, `official-only`, `runtime-only`, `probable`, `workaround`, `blocked`, or `deprecated`.
- `evidence_tier`: one of `official-current`, `mcp-runtime`, `schema-seen`, `dry-run-pass`, `roundtrip-pass`, `semantic-pass`, `semantic-pass-observation`, `ui-pass`, `live-verified`, `live-verified-regression`, `semantic-mixed`, `historical-derived`, or `deprecated`.
- `official_source`: official URL or official-doc text snapshot path.
- `mcp_source`: MCP surface, resource, tool, or schema path.
- `live_artifact`: Android/MCP artifact directory when tested.
- `app_version`: app version for runtime/live evidence.
- `last_verified`: ISO date or empty string for unverified rows.
- `staleness_policy`: when to retest.
- `retention`: whether phone-side validation files/objects were retained, restored, or cleaned up.
- `notes`: short operational notes.

The machine-readable registry lives at `assets/evidence/registry.json`. Its formal schema is `assets/schemas/evidence-registry.schema.json`; `scripts/validate_tavo_artifact.py --kind registry` and `scripts/audit_tavo_skill.py` enforce the same enums and claim contract.

## Verdict Meanings

- `verified`: The behavior has current evidence from MCP, Android UI, screenshot, or roundtrip proof.
- `mixed`: Current evidence contains both a positive and a reproducible negative result, or proves the declared API exists while the runtime behavior is unreliable.
- `official-only`: Official docs describe the capability, but it has not been tested in this local environment.
- `runtime-only`: Current MCP exposes a tool/schema/resource, but no Android behavior proof exists yet.
- `probable`: Evidence supports a likely route, but the exact behavior needs a targeted test.
- `workaround`: The direct feature is not proven, but a practical alternative is documented.
- `blocked`: The current app/runtime lacks the needed entry point or the test cannot run safely yet.
- `deprecated`: Historical claim that must not be used as current behavior.

## Evidence Rules

- `official-current`, `mcp-runtime`, and `schema-seen` prove declaration or surface shape, not runtime success.
- `dry-run-pass` proves acceptance only. It does not prove persistence, rendering, prompt injection, or model effect.
- `roundtrip-pass` proves a create/import -> read/export -> compare path for the asserted fields. It does not prove visual layout or model semantics.
- `semantic-pass` requires a real model exchange, unique expected markers, persistent message readback, and a declared control where leakage is plausible.
- `semantic-pass-observation` is a dated positive that lacks enough controls or repeatability to support a reliability guarantee.
- `ui-pass` requires screenshot/UI evidence of the asserted visual or interaction state. Source text, an MCP object, or an unrendered HTML bubble is insufficient.
- `live-verified-regression` records a reproducible current failure with a working control. It is evidence, not an infrastructure error.
- `semantic-mixed` combines scoped positive and negative evidence. Keep both artifact paths and explain the discriminating conditions that remain unknown.
- Semantic, visual, persistence, import, and schema proof are orthogonal. A claim may need several registry rows instead of one artificial promotion ladder.
- If actual import normalizes fields, preserve both the submitted object and readback diff; do not claim field preservation.
- A live regression controls reliability wording even when official docs still advertise the feature.

## Initial Registry Rows

### Current 0.92 Rows

These rows are the current overlay. Use `assets/evidence/0.92.0/20260717-live-matrix.json` for exact 0.92 assertions; never collapse its F05/F09/F11 mixed cases or media/UI boundaries into blanket passes.

| Claim | Verdict | Evidence | Official/MCP source | Live artifact or next case |
| --- | --- | --- | --- | --- |
| A redacted Android device runs Tavo 0.92.0/920 and the ADB/MCP transport gate is healthy. | `verified` | `live-verified` | `assets/schemas/mcp-surface-0.92.0-20260716.json` | `assets/evidence/0.92.0/20260716-gate.json` |
| Current MCP surface is 70 tools, 18 resources, 7 templates, 0 prompts with 17/17 selected docs/schema reads and a successful `tavo_status` call. | `verified` | `live-verified` | `assets/schemas/mcp-surface-index-0.92.0-20260716.json` | `assets/evidence/0.92.0/20260716-gate.json` |
| Root entry-only plugins execute without UI contributions; legacy actions execute; dual declarations dispatch only `entry`. | `verified` | `live-verified` | Plugin Development + `tavo://docs/plugins` | F01-F03 in `20260717-live-matrix.json` |
| `tavo.plugin.config.get/all` returns effective defaults/overrides and mutating the `all()` copy does not persist. | `verified` | `live-verified` | Plugin Development + `tavo://docs/plugins` | F04 |
| Chat/message notifications preserve specific-before-umbrella ordering, persistent-add boundary, and handler isolation, but the tested `chat:changed` alias missed `chat:updated`. | `mixed` | `live-verified-regression` | Plugin Development + `tavo://docs/plugins` | F05 |
| `input:beforeSend/afterSend` covers UI, TavoJS, and MCP with rewrite/cancel and handler-local fail-open; attachment preservation was not exposed. | `verified` | `live-verified` | Plugin Development + `tavo://docs/plugins` | F06 |
| Generation prepare/success/error/cancel semantics passed atomically, while the tested `othersContinuation` source and auxiliary exclusions did not reach a blanket pass. | `mixed` | `live-verified-regression` | Plugin Development + `tavo://docs/plugins` | F07-F09 |
| `tavo.input.send()` returns structured accepted/rejected state before downstream generation completes; `busy` was not observed. | `verified` | `live-verified` | TavoJS page + `tavo://docs/tavojs` | F10 |
| Character TTS and queued calls reached a deterministic provider after binding; persona and audible identity/quality/stop remain blocked/manual. | `mixed` | `live-verified` | TavoJS/Plugin Development + runtime docs | F11 + media supplemental evidence |
| Root/wrapper/development-zip imports, same-id update preservation, and Backup B plugin restoration completed with matching readback. | `verified` | `roundtrip-pass` | Plugin/Backup docs + runtime | import/update/backup rows in `20260717-live-matrix.json` |
| Theme additions and role/user voice-rule scopes persisted and were restored; NovelAI save/reopen/delete is UI-only. | `verified` | `ui-pass` | current Android UI | supplemental rows in `20260717-live-matrix.json` |
| ASR remains absent from docs/MCP but native UI plus fake-gateway multipart transcription worked; human accuracy remains manual. | `mixed` | `live-verified` | full 0.92 MCP surface + Android UI | ASR supplemental row |

The iOS immersive-mode quick-scroll repair is Android `not-applicable` and is not entered as `verified`, `blocked`, or `deprecated`. The current registry verdict enum intentionally has no cross-platform N/A promotion.

### Prior-Version Seed Rows

These rows come from the 2026-07-09 phone method smoke and should be kept current by rerunning the matching validation cases:

| Claim | Verdict | Evidence | Artifact |
| --- | --- | --- | --- |
| MCP tool calls must use JSON-RPC `tools/call`; direct tool-name methods fail. | `verified` | `live-verified` | `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-direct-method-failed.json` |
| MCP input set/get/send can send a short chat message and read it back. | `verified` | `roundtrip-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-tool-send-result.json` |
| UIAutomator can read the Flutter chat UI tree well enough to locate title, input, messages, and button bounds. | `verified` | `ui-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/ui-before.xml` |
| Accessibility click is unavailable on the current phone unless a service is enabled; ADB tap from UI bounds works as fallback. | `verified` | `ui-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/ui-after-click.xml` |
| Lorebook import dryRun and actual import work, but import may normalize fields. | `verified` | `roundtrip-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-import-switch-result.json` |
| Character card import, new chat creation, and current chat switching work for a disposable imported character. | `verified` | `roundtrip-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-character-thread-switch-result.json` |
| Newly switched character chats can show a greeting selector before the first message materializes. | `verified` | `ui-pass` | `artifacts/tavo-validation/20260709-phone-method-smoke/screen-after-character-switch.png` |

## Answer Usage

When answering a user, load the registry if the question is about a known boundary. Reply with:

1. verdict;
2. evidence tier;
3. current proof path;
4. safest implementation route;
5. exact validation row if the claim still needs live proof.

Do not cite old skill material as evidence unless the row is marked `historical-derived` or `deprecated`.
