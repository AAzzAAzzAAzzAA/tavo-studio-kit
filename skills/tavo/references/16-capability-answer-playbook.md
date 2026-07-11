# Capability Answer Playbook

Use this playbook when the user asks whether Tavo can do something, especially unusual UI, rendering, automation, or authoring questions that official docs do not spell out.

## Answer Shape

Reply with:

1. `Verdict`: yes, no, workaround, probable, or needs test.
2. `Evidence`: official-current, mcp-runtime, live-verified, historical-derived, or deprecated.
3. `How`: the shortest practical implementation path.
4. `Limits`: what is not guaranteed.
5. `Validation`: the exact dry-run, readback, UI, screenshot, or matrix row that proves or would prove it.

Avoid binary certainty when the evidence is only official prose or old skill material.

## Decision Ladder

1. Search official docs index and relevant reference.
2. Check `assets/evidence/registry.json`.
3. Check current MCP surface if the answer depends on tools, schemas, import, switch, or state.
4. Check live artifacts if visual rendering, JS, plugin UI, or Android behavior matters.
5. If still uncertain, design the smallest safe validation case in `references/12-validation-matrix.md`.

## Common Question Families

| User asks | First references | Proof needed |
| --- | --- | --- |
| Can I make a floating button in a chat/message? | `07-rendering-tavojs.md`, `18-ar-tavojs-plugin-patterns.md` | Android screenshot plus click/readback marker |
| Can a card include JS/CSS/HTML? | `07-rendering-tavojs.md` | Import/render proof; source text appearing is not enough |
| Can a plugin add an action or UI? | `08-plugins-tpg.md`, `18-ar-tavojs-plugin-patterns.md` | package validation, import, visible action or tool readback |
| Can MCP import/switch/read this object? | `11-mcp-runtime.md`, `15-phone-validation-runbook.md` | fresh MCP tools/list, dryRun, actual disposable write, readback |
| Can a worldbook trigger only in condition X? | `05-prompt-authoring.md`, `12-validation-matrix.md` | trigger/non-trigger chat pair or prompt-view proof |
| Can regex fix model output safely? | `05-prompt-authoring.md` | before/after fixtures plus live scoped test |
| Can EJS/macros compute dynamic prompt text? | `06-macros-ejs.md` | render/expansion proof in target context |
| Can API/model settings be changed by MCP? | `10-app-settings-data.md`, `11-mcp-runtime.md` | current MCP surface; historical evidence says API connection settings are UI-only |

## Verdict Calibration

- Say `可以，已真机验证` only when the registry or artifact proves the exact behavior.
- Say `可以，官方有这个能力` when docs support the feature but no local runtime proof exists.
- Say `MCP 当前暴露了入口` when tool/schema proof exists but no UI behavior proof exists.
- Say `能做，但要换实现路径` when direct implementation is unproven but AR, plugin, prompt, regex, or MCP offers a practical route.
- Say `现在不能当成已支持` when the only evidence is an old skill or older emulator result.

## Minimum Experiment Pattern

For undocumented capability questions, design a minimal artifact:

- one disposable card/chat/plugin/worldbook;
- one visible marker or variable value;
- one dry-run/import step;
- one readback or screenshot;
- one retention or cleanup decision.

The experiment should not use real user data, destructive restore, or persistent settings unless the user explicitly requests that scope. Real-phone validation files and disposable test objects are retained by default for evidence.
