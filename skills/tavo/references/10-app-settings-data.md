# App Settings And Data

This reference covers app-level settings, provider configuration, backup, storage, theme, and data management.

Current evidence snapshot: complete official crawl `assets/official-docs/text-20260716/`, Tavo `0.92.0` MCP surface `assets/schemas/mcp-surface-0.92.0-20260716.json`, and the atomic live summary `assets/evidence/0.92.0/20260717-live-matrix.json`.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/api-setting/`
- `https://docs.tavoai.dev/cn/guides/api-setting/api-setting-1/`
- `https://docs.tavoai.dev/cn/guides/api-setting/select-model/`
- provider key pages under `guides/api-setting/get-key/`
- `https://docs.tavoai.dev/cn/guides/theme/`
- `https://docs.tavoai.dev/cn/guides/others/backup/`
- `https://docs.tavoai.dev/cn/guides/others/storage-space/`
- `https://docs.tavoai.dev/cn/guides/others/customize-keyboard/`
- `https://docs.tavoai.dev/cn/guides/others/quickly-group-chat/`
- `https://docs.tavoai.dev/cn/privacy-policy/`

## Official-Current API And Model Surface

The current official docs include:

- general API setup;
- API settings;
- model selection;
- provider key pages for OpenAI, Claude, Gemini, DeepSeek, OpenRouter, Doubao/Volcano/ByteDance, Volink, and custom OpenAI-compatible protocol;
- common API error troubleshooting.

Treat UI configuration as official. Treat programmatic editing of provider connections as `needs-mcp` or UI-only until current runtime tools prove otherwise.

Official-current configuration notes:

- novice flow can use one-click provider setup where offered;
- manual flow creates an API connection, selects platform/model, fills provider config, and saves;
- custom OpenAI-compatible endpoints may need `/v1` as base URL, but should not be filled down to `/chat/completions`;
- compatibility is not guaranteed for every third-party endpoint;
- prompt-format converters include options for merging adjacent same-role messages and handling providers that restrict system/user message shape;
- global model settings include context memory length, reply token limit, temperature, Top-P, Top-K, and streaming;
- API-connection-level parameters usually override global model settings.

## Local Data And Privacy Boundary

Official-current privacy docs describe Tavo as using local-first storage for:

- chat history;
- personalized settings and preferences;
- API key information;
- user-created character data;
- other app-related configuration.

The same docs say chat content and API keys are transmitted to third-party AI providers only when the user uses those provider services, through HTTPS, and then fall under the provider's own terms and privacy policy. For skill answers, this means "stored locally by Tavo" is official-current, while "never leaves the device" is too broad once a provider call is made.

## Theme

Official-current theme docs say users can open theme management from the left side menu and:

- apply an official default theme or a self-made theme;
- copy an official theme as a template and modify the copy;
- customize chat background, status bar, message bubble style, font, character avatar display, and functional elements such as inner-monologue hint style.

Treat theme editing as a real app capability. Treat theme export/import format, CSS-like expressiveness, and MCP visibility as `needs-live-verify`.

The current official theme page does not enumerate the newly announced font styles, left/right bubble layout controls, or visual-novel percentage controls. The 0.92 MCP surface also exposes no theme tool/schema. The 0.92 UI matrix nevertheless saved/reopened bold+italic text, role/user bubble sides, and a 70% visual-novel setting; retained 30% and 70% previews visibly differed, and the original theme was restored. Treat these as `ui-pass`, not official/MCP surface claims or theme-format proof.

## Backup And Restore

Official-current backup docs say Tavo can back up core data and restore from backup files. They also say backup may include API keys if selected.

Important boundaries:

- Backup files are sensitive because they can include API keys.
- Backups from a higher app version may not restore into lower versions.
- Before destructive testing, create a backup and record app version.
- Restore strategy, overwrite/merge behavior, and backup file schema need live verification before any automated restore work.

For the 0.92 plugin-restore case, use two distinct files:

- Backup A: full pre-test rollback before any write. Store in a permission-restricted directory and record only size/SHA-256 in ordinary evidence.
- Backup B: created after installing/enabling the unique backup fixture and saving its config marker; use it to test uninstall -> restore -> exact plugin/config/enabled/runtime-contribution readback.

Backup B restoration is a high-risk, late-stage case. Run only after lower-risk plugin tests pass. On any restore anomaly, stop writes and use Backup A for rollback. Neither backup contents nor provider secrets may be inspected, logged, committed, or embedded in the Skill.

The 0.92 Backup B case completed the native create -> uninstall fixture -> restore -> exact readback roundtrip. Plugin id/version, configuration marker, enabled state, and runtime contributions matched; the restored fixture was disabled only after the comparison passed. Tavo restarted during native restore, so PID continuity is not an acceptance condition for backup restoration. Backup contents were never inspected. This is a bounded `roundtrip-pass`, not a claim about cross-version downgrade restore or every data class.

## Storage Space

Official-current storage docs say the storage page shows used space and safe cleanup categories such as:

- cache, including TTS voice cache;
- logs, including context/load-balancer logs;
- role/character-related assets such as avatars and images.

Docs explicitly distinguish core "data" from cleanup categories; chat records, characters, worldbooks, and similar core data should not be assumed removable through storage cleanup.

## Shortcuts And Quick Group Speech

Official docs include custom shortcuts and quick group chat speech. These belong to app workflow configuration and should be summarized in later UI-focused expansion. Treat exact UI paths and exportability as `needs-live-verify`.

## 0.92 Announcement And Live Boundaries

- NovelAI provider form save/reopen/delete has bounded `ui-pass` evidence with a disposable fake key and force-save after network failure. It does not prove real NovelAI wire compatibility.
- Voice playback rules such as role-only/user-only have bounded save/reopen/delete/restoration `ui-pass` evidence. It does not prove audible filtering.
- iOS immersive-mode quick-scroll-to-top repair: `not-applicable` on the connected Android 16 device. Do not convert Android non-testing into a pass/fail statement about iOS.

## Historical-Derived Guidance

- API provider settings are high-secrecy; do not screenshot or persist full keys.
- Provider/model capability flags are not enough; image, reasoning, function, and structured-output support should be tested against the selected endpoint.
- Backup and restore tests should always record app version and rollback path.
- Storage cleanup is not a data reset tool.

## Verification Targets

- Current provider list and model fields.
- Custom OpenAI-protocol endpoint behavior.
- Backup artifact format and secret handling.
- Backup A rollback availability and Backup B plugin/config/enabled/contribution restoration in the isolated Android test state.
- New theme font, bubble-side, and visual-novel percentage UI at 30%/70%, followed by exact theme restoration.
- Disposable NovelAI form save/reopen/delete without a real key or provider call.
- Storage cleanup categories and preserved data.
- Shortcut export/import or MCP visibility.
