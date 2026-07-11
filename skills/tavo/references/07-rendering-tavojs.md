# Rendering And TavoJS

This reference covers Advanced Rendering, CSS/JS behavior, TavoJS, and Android visual verification.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/advanced-rendering/`
- `https://docs.tavoai.dev/cn/guides/javascript-api/`

Current evidence snapshot: `assets/official-docs/text-20260716/`, `assets/schemas/mcp-surface-0.92.0-20260716.json`, and the 0.92 atomic live summary `assets/evidence/0.92.0/20260717-live-matrix.json`. Retained AR panel examples below are still 0.91-only, while the structured input/TTS/plugin-lifecycle claims are promoted only where the 0.92 matrix names an exact passing assertion.

## Official-Current Advanced Rendering

Advanced Rendering allows chat pages to render standard HTML and CSS in message bubbles. The official page currently documents:

- settings path: left sidebar -> more -> settings -> Advanced Rendering;
- basic use: edit a chat bubble and paste HTML content;
- examples using colored inline text, bold text, and images;
- the general claim that HTML/CSS can support flexible page-like message beautification.

Boundary:

- The official page is short. It does not fully specify sanitizer behavior, JavaScript mode behavior, iframe details, CSS support matrix, persistence, or event timing.
- Treat complex UI, clickable controls, fixed positioning, z-index, injected scripts, and browser-like lifecycle as `needs-live-verify`.

## Official-Current TavoJS Surface

TavoJS API is official-current since v0.75.0 and is described as beta/continuously updated. Current fetched docs expose these broad namespaces and functions:

- Variables: `tavo.get`, `tavo.set`, `tavo.update`, `tavo.unset`.
- Messages: `tavo.message.find`, `tavo.message.get`, `tavo.message.current`, `tavo.message.update`, `tavo.message.count`, `tavo.message.append`, `tavo.message.delete`.
- Chat: `tavo.chat.current`, `tavo.chat.update`.
- Characters: `tavo.character.all`, `tavo.character.get`, `tavo.character.find`, `tavo.character.create`, `tavo.character.update`, `tavo.character.import`, `tavo.character.delete`.
- Personas: `tavo.persona.all`, `tavo.persona.get`, `tavo.persona.find`, `tavo.persona.create`, `tavo.persona.update`, `tavo.persona.delete`.
- Presets: `tavo.preset.all`, `tavo.preset.get`, `tavo.preset.find`, `tavo.preset.import`, `tavo.preset.create`, `tavo.preset.update`, `tavo.preset.delete`.
- Lorebooks: `tavo.lorebook.all`, `tavo.lorebook.get`, `tavo.lorebook.find`, `tavo.lorebook.import`, `tavo.lorebook.create`, `tavo.lorebook.update`, `tavo.lorebook.delete`.
- Regexes: `tavo.regex.all`, `tavo.regex.get`, `tavo.regex.find`, `tavo.regex.import`, `tavo.regex.create`, `tavo.regex.update`, `tavo.regex.delete`.
- Memory: `tavo.memory.current`, `tavo.memory.update`.
- Generation and images: `tavo.generate`, `tavo.image.generate`.
- TTS: `tavo.tts.play`, `tavo.tts.stop`.
- Files: `tavo.file.save`, `tavo.file.load`, `tavo.file.url`, `tavo.file.delete`, `tavo.file.exists`.
- Input box: `tavo.input.get`, `tavo.input.set`, `tavo.input.append`, `tavo.input.clear`, `tavo.input.send`.
- Utilities/app: `tavo.utils.export`, `tavo.utils.preview`, `tavo.utils.toast`, `tavo.utils.openUrl`, `tavo.utils.select`, `tavo.app.version`, `tavo.app.versionNumber`.

The official docs also show older compatibility surface naming such as `tavo.v1.get`. Prefer current documented `tavo.*` APIs for new code unless a compatibility task explicitly requires otherwise.

