// SPDX-License-Identifier: GPL-2.0-or-later
//
// Pure helpers for the prefs window. No secrets, no D-Bus, no GTK.

export const POLL_MIN = 60;
export const POLL_MAX = 900;
export const POLL_DEFAULT = 120;
export const UNDO_MIN = 2;
export const UNDO_MAX = 30;
export const UNDO_DEFAULT = 5;
export const HISTORY_AMOUNT_MIN = 1;
export const HISTORY_AMOUNT_MAX = 999;
export const HISTORY_AMOUNT_DEFAULT = 1;
export const HISTORY_UNIT_DEFAULT = 'years';
export const HISTORY_UNITS = ['hours', 'days', 'weeks', 'months', 'years'];
export const HISTORY_UNIT_LABELS = ['Hours', 'Days', 'Weeks', 'Months', 'Years'];

const DAY_SECONDS = 86400;
const HISTORY_SCALE = {
    hours: 3600,
    days: DAY_SECONDS,
    weeks: 7 * DAY_SECONDS,
    months: 30 * DAY_SECONDS,
    years: 365 * DAY_SECONDS,
};

function positive(value) {
    return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function clampSeconds(value, lower, upper, fallback) {
    if (!positive(value))
        return fallback;
    return Math.min(upper, Math.max(lower, Math.round(value)));
}

export function effectivePollSeconds(stored, config) {
    if (positive(stored))
        return clampSeconds(stored, POLL_MIN, POLL_MAX, POLL_DEFAULT);
    if (positive(config))
        return clampSeconds(config, POLL_MIN, POLL_MAX, POLL_DEFAULT);
    return POLL_DEFAULT;
}

export function effectiveUndoSeconds(stored) {
    if (positive(stored))
        return clampSeconds(stored, UNDO_MIN, UNDO_MAX, UNDO_DEFAULT);
    return UNDO_DEFAULT;
}

export function historyAmount(value) {
    if (!positive(value))
        return HISTORY_AMOUNT_DEFAULT;
    return Math.min(HISTORY_AMOUNT_MAX, Math.max(HISTORY_AMOUNT_MIN, Math.round(value)));
}

export function historyUnit(value) {
    return HISTORY_UNITS.includes(value) ? value : HISTORY_UNIT_DEFAULT;
}

export function historySeconds(enabled, amount, unit) {
    if (enabled !== true)
        return null;
    return historyAmount(amount) * HISTORY_SCALE[historyUnit(unit)];
}

export const FEED_RESET_KEYS = ['poll-seconds', 'undo-seconds'];

export function resetFeedSettings(settings, configPoll) {
    const touched = [];
    for (const key of FEED_RESET_KEYS) {
        if (settings && typeof settings.reset === 'function')
            settings.reset(key);
        touched.push(key);
    }
    return {
        touched,
        poll: effectivePollSeconds(null, configPoll),
        undo: effectiveUndoSeconds(null),
    };
}

export function sameBotList(current, next) {
    const names = rows => (rows || [])
        .map(row => (row && typeof row.name === 'string' ? row.name : ''))
        .join('\0');
    return names(current) === names(next);
}

export function rememberExpansion(open, name, choice) {
    const next = new Set((open || []).filter(item => typeof item === 'string' && item));
    if (choice === true && typeof name === 'string' && name)
        next.add(name);
    else if (choice === false)
        next.delete(name);
    return [...next].sort();
}

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
