// SPDX-License-Identifier: GPL-2.0-or-later
//
// Clipboard offer rules. No D-Bus, no GTK, no secrets. The extension
// uses this before it reads text or calls the bridge.

export const CLIPBOARD_LIMIT_DEFAULT = 50;
export const CLIPBOARD_LIMIT_MIN = 1;
export const CLIPBOARD_LIMIT_MAX = 500;
export const CLIPBOARD_TEXT_MAX = 1000000;
export const MENU_LIMIT = 12;
export const LOOKALIKE_SKIP = 'skip';
export const LOOKALIKE_MASK = 'mask';
export const LOOKALIKE_MODES = [LOOKALIKE_SKIP, LOOKALIKE_MASK];
export const LOOKALIKE_LABELS = ['Skip', 'Hide for 30 seconds'];
export const CLIPBOARD_MASK_LABEL = 'Hidden password';
export const LOOKALIKE_MIN = 8;
export const LOOKALIKE_MAX = 128;
export const IMAGE_MAX_BYTES = 10 * 1024 * 1024;

const IMAGE_MIME_ORDER = [
    'image/png',
    'image/jpeg',
    'image/webp',
    'image/bmp',
    'image/gif',
    'image/tiff',
    'image/svg+xml',
];

const IMAGE_NAMES = {
    'image/png': 'PNG',
    'image/jpeg': 'JPEG',
    'image/webp': 'WEBP',
    'image/bmp': 'BMP',
    'image/gif': 'GIF',
    'image/tiff': 'TIFF',
    'image/svg+xml': 'SVG',
};

export const DEFAULT_EXCLUDED_APPS = [
    '1password',
    'bitwarden',
    'keepassxc',
    'keepass',
    'org.keepassxc.KeePassXC',
    'org.gnome.World.Secrets',
    'gnome-keyring',
    'seahorse',
    'kwalletmanager',
    'kwallet',
    'proton-pass',
    'protonpass',
    'lastpass',
    'dashlane',
    'enpass',
    'gopass',
];

const TEXT_MIMES = new Set([
    'text/plain',
    'utf8_string',
    'string',
    'text',
    'compound_text',
    'text/unicode',
]);

const APP_ID = /^[A-Za-z0-9._-]{2,128}$/;
const UUID_TEXT = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const EMAIL_TEXT = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const FILENAME_TEXT = /^[A-Za-z0-9_-]+\.[A-Za-z]{1,8}$/;

export function clipboardLimit(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0)
        return CLIPBOARD_LIMIT_DEFAULT;
    return Math.min(CLIPBOARD_LIMIT_MAX, Math.max(CLIPBOARD_LIMIT_MIN, Math.round(value)));
}

export function excludedApps(values) {
    if (!Array.isArray(values))
        return [];
    const seen = [];
    const folded = new Set();
    for (const value of values) {
        if (typeof value !== 'string' || !APP_ID.test(value.trim()))
            continue;
        const name = value.trim();
        const key = name.toLowerCase();
        if (folded.has(key))
            continue;
        folded.add(key);
        seen.push(name);
        if (seen.length >= 64)
            break;
    }
    return seen;
}

export function lookalikeMode(value) {
    return LOOKALIKE_MODES.includes(value) ? value : LOOKALIKE_SKIP;
}

export function looksLikePassword(text) {
    const body = singleLine(text);
    if (body === null)
        return false;
    if (body.length < LOOKALIKE_MIN || body.length > LOOKALIKE_MAX)
        return false;
    const folded = body.toLowerCase();
    if (body.includes('://') || folded.startsWith('www.'))
        return false;
    if (body.includes('/') || body.includes('\\') || body.startsWith('~'))
        return false;
    if (/^[0-9]+$/.test(body))
        return false;
    if (UUID_TEXT.test(body) || EMAIL_TEXT.test(body) || FILENAME_TEXT.test(body))
        return false;
    let lower = false;
    let upper = false;
    let digit = false;
    let symbol = false;
    for (const char of body) {
        if (char >= 'a' && char <= 'z')
            lower = true;
        else if (char >= 'A' && char <= 'Z')
            upper = true;
        else if (char >= '0' && char <= '9')
            digit = true;
        else
            symbol = true;
    }
    return Number(lower) + Number(upper) + Number(digit) + Number(symbol) >= 3;
}

