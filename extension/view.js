// SPDX-License-Identifier: GPL-2.0-or-later
//
// Popup and notification mapping. This file imports nothing, so a GJS
// test can run it without GNOME Shell. The extension sends the calls.

export const BUS_NAME = 'io.github.grokkinggrok.TetherBot1';
export const OBJECT_PATH = '/io/github/grokkinggrok/TetherBot1';
export const ITEM_FILTER = '{"include_snoozed":false}';
export const UPDATE_MESSAGE = 'This feed uses a newer protocol. Update TetherBot.';
export const BRIDGE_DOWN = 'Bridge not running';

export const PROXY_METHODS = [
    'GetItemsRemote',
    'PerformActionRemote',
    'SnoozeRemote',
    'OpenChatRemote',
    'SyncNowRemote',
    'RequestSecretEntryRemote',
    'MarkSeenRemote',
    'OpenWindowRemote',
    'UndoRemote',
];

export const PROXY_SIGNALS = [
    'ItemsChanged',
    'NotificationRequested',
    'ActionResult',
    'StateChanged',
];

export const TODO_LIMIT = 8;
export const UNDO_MS = 5000;

const CHIP_TONES = new Set([
    'red', 'orange', 'amber', 'yellow', 'green', 'teal',
    'blue', 'purple', 'pink', 'gray', 'neutral',
]);

function number(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0)
        return 0;
    return Math.floor(parsed);
}

function needsUpdate(reason) {
    const text = String(reason || '').toLowerCase();
    return text.includes('unsupported schema') || text.includes('update tetherbot');
}

export function itemKey(item) {
    if (item && typeof item.key === 'string' && item.key)
        return item.key;
    const bot = item?.source?.bot;
    if (typeof bot === 'string' && bot && typeof item.id === 'string' && item.id)
        return `${bot}/${item.id}`;
    return '';
}

function botId(item) {
    if (typeof item?.bot === 'string' && item.bot)
        return item.bot;
    const source = item?.source?.bot;
    if (typeof source === 'string')
        return source;
    const key = itemKey(item);
    const slash = key.indexOf('/');
    return slash > 0 ? key.slice(0, slash) : '';
}

function acted(item) {
    const record = item?.local?.acted;
    return Boolean(record && typeof record.action === 'string' && record.action);
}

function snoozed(item, nowMs) {
    const until = item?.local?.snoozed_until;
    if (!until)
        return false;
    const parsed = Date.parse(until);
    return Number.isFinite(parsed) && parsed > nowMs;
}

export function indicatorView({running, state, counts}) {
    const asks = running ? number(counts?.asks) : 0;
    const todos = running ? number(counts?.todos) : 0;
    const dimmed = !running || state === 'unconfigured' || state === 'failed_closed';
    const attention = Boolean(running) && !dimmed && asks > 0;
    let iconName = 'mail-unread-symbolic';
    if (dimmed)
        iconName = 'network-offline-symbolic';
    else if (attention)
        iconName = 'emblem-important-symbolic';
    const accessibleName = running
        ? `TetherBot: ${asks} asks, ${todos} todos`
        : 'TetherBot: bridge not running';
    return {
        asks,
        todos,
        badge: asks + todos,
        dimmed,
        attention,
        iconName,
        accessibleName,
    };
}

export function formatLastSeen(unix, nowMs) {
    const seen = number(unix);
    if (!seen)
        return 'last seen unknown';
    const seconds = Math.max(0, Math.floor(nowMs / 1000) - seen);
    if (seconds < 45)
        return 'last seen just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60)
        return `last seen ${minutes} m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24)
        return `last seen ${hours} h ago`;
    return `last seen ${Math.floor(hours / 24)} d ago`;
}

export function formatNextRun(unix, nowMs) {
    const when = number(unix);
    if (!when)
        return '';
    const seconds = when - Math.floor(nowMs / 1000);
    if (seconds < 60)
        return 'next run due';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60)
        return `next run in ${minutes} m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24)
        return `next run in ${hours} h`;
    return `next run in ${Math.floor(hours / 24)} d`;
}

