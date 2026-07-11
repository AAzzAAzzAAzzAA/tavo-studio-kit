# Deprecated And Historical Claims

This file quarantines old Tavo-family skill material so it can be retested without polluting current answers.

## Historical Skill Sources

- `/Users/<user>/.agents/skills/tavo-complete`
- `/Users/<user>/.agents/skills/tavo-studio`
- `/Users/<user>/.agents/skills/zhimengren`
- `/Users/<user>/.codex/skills/sillytavern-card-worldbook`
- `/Users/<user>/Documents/Codex/.agents/skills/tavo-android-operator`
- `/Users/<user>/Documents/Codex/.agents/skills/tavo-card-craft`
- `/Users/<user>/Documents/Codex/.agents/skills/tavo-card-studio-verified`
- `/Users/<user>/Documents/Codex/.agents/skills/tavo-studio`

## Claims To Treat As Deprecated Until Reproved

- TavoJS event APIs named like `tavo.event.on` or `tavo.event.off`.
- TavoJS user or character accessors named like `tavo.user.get` or `tavo.character.current`.
- Callback-style `tavo.update` patterns where current docs require promise-like behavior or another mechanism.
- Claims that `tavo.get` / `tavo.set` must always be awaited; current docs distinguish variable operations from many async object APIs.
- Claims that variable scopes are only `chat` and `global`; current docs include message-level use cases.
- Undocumented helper names such as `tavo.sendMessage` unless current docs/MCP expose them.
- Claims that message data is read-only or writable without checking current runtime docs.
- Hard-coded Android or Linux paths from old local probes.
- Version-specific claims from older app baselines such as 0.81 or 0.90.
- Any old plugin, rendering, or MCP write claim that lacks current official or live runtime evidence.
- Old endpoint/model registry counts, Vertex region counts, warning-key counts, external import-source counts, and TTS platform counts from APK reverse engineering unless current official docs, MCP, or fresh APK evidence reconfirms them.
- Old Dev Kit results such as AR widget markers, regex JS markers, model probes, and "all verified" summaries from Tavo 0.81.3 or 0.90 runs unless retested against the current Android app.
- Any claim that UI/file import, card-embedded `character_book`, TavoJS `import`, and TavoJS `create/update` are the same data shape.

## Recyclable Material

- SillyTavern PNG embedding and extraction scripts.
- Worldbook to `character_book` conversion logic, subject to current import verification.
- Card craft heuristics about voice, scenario, examples, and conflict design.
- Prior lists of risky areas to retest: Advanced Rendering, TavoJS, EJS, regex replacement, plugin packaging, and import persistence.
- Historical Dev Kit testing philosophy: local type checks, JSON validation, Android UI import, screenshots, UI text, and reports can be reused as a validation design, not as current product proof.

## Current Warning Seeds

- Standard PNG card payloads are a file-sharing path; custom PNG chunks should not be described as auto-imported Tavo resources.
- Advanced Rendering success requires rendered evidence, not browser preview alone.
- Regex JS behavior must be split into import success, replacement success, and script execution success.
- MCP is excellent for schema/dry-run/import validation, but API key/base URL/provider configuration should be treated as UI-only unless current runtime tools expose it.

## Migration Rule

When a historical claim becomes current again, move it into the relevant topic reference with an evidence label and a validation path. Leave a note here that the old claim was retested rather than silently copied.
