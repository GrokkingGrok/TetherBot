// SPDX-License-Identifier: GPL-2.0-or-later
//
// Pure helpers for the prefs window. No secrets, no D-Bus, no GTK.

export const POLL_MIN = 60;
export const POLL_MAX = 900;
export const POLL_DEFAULT = 120;
export const UNDO_MIN = 2;
export const UNDO_MAX = 30;
export const UNDO_DEFAULT = 5;

export function keyButtonLabel(stored) {
    return stored ? 'Replace keys…' : 'Set up keys…';
}

export function idList(current, name, keep) {
    const next = new Set((current || []).filter(item => typeof item === 'string' && item));
    if (keep)
        next.delete(name);
    else if (typeof name === 'string' && name)
        next.add(name);
    return [...next].sort();
}

export function setupSlots(payload) {
    const slots = payload && Array.isArray(payload.slots) ? payload.slots : [];
    return slots.map(slot => ({
        slot: typeof slot.slot === 'string' ? slot.slot : '',
        kind: slot.kind === 'github-token' ? 'github-token' : 'webhook',
        stored: slot.stored === true,
        bots: Array.isArray(slot.bots)
            ? slot.bots.filter(name => typeof name === 'string' && name)
            : [],
    })).filter(slot => slot.slot);
}

export function botChoices(setupBots, hidden, muted) {
    const rows = new Map();
    for (const bot of setupBots || []) {
        if (!bot || typeof bot.name !== 'string' || !bot.name)
            continue;
        const display = typeof bot.display_name === 'string' && bot.display_name
            ? bot.display_name
            : bot.name;
        rows.set(bot.name, display);
    }
    const extra = [...(hidden || []), ...(muted || [])];
    for (const name of extra.sort()) {
        if (typeof name === 'string' && name && !rows.has(name))
            rows.set(name, name);
    }
    return [...rows.entries()].map(([name, displayName]) => ({name, displayName}));
}