### Current TTS And Input Contracts

- `tavo.tts.play(text, options)` uses an existing character/persona TTS binding. In plugin contexts `voice` is required and must select exactly one `character` or `persona` id/object. Ordinary message TavoJS may omit it and inherit the host message speaker.
- `queue` and `applyPlaybackRules` default to `false`; `play()` returns `true` when playback starts or queues, and `false` for empty text, missing targets, or unusable bindings.
- `tavo.tts.stop()` stops the current chat's shared TTS playback and clears the queue. Current docs do not expose direct `voiceId` or endpoint-id playback.
- `await tavo.input.send()` resolves after Tavo accepts or rejects the current input, not after model/image completion. Success is `{ok: true, text}`; failure is `{ok: false, reason, text}` with `reason` in `cancelled`, `busy`, or `rejected`, and plugin cancellation may add `cancelledBy` and `message`.

The 0.92 live matrix observed the structured `send()` success/failure shape, acceptance-time resolution, and input interception from UI, TavoJS, and MCP sources. It did not observe the `busy` reason or attachment preservation metadata. Configured character TTS and two queued calls were accepted by a deterministic OpenAI-compatible gateway, but persona playback, audible identity/quality, and audible queue clearing remain blocked or manual.

### Plugin Lifecycle Boundary

`generation:prepare/success/error/cancelled` and `input:beforeSend/afterSend` are not pure message/character TavoJS events. Only an installed plugin `entry` script can register them with `tavo.plugin.on(...)`; HTML fragments cannot register generation lifecycle Hooks. See `references/08-plugins-tpg.md`.

## Programming Boundaries

- Treat most non-variable operations as async unless the current docs show otherwise.
- Variable scopes include chat-default, global, and message-level use cases in current docs; scopes are separate and should not be treated as overriding each other.
- Do not call undocumented `window.tav` internals in generated user code. If old references mention internals, use them only to understand behavior.
- Do not assume TavoJS can configure API providers, TTS endpoints, backup/restore, or storage cleanup. Current official TavoJS surface is broad but still scoped to exposed script objects.
- Confirm import/create/update object schemas through MCP or live exports before generating files meant for direct import.
- Treat `tavo.update` as current official API, but do not reuse old callback/updater patterns unless current docs show that exact signature.

## Official-Current Runtime Details To Preserve

- `tavo.generate(prompt, options)` returns a complete text result rather than a stream, uses the current chat-bound API connection, and can fail when no usable API is configured. Do not confuse that API binding with conversation context: official-current docs define `context` as `false` by default; only `context: true` includes the current conversation state.
- Treat `preset` and `settings` as optional per-call overrides. When the goal is to preserve the user's active chat configuration, pass only the options that are required and do not inject a preset, token cap, temperature, or other model setting unintentionally.
- `tavo.image.generate(prompt, options)` returns a data URL or a saved virtual path when `saveAs` is used. Current docs list options such as size, aspect ratio, negative prompt, reference images, extra request body, save target, and scope. It does not imply prompt expansion or a confirmation dialog.
- File APIs operate on Tavo virtual files. Current docs warn against unsafe filenames such as slash, backslash, colon, or path traversal. Chat-scoped files follow chat lifecycle; global files should be cleaned manually.
- Input APIs can get, set, append, clear, and send the chat input content.
- Utility APIs include toast, URL opening, export, preview, selection UI, and compatibility slash-command triggering.
- Chat update can change title, character list, persona, and conversation-level background. Background precedence and exact visual result need live verification.

## Android WebView Native-Method Receiver

`live-verified-regression` on Android with Tavo `0.91.0`: saving a bare WebView-native `window.fetch` function and later invoking it with a different receiver can throw `Failed to execute 'fetch' on 'Window': Illegal invocation`.

