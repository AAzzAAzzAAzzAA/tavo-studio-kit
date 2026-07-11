# Chat Workflows

This reference covers chat operation answers and workflow design.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/chat/`
- `https://docs.tavoai.dev/cn/guides/chat/start/`
- `https://docs.tavoai.dev/cn/guides/chat/chat-actions/`
- `https://docs.tavoai.dev/cn/guides/chat/advanced-settings/`
- `https://docs.tavoai.dev/cn/guides/chat/group-chat/`
- `https://docs.tavoai.dev/cn/guides/chat/history/`
- `https://docs.tavoai.dev/cn/guides/chat/import-export/`
- `https://docs.tavoai.dev/cn/guides/chat/translation/`
- `https://docs.tavoai.dev/cn/guides/others/quickly-group-chat/`
- `https://docs.tavoai.dev/cn/guides/others/customize-keyboard/`
- `https://docs.tavoai.dev/cn/qa/`

## Official-Current Chat Operations

| Feature | Official-current behavior |
| --- | --- |
| Start chat | Users can start from character/start-chat entry points. Exact UI paths should be visually verified before automation. |
| Filter chats by character | Chat list can be filtered by role/character to show only related histories. |
| Rename chat | Current chat title can be edited from the chat page title area. |
| Pin chat | A chat can be pinned from the chat-list item menu. |
| Statistics | Current chat stats include companionship duration, message counts, and total text volume. |
| Restart chat | Clears the current chat history and starts a new blank session with the same role/settings baseline; docs warn deletion is permanent. |
| Clone chat | Copies a chat and its history into a separate branch for experimentation. |
| Delete chat | Permanently deletes a chat and its messages after confirmation. |
| Character history | Character page can open historical chats for that character. |
| History import/export | Docs describe importing `.jsonl` chat records. Export formats are documented as `.txt` and `.json`; verify exact schema before generating files. |

## Official-Current Diagnostics And Session State

Current FAQ docs add these chat-level facts:

- Context logs can be enabled from chat settings and then opened from the chat side panel. They expose token consumption, worldbook/regex/preset match and trigger status, context construction, and model-call details.
- "Reroll" option history is session-scoped. During the current app launch, reroll history remains available across chat switching and message backtracking; after app restart, prior reroll alternatives are cleared and only the currently selected visible result remains.
- "Hide model chain of thought" is a display setting. It hides visible thinking text in chat bubbles, but docs say it does not change generation logic, generation time, or generation quality/effect.

## Advanced Chat Settings

The chat side panel exposes per-chat or current-conversation controls:

- switch API connection/model;
- enable or switch preset;
- enable or switch worldbook;
- enable or switch regex;
- enable long memory;
- configure translation from chat settings.

Treat these as official UI capabilities. Do not claim MCP can edit them until `references/11-mcp-runtime.md` or live tools prove the write path.

## Group Chat

Official-current group chat capabilities:

- start a group chat from the left menu `+`;
- select multiple characters;
- add members, remove members, and mute/unmute members in the group side panel;
- choose reply mode:
  - natural chat: mentioned character replies first; otherwise a random character may speak;
  - all reply: every character replies to each user message;
  - specified speaker: user must mention a character;
  - contextual speaker: Tavo asks a model to choose which character(s) should speak next.
- contextual speaker settings can use a dedicated API and a prompt that should keep `{{group}}` so the current group list is injected.
- quick group speech can be enabled in chat settings. In group chat, member avatar buttons appear near the input area; after typing content, tapping a character avatar can specify that character as the respondent without manually writing `@角色名`.

## Translation

Official-current translation workflow:

- enable message translation in chat settings;
- choose target language, with device language or manual language selection;
- optionally configure a dedicated translation API so translation traffic does not use the normal chat API;
- maintain `{{language}}` and `{{content}}` in the translation prompt unless intentionally changing the template;
- long-press a chat bubble and use the translate action.

## Historical-Derived Guidance

- Treat chat operations as high-risk if they delete, restart, or restore data. Use backup/export before destructive live tests.
- For group chat, always define the expected speaking policy in the preset or group prompt; otherwise multi-character chats often drift into either silence or all-speaker noise.
- For translation, separate "translate accurately" from "localize naturally"; both may need prompt wording and a dedicated model choice.
- For automation, active screen matters. MCP/runtime state may be unavailable outside the relevant chat page.
- When importing histories, official docs mention matching by same character name and manual selection when no same-name character exists. Treat matching behavior as `needs-live-verify` before bulk import.

## Validation Targets

- JSONL chat import/export schema.
- Which advanced settings are exposed through MCP vs UI-only.
- Group reply-mode behavior under mention/no-mention cases.
- Contextual speaker prompt behavior and dedicated API selection.
- Translation prompt customization and result placement.
