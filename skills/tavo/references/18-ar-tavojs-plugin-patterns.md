# Advanced Rendering, TavoJS, And Plugin Patterns

This file records implementation patterns for UI-like behavior in Tavo. Treat each pattern as evidence-bounded: official prose and old skill examples are not enough for final product claims.

Current declaration snapshot: `assets/official-docs/text-20260716/` and Tavo `0.92.0` runtime docs in `assets/schemas/mcp-surface-0.92.0-20260716.json`. Current plugin/runtime behavior is summarized atomically in `assets/evidence/0.92.0/20260717-live-matrix.json`; retained AR panel proofs remain 0.91 unless explicitly labeled otherwise.

## Rendering Model

Tavo Advanced Rendering should be treated as HTML/CSS/JS rendered inside an app-controlled WebView/chat surface, not as a normal browser page. Browser APIs, inline event handlers, CSS positioning, sanitization, script lifecycle, storage, and app bridges must be verified in Tavo itself.

## Safer Interactive Button Pattern

Preferred shape for clickable rendered controls:

```html
<div class="tavo-card-actions" data-tavo-widget="example">
  <button type="button" data-action="append" data-text="继续调查线索">继续调查线索</button>
  <button type="button" data-action="append" data-text="查看角色状态">查看角色状态</button>
</div>
<script>
(() => {
  const root = document.currentScript.closest('[data-tavo-widget="example"]') || document;
  root.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action="append"]');
    if (!button) return;
    const text = button.getAttribute('data-text') || '';
    if (window.tavo && window.tavo.input && typeof window.tavo.input.append === 'function') {
      await window.tavo.input.append(text);
    }
  });
})();
</script>
```

Evidence boundary: the delegated `data-*` pattern plus `tavo.input.set/append` and chat-scope `tavo.set/get` is live-verified on Tavo 0.91 in the v23 rendered message panel. The exact snippet above is still a template, so validate changed mount points, selectors, and API calls rather than treating one successful panel as universal browser compatibility.

## Floating Or Overlay UI

For "floating button in a dialogue box" questions, distinguish four targets:

- inside one rendered message bubble;
- visually overlaying the chat viewport;
- plugin-provided chat action in the native input `+` menu;
- persistent app-level floating action outside Tavo's chat WebView.

Likely routes:

- message-bubble floating: Advanced Rendering with CSS `position:absolute` inside a bounded container;
- viewport overlay: Advanced Rendering may be constrained by WebView/message clipping, needs screenshot proof;
- native input `+` menu action: plugin route is live-verified on Tavo 0.91 for filling/appending input text; 0.92 retest remains pending;
- app-level persistent floating control: no current evidence; answer as unsupported or unverified unless a future Tavo plugin API exposes it.

Minimum proof:

- render marker visible in screenshot;
- click changes input text or visible state;
- UI remains usable after scroll/chat switch;
- retained evidence records the test card/chat/plugin and final readback state.

## TavoJS Boundary

Use `window.tavo` as the public scripting boundary. Do not rely on internal bridges such as `window.tav` unless current official docs or runtime docs explicitly expose them.

Before claiming an API:

1. Check official JavaScript API docs.
2. Check current MCP `tavo://docs/tavojs` resource.
3. Search deprecated claims for older wrong APIs.
4. Run a minimal render case if behavior affects UI, input, variables, messages, or files.

`tavo.tts.play/stop` and the structured `tavo.input.send()` result are now current official/MCP declarations. Generation/input lifecycle Hooks are not ordinary message TavoJS: they belong to installed plugin `entry` scripts only.

## Plugin Package Boundary

Plugin proof must be staged:

1. validate manifest and package shape locally;
2. validate through MCP tool if exposed;
3. import/install a disposable package;
4. verify action/UI/setting registration;
5. trigger the action;
6. verify persistence, final readback, and retained evidence location.

Never treat "zip was created" or "manifest parsed" as plugin success.

For new packages, use root `manifest.json` plus `entry: "entry.js"`. Keep `scripts.actions` only as a legacy fixture. A hook-only plugin may have `entry` without UI contributions; a fragment/settings-only package can omit it when no plugin-level JavaScript runs.

Plugin entry/actions/fragments should use the unqualified lexical `tavo` binding:

```js
tavo.plugin.on('chat:opened', async (event) => {
  const enabled = tavo.plugin.config.get('enabled')
  if (enabled) await tavo.utils.toast(`chat=${event.chatId}`)
})
```

Do not rewrite this as `window.tavo`/`globalThis.tavo` for plugin scope. In contrast, ordinary rendered message TavoJS is a separate host; success in one host cannot substitute for the other.

## 0.92 Hook And TTS Pattern Boundary

- Chat/message notifications observe persistent state and cannot cancel chat/generation.
- `input:beforeSend` can rewrite/cancel UI, TavoJS, and MCP sends; `input:afterSend` only means accepted input.
- Generation prepare/success are serial fail-open interceptors; error/cancelled are terminal notifications; HTML fragments cannot register them.
- Plugin TTS must explicitly resolve one character/persona speaker and uses the shared current-chat queue.
- The 0.92 matrix promotes only bounded pieces: persistent-message ordering and handler isolation; three-source input rewrite/cancel/fail-open; generation prepare/success/terminal semantics; and configured character TTS integration. The chat alias, one generation source, persona TTS, and audible behavior remain mixed/blocked/manual.

## Pattern Status Table

| Pattern | Status | Proof path |
| --- | --- | --- |
| Plugin input `+` action plus `tavo.input.append` | `live-verified` on 0.91; 0.92 retest pending | `artifacts/tavo-validation/20260710-plugin-ui-action/` |
| Delegated `data-*` AR click handler plus `tavo.input.set/append` | `ui-pass` on 0.91; 0.92 retest pending | `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/` |
| Scoped responsive CSS panel with mobile one-column media query | `ui-pass` on 0.91; 0.92 retest pending | v23 per-case before/after screenshot, UI XML, and panel source |
| Root `entry.js`, legacy alias, and dual-entry precedence | `live-verified` on 0.92 | F01-F03 in `20260717-live-matrix.json` |
| Entry without UI contributions and plugin config reads | `live-verified` on 0.92 | F01/F04; notification reliability is separately mixed in F05 |
| Input lifecycle Hooks | `live-verified` on 0.92 within three-source/fault boundary | F06 |
| Generation lifecycle Hooks | `mixed` on 0.92 | F07/F08 pass atomically; F09 source matrix mixed |
| Plugin `tavo.tts.play/stop` | `mixed` on 0.92 | Configured character/queue integration passed; persona and audible semantics remain unproved |
| CSS floating inside a rendered message | `probable` | Needs `css-webview-layout` and `floating-button` cases |
| Plugin HTML fragment panel in chat WebView | `ui-tree-pass, visual-partial` | Fragment text seen in WebView UI tree; native plugin action screenshot does not prove fragment-button click or floating layout |
| App-level persistent floating control outside chat WebView | `unverified` | No current official/runtime evidence |
| Direct inline `onclick` | `unreliable-historical` | Use only if current test proves it |
| Internal `window.tav` calls | `deprecated-risk` | Avoid unless current docs/runtime expose it |
