# Prompt Authoring

This reference covers presets, worldbooks, regexes, long memory, and prompt architecture.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/preset/`
- `https://docs.tavoai.dev/cn/guides/lore-book/`
- `https://docs.tavoai.dev/cn/guides/regular/`
- `https://docs.tavoai.dev/cn/guides/long-memory/`
- `https://docs.tavoai.dev/cn/guides/supported-macros/`
- `https://docs.tavoai.dev/cn/guides/ejs-template/`

## Official-Current Prompt Layers

| Layer | What it controls | What it should not be treated as |
| --- | --- | --- |
| Preset | Reusable baseline configuration, role behavior, dialogue style, scenario framing, user relationship, group progression, continuation, and impersonation/help-answer prompts. | A concrete character biography or permanent lore database. |
| Worldbook | Background encyclopedia and story guide injected behind the scenes when triggers/budget/scanning allow. | A guarantee the model will never forget or obey a fact. |
| Regex | Text recognition, cleanup, replacement, formatting, and transformation across configured scopes/timings. | A state database or guaranteed JavaScript runner. |
| Long memory | Cross-session retention of user preferences, habits, relationship facts, and important details via manual or automatic extraction. | A deterministic database recall promise. |
| Macros | Dynamic macro tokens and variable operations inside role definitions, presets, worldbooks, regex, and other generation-prompt positions. | Universal execution in every display surface or file metadata field. |
| EJS | Logic layer for prompt fields: conditions, loops, variable operations, and macro-producing templates. | Full Node/browser EJS with include/partial/custom delimiters. |

## Presets

Official docs frame presets as reusable behavior and prompt structures. They can define:

- user identity relationship;
- character identity/background;
- personality traits;
- scenario;
- new example chat;
- new chat behavior;
- group chat progression;
- continuation behavior;
- impersonation/help-answer prompt behavior.

Current TavoJS docs expose a preset object shape with:

- `basicPrompts`;
- `entries`;
- entry-level fields such as identifier/name/content/enabled/active/type/role/injection position/injection depth.

Official-current built-in identifiers include:

- `main`
- `worldInfoBefore`
- `personaDescription`
- `charDescription`
- `charPersonality`
- `scenario`
- `enhanceDefinitions`
- `nsfw`
- `worldInfoAfter`
- `dialogueExamples`
- `chatHistory`
- `jailbreak`

Historical-derived guidance that is safe to reuse:

- Use presets for system-level behavior and output rules, not for every character-specific fact.
- Keep character identity facts in the card unless a preset is intentionally shared by a family of characters.
- Use presets to decide how card fields, persona, worldbook, and history are assembled into a generation request.

## Worldbooks

Official-current purpose:

- maintain world consistency;
- keep narrative focus;
- gradually reveal large settings through triggered entries.

Official examples emphasize trigger words and content entries. Current docs say worldbooks work behind the scenes; entries do not simply appear as user-visible messages.

Historical-derived guidance that is safe to reuse:

- Write entry `content` so it stands alone. Do not rely on title, key, or comment being injected.
- Use short, precise trigger terms plus common aliases.
- Split large lore into small entries by use case: location, faction, rule, secret, relationship, timeline, object.
- Worldbooks are best for stable objective facts and conditional background, not for current emotional state or output style.
- Competing entries, insertion order, recursion, and budget behavior need live validation before exact claims.

Current TavoJS docs expose worldbook fields including:

- `strategy`: `constant` or `keyword`;
- `keywords`;
- `secondaryKeywords`;
- `secondaryKeywordStrategy`;
- `scanDepth`;
- `caseSensitive`;
- `matchWholeWord`;
- `injectionPosition`;
- `injectionDepth`;
- `injectionRole`;
- `probability`;
- `sticky`;
- `cooldown`;
- `delay`.

Official/TavoJS docs also document compatibility mappings from CC-style fields such as keys, secondary keys, constant/selective flags, and insertion position. Use these as guidance only; exact import/export conversion should still be checked through current dry-run or exports.

## Regex

Official-current use cases:

- identify text patterns;
- modify or replace text;
- clean redundant characters or formatting;
- use built-in regex assistant templates for categories such as reasoning, quote, narration, markdown code block, and tag-style text;
- configure name, find regex, replacement, trim-out, scope, and execution timing.

Historical-derived guidance that is safe to reuse:

- Regex can produce text, macros, or HTML, but whether later systems execute those outputs depends on timing and downstream processing.
- Do not treat regex import object fields as identical to TavoJS regex object fields; file import format must be checked through current exports/import tools.
- Use regex for cleanup, shorthand expansion, status display formatting, and guarded transformations.
- Avoid destructive regexes unless the before/after behavior has test fixtures.

Current TavoJS docs expose regex object concepts including:

- placements such as user, character, reasoning, and lorebook contexts;
- timing such as display, send, send-and-display, receive, and edit-and-receive paths;
- substitution modes such as none/raw/escaped;
- optional depth ranges.

Official docs also describe regex assistant templates for reasoning, quote, narration, markdown code block, and tag-like text.

## Long Memory

Official-current behavior:

- long memory can preserve user preferences, interests, habits, and important details across future conversations;
- it has management controls so users can decide what is saved and when;
- docs describe manual extraction and automatic extraction after 10 conversation turns/messages as distinct mechanisms.

Boundaries:

- Do not promise every saved fact will always be recalled.
- Do not use long memory for static world rules that belong in card/worldbook.
- Treat extraction quality and injection timing as model/runtime-dependent until verified.

Current TavoJS docs describe current-chat memory as an enabled flag plus a list of memory strings. Treat automatic extraction, injection position, deletion/merge strategy, and cross-chat behavior as `needs-live-verify`.

## Authoring Standards

- Prefer small, inspectable prompt components over monolithic blocks.
- Make every worldbook entry answer why it exists, when it should fire, and what it must not override.
- Keep regexes reversible where possible; document destructive replacements.
- Separate style guidance from factual memory so future edits are safer.
- Add validation rows in `references/12-validation-matrix.md` for any prompt behavior that depends on exact insertion order or runtime variable expansion.