- Preserve the receiver when storing or injecting WebIDL/native browser methods; for fetch, use a bound function such as `globalThis.fetch.bind(globalThis)`.
- Do not treat a Node or jsdom mock that accepts any receiver as Android proof. Add a receiver/brand-checking regression test and retain a real-WebView verification step.
- Keep this claim version- and host-scoped. It is a concrete Android WebView rule, not proof that every browser API or every Tavo version has the same failure.

## Historical-Derived Rendering Guidance

Reusable warnings from old `tavo-studio`:

- Tavo message rendering is not a normal full-page browser environment.
- Regex outputting `<script>` is not proof that script executed; execution depends on Advanced Rendering and JavaScript settings.
- A visual marker, toast, variable change, appended message, or MCP/app-state readback is required before claiming JS behavior works.
- For card UX, use static HTML/CSS first; add JS only when a specific interaction needs it and can be validated.

## Capability Inference Example

For a question like "can I float a button inside a dialogue box?":

1. If the button is inside an Advanced Rendering message or plugin HTML fragment, it is plausibly possible but needs Android visual verification.
2. If the button must float over native app chrome outside the message/plugin surface, current docs do not prove support.
3. If click behavior must call app state, check whether TavoJS or plugin actions expose the needed operation.
4. Put the experiment in `references/12-validation-matrix.md` with screenshots and rollback.

## Verification Axes

- CSS position behavior: fixed, sticky, absolute, overflow, z-index.
- JS execution timing: load, rerender, message update, chat navigation.
- TavoJS calls: namespace availability, async behavior, error shape, permission boundary.
- Sanitization: stripped tags, blocked attributes, URL schemes, iframe behavior.
- Persistence: rerender, chat switch, app restart, export/import.

## Live-Verified Rendering Settings Baseline

`live-verified` on 2026-07-10, Tavo `0.91.0`, artifact `artifacts/tavo-validation/20260710-plugin-ui-action/`:

- A plugin input action that contributed an HTML fragment refused to run until Advanced Rendering was enabled.
- The Advanced Rendering settings screen exposed a main `高级渲染` switch and showed `JavaScript 支持` as a separate setting.
- Enabling Advanced Rendering changed the chat content area into an `android.webkit.WebView` in UIAutomator output.
- Setting JavaScript support to `自动` opened a risk warning that required explicit acknowledgment.
- After Advanced Rendering and JavaScript auto mode were enabled, the plugin action handler appended text into the input box and MCP read it back.

Implications:

- Do not treat AR as just a visual toggle; it changes the UI/runtime surface.
- When planning AR/TavoJS tests, include the AR switch, JS mode, and warning-confirmation state in the artifact.
- UIAutomator can still expose some WebView text, but screenshots remain required for layout and visual proof.

## Live-Verified Responsive CSS And TavoJS Panel

`ui-pass` on 2026-07-10, Tavo `0.91.0`, retained artifact `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/`:

- A real message bubble rendered a styled panel with scoped `<style>`, bounded width, padding, border, background, typography, grid actions, focus styling, status text, and a mobile media query.
- On the `1200x2670` Android device, the media query produced one full-width button per row with no visible horizontal overflow; heading, marker, five controls, and status text remained readable in the screenshot.
- Delegated `data-action` click handling executed inside the rendered message. The clicked button changed visible status to `state=clicked` and called chat-scope `tavo.set/get` plus `tavo.input.set` or `append`.
- The same unique marker appeared in the panel, composer screenshot/UI XML, and MCP `tavo_input_get` readback. Five panel actions then fed five normal model exchanges in the terminal semantic run.

Use this as the proven baseline for card-local responsive panels. It proves scoped CSS, a one-column mobile layout, delegated click handling, chat-scope variable read/write, and composer mutation in one WebView/runtime version. It does not prove `position: fixed`, `sticky`, cross-bubble overlays, iframe/URL sanitization, arbitrary browser APIs, desktop layout, restart persistence, or controls outside the chat WebView.
