# Authoring Blueprints

This file turns Tavo creation work into repeatable production workflows. Use it with the topic references and validators instead of writing cards, prompts, regexes, or plugins freehand.

## Universal Creation Loop

1. Intake: identify target object, import path, runtime target, model, language, and validation depth.
2. Select template from `assets/templates/`.
3. Draft artifact with clear names using `Codex` only for test assets, not user deliverables.
4. Run local validation.
5. Run MCP dry-run when available.
6. Run actual disposable import when the user wants proof or when the format is uncertain.
7. Read back/export and compare.
8. Capture screenshot only for visual behavior.
9. Clean up disposable objects or register leftovers.

## Choose The Smallest Correct Mechanism

| Need | Start with | Move up only when |
| --- | --- | --- |
| Stable identity, voice, scenario, greeting | Character card | facts are conditional, behavior is dynamic, or UI is required |
| Conditional facts and setting recall | Worldbook | stateful logic or reusable app behavior is required |
| Global response policy and prompt ordering | Preset | the rule belongs to one card or needs runtime state |
| Simple dynamic prompt values | Macros | branching, loops, defaults, or calculations become awkward |
| Prompt-time branching and variable math | EJS | the task needs DOM, composer, messages, files, or asset CRUD |
| Bounded text transformation | Regex | the task is actually stateful or interactive |
| Visible UI inside a rendered message | Advanced Rendering plus TavoJS | behavior must be reusable across cards/chats or contribute native actions |
| Reusable native actions, settings, or HTML fragments | TPG plugin | an external agent, batch import, or out-of-app automation is the real requirement |
| External inspection/import/automation | MCP | the behavior must execute inside the chat WebView or plugin host |

Do not solve a prompt problem with a plugin merely because JavaScript is available. Do not solve an app-operation problem with EJS merely because EJS can mutate chat/global variables.

## Deliverable Contract

For every generated object, return or retain:

- the importable source file, not only prose or a code excerpt;
- a short field/dependency manifest;
- local validation output;
- exact import order when multiple objects are involved;
- evidence label for each product claim;
- runtime test steps and expected markers;
- known unsupported or unverified edges;
- readback/export diff when Tavo can normalize fields.

Do not hide an unverified assumption inside an otherwise valid artifact. Put it in the manifest as a named validation case.

## Character Cards

Use character cards for identity, speaking style, durable role rules, first message, scenario, and embedded character book when the card needs portable lore.

Do:

- keep identity and voice stable;
- separate public-facing greeting from hidden control instructions;
- put reusable lore in `character_book` or external worldbook;
- include testable opening messages;
- keep ST/CCv2 compatibility when the target is portable PNG/JSON.

Avoid:

- putting large world rules in a single description field;
- treating old hard lints as product requirements;
- claiming Tavo-native field preservation without import/readback evidence.

Production sequence:

1. Write the attraction core, relationship, agency, boundaries, and speaking style in plain language.
2. Place stable identity in description/personality, current pressure in scenario, voice demonstration in `first_mes`, and interaction examples in `mes_example`.
3. Extract conditional setting facts into a worldbook instead of duplicating them across fields.
4. Add alternate greetings only when they represent genuinely different starting states.
5. Validate JSON/PNG locally, dry-run import, actual import, stable-id readback/export, greeting selection, and one normal model exchange when delivery must be phone-proven.

Read `references/03-characters-cards-personas.md` and `references/24-character-opening-and-examples.md` for exact current fields, alternate greeting behavior, dialogue examples, and CCv2/CCv3/PNG boundaries.

## Worldbooks

Use worldbooks for conditional facts, setting rules, scene state, terminology, safety rails, and mode-specific injections.

Validation must include:

- trigger case;
- non-trigger case;
- priority/order case when multiple entries compete;
- readback after import because Tavo may normalize fields.

Author each entry as an independently useful prompt fragment:

- `comment` is for the author; `content` must still make sense without it;
- choose constant versus keyword activation explicitly;
- record primary keys, secondary keys, secondary logic, case sensitivity, whole-word behavior, scan depth, insertion position/role/depth, priority/order, probability, sticky/cooldown/delay, and enabled state;
- use unique test markers that never appear in the user prompt or unrelated entries;
- pair every positive with a non-trigger control when activation is the claim.

Do not infer native semantics from SillyTavern field names alone. Use `references/21-worldbook-entry-semantics.md` for the native/compatibility mapping and current mixed keyword evidence.

## Presets

Use presets for model behavior, prompt order, global response style, roleplay constraints, and generation controls.

Validation should check:

- prompt item order;
- enabled/disabled flags;
- model/provider assumptions;
- whether macros/EJS expand in the target fields;
- behavior probe in a disposable chat when exact prompt assembly is not exposed.

Treat prompt items as an ordered program. For every item, document whether it is relative or absolute, its role, enabled state, order, depth, source field, and intended neighboring item. Test one isolated marker before stacking multiple entries. Marker visibility proves context presence; exact adjacency/role/order needs runtime prompt inspection or a capture gateway.

Use `references/22-preset-prompt-injection.md` for the current native item model and evidence boundaries.

## Regex

