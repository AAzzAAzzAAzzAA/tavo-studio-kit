#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

function usage() {
    console.log(`Usage:
  node worldbook_to_character_book.mjs --in /path/worldbook.json --out /path/character_book.json [--name "Lorebook Name"]
`);
}

function parseArgs(argv) {
    const args = {};

    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i];
        if (!arg.startsWith('--')) {
            throw new Error(`Unknown argument: ${arg}`);
        }

        const next = argv[i + 1];
        if (!next || next.startsWith('--')) {
            throw new Error(`Missing value for ${arg}`);
        }

        args[arg.slice(2)] = next;
        i++;
    }

    return args;
}

function toArray(value) {
    if (Array.isArray(value)) {
        return value;
    }
    if (value === undefined || value === null || value === '') {
        return [];
    }
    return [value];
}

function convertEntry(entryKey, entry) {
    const id = entry.uid ?? Number(entryKey);
    const numericPosition = Number.isFinite(entry.position) ? entry.position : 0;

    return {
        id,
        keys: toArray(entry.key),
        secondary_keys: toArray(entry.keysecondary),
        comment: entry.comment ?? '',
        content: entry.content ?? '',
        constant: Boolean(entry.constant),
        selective: Boolean(entry.selective),
        enabled: !Boolean(entry.disable),
        insertion_order: entry.order ?? 100,
        position: numericPosition === 0 ? 'before_char' : 'after_char',
        extensions: {
            ...(typeof entry.extensions === 'object' && entry.extensions && !Array.isArray(entry.extensions) ? entry.extensions : {}),
            position: numericPosition,
            exclude_recursion: entry.excludeRecursion ?? false,
            display_index: entry.displayIndex ?? id,
            probability: entry.probability ?? 100,
            useProbability: entry.useProbability ?? true,
            depth: entry.depth ?? 4,
            selectiveLogic: entry.selectiveLogic ?? 0,
            outlet_name: entry.outletName ?? '',
            group: entry.group ?? '',
            group_override: entry.groupOverride ?? false,
            group_weight: entry.groupWeight ?? 100,
            prevent_recursion: entry.preventRecursion ?? false,
            delay_until_recursion: entry.delayUntilRecursion ?? false,
            scan_depth: entry.scanDepth ?? null,
            match_whole_words: entry.matchWholeWords ?? null,
            use_group_scoring: entry.useGroupScoring ?? null,
            case_sensitive: entry.caseSensitive ?? null,
            automation_id: entry.automationId ?? '',
            role: entry.role ?? 0,
            vectorized: entry.vectorized ?? false,
            sticky: entry.sticky ?? null,
            cooldown: entry.cooldown ?? null,
            delay: entry.delay ?? null,
            match_persona_description: entry.matchPersonaDescription ?? false,
            match_character_description: entry.matchCharacterDescription ?? false,
            match_character_personality: entry.matchCharacterPersonality ?? false,
            match_character_depth_prompt: entry.matchCharacterDepthPrompt ?? false,
            match_scenario: entry.matchScenario ?? false,
            match_creator_notes: entry.matchCreatorNotes ?? false,
            triggers: Array.isArray(entry.triggers) ? entry.triggers : [],
            ignore_budget: entry.ignoreBudget ?? false,
        },
    };
}

function main() {
    const args = parseArgs(process.argv.slice(2));

    if (!args.in || !args.out) {
        usage();
        process.exit(1);
    }

    const input = JSON.parse(fs.readFileSync(args.in, 'utf8'));
    if (!input || typeof input !== 'object' || !input.entries || typeof input.entries !== 'object' || Array.isArray(input.entries)) {
        throw new Error('Input file must be a standalone SillyTavern worldbook JSON with an entries object.');
    }

    const characterBook = {
        name: args.name || input.name || path.parse(args.in).name,
        description: input.description ?? '',
        scan_depth: input.scan_depth ?? null,
        token_budget: input.token_budget ?? null,
        recursive_scanning: input.recursive_scanning ?? false,
        extensions: typeof input.extensions === 'object' && input.extensions && !Array.isArray(input.extensions) ? input.extensions : {},
        entries: Object.entries(input.entries)
            .sort(([, a], [, b]) => (a.displayIndex ?? a.uid ?? 0) - (b.displayIndex ?? b.uid ?? 0))
            .map(([entryKey, entry]) => convertEntry(entryKey, entry)),
    };

    fs.mkdirSync(path.dirname(args.out), { recursive: true });
    fs.writeFileSync(args.out, `${JSON.stringify(characterBook, null, 2)}\n`, 'utf8');

    console.log(`Wrote ${args.out}`);
    console.log(`Entries: ${characterBook.entries.length}`);
    console.log(`Name: ${characterBook.name}`);
}

try {
    main();
} catch (error) {
    console.error(error.message);
    process.exit(1);
}
