// SPDX-License-Identifier: GPL-2.0-or-later
//
// Clipboard offer rules. No D-Bus, no GTK, no secrets. The extension
// uses this before it reads text or calls the bridge.

export const CLIPBOARD_LIMIT_DEFAULT = 50;
export const CLIPBOARD_LIMIT_MIN = 1;
export const CLIPBOARD_LIMIT_MAX = 500;
export const CLIPBOARD_TEXT_MAX = 1000000;
export const MENU_LIMIT = 12;

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

export function classifyClipboard({
    text = null,
    mimes = [],
    wmClass = '',
    enabled = true,
    excluded = DEFAULT_EXCLUDED_APPS,
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
    return 'stored';
}

export function menuLabel(text) {
    const line = String(text || '').replace(/\s+/g, ' ').trim();
    if (!line)
        return 'Empty';
    if (line.length <= 80)
        return line;
    return `${line.slice(0, 79)}…`;
}

function isSensitiveMime(mime) {
    const folded = String(mime || '').toLowerCase();
    return folded.includes('passwordmanagerhint') || folded.includes('concealed');
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

function byteLength(text) {
    if (typeof TextEncoder === 'function')
        return new TextEncoder().encode(text).length;
    return unescape(encodeURIComponent(text)).length;
}
