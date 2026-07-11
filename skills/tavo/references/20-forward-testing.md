# Forward Testing

Forward-test `$tavo` with subagents whenever references, scripts, templates, or validation behavior change materially.

## Rules

- Give the subagent the skill path and a realistic user request.
- Do not leak the expected answer, suspected bug, or intended fix.
- Prefer tasks that require the skill to route itself to the right reference.
- Capture the subagent's final answer, any artifacts, and whether it used evidence labels correctly.
- If a forward test fails, improve the skill and rerun a fresh test.

## Required Test Families

| Family | Example prompt |
| --- | --- |
| Capability boundary | `Use $tavo to answer: Tavo 能不能在聊天气泡里做一个悬浮按钮，点击后把文字塞进输入框？` |
| Character creation | `Use $tavo to design an importable role card and explain how to validate it.` |
| Worldbook/regex/preset | `Use $tavo to create a small worldbook plus regex fixture and validation plan.` |
| Advanced Rendering | `Use $tavo to write a minimal Advanced Rendering marker and explain proof requirements.` |
| Plugin | `Use $tavo to outline a minimal TPG plugin package and validation steps.` |
| MCP workflow | `Use $tavo to explain how to import a card, create a chat, switch to it, and prove it on phone.` |
| Real model request | `Use $tavo to design a controlled 50-call real-phone model request batch and explain retained evidence requirements.` |
| EJS/macro runtime | `Use $tavo to design live tests for EJS conditionals, macro variables, and missing-variable behavior.` |
| Old claim audit | `Use $tavo to decide whether an old TavoJS snippet using window.tav should be reused.` |

## Scoring

Score each run:

- `route`: loaded the right reference files.
- `evidence`: used evidence labels and did not overclaim.
- `artifact`: produced valid JSON/package/snippet when asked.
- `validation`: included local, MCP, and phone proof where needed.
- `safety`: avoided secrets, destructive operations, and stale MCP state.
- `old-skill-hygiene`: did not treat old skills as current product facts.

Pass requires all relevant criteria for the prompt. Failure should name the exact missing reference, script, template, or evidence row.

## Current Forward-Test Backlog

- Capability answer: floating chat button.
- Creation: ST/CCv2 card plus PNG roundtrip.
- Creation: worldbook trigger plus regex cleanup.
- Rendering: AR marker with click handler.
- Plugin: minimal package validation.
- MCP: character import plus chat switch.
- Audit: old TavoJS API reuse.