function bannerFor({running, state, reason}) {
    if (!running)
        return BRIDGE_DOWN;
    if (needsUpdate(reason))
        return UPDATE_MESSAGE;
    if (!state || state === 'ok')
        return '';
    return reason || state;
}

export function menuModel({
    running,
    state,
    reason,
    bots,
    items,
    queueLength,
    nowMs,
    undoHolds = [],
}) {
    const banner = bannerFor({running, state, reason});
    if (!running) {
        return {
            banner,
            bots: [],
            asks: [],
            todos: [],
            footer: null,
        };
    }
    const routes = new Map();
    const botRows = [];
    for (const bot of bots || []) {
        if (!bot || typeof bot.name !== 'string' || !bot.name)
            continue;
        routes.set(bot.name, Boolean(bot.routes && bot.routes.outbound));
        botRows.push({
            name: bot.display_name || bot.name,
            bot: bot.name,
            state: bot.state || '',
            summary: bot.summary || '',
            lastSeen: formatLastSeen(bot.last_seen, nowMs),
            nextRun: formatNextRun(bot.next_run, nowMs),
        });
    }
    const asks = [];
    const todos = [];
    for (const item of items || []) {
        if (!item || item.status !== 'open' || snoozed(item, nowMs) || acted(item))
            continue;
        if (item.local && (item.local.done_locally || item.local.resolved))
            continue;
        const key = itemKey(item);
        const bot = botId(item);
        if (item.kind === 'ask') {
            const actions = (item.actions || []).filter(action =>
                action === 'approve' || action === 'veto');
            asks.push({
                key,
                title: item.title || key || 'Ask',
                bot,
                due: item.due || '',
                actions,
            });
        } else if (item.kind === 'todo') {
            const listed = (item.actions || []).includes('done');
            todos.push({
                key,
                title: item.title || key || 'Todo',
                bot,
                due: item.due || '',
                canSendDone: listed && routes.get(bot) === true,
                chips: chipRow(item),
            });
        }
    }
    const presented = presentTodos(todos, undoHolds, nowMs);
    return {
        banner,
        bots: botRows,
        asks,
        todos: presented.todos,
        moreLabel: presented.moreLabel,
        footer: {
            state: state || '',
            reason: reason || '',
            queueLength: number(queueLength),
        },
    };
}

export function notificationModel(payload, reason) {
    const item = typeof payload === 'string' ? JSON.parse(payload) : payload;
    if (!item || typeof item !== 'object')
        throw new Error('notification payload must be an object');
    const key = itemKey(item);
    const bot = botId(item);
    const listed = Array.isArray(item.actions) ? item.actions : [];
    const actions = [];
    if (reason === 're-paste' || listed.includes('request_secret')) {
        actions.push({
            id: 'request_secret',
            label: 'Re-paste key',
            slot: typeof item.slot === 'string' ? item.slot : '',
        });
    } else if (reason !== 'action_result' && reason !== 'delivery_failed') {
        if (listed.includes('approve') && key)
            actions.push({id: 'approve', label: 'Approve', key});
        if (listed.includes('veto') && key)
            actions.push({id: 'veto', label: 'Veto', key});
        if (key) {
            actions.push({id: 'snooze-hour', label: 'Snooze 1 h', key});
            actions.push({id: 'snooze-tomorrow', label: 'Snooze until tomorrow', key});
        }
        if (bot)
            actions.push({id: 'open_chat', label: 'Open chat', bot});
    } else if (bot && reason === 'delivery_failed') {
        actions.push({id: 'open_chat', label: 'Open chat', bot});
    }
    return {
        title: item.title || 'TetherBot',
        body: typeof item.body === 'string' ? item.body : '',
        reason: reason || '',
        actions,
    };
}

