// SPDX-License-Identifier: GPL-2.0-or-later
//
// Inline clip editors in the panel clipboard menu. This file imports
// nothing, so `node extension/clip_inline_checks.js` can run it. The shell
// owns these editors. Nothing here opens or messages the TetherBot window.

export const TAG_NAME_MAX = 40;
export const CLIP_TAG_MAX = 8;
export const TAG_SAVE_ERROR = 'Tags could not be saved';
export const TAG_LIMIT_LINE = `A clip keeps up to ${CLIP_TAG_MAX} tags.`;
export const TAG_NAME_LINE = `A tag is 1 to ${TAG_NAME_MAX} characters.`;

const TAG_TONES = new Set([
    'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'gray',
]);

export function tagTone(color) {
    return TAG_TONES.has(color) ? color : 'gray';
}

// Same rule as the bridge: collapse whitespace, at most 40 characters, no
// control characters.
export function normalizeTagName(raw) {
    if (typeof raw !== 'string')
        return '';
    const name = raw.split(/\s+/).filter(Boolean).join(' ');
    const chars = [...name];
    if (!chars.length || chars.length > TAG_NAME_MAX)
        return '';
    if (chars.some(char => char.codePointAt(0) < 32))
        return '';
    return name;
}

function tagKey(name) {
    return name.toLowerCase();
}

function copyChips(chips) {
    return (Array.isArray(chips) ? chips : []).map(chip => ({...chip}));
}

export function selectedTagCount(chips) {
    return (Array.isArray(chips) ? chips : []).filter(chip => chip && chip.selected).length;
}

// The clip's own tags come first and are selected. GetTags rows (`tag`) and
// tags seen on other clips (`name`) follow in name order, unselected.
export function tagChips({known = [], clipTags = [], otherTags = []} = {}) {
    const chips = [];
    const index = new Map();
    const add = (name, color, selected) => {
        const clean = normalizeTagName(name);
        if (!clean)
            return;
        const key = tagKey(clean);
        const found = index.get(key);
        if (found) {
            if (!found.color && typeof color === 'string')
                found.color = color;
            return;
        }
        const chip = {name: clean, color: typeof color === 'string' ? color : '', selected};
        index.set(key, chip);
        chips.push(chip);
    };
    for (const tag of Array.isArray(clipTags) ? clipTags : [])
        add(tag && tag.name, tag && tag.color, true);
    const rest = [];
    for (const row of Array.isArray(known) ? known : [])
        rest.push([row && row.tag, row && row.color]);
    for (const tag of Array.isArray(otherTags) ? otherTags : [])
        rest.push([tag && tag.name, tag && tag.color]);
    rest.sort((a, b) => String(a[0]).toLowerCase().localeCompare(String(b[0]).toLowerCase()));
    for (const [name, color] of rest)
        add(name, color, false);
    return chips;
}

// GetTags arrived after the editor opened. Keep the user's choices.
export function mergeKnownTags(chips, known) {
    const merged = copyChips(chips);
    const seen = new Set(merged.map(chip => tagKey(chip.name)));
    for (const chip of tagChips({known})) {
        if (seen.has(tagKey(chip.name)))
            continue;
        seen.add(tagKey(chip.name));
        merged.push(chip);
    }
    return merged;
}

export function toggleTagChip(chips, name) {
    const next = copyChips(chips);
    const key = tagKey(String(name || ''));
    const chip = next.find(candidate => tagKey(candidate.name) === key);
    if (!chip)
        return {chips: next, error: ''};
    if (!chip.selected && selectedTagCount(next) >= CLIP_TAG_MAX)
        return {chips: next, error: TAG_LIMIT_LINE};
    chip.selected = !chip.selected;
    return {chips: next, error: ''};
}

// Enter in New tag… adds a selected chip, or selects the one already there.
export function addTagChip(chips, raw) {
    const next = copyChips(chips);
    const name = normalizeTagName(raw);
    if (!name) {
        const typed = typeof raw === 'string' && raw.trim() !== '';
        return {chips: next, added: '', error: typed ? TAG_NAME_LINE : ''};
    }
    const found = next.find(chip => tagKey(chip.name) === tagKey(name));
    if (found && found.selected)
        return {chips: next, added: found.name, error: ''};
    if (selectedTagCount(next) >= CLIP_TAG_MAX)
        return {chips: next, added: '', error: TAG_LIMIT_LINE};
    if (found) {
        found.selected = true;
        return {chips: next, added: found.name, error: ''};
    }
    next.push({name, color: '', selected: true});
    return {chips: next, added: name, error: ''};
}

// The SetClipboardTags argument. The bridge picks a color for a new tag.
export function tagsPayload(chips) {
    const tags = [];
    for (const chip of Array.isArray(chips) ? chips : []) {
        if (!chip || !chip.selected)
            continue;
        const tag = {name: chip.name};
        if (typeof chip.color === 'string' && chip.color)
            tag.color = chip.color;
        tags.push(tag);
    }
    return JSON.stringify(tags);
}

export function historyTags(entries) {
    const tags = [];
    for (const entry of Array.isArray(entries) ? entries : []) {
        for (const tag of Array.isArray(entry && entry.tags) ? entry.tags : [])
            tags.push(tag);
    }
    return tags;
}

export function planEditorPress(current, kind, id) {
    if (current && current.kind === kind && current.id === id)
        return 'keep';
    return current ? 'replace' : 'open';
}

// One inline editor at a time. A menu rebuild waits until it closes, so a
// copy during an edit does not destroy the editor or its text.
export class ClipEditorSlot {
    constructor({mount, unmount, rebuild}) {
        this._mount = mount;
        this._unmount = unmount;
        this._rebuild = rebuild;
        this._current = null;
        this._token = 0;
        this._rebuildPending = false;
    }

    get current() {
        return this._current;
    }

    get isOpen() {
        return this._current !== null;
    }

    get rebuildPending() {
        return this._rebuildPending;
    }

    press(kind, entry) {
        const id = entry && typeof entry.id === 'string' ? entry.id : '';
        if (!id)
            return 'ignored';
        const plan = planEditorPress(this._current, kind, id);
        if (plan === 'keep') {
            this._current.handle?.focus?.();
            return plan;
        }
        if (plan === 'replace')
            this._teardown();
        this._token += 1;
        const current = {kind, id, token: this._token, handle: null};
        this._current = current;
        const handle = this._mount(kind, entry, current.token);
        if (!handle) {
            this._current = null;
            this._flush();
            return 'failed';
        }
        current.handle = handle;
        return plan;
    }

    isCurrent(token) {
        return this._current !== null && this._current.token === token;
    }

    close(token) {
        if (!this._current)
            return false;
        if (token !== undefined && token !== this._current.token)
            return false;
        this._teardown();
        this._flush();
        return true;
    }

    requestRebuild() {
        if (this._current) {
            this._rebuildPending = true;
            return 'deferred';
        }
        this._rebuildPending = false;
        this._rebuild();
        return 'now';
    }

    dispose() {
        this._rebuildPending = false;
        this._teardown();
    }

    _teardown() {
        const current = this._current;
        this._current = null;
        if (current && current.handle)
            this._unmount(current.handle);
    }

    _flush() {
        if (!this._rebuildPending)
            return;
        this._rebuildPending = false;
        this._rebuild();
    }
}
