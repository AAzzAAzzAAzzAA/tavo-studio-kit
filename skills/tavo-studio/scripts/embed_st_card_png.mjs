#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

import { readPngFile, readJsonFile, writeCharacterPayloadToPng, readCharacterPayloadFromPng } from './png-card-lib.mjs';

function usage() {
    console.log(`Usage:
  node embed_st_card_png.mjs --png /path/base.png --json /path/card.json --out /path/card.png [--overwrite] [--chara-only]

Options:
  --png         Base PNG image path
  --json        Character card JSON path
  --out         Output PNG path
  --overwrite   Allow overwriting the output file
  --chara-only  Only write the 'chara' chunk and skip the optional 'ccv3' compatibility chunk
`);
}

function parseArgs(argv) {
    const args = { overwrite: false, charaOnly: false };

    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i];

        if (arg === '--overwrite') {
            args.overwrite = true;
            continue;
        }

        if (arg === '--chara-only') {
            args.charaOnly = true;
            continue;
        }

        if (arg.startsWith('--')) {
            const next = argv[i + 1];
            if (!next || next.startsWith('--')) {
                throw new Error(`Missing value for ${arg}`);
            }
            args[arg.slice(2)] = next;
            i++;
            continue;
        }

        throw new Error(`Unknown argument: ${arg}`);
    }

    return args;
}

function inspectCard(card) {
    const errors = [];
    const warnings = [];

    if (card.spec !== 'chara_card_v2') {
        errors.push('spec must be "chara_card_v2"');
    }

    if (card.spec_version !== '2.0') {
        errors.push('spec_version must be "2.0"');
    }

    if (!card.data || typeof card.data !== 'object') {
        errors.push('data must be an object');
        return { errors, warnings };
    }

    const strictDataFields = [
        'name',
        'description',
        'personality',
        'scenario',
        'first_mes',
        'mes_example',
    ];

    const recommendedDataFields = [
        'creator_notes',
        'system_prompt',
        'post_history_instructions',
        'alternate_greetings',
        'tags',
        'creator',
        'character_version',
        'extensions',
    ];

    for (const field of strictDataFields) {
        if (!(field in card.data)) {
            errors.push(`data.${field} is missing`);
        }
    }

    for (const field of recommendedDataFields) {
        if (!(field in card.data)) {
            warnings.push(`data.${field} is missing; ST may still load it, but new cards should include it`);
        }
    }

    if ('alternate_greetings' in card.data && !Array.isArray(card.data.alternate_greetings)) {
        errors.push('data.alternate_greetings must be an array');
    }

    if ('tags' in card.data && !Array.isArray(card.data.tags)) {
        errors.push('data.tags must be an array');
    }

    if ('extensions' in card.data && (typeof card.data.extensions !== 'object' || card.data.extensions === null || Array.isArray(card.data.extensions))) {
        errors.push('data.extensions must be an object');
    }

    if (card.data.character_book !== undefined) {
        const book = card.data.character_book;
        if (typeof book !== 'object' || book === null || Array.isArray(book)) {
            errors.push('data.character_book must be an object');
        } else {
            if (!('extensions' in book) || typeof book.extensions !== 'object' || book.extensions === null || Array.isArray(book.extensions)) {
                errors.push('data.character_book.extensions must be an object');
            }
            if (!Array.isArray(book.entries)) {
                errors.push('data.character_book.entries must be an array');
            }
        }
    }

    return { errors, warnings };
}

function main() {
    const args = parseArgs(process.argv.slice(2));

    if (!args.png || !args.json || !args.out) {
        usage();
        process.exit(1);
    }

    if (fs.existsSync(args.out) && !args.overwrite) {
        throw new Error(`Output file already exists: ${args.out}. Pass --overwrite to replace it.`);
    }

    const pngBuffer = readPngFile(args.png);
    const jsonText = readJsonFile(args.json);
    const parsed = JSON.parse(jsonText);
    const { errors, warnings } = inspectCard(parsed);

    if (errors.length) {
        throw new Error(`Character JSON failed validation:\n- ${errors.join('\n- ')}`);
    }

    if (warnings.length) {
        console.warn(`Warnings:\n- ${warnings.join('\n- ')}`);
    }

    const outputBuffer = writeCharacterPayloadToPng(pngBuffer, JSON.stringify(parsed), {
        includeCcv3: !args.charaOnly,
    });

    fs.mkdirSync(path.dirname(args.out), { recursive: true });
    fs.writeFileSync(args.out, outputBuffer);

    const roundTrip = readCharacterPayloadFromPng(outputBuffer, { prefer: 'chara' });
    const roundTripJson = JSON.parse(roundTrip.jsonText);

    console.log(`Wrote ${args.out}`);
    console.log(`Embedded chunk: ${roundTrip.keyword}`);
    console.log(`Card name: ${roundTripJson.data?.name ?? '(unknown)'}`);
}

try {
    main();
} catch (error) {
    console.error(error.message);
    process.exit(1);
}