export function classifyClipboard({
    text = null,
    mimes = [],
    wmClass = '',
    enabled = true,
    excluded = DEFAULT_EXCLUDED_APPS,
    lookalike = LOOKALIKE_SKIP,
} = {}) {
    if (enabled !== true)
        return 'skipped-disabled';
    const types = Array.isArray(mimes) ? mimes.filter(mime => typeof mime === 'string') : [];
    if (types.some(isSensitiveMime))
        return 'skipped-sensitive';
    if (appExcluded(wmClass, excluded))
        return 'skipped-app';
    if (types.length && !types.some(isTextMime))
        return 'skipped-binary';
    if (text === null || text === undefined)
        return 'needs-text';
    if (typeof text !== 'string' || text.includes('\u0000'))
        return 'skipped-binary';
    if (!text.trim())
        return 'skipped-empty';
    if (byteLength(text) > CLIPBOARD_TEXT_MAX)
        return 'skipped-huge';
    if (looksLikePassword(text))
        return lookalikeMode(lookalike) === LOOKALIKE_MASK ? 'stored-masked' : 'skipped-lookalike';
    return 'stored';
}

export function canonicalImageMime(mime) {
    if (typeof mime !== 'string')
        return null;
    let folded = mime.toLowerCase().split(';', 1)[0].trim();
    if (folded === 'image/jpg')
        folded = 'image/jpeg';
    return Object.hasOwn(IMAGE_NAMES, folded) ? folded : null;
}

export function pickImageMime(mimes) {
    const types = Array.isArray(mimes) ? mimes.filter(mime => typeof mime === 'string') : [];
    if (types.some(isTextMime))
        return null;
    const found = types.map(canonicalImageMime).filter(Boolean);
    if (found.includes('image/png'))
        return 'image/png';
    for (const mime of IMAGE_MIME_ORDER) {
        if (found.includes(mime))
            return mime;
    }
    return null;
}

export function imageWithinCap(size) {
    return Number.isInteger(size) && size >= 1 && size <= IMAGE_MAX_BYTES;
}

export function imageLabel(mime, size) {
    const name = IMAGE_NAMES[canonicalImageMime(mime)] || 'Image';
    return `Image · ${name} · ${formatBytes(size)}`;
}

export function menuLabel(text, masked = false) {
    if (masked === true)
        return CLIPBOARD_MASK_LABEL;
    const line = String(text || '').replace(/\s+/g, ' ').trim();
    if (!line)
        return 'Empty';
    if (line.length <= 80)
        return line;
    return `${line.slice(0, 79)}…`;
}

function isSensitiveMime(mime) {
    const folded = String(mime || '').toLowerCase();
    return folded.includes('passwordmanagerhint') ||
        folded.includes('concealed') ||
        folded.includes('confidential') ||
        folded.includes('sensitive');
}

function singleLine(text) {
    if (typeof text !== 'string' || !text)
        return null;
    let body = text;
    if (body.endsWith('\r\n'))
        body = body.slice(0, -2);
    else if (body.endsWith('\n') || body.endsWith('\r'))
        body = body.slice(0, -1);
    if (!body || /\s/u.test(body))
        return null;
    return body;
}

function isTextMime(mime) {
    const folded = String(mime || '').toLowerCase().trim();
    if (TEXT_MIMES.has(folded))
        return true;
    return TEXT_MIMES.has(folded.split(';', 1)[0].trim());
}

function appExcluded(wmClass, excluded) {
    const folded = String(wmClass || '').toLowerCase().trim();
    if (!folded)
        return false;
    for (const name of excludedApps(excluded)) {
        const ident = name.toLowerCase();
        if (folded === ident || folded.includes(ident))
            return true;
    }
    return false;
}

function formatBytes(size) {
    const value = Number(size);
    if (!Number.isFinite(value) || value < 0)
        return '0 B';
    if (value < 1024)
        return `${Math.round(value)} B`;
    if (value < 1024 * 1024)
        return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function byteLength(text) {
    if (typeof TextEncoder === 'function')
        return new TextEncoder().encode(text).length;
    return unescape(encodeURIComponent(text)).length;
}
