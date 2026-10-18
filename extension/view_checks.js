// SPDX-License-Identifier: GPL-2.0-or-later
//
// Assertions for the popup mapping. Run with `gjs -m` or `node`.

import {
    BRIDGE_DOWN,
    BUS_NAME,
    ITEM_FILTER,
    OBJECT_PATH,
    PROXY_METHODS,
    PROXY_SIGNALS,
    UPDATE_MESSAGE,
    formatLastSeen,
    indicatorView,
    itemKey,
    menuModel,
    notificationModel,
    performCall,
    snoozeCall,
    snoozeIso,
    snoozeMoment,
} from './view.js';

function assert(condition, message) {
    if (!condition)
        throw new Error(message);
}

const NOW = Date.parse('2026-10-17T12:00:00Z');

function ask(extra = {}) {
    return {
        key: 'primary/sample-01',
        id: 'sample-01',
        kind: 'ask',
        title: 'Approve the sample',
        status: 'open',
        due: '2026-10-18',
        actions: ['approve', 'veto'],
        source: {bot: 'primary'},
        ...extra,
    };
}

export function runViewChecks() {
    assert(BUS_NAME === 'io.github.grokkinggrok.TetherBot1', 'bus name');
    assert(OBJECT_PATH === '/io/github/grokkinggrok/TetherBot1', 'object path');
    assert(ITEM_FILTER === '{"include_snoozed":false}', 'item filter');
    assert(PROXY_METHODS.includes('PerformActionRemote'), 'perform method');
    assert(PROXY_SIGNALS.includes('NotificationRequested'), 'notify signal');

    const down = indicatorView({running: false, state: '', counts: {asks: 2, todos: 3}});
    assert(down.dimmed === true, 'down is dimmed');
    assert(down.badge === 0, 'down hides the badge');
    assert(down.accessibleName === 'TetherBot: bridge not running', 'down name');
    assert(down.iconName === 'network-offline-symbolic', 'down icon');

    const closed = indicatorView({
        running: true,
        state: 'failed_closed',
        counts: {asks: 2, todos: 3},
    });
    assert(closed.dimmed === true, 'failed_closed is dimmed');
    assert(closed.accessibleName === 'TetherBot: 2 asks, 3 todos', 'closed still counts');
    assert(closed.attention === false, 'dimmed is not attention');

    const attention = indicatorView({
        running: true,
        state: 'ok',
        counts: {asks: 2, todos: 3},
    });
    assert(attention.badge === 5, 'badge is asks plus todos');
    assert(attention.attention === true, 'open asks are attention');
    assert(attention.iconName === 'emblem-important-symbolic', 'attention icon');
    assert(attention.accessibleName === 'TetherBot: 2 asks, 3 todos', 'count name');

    const quiet = indicatorView({running: true, state: 'ok', counts: {asks: 0, todos: 1}});
    assert(quiet.attention === false, 'todos alone are not attention');
    assert(quiet.iconName === 'mail-unread-symbolic', 'quiet icon');

    const offlineMenu = menuModel({
        running: false,
        state: '',
        reason: '',
        bots: [{name: 'primary'}],
        items: [ask()],
        queueLength: 4,
        nowMs: NOW,
    });
    assert(offlineMenu.banner === BRIDGE_DOWN, 'bridge down banner');
    assert(offlineMenu.asks.length === 0, 'no asks while down');
    assert(offlineMenu.bots.length === 0, 'no bots while down');
    assert(offlineMenu.footer === null, 'no footer while down');

    const menu = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [
            {
                name: 'primary',
                display_name: 'primary',
                state: 'ok',
                summary: 'Idle',
                last_seen: Math.floor(NOW / 1000) - 240,
                routes: {outbound: true},
            },
            {
                name: 'notes',
                summary: '',
                last_seen: 0,
                routes: {outbound: false},
            },
        ],
        items: [
            ask(),
            ask({
                key: 'primary/later',
                title: 'Later',
                local: {snoozed_until: '2026-10-17T13:00:00+00:00'},
            }),
            {
                key: 'primary/todo-1',
                kind: 'todo',
                title: 'Send the note',
                status: 'open',
                actions: ['done'],
                source: {bot: 'primary'},
            },
            {
                key: 'notes/todo-2',
                kind: 'todo',
                title: 'Local only',
                status: 'open',
                actions: ['done'],
                source: {bot: 'notes'},
            },
            {
                key: 'primary/watch-1',
                kind: 'watch',
                title: 'A bill',
                status: 'open',
                amount: '12.00',
            },
        ],
        queueLength: 2,
        nowMs: NOW,
    });
    assert(menu.banner === '', 'ok has no banner');
    assert(menu.asks.length === 1, 'snoozed ask is hidden');
    assert(menu.asks[0].actions.join(',') === 'approve,veto', 'ask buttons');
    assert(menu.asks[0].due === '2026-10-18', 'ask due');
    assert(menu.todos.length === 2, 'both todos are listed');
    assert(menu.todos[0].canSendDone === true, 'routed todo can send done');
    assert(menu.todos[1].canSendDone === false, 'unrouted todo is not sent');
    assert(menu.bots[0].lastSeen === 'last seen 4 m ago', 'relative last seen');
    assert(menu.bots[1].lastSeen === 'last seen unknown', 'missing last seen');
    assert(menu.footer.queueLength === 2, 'queue length');
    assert(!JSON.stringify(menu).includes('12.00'), 'watch amount stays out of this menu');

    const stale = menuModel({
        running: true,
        state: 'degraded',
        reason: 'feed/primary.json: unsupported schema tetherbot/2, update tetherbot',
        bots: [],
        items: [ask()],
        queueLength: 0,
        nowMs: NOW,
    });
    assert(stale.banner === UPDATE_MESSAGE, 'schema banner');
    assert(stale.asks.length === 1, 'stale feed keeps the ask on screen');

    assert(formatLastSeen(Math.floor(NOW / 1000) - 10, NOW) === 'last seen just now', 'just now');
    assert(itemKey({id: 'sample-01', source: {bot: 'primary'}}) === 'primary/sample-01', 'derived key');

    const notified = notificationModel(JSON.stringify({
        id: 'sample-01',
        title: 'Approve the sample',
        body: 'Details',
        actions: ['approve', 'veto'],
        source: {bot: 'primary'},
    }), 'new');
    const labels = notified.actions.map(action => action.label);
    assert(labels.join(',') === 'Approve,Veto,Snooze 1 h,Snooze until tomorrow,Open chat', 'notify buttons');
    assert(notified.actions[0].key === 'primary/sample-01', 'notify key');

    const repaste = notificationModel({
        title: 'Re-paste key',
        body: 'The route stopped',
        bot: 'primary',
        slot: 'primary-actions',
        actions: ['request_secret'],
    }, 're-paste');
    assert(repaste.actions.length === 1, 're-paste has one button');
    assert(repaste.actions[0].id === 'request_secret', 're-paste action');
    assert(repaste.actions[0].slot === 'primary-actions', 're-paste slot');

    const failed = notificationModel({
        title: 'Delivery failed',
        body: 'rate cap',
        bot: 'primary',
    }, 'delivery_failed');
    assert(failed.actions.map(action => action.id).join(',') === 'open_chat', 'delivery opens chat');

    assert(performCall('approve', 'primary/sample-01').args.join('|') === 'primary/sample-01|approve|{}', 'approve call');
    const hour = snoozeMoment('hour', new Date(NOW));
    assert(hour.getTime() - NOW === 60 * 60 * 1000, 'snooze one hour');
    const tomorrow = snoozeMoment('tomorrow', new Date(NOW));
    assert(tomorrow.getHours() === 9 && tomorrow.getMinutes() === 0, 'snooze at 09:00');
    const iso = snoozeIso('hour', new Date(NOW));
    assert(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(iso), 'snooze offset');
    assert(snoozeCall('primary/sample-01', iso).method === 'Snooze', 'snooze method');
}

if (typeof process !== 'undefined' && process.argv[1] && process.argv[1].endsWith('view_checks.js'))
    runViewChecks();
