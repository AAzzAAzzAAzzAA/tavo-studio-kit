#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

import { readPngFile, readCharacterPayloadFromPng } from './png-card-lib.mjs';

function usage() {
    console.log(`Usage:
  node extract_st_card_png.mjs --png /path/card.png [--out /path/card.json] [--prefer-chara]

Options:
  --png           PNG card path
  --out           Optional output JSON path
  --prefer-chara  Prefer 'chara' over 'ccv3' when both are present
`);
}

function parseArgs(argv) {
    const args = { preferChara: false };

    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i];

        if (arg === '--prefer-chara') {
            args.preferChara = true;
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

function main() {
    const args = parseArgs(process.argv.slice(2));

    if (!args.png) {
        usage();
        process.exit(1);
    }

    const pngBuffer = readPngFile(args.png);
    const result = readCharacterPayloadFromPng(pngBuffer, {
        prefer: args.preferChara ? 'chara' : 'ccv3',
    });
    const prettyJson = `${JSON.stringify(JSON.parse(result.jsonText), null, 2)}\n`;

    if (args.out) {
        fs.mkdirSync(path.dirname(args.out), { recursive: true });
        fs.writeFileSync(args.out, prettyJson, 'utf8');
        console.log(`Extracted ${result.keyword} payload to ${args.out}`);
        return;
    }

    process.stdout.write(prettyJson);
}

try {
    main();
} catch (error) {
    console.error(error.message);
    process.exit(1);
}
