# Creation Craft Workflows

This reference contains `historical-derived` and `creative-guidance` material migrated from the old `tavo-studio` skill. It is for writing better cards, worldbooks, regexes, and roleplay packages. It is not a product API reference.

## Evidence Label

Use these ideas as:

- `creative-guidance` when improving writing quality or workflow;
- `historical-derived` when the advice came from old Tavo Studio/ST practice and still needs current Tavo validation;
- `needs-live-verify` when the advice touches import schema, TavoJS behavior, Advanced Rendering, plugins, or Android UI persistence.

## From-Zero Card Ideation

When the user starts with a vague card idea, do not jump straight into JSON. First find the role's "引力核心": the specific thing that makes the user want to keep talking.

Common attraction cores:

- personality tension;
- relationship dynamic;
- atmosphere;
- gameplay loop;
- mystery or conflict;
- caretaking, rivalry, danger, apprenticeship, intimacy, betrayal, or recovery arc.

Ask one dimension at a time. Prefer short choices with an open escape hatch, then challenge contradictions instead of politely preserving everything.

## Field Placement

Use field lifecycle thinking:

- `description`: stable identity, background, body/visual traits, permanent behavior boundaries, world-linked facts.
- `personality`: compressed temperament and reaction patterns.
- `scenario`: current relationship/situation, location, immediate tension, starting condition.
- `first_mes`: style anchor; teaches pacing, action density, sentence shape, and opening energy.
- `mes_example`: voice and interaction examples, not a lore encyclopedia.
- `creator_notes`: metadata and author notes, not required prompt facts.
- persona/user identity: who `{{user}}` is, what they know, why they are here, and how the character sees them.
- worldbook: conditional background facts, not everyday style control.
- preset: system behavior and output rules, not a replacement for character identity.

## Living Character Depth

Avoid service-NPC flattening. A role should have motives, pressure points, and relationship-specific behavior.

Useful depth axes:

- fear: what the role avoids admitting or facing;
- old wound: what shaped their defense style;
- language habit: how they dodge, confess, joke, argue, or go silent;
- hidden side: what appears only under stress or trust;
- contradiction: the tension between public mask and private need;
- agency: what the character wants even when it conflicts with the user.

Pick the 2-3 axes that reinforce the attraction core. Do not fill every possible trauma slot by default.

## Worldbook Craft

Use worldbooks for stable facts and conditional context:

- places, factions, rules, secrets, history, NPCs, objects, systems;
- trigger terms and aliases that the user/model will naturally mention;
- compact `content` that stands alone if inserted without title/comment;
- layered reveal: public knowledge, private truth, later-discovered facts;
- patching strategy: add new entries when the story grows instead of overloading one master entry.

Avoid:

- dumping the whole card into every entry;
- using worldbook as a personality style prompt;
- hiding essential character facts only in rare triggers;
- vague triggers that fire constantly.

## Regex Craft

Use regex for text transformation:

- clean model artifacts;
- expand user shorthand;
- format status bars;
- normalize tags/code blocks;
- extract or display values.

Do not treat regex as a state store or JavaScript runner. If regex outputs macros or HTML, prove the downstream macro/rendering chain separately.

For risky regexes, keep fixtures:

- input text;
- matched groups;
- replacement output;
- expected side effects;
- destructive behavior notes.

## Gameplay Mode Planning

The old Tavo Studio skill used nine useful planning modes. Treat them as creative templates, not Tavo requirements:

- pure character;
- wuxia growth;
- xianxia growth;
- fantasy growth;
- ARPG growth;
- story RPG;
- survival simulation;
- farming/management;
- relationship/affection route.

Default to pure character unless the user asks for systems. Add worldbooks, presets, macros, regexes, Advanced Rendering, or plugins only when they solve a real gameplay problem.

## Chinese Prose Cleanup

Use the old AI-cliche blacklist as a default cleanup suggestion, not a rigid ban. Common weak patterns:

- passive emotion words like "不禁", "情不自禁", "油然而生";
- overused similes like "宛如", "仿佛", "如同";
- vague modifiers like "淡淡的", "轻轻地", "微微一笑", "深邃的眼眸";
- melodramatic stock phrases like "命运的齿轮", "难以言喻".

Replace with concrete action, tone shift, posture, silence, decision, or dialogue.

## Multi-Object Delivery Order

For complex packages:

1. Write the role/card text first.
2. Extract worldbook entries from facts that are conditional or too large for the card.
3. Add preset behavior only if the role needs a special generation policy.
4. Add macros/EJS for dynamic state only when the design needs it.
5. Add regex for transformation and display.
6. Add Advanced Rendering for visual layout.
7. Add plugin packaging only when the behavior should be reusable across cards/chats.
8. Validate each layer before adding the next.

## Quality Checklist

- Does the card have one clear attraction core?
- Are permanent facts in persistent fields rather than buried in notes?
- Does the opening message teach the desired style?
- Do examples demonstrate voice and relationship dynamics?
- Are worldbook triggers specific enough?
- Are regexes tested against before/after examples?
- Are dynamic variables documented and initialized?
- Is every live/product claim labeled with official, MCP, or Android evidence?
- Are old-version claims quarantined unless retested?
