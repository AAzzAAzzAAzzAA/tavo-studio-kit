# Characters, Cards, And Personas

This reference routes character-card, persona, PNG-card, and SillyTavern compatibility work.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/bots/`
- `https://docs.tavoai.dev/cn/guides/bots/create/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/aicharactercards/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/chubai/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/janitorai/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/pygmalion/`
- `https://docs.tavoai.dev/cn/guides/bots/cards/realmrisuai/`
- `https://docs.tavoai.dev/cn/guides/bots/support/`
- `https://docs.tavoai.dev/cn/guides/bots/support/aicharactercards/`
- `https://docs.tavoai.dev/cn/guides/bots/support/chubai/`
- `https://docs.tavoai.dev/cn/guides/bots/support/pygmalion/`
- `https://docs.tavoai.dev/cn/guides/bots/support/realmrisuai/`
- `https://docs.tavoai.dev/cn/guides/bots/persona/`
- create-field subpages under `guides/bots/create/`

## Official-Current Character Surface

Tavo official docs currently present character creation as a set of editable fields rather than a published import schema. Treat these field meanings as `official-current`, and treat file/schema shape as `needs-mcp` until validated through MCP or export samples.

| Field or page | Official-current role |
| --- | --- |
| Character description | Long-lived character description: body traits, background, concrete features, stable identity facts, and role-specific details. Official examples lean toward specific, sensory, behavior-shaping details. |
| First message | Opening message that teaches tone, pacing, action density, and scene rhythm. It can carry strong style anchoring. |
| Dialogue examples | Examples should be separated with `<START>` and use `{{char}}` / `{{user}}` style macro tokens. Docs say examples are inserted gradually when context space allows and are converted differently by completion vs chat-style APIs. |
| Main Prompt | Character-specific behavior instruction layer that can override or supplement the current preset Main Prompt. Docs show `{｛original}}` style preservation of the original prompt; confirm exact brace form in app before generating importable files. |
| Post-History Instructions | Continuity layer after chat history: relationship continuity, emotional progression, and "do not reset" style instructions. Also supports preserving original content. |
| Group chat greeting | Group-chat-only first message. It does not affect one-to-one chats. Multiple greetings can be separated with `<START>`, and the app can randomly select one. |
| Nickname | Group-chat-only familiar name or alias. It does not affect one-to-one chats and does not replace the character `name`; single-chat nickname behavior must be written into description or greeting text. |
| Source | Provenance field for author ID or original link. The original author can modify it; other users can append notes but cannot overwrite the author source inside Tavo. Files can still be damaged outside Tavo, and reinstalling or changing devices can lose edit/delete permission for this field. |
| Tags | Short comma-separated classification/search labels. Docs recommend tag-like keywords rather than paragraphs; tags are for humans and organization and do not affect chat content. |
| Creator notes | User/reader-facing author notes shown around the character listing. The character does not see them; do not put must-follow behavior only here. |
| Traits and scene | Character personality traits and situation/scene setting fields. Treat as official-current UI fields; exact schema names still need MCP/export proof. |
| Persona / user identity | Defines who `{{user}}` is, how `{{char}}` sees them, relationship, current state, and interaction tone. Multiple identities can be created, edited, deleted, and set as default in the app UI. |

Official docs and TavoJS together indicate these import/create surfaces:

- UI supports creating roles and importing character cards through URL/file paths documented in this reference.
- Official docs mention JSON and PNG image import; PNG without an embedded text payload can fail, so PNG roundtrip must be tested.
- TavoJS docs expose character CRUD/import. Current docs show `name` and `firstMes` as required for creating characters.
- TavoJS import accepts CC-style payloads, including structured `data` objects. Current docs mention handling of card-attached `character_book` and `extensions.regex_scripts`, but these must be validated through MCP dry-run or Android import before writing "it works" in delivery docs.
- TavoJS persona CRUD exposes persona objects with required `name` and `description`; docs also mention optional avatar, active/default behavior, and sort order. UI binding/export behavior remains `needs-live-verify`.

## Official-Current Import Sources

Tavo docs expose two broad import paths:

- URL import for shared characters. Use a single character-card URL; private, unauthorized, or inaccessible source pages may fail in the app and need live error capture before automation.
- Downloaded character-card file import. The current docs route this through downloaded card files; JSON and PNG are mentioned in the wider character import surface, but exact accepted extensions, picker behavior, and failure text must be validated.

The current complete crawl includes source-specific pages for:

- `aicharactercards.com`
- `chub.ai`
- `janitorai.com` for URL import only in the current docs crawl
- `pygmalion.chat`
- `realm.risuai.net`

The docs list file import pages for `aicharactercards.com`, `chub.ai`, `pygmalion.chat`, and `realm.risuai.net`. Do not infer JanitorAI file import from URL import without current docs or live import evidence. PNG image cards without an embedded text/card payload can fail; distinguish "image file exists" from "card data is embedded and extractable."

## Historical-Derived Creation Guidance

The old `tavo-studio` skill contains craft guidance that is compatible with the official field surface and can be reused as `creative-guidance`:

- Put stable, must-remember facts in description-style fields rather than only in creator notes or worldbooks.
- Use first message as a style anchor; it teaches response length, action/text balance, and speech rhythm more strongly than abstract style rules.
- Use dialogue examples to demonstrate voice and interaction patterns, not to dump encyclopedic lore.
- Keep persona short and relational: who the user is, why they are in the scene, what the relationship dynamic is, and the immediate tone.
- For vague user ideas, first identify the "引力核心": the specific tension, relationship dynamic, atmosphere, or gameplay loop that makes the user want to continue.
- Prevent service-NPC flattening: give the character boundaries, hesitations, misreadings, private motives, and relationship-specific reactions.
- Clean AI-cliche prose after generation; replace vague emotion words with concrete action, tone, and decision.
- Choose gameplay mode before overbuilding resources. A pure character may only need a card; RPG/growth/survival/farming/relationship systems often need worldbook, preset, variables/macros, regex, and possibly rendering.

For the full historical-derived creation workflow, read `references/13-creation-craft-workflows.md`.

## SillyTavern And PNG Utilities

The bundled helper scripts are reusable utility material:

- `scripts/embed_st_card_png.mjs`
- `scripts/extract_st_card_png.mjs`
- `scripts/worldbook_to_character_book.mjs`
- `scripts/png-card-lib.mjs`

Use them for ST-compatible PNG/card workflows, but keep these boundaries:

- `chara_card_v2` / CC-style JSON and PNG payload handling are file-format utilities.
- Tavo import behavior is a separate app/runtime question and must be validated with MCP dry-run or Android import.
- A `data.character_book` embedded in a card is plausible ST-compatible packaging, but whether Tavo preserves and activates it needs current import proof.
- Extra PNG chunks for regex/presets/plugins should be treated as packaging only, not as something Tavo automatically imports.

## Validation Targets

- Map all official create-field pages to a Tavo-native card schema through MCP or export samples.
- Verify persona create/bind/export/import behavior.
- Verify URL import and file import for each official-current source page.
- Verify JSON and PNG import, extraction, and re-export roundtrip.
- Verify whether embedded `character_book` survives import and how it appears in Tavo.
- Verify whether card-attached regex scripts import, prompt for confirmation, and bind to the expected chat/character context.
