import fs from 'node:fs';

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

let crcTable = null;

function getCrcTable() {
    if (crcTable) {
        return crcTable;
    }

    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) {
            c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        }
        crcTable[n] = c >>> 0;
    }

    return crcTable;
}

function crc32(buffer) {
    const table = getCrcTable();
    let crc = 0xffffffff;

    for (const byte of buffer) {
        crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    }

    return (crc ^ 0xffffffff) >>> 0;
}

export function assertPng(buffer) {
    if (!Buffer.isBuffer(buffer)) {
        throw new Error('Expected a Buffer.');
    }

    if (buffer.length < PNG_SIGNATURE.length || !buffer.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) {
        throw new Error('Input is not a valid PNG file.');
    }
}

export function parsePngChunks(buffer) {
    assertPng(buffer);
    const chunks = [];
    let offset = PNG_SIGNATURE.length;

    while (offset < buffer.length) {
        const length = buffer.readUInt32BE(offset);
        const type = buffer.subarray(offset + 4, offset + 8).toString('latin1');
        const dataStart = offset + 8;
        const dataEnd = dataStart + length;
        const crc = buffer.readUInt32BE(dataEnd);
        const data = Buffer.from(buffer.subarray(dataStart, dataEnd));

        chunks.push({ type, data, crc });
        offset = dataEnd + 4;

        if (type === 'IEND') {
            break;
        }
    }

    return chunks;
}

export function buildPngBuffer(chunks) {
    const parts = [PNG_SIGNATURE];

    for (const chunk of chunks) {
        const typeBuffer = Buffer.from(chunk.type, 'latin1');
        const lengthBuffer = Buffer.alloc(4);
        lengthBuffer.writeUInt32BE(chunk.data.length, 0);

        const crcBuffer = Buffer.alloc(4);
        crcBuffer.writeUInt32BE(crc32(Buffer.concat([typeBuffer, chunk.data])), 0);

        parts.push(lengthBuffer, typeBuffer, chunk.data, crcBuffer);
    }

    return Buffer.concat(parts);
}

export function decodeTextChunkData(data) {
    const separatorIndex = data.indexOf(0x00);
    if (separatorIndex === -1) {
        throw new Error('Malformed PNG tEXt chunk.');
    }

    return {
        keyword: data.subarray(0, separatorIndex).toString('latin1'),
        text: data.subarray(separatorIndex + 1).toString('latin1'),
    };
}

export function encodeTextChunk(keyword, text) {
    const keywordBuffer = Buffer.from(keyword, 'latin1');
    const textBuffer = Buffer.from(text, 'latin1');
    return {
        type: 'tEXt',
        data: Buffer.concat([keywordBuffer, Buffer.from([0]), textBuffer]),
    };
}

export function listTextChunks(buffer) {
    return parsePngChunks(buffer)
        .filter(chunk => chunk.type === 'tEXt')
        .map(chunk => decodeTextChunkData(chunk.data));
}

export function readCharacterPayloadFromPng(buffer, { prefer = 'ccv3' } = {}) {
    const textChunks = listTextChunks(buffer);
    const preferLower = String(prefer).toLowerCase();
    const orderedKeywords = preferLower === 'chara' ? ['chara', 'ccv3'] : ['ccv3', 'chara'];

    for (const keyword of orderedKeywords) {
        const match = textChunks.find(chunk => chunk.keyword.toLowerCase() === keyword);
        if (match) {
            return {
                keyword: match.keyword,
                jsonText: Buffer.from(match.text, 'base64').toString('utf8'),
                base64Text: match.text,
            };
        }
    }

    throw new Error('No SillyTavern character payload found in PNG.');
}

export function writeCharacterPayloadToPng(buffer, jsonText, { includeCcv3 = true } = {}) {
    JSON.parse(jsonText);
    const chunks = parsePngChunks(buffer);
    const filtered = [];

    for (const chunk of chunks) {
        if (chunk.type !== 'tEXt') {
            filtered.push(chunk);
            continue;
        }

        const decoded = decodeTextChunkData(chunk.data);
        const keyword = decoded.keyword.toLowerCase();
        if (keyword === 'chara' || keyword === 'ccv3') {
            continue;
        }

        filtered.push(chunk);
    }

    const iendIndex = filtered.findIndex(chunk => chunk.type === 'IEND');
    if (iendIndex === -1) {
        throw new Error('PNG is missing IEND chunk.');
    }

    const insertions = [];
    const charaBase64 = Buffer.from(jsonText, 'utf8').toString('base64');
    insertions.push(encodeTextChunk('chara', charaBase64));

    if (includeCcv3) {
        try {
            const parsed = JSON.parse(jsonText);
            parsed.spec = 'chara_card_v3';
            parsed.spec_version = '3.0';
            const ccv3Base64 = Buffer.from(JSON.stringify(parsed), 'utf8').toString('base64');
            insertions.push(encodeTextChunk('ccv3', ccv3Base64));
        } catch {
            // Ignore ccv3 generation failures.
        }
    }

    filtered.splice(iendIndex, 0, ...insertions);
    return buildPngBuffer(filtered);
}

export function readJsonFile(path) {
    return fs.readFileSync(path, 'utf8');
}

export function readPngFile(path) {
    return fs.readFileSync(path);
}