export function performCall(action, key) {
    return {method: 'PerformAction', args: [key, action, '{}']};
}

export function openWindowCall(key) {
    return {method: 'OpenWindow', args: [typeof key === 'string' ? key : '']};
}

export function undoCall(key) {
    return {method: 'Undo', args: [key]};
}

export function todoFilter(query) {
    const spec = {include_snoozed: false, kinds: ['todo']};
    const text = String(query || '').trim();
    if (text)
        spec.query = text;
    return JSON.stringify(spec);
}

export function mergeTodoSearch(items, searched) {
    if (!Array.isArray(searched))
        return Array.isArray(items) ? items : [];
    const rest = (items || []).filter(item => item && item.kind !== 'todo');
    const todos = searched.filter(item => item && item.kind === 'todo');
    return rest.concat(todos);
}

export function chipRow(item) {
    const chips = item?.chips;
    if (!chips || typeof chips !== 'object')
        return null;
    const tags = Array.isArray(chips.tags) ? chips.tags : [];
    const shown = tags.slice(0, 3).map(tag => ({
        label: typeof tag?.label === 'string' && tag.label ? tag.label : `@${tag?.tag || ''}`,
        tone: chipTone(tag?.tone),
    })).filter(tag => tag.label !== '@');
    const priority = chips.priority && typeof chips.priority === 'object' ? chips.priority : null;
    const due = chips.due && typeof chips.due === 'object' ? chips.due : null;
    return {
        priority: typeof priority?.label === 'string' ? priority.label : '',
        priorityTone: chipTone(priority?.tone),
        due: typeof due?.label === 'string' ? due.label : '',
        dueTone: chipTone(due?.tone),
        tags: shown,
        extra: Math.max(0, tags.length - shown.length),
    };
}

export function presentTodos(todos, holds, nowMs) {
    const pending = new Map();
    for (const hold of holds || []) {
        if (!hold || typeof hold.key !== 'string' || !(hold.until > nowMs) || !hold.row)
            continue;
        pending.set(hold.key, hold.row);
    }
    const merged = [];
    const seen = new Set();
    for (const row of todos || []) {
        if (pending.has(row.key)) {
            merged.push({...row, undo: true, canSendDone: false});
            seen.add(row.key);
        } else {
            merged.push({...row, undo: false});
        }
    }
    for (const [key, row] of pending) {
        if (seen.has(key))
            continue;
        merged.unshift({...row, undo: true, canSendDone: false});
    }
    const undoRows = merged.filter(row => row.undo);
    const openRows = merged.filter(row => !row.undo);
    const room = Math.max(0, TODO_LIMIT - undoRows.length);
    const shown = undoRows.concat(openRows.slice(0, room));
    const more = merged.length > shown.length;
    return {
        todos: shown,
        moreLabel: more ? `Open TetherBot to see all ${merged.length}` : '',
    };
}

function chipTone(value) {
    return CHIP_TONES.has(value) ? value : 'neutral';
}

export function snoozeCall(key, untilIso) {
    return {method: 'Snooze', args: [key, untilIso]};
}

function pad(value) {
    return String(Math.abs(value)).padStart(2, '0');
}

export function formatIsoWithOffset(date) {
    const offsetMin = -date.getTimezoneOffset();
    const sign = offsetMin >= 0 ? '+' : '-';
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
        `${sign}${pad(Math.trunc(Math.abs(offsetMin) / 60))}:${pad(Math.abs(offsetMin) % 60)}`;
}

export function snoozeMoment(which, now) {
    if (which === 'hour')
        return new Date(now.getTime() + 60 * 60 * 1000);
    const next = new Date(now.getTime());
    next.setDate(next.getDate() + 1);
    next.setHours(9, 0, 0, 0);
    return next;
}

export function snoozeIso(which, now) {
    return formatIsoWithOffset(snoozeMoment(which, now));
}
