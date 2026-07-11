# Macros And EJS

This reference routes macro and EJS work.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/supported-macros/`
- `https://docs.tavoai.dev/cn/guides/ejs-template/`

## Official-Current Macro Model

Official docs describe macros as dynamic macro tokens that can be used in:

- character definitions;
- presets;
- worldbooks;
- regexes;
- other generation-prompt positions.

Basic syntax:

- `{{macroName}}`
- `{{macroName::arg}}`
- escaped braces when literal braces are desired;
- comment-style macro that renders empty.

Important boundary: macro support in prompt fields does not mean macros execute in every HTML display surface, PNG metadata field, plugin file, or app setting. Treat macro execution as tied to the generation/prompt/regex pipeline unless live evidence says otherwise.

## Macro Families From Official Docs

The official macro page includes these families:

- role/group macros such as user, character, group, and muted/non-muted group variants;
- character-card macros for description, personality, scenario, persona, prompts, examples, version, and creator notes;
- message macros such as last message, current input, and last user message;
- date and time macros;
- random and formatting helper macros;
- chat variable macros such as set/add/increment/decrement/get-style operations;
- global variable macros with matching global-state variants;
- legacy macros kept for compatibility;
- usage examples where worldbooks initialize variables and regex displays status values.

Do not teach an exact macro as current until checked against the fetched official macro text or live MCP docs; the macro list is marked as continually updating.

## Official-Current EJS Model

EJS templates are official-current since v0.87.0. Docs say EJS can be embedded in generation prompt fields including:

- character card fields such as description, personality, scenario, and opening messages;
- presets;
- worldbooks;
- regexes.

EJS is for logic that macros cannot comfortably express:

- conditionals;
- loops;
- variable math/read/write;
- producing macro text that the macro engine later consumes.

Official render order: EJS renders first, then the result goes to the `{{}}` macro engine. This means EJS output can intentionally produce macros for the next step.

Official limitations:

- Tavo uses a common EJS subset;
- include, partial, and custom delimiter features are not part of the documented supported set;
- EJS is enabled by default, with a compatibility setting if it does not work.

Current docs also describe:

- variable helper functions such as `getvar`, `setvar`, `incvar`, `decvar`, and `delvar`;
- default `chat` scope and persistent `global` scope, with compatibility notes for message/initial/cache-style scopes;
- built-in constants such as `charName`, `userName`, `lastUserMessage`, `lastCharMessage`, and `characterId`;
- error behavior where a bad EJS tag can make the whole field fall back to the original unrendered text.

For debugging, keep risky EJS tags isolated while testing so one broken tag does not obscure all output in the same field.

## Live-Verified Final Request Assembly

`live-verified` on 2026-07-11, Tavo `0.91.0`, retained artifact `artifacts/tavo-validation/20260711-ejs-request-capture-v1/` and gateway request `2b937cc103c34a13`:

- A previously semantic-passed EJS character chat was sent through Tavo's normal input flow to a credential-redacting OpenAI-compatible capture relay.
- The final request contained four messages in exact wire order: `system`, prior `user`, prior `assistant`, current `user`.
- The `system` message contained rendered `setvar/getvar/default`, conditional `ALPHA`, loop result `1,2,3`, increment result, and an externally seeded chat-scope value.
- The source expression that emitted `{{char}}|{{user}}` reached the final request as the actual character and persona names. This directly confirms EJS-first, macro-second ordering for this character description path.
- Across the final `messages` array, raw `<%`, `{{char}}`, and `{{user}}` each had zero occurrences. The current user marker occurred once, and the model completed the streaming request with persistent assistant reply `ACK`.
- The request used `deepseek-v4-pro`, `stream: true`, and the standard OpenAI-compatible `messages` body. The exact provider/model is transport evidence, not a requirement for EJS itself.

This proves final request assembly for the tested character-description path. It does not automatically prove identical placement for every preset, worldbook, regex, greeting, or Advanced Rendering field; use the field-specific evidence matrix before generalizing.

When debugging prompt assembly, inspect the captured `messages` rather than asking the model to describe its prompt. A model reply can prove semantic visibility, but only a capture relay can prove final role/order and raw-tag absence.

## Authoring Rules

- Keep templates readable before making them clever.
- Test one variable family at a time.
- Escape user-generated text before mixing it into HTML, JS, regex, or JSON.
- Prefer explicit fallbacks for optional fields.
- Record exact runtime evidence before teaching a macro as universal.

## Historical-Derived Guidance

- For RPG/status systems, use EJS for branching and macros for compact state operations when possible.
- Prefer macro names and variable keys that are short, stable, and documented in the card/worldbook notes.
- When using regex to display status, separate "display value" from "state mutation"; displaying `{{getvar::hp}}` is not the same as updating `hp`.
- When EJS emits HTML that later reaches Advanced Rendering, validate escaping and render behavior on Android.

## Validation Targets

- Macro expansion in card, preset, worldbook, regex, rendering-adjacent text, and plugin contexts.
- Missing variable behavior.
- EJS conditionals and loops.
- EJS variable mutation and macro emission.
- EJS output fed into Advanced Rendering.
