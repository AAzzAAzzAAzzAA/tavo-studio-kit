# Source Of Truth

This file defines how the Tavo skill decides what is current, what is inferred, and what is historical.

## Current 0.92 Evidence Baseline

- `official-current`: complete 83-page crawl fetched on 2026-07-16, stored in `assets/official-docs/text-20260716/`, `assets/official-docs/official_manifest-20260716.json`, and `assets/official-docs/url_map-20260716.json`.
- `mcp-runtime`: redacted Tavo `0.92.0` surface stored in `assets/schemas/mcp-surface-0.92.0-20260716.json` with compact index `assets/schemas/mcp-surface-index-0.92.0-20260716.json`.
- `live-verified`: the 2026-07-16 ADB/MCP readiness gate plus the redacted 2026-07-17 atomic matrix in `assets/evidence/0.92.0/20260717-live-matrix.json`. The matrix promotes only its named assertions: eight core cases passed; F05 notifications, F09 generation sources, and F11 TTS remain mixed. Package/update/Backup B roundtrips and bounded theme, voice-rule, ASR/TTS/image, and NovelAI UI/integration results are recorded separately. Prior 0.91 artifacts remain version-scoped controls.

The official site has no dedicated release-notes page in the current 83-page information architecture. Treat the MCP `serverInfo.version` and Android package version as runtime version evidence; do not infer a complete 0.92 changelog from documentation diffs.

## Source And Behavior Order

For **declared capabilities and field shapes**:

1. `official-current`: the latest crawl of `https://docs.tavoai.dev/cn/` produced by `scripts/fetch_official_docs.py`.
2. `mcp-runtime`: live tools, resources, schemas, runtime docs, and read-only app state from the connected phone.
3. `historical`: older Tavo-family skills, old probe logs, and old generated guides.

For **whether a feature actually works and is reliable**, use `live-verified` evidence from the current app version. Positive and negative Android/MCP experiments both count. A reproducible live regression outranks a general official support statement for the narrower runtime-behavior claim.

When a current official page and the current MCP runtime document the same new contract, label it `official-current` or `mcp-runtime` until the exact Android effect is executed and read back. Two declarations do not equal a live test.

## Conflict Policy

- When official docs and old skills conflict, use official docs as the current claim and move the old claim to `references/historical/deprecated-claims.md`.
- When official docs are vague but MCP runtime exposes a concrete schema/tool, describe the MCP evidence and mark the result `mcp-runtime`.
- When docs and MCP both leave a behavior ambiguous, design an Android experiment in `references/12-validation-matrix.md` before answering as fact.
- When official docs or MCP expose a feature but current live tests fail, say that the feature is declared but currently unreliable. Preserve both sides and use a `mixed` or `blocked` verdict; do not let documentation overwrite the regression.
- When live positive and live negative results conflict, scope each configuration, app/runtime state, and date. The aggregate reliability verdict remains `mixed` until a discriminating retest resolves it.
- When answering creative quality questions, separate product guarantees from authoring guidance. Use `creative-guidance` for craft advice.
- Use `historical-derived` for non-conflicting material from old skills that improves workflow but still needs current Tavo validation before becoming a product fact.

## Old Skill Quarantine

Old Tavo skills are valuable as search material, not as truth. They may provide:

- candidate workflows to retest;
- script ideas and stable SillyTavern-format utilities;
- known traps, removed APIs, and stale mental models;
- examples of card/worldbook/prompt structure that still need current validation.

They must not provide:

- current API signatures without MCP or official-doc confirmation;
- current app UI paths without Android confirmation;
- current plugin or TavoJS behavior without retesting;
- claims about write permission, persistence, or import success without a current evidence path.

## Evidence In Answers

For non-trivial capability answers, state the evidence tier briefly:

- "官方文档当前写到..." for `official-current`;
- "MCP 当前暴露..." for `mcp-runtime`;
- "真机本轮验证..." for `live-verified`;
- "旧 skill 的创作经验可借用，但尚未当作当前产品事实..." for `historical-derived`;
- "旧 skill 里有这个说法，但尚未重验..." for `historical`;
- "旧 skill 里的这个说法现在按废弃处理..." for `deprecated`.

## Refresh Commands

```bash
python3 scripts/fetch_official_docs.py --output /tmp/tavo-official-docs-current
python3 scripts/normalize_official_docs.py
python3 scripts/dump_mcp_surface.py --strict --output /tmp/tavo-mcp-surface-current
python3 scripts/audit_skill_skeleton.py skills/tavo
python3 scripts/audit_tavo_skill.py skills/tavo
```

The current complete official-doc text snapshot is stored under `assets/official-docs/text-20260716/`, with normalized metadata in `assets/official-docs/official_manifest.json`. The 2026-07-10 snapshot is intentionally retained as the 0.91-era comparison baseline. Refresh the live site and MCP surface before treating this draft as current after future product updates.

`scripts/fetch_official_docs.py` is fail-closed by default: incomplete crawl, fetch errors, or unfetched discovered URLs should return nonzero unless `--allow-partial` is explicitly passed.