Use regex for bounded transformation, cleanup, routing markers, or UI-triggered affordances. Keep each rule narrow and fixture-backed.

Validation should include:

- input that should match;
- input that must not match;
- markdown/code-block safety case;
- Chinese and punctuation case when relevant;
- live scoped test if the rule affects chat output.

Each regex deliverable should include:

- raw pattern and flags;
- replacement string with capture-group notation explained;
- placement/scope and timing;
- min/max depth and disabled state;
- fixtures for match, non-match, multiple matches, Unicode/punctuation, Markdown, fenced code, and replacement literals;
- whether display text, sent text, or persisted message content is expected to change.

Never claim a regex changed a worldbook asset merely because its transformed text affected a later trigger. Asset mutation requires an explicit TavoJS/plugin/MCP write plus stable-id readback. Use `references/23-regex-execution-pipeline.md` for the full pipeline.

## EJS And Macros

Use EJS/macros when dynamic prompt text is easier and safer than a plugin. Keep output plain text unless a rendering pipeline explicitly expects HTML.

Validation should include:

- missing variable behavior;
- escaping behavior;
- loops/conditionals;
- target-context expansion: card, preset, worldbook, regex, or rendering.

Before writing EJS, define:

1. host field and when that field enters prompt assembly;
2. input constants and variable scope (`chat` or `global`);
3. variable namespace, defaults, mutations, and ownership;
4. exact plain-text output contract;
5. whether EJS intentionally emits `{{...}}` for the second macro pass;
6. escaping boundary if output enters JSON, regex, HTML, or JavaScript;
7. malformed-template fallback and a visible failure marker.

Prefer one statement or output concern per tag while debugging. Use `<%- ... %>` or `<%= ... %>` only according to the current Tavo EJS docs; do not import Node EJS include/partial/custom-delimiter assumptions. A good test has a runtime-only token, a default, a branch, a short loop, a side-effect counter, forbidden raw tags, and a persistent model reply. Use the capture gateway only when final wire role/order or raw-tag absence is the unresolved question.

## Advanced Rendering And TavoJS

Use Advanced Rendering for visible chat-bubble UI and TavoJS for supported app interactions from that rendered context.

Validation must prove:

- HTML/CSS renders as intended;
- JS runs in the target context;
- click handlers work;
- state read/write or input append happens when claimed;
- layout survives Android viewport and scrolling.

Prefer data attributes plus delegated event listeners. Treat inline `onclick` and full-browser assumptions as unverified unless a current artifact proves them.

Build order:

1. Create one scoped root with a unique `data-*` identity.
2. Put CSS under that root; define width, overflow wrapping, stable control dimensions, mobile tracks, and visible focus.
3. Render a static marker before adding JavaScript.
4. Add one delegated handler and one visible status node.
5. Call only current documented `tavo.*` APIs and handle async errors visibly.
6. Make the action produce two proofs: visible state plus app-state readback such as composer text, variable value, or stable message id.
7. Capture screenshot and UI XML at the real Android viewport; add scroll, rerender, switch, or restart cases only if the feature promises them.

The live baseline proves a responsive one-column mobile panel, delegated clicks, chat-scope `tavo.set/get`, and `tavo.input.set/append`. It does not prove `fixed`, `sticky`, cross-bubble overlays, iframe/sanitizer behavior, or native-app overlays. Read `references/07-rendering-tavojs.md`, `references/18-ar-tavojs-plugin-patterns.md`, and `references/25-ejs-tavojs-plugin-boundaries.md` before promising those edges.

## Plugins

Use plugins when the feature should be app-level, reusable, configurable, or available outside one card/chat bubble.

Validation must separate:

- package shape valid;
- manifest accepted;
- import/install accepted;
- action/UI registered;
- permissions behave as claimed;
- settings persist across reload if persistence is part of the feature.

Production sequence:

1. Choose a stable lowercase plugin id and version.
2. Declare only needed permissions; permissions describe intent and do not prove a hard sandbox.
3. Put `manifest.json` at package root and use package-local `/` paths.
4. Declare `inputActions`, `sidebar`, `htmlFragments`, and settings separately. If native actions exist, point `scripts.actions` at a real registration file.
5. Register each declared action id exactly once in `actions.js`; keep handler failures visible through toast, status, or returned markers.
6. Scope fragment HTML/CSS/JS to its mount. Remember that `/messages` fragments can have current-message context while `/chat` actions/fragments may not.
7. Run `scripts/validate_tpg_package.py`, MCP manifest validation, package dry-run, install dry-run, actual install, plugin readback, and runtime-contribution readback.
8. Open the real UI, trigger the native action or fragment control, handle observed confirmations, and verify the exact side effect by stable id or MCP readback.

Registration is not execution; UI text is not a successful data mutation; a native input action is not proof that an HTML fragment button works. Preserve these as three separate verdicts.

## Multi-Object Packages

For large creative projects, deliver a manifest that names each object and dependency:

- character card;
- persona;
- preset;
- worldbook;
- regex;
- plugin;
- media;
- validation steps;
- import order;
- rollback/cleanup steps.

The import order should minimize broken references: media first if required, then plugin/settings, then presets/worldbooks/regexes, then characters/chats, then bindings/switches.
