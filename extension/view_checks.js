// SPDX-License-Identifier: GPL-2.0-or-later
//
// Assertions for the popup mapping. Run with `gjs -m` or `node`.

import {
    ACTIVATE_RETRY_MS,
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
    openWindowCall,
    performCall,
    snoozeCall,
    snoozeIso,
    snoozeMoment,
    startServiceCall,
    todoFilter,
    undoCall,
    mergeTodoSearch,
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

    const waiting = menuModel({
        running: false,
        activationFailed: false,
        state: '',
        reason: '',
        bots: [{name: 'primary'}],
        items: [ask()],
        queueLength: 1,
        nowMs: NOW,
    });
    assert(waiting.banner === '', 'no banner while the bridge is starting');
    assert(waiting.asks.length === 0, 'no asks while the bridge is starting');
    const waitingIcon = indicatorView({
        running: false,
        activationFailed: false,
        state: '',
        counts: {asks: 1, todos: 0},
    });
    assert(waitingIcon.dimmed === true, 'starting stays dimmed');
    assert(waitingIcon.accessibleName === 'TetherBot', 'starting name');
    const activation = startServiceCall();
    assert(activation.method === 'StartServiceByName', 'activation method');
    assert(activation.name === BUS_NAME, 'activation name');
    assert(activation.flags === 0, 'activation flags');
    assert(activation.interfaceName === 'org.freedesktop.DBus', 'activation interface');
    assert(ACTIVATE_RETRY_MS >= 2000 && ACTIVATE_RETRY_MS <= 10000, 'activation retry');

    const menu = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [
            {
                name: 'primary',
                display_name: 'primary',
                state: 'needs_you',
                summary: '1 open ask.',
                last_seen: Math.floor(NOW / 1000) - 240,
                next_run: Math.floor(NOW / 1000) + 3600,
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
            ask({
                key: 'primary/vetoed',
                title: 'Already vetoed',
                local: {
                    acted: {
                        action: 'veto',
                        action_id: 'a-veto1',
                        at: '2026-10-17T12:00:00+00:00',
                    },
                },
            }),
            {
                key: 'primary/todo-1',
                kind: 'todo',
                title: 'Send the note',
                status: 'open',
                due: '2026-10-19',
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
    assert(menu.asks.length === 1, 'snoozed and acted asks are hidden');
    assert(menu.asks[0].actions.join(',') === 'approve,veto', 'ask buttons');
    assert(menu.asks[0].due === '2026-10-18', 'ask due');
    assert(menu.todos.length === 2, 'both todos are listed');
    assert(menu.todos[0].title === 'Send the note', 'todo title');
    assert(menu.todos[0].due === '2026-10-19', 'todo due');
    assert(menu.todos[0].chips === null, 'old todo has no chips');
    assert(menu.todos[0].undo === false, 'fresh todo is not an undo row');
    assert(menu.todos[1].due === '', 'todo due is optional');
    assert(menu.todos[0].canSendDone === true, 'routed todo can send done');
    assert(menu.todos[1].canSendDone === false, 'unrouted todo is not sent');
    assert(menu.bots[0].state === 'needs_you', 'per-bot state');
    assert(menu.bots[0].summary === '1 open ask.', 'feed summary');
    assert(menu.bots[0].lastSeen === 'last seen 4 m ago', 'relative last seen');
    assert(menu.bots[0].nextRun === 'next run in 1 h', 'next run');
    assert(menu.bots[1].lastSeen === 'last seen unknown', 'missing last seen');
    assert(menu.bots[1].nextRun === '', 'missing next run');
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

    const rich = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: [{
            key: 'primary/rich',
            kind: 'todo',
            title: 'Pack the bag',
            status: 'open',
            due: '2026-10-17 15:00',
            actions: ['done'],
            source: {bot: 'primary'},
            chips: {
                priority: {label: '#1', tone: 'red'},
                due: {label: 'Due Sat 10/17 15:00', tone: 'amber'},
                tags: [
                    {tag: 'home', label: '@home', tone: 'teal'},
                    {tag: 'errand', label: '@errand', tone: 'blue'},
                    {tag: 'wool', label: '@wool', tone: 'green'},
                    {tag: 'extra', label: '@extra', tone: 'pink'},
                ],
            },
        }],
        queueLength: 0,
        nowMs: NOW,
    });
    assert(rich.todos[0].chips.priority === '#1', 'priority chip');
    assert(rich.todos[0].chips.priorityTone === 'red', 'priority tone');
    assert(rich.todos[0].chips.due === 'Due Sat 10/17 15:00', 'due chip');
    assert(rich.todos[0].chips.tags.length === 3, 'three tags');
    assert(rich.todos[0].chips.extra === 1, 'extra tag count');
    assert(rich.todos[0].due === '2026-10-17 15:00', 'raw due stays');

    const many = [];
    for (let index = 0; index < 9; index++) {
        many.push({
            key: `primary/t${index}`,
            kind: 'todo',
            title: `Todo ${index}`,
            status: 'open',
            actions: ['done'],
            source: {bot: 'primary'},
        });
    }
    const capped = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: many,
        queueLength: 0,
        nowMs: NOW,
    });
    assert(capped.todos.length === 8, 'popup shows eight todos');
    assert(capped.moreLabel === 'Open TetherBot to see all 9', 'the rest stay behind the window');

    const undone = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: [],
        queueLength: 1,
        nowMs: NOW,
        undoHolds: [{
            key: 'primary/todo-1',
            until: NOW + 1000,
            row: {
                key: 'primary/todo-1',
                title: 'Send the note',
                bot: 'primary',
                due: '2026-10-19',
                canSendDone: true,
                chips: null,
            },
        }],
    });
    assert(undone.todos.length === 1, 'undo keeps the row');
    assert(undone.todos[0].undo === true, 'undo flag');
    assert(undone.todos[0].canSendDone === false, 'undo replaces done');
    assert(undone.todos[0].title === 'Send the note', 'undo title');

    const filtered = JSON.parse(todoFilter(' @home due:today '));
    assert(filtered.kinds.join(',') === 'todo', 'search stays on todos');
    assert(filtered.query === '@home due:today', 'search query');
    assert(filtered.include_snoozed === false, 'search hides snoozed');
    const asksKept = mergeTodoSearch(
        [ask(), {key: 'primary/todo-1', kind: 'todo', title: 'Old', status: 'open'}],
        [{key: 'primary/todo-9', kind: 'todo', title: 'Found', status: 'open'}],
    );
    assert(asksKept.length === 2, 'search keeps asks');
    assert(asksKept[0].kind === 'ask', 'ask stays first');
    assert(asksKept[1].title === 'Found', 'searched todo replaces the list');

    assert(openWindowCall('primary/rich').args[0] === 'primary/rich', 'open one item');
    assert(openWindowCall('').args[0] === '', 'open the list');
    assert(undoCall('primary/todo-1').method === 'Undo', 'undo method');
    assert(PROXY_METHODS.includes('OpenWindowRemote'), 'open window method');
    assert(PROXY_METHODS.includes('UndoRemote'), 'undo remote');
}

if (typeof process !== 'undefined' && process.argv[1] && process.argv[1].endsWith('view_checks.js'))
    runViewChecks();
