# Media, Voice, And Image

This reference covers voice, TTS/STT-like flows, image providers, image generation, and image sending.

Current evidence snapshot: `assets/official-docs/text-20260716/`, `assets/schemas/mcp-surface-0.92.0-20260716.json`, and `assets/evidence/0.92.0/20260717-live-matrix.json`. Media evidence is deliberately split into provider-request integration, UI persistence, chat insertion, and human sensory judgment.

## Official Pages

- `https://docs.tavoai.dev/cn/guides/voice-connection/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/get-keys/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/get-keys/elevenlabs/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/get-keys/gemmini/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/get-keys/volink/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/voice-api-settings/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/voice-setting/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/voice-binding/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/tts-guide/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/tts-guide/google-tts/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/tts-guide/iflyrec-tts/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/image-api-settings/`
- `https://docs.tavoai.dev/cn/guides/voice-connection/image-setting/`
- `https://docs.tavoai.dev/cn/guides/others/image-sent/`

## Official-Current Voice Surface

The official docs include:

- voice API key acquisition pages for Volink, Gemini, and ElevenLabs;
- voice API settings;
- voice settings;
- character voice binding;
- local TTS service configuration;
- Google TTS guide;
- iFlyrec TTS guide.

Treat provider credential setup, provider status, and actual sample playback as separate validation layers. A configured key is not proof that a voice can be generated or played.

Official-current settings details to preserve:

- voice API setup creates a provider config, selects platform, fills API key, chooses a voice model, and saves;
- custom OpenAI-compatible TTS may require manually entering a model id or voice id;
- voice binding is under the voice settings area and binds a role/character to a configured voice;
- voice playback settings include automatic playback, narration handling, quote/code/tag handling, and background playback;
- voice playback regex can include or exclude matched content for speech output.

## Official-Current TavoJS TTS

The current TavoJS page and MCP runtime docs expose:

- `tavo.tts.play(text, options)` through an existing character/persona binding;
- `tavo.tts.stop()` for the current chat's shared playback and queue;
- exactly one `character` or `persona` selector in `voice` when called from plugin code;
- optional speaker inheritance for ordinary message TavoJS;
- `queue: false` and `applyPlaybackRules: false` defaults;
- boolean `play()` result, with `false` for empty text, missing targets, or unusable bindings;
- no direct `voiceId` or TTS endpoint-id option in the current public contract.

The 0.92 fake-gateway run observed authorized `/v1/audio/speech` JSON with `input`, `model`, and `voice`, then accepted configured character playback and two queued character calls. Missing voice and dual character+persona selection were rejected. Persona playback with a working binding was not retested. UI/gateway state cannot prove the selected voice sounded correct or that stop audibly cleared the queue; retain human listening for identity, quality, and stop semantics.

## ASR / Speech Input Boundary

The current 83-page official crawl contains no ASR, STT, speech-recognition, transcription, or microphone-input guide. The 0.92 MCP surface likewise contains no matching tool, resource, resource template, runtime-doc section, or schema.

This absence means only **not exposed through current official docs or MCP**. It does not prove that no native Android UI exists. Inspect the app UI, Android microphone permission flow, provider schema, and logs without a key first. If a provider key is required, the user must enter it directly on the phone; never pass it through chat, ADB, CLI, logs, screenshots, or the evidence registry.

The 0.92 Android UI exposed ASR provider configuration and microphone/nearby-device permission surfaces even though docs/MCP do not expose ASR. A deterministic OpenAI-compatible gateway received multipart WAV transcription requests with model and response-format metadata. Release-to-send, explicit Cancel, Fill input field, edit/clear, and bounded transport-unavailable recovery were observed. This is a `mixed` integration result: it does not establish official API status, real-provider compatibility, HTTP-500/malformed-response handling, or human-spoken recognition accuracy. The last item remains manual.

## Official-Current Image Surface

The official docs include:

- image API settings;
- image generation settings;
- image sending.

Image sending docs say the feature lets the user send images to characters, and a multimodal model API must be selected for image understanding. The docs distinguish:

- enabling image sending;
- configuring an image-description API;
- using a model with image understanding;
- configuring description generation and injection prompts;
- sending images in chat.

Treat image-provider configuration, generated image creation, and chat attachment behavior as separate validation layers.

Official-current image-generation details:

- image API settings are separate from voice API settings;
- Volink has a one-click style configuration path in docs;
- users can generate from the chat input `+` menu or with `/imagine <prompt>`;
- preview supports editing prompt, regenerating, and downloading;
- image injection prompt defaults to a text marker that includes `{{prompt}}`.

The TavoJS image docs mention NovelAI/SD behavior for negative prompts and say the NovelAI protocol uses only the first reference image. On 0.92, a disposable fake-key NovelAI entry followed the force-save path after a network failure, reopened with its provider/model fields, and was deleted. This is UI lifecycle proof only; no real NovelAI request or credential was used.

The deterministic image gateway also received `/v1/images/generations` with `model`, `n`, and `prompt`; its transparent one-pixel result produced a tiny image message in the isolated chat. This proves request invocation and bounded insertion, not visual quality, prompt fidelity, or real-provider compatibility.

## Secret Handling

- Never store real API keys in this skill.
- Do not paste provider keys into reference files, prompt examples, logs, screenshots, or MCP dumps.
- Use minimal harmless prompts for provider tests.
- Record only provider name, model name, status, and non-secret error text.

## Historical-Derived Guidance

- Media features often fail at provider, model, permission, or prompt-injection layers separately; test each layer independently.
- For image sending, use a tiny harmless local image first before testing generation.
- For voice binding, verify both binding persistence and actual playback/generation.
- Keep media tests cheap and reversible.

## Remaining Validation Targets

- Persona TTS with a working binding plus human speaker, quality, and audible queue-stop confirmation.
- Voice playback selection rules are UI-verified for role-only/user-only save and reopen; future provider/audio tests must not treat that persistence proof as audible behavior.
- Voice provider settings with secret redaction.
- Character voice binding.
- TTS sample generation/playback.
- Human ASR accuracy plus controlled HTTP-500/malformed-response cases; preserve the existing native-UI/fake-gateway integration boundary.
- Image provider settings.
- Real NovelAI wire compatibility only when a revocable key is explicitly provided; current save/reopen/delete remains UI-only.
- Meaningful image preview/fidelity and real-provider generation; the one-pixel fixture proves only invocation/insertion.
- Image sending to chat and resulting prompt/context injection.
