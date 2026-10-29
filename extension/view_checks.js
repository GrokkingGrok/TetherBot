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
    approvalCount,
    elapsedSeconds,
    formatElapsed,
    formatLastSeen,
    formatTopBar,
    topBarWidthSample,
    formatTracked,
    keepAssigning,
    parseStartClock,
    todoActivation,
    isMainWindow,
    isClipEditor,
    clipEditorFrame,
    topRightFrame,
    WINDOW_APP_ID,
    indicatorView,
    badgeBox,
    panelIcon,
    overdueCount,
    itemKey,
    parseSetTime,
    timerModel,
    compactBotSection,
    summaryTone,
    chipSequence,
    menuModel,
    dueUndoKeys,
    menuClosePlan,
    nextUndoDelay,
    noticeKey,
    notificationModel,
    shareUndoWindow,
    botRowCall,
    openWindowCall,
    performCall,
    snoozeCall,
    snoozeIso,
    snoozeMoment,
    startServiceCall,
    startWindowCall,
    clipOpenPlan,
    openWindowKey,
    openWindowDispatch,
    openWindowResult,
    windowServicePlan,
    OPEN_WINDOW_ERROR,
    todoFilter,
    undoCall,
    undoFraction,
    presentTodos,
    mergeTodoSearch,
    actionResultNotice,
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

    const down = indicatorView({running: false, state: '', items: [ask()]});
    assert(down.dimmed === true, 'down is dimmed');
    assert(down.mark === 'slash', 'down uses the slash');
    assert(down.text === '', 'down hides the time');
    assert(down.accessibleName === 'TetherBot: bridge not running', 'down name');
    assert(down.iconFile === 'slash', 'down icon');
    assert(down.overlay === '', 'a slash has no colored mark');

    const closed = indicatorView({
        running: true,
        state: 'failed_closed',
        items: [ask()],
    });
    assert(closed.dimmed === true, 'failed_closed is dimmed');
    assert(closed.mark === 'slash', 'failed_closed uses the slash');
    assert(closed.accessibleName === 'TetherBot: bridge not running', 'failed_closed name');

    const attention = indicatorView({
        running: true,
        state: 'ok',
        items: [ask(), ask({key: 'primary/sample-02', id: 'sample-02'})],
        nowMs: NOW,
    });
    assert(attention.mark === 'dot', 'open asks are the dot');
    assert(attention.iconFile === 'base', 'the face stays the symbolic icon');
    assert(attention.overlay === 'blue', 'an ask adds the blue dot');
    assert(attention.text === '', 'asks add no toolbar number');
    assert(attention.accessibleName === 'TetherBot: an ask is waiting', 'approval name');

    const quiet = indicatorView({
        running: true,
        state: 'ok',
        items: [],
        nowMs: NOW,
    });
    assert(quiet.mark === null, 'an empty list has no badge');
    assert(quiet.iconFile === 'base', 'clear icon');
    assert(quiet.overlay === '', 'a clear icon has no mark');
    assert(quiet.accessibleName === 'TetherBot: all clear', 'clear name');

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
    assert(waitingIcon.mark === null, 'starting has no slash yet');
    assert(waitingIcon.accessibleName === 'TetherBot', 'starting name');
    assert(PROXY_SIGNALS.includes('TimerChanged'), 'timer signal');
    assert(PROXY_METHODS.includes('GetTimerRemote'), 'get timer method');
    assert(formatElapsed(42 * 60 + 10) === '42:10', 'minutes and seconds');
    assert(formatElapsed(3600 + 42 * 60 + 10) === '1:42:10', 'hours');
    assert(formatTopBar(0) === '0m', 'zero minutes');
    assert(formatTopBar(5 * 60) === '5m', 'five minutes');
    assert(formatTopBar(41 * 60) === '41m', 'forty one minutes');
    assert(formatTopBar(3600 + 5 * 60) === '1:05', 'one hour five');
    assert(formatTopBar(12 * 3600 + 40 * 60) === '12:40', 'twelve forty');
    assert(formatTopBar(42 * 60 + 10) === '42m', 'top bar drops seconds');
    assert(formatTopBar(-1) === '--:--', 'top bar dashes');
    assert(topBarWidthSample('5m') === '8m', 'one minute digit shares a width');
    assert(topBarWidthSample('41m') === '88m', 'two minute digits share a width');
    assert(topBarWidthSample('1:29') === '8:88', 'hour clock sample');
    assert(topBarWidthSample('1:05') === topBarWidthSample('1:29'), 'same clock width');
    assert(topBarWidthSample('12:40') === '88:88', 'two hour digits');
    assert(topBarWidthSample('5m').length < topBarWidthSample('41m').length, '5m is narrower');
    assert(topBarWidthSample('41m').length < topBarWidthSample('1:29').length, 'minutes are narrower than a clock');
    assert(topBarWidthSample('') === '', 'no timer has no width');
    assert(topBarWidthSample('--:--') === '88:88', 'warning width');
    const clockNow = new Date(2026, 9, 19, 12, 0, 0).getTime();
    assert(parseStartClock('11:00', clockNow) ===
        Math.floor(new Date(2026, 9, 19, 11, 0, 0).getTime() / 1000), 'start earlier today');
    assert(parseStartClock('13:05', clockNow) ===
        Math.floor(new Date(2026, 9, 18, 13, 5, 0).getTime() / 1000), 'start yesterday');
    assert(parseStartClock('24:00', clockNow) === null, 'hour out of range');
    assert(formatElapsed(-3) === '--:--', 'negative time is dashes');
    assert(formatTracked(3600 + 42 * 60) === '1:42 tracked', 'tracked chip');
    assert(parseSetTime('1:42') === 3600 + 42 * 60, 'set time hours');
    assert(parseSetTime('1:60') === null, 'set time rejects a bad minute');
    const activation = startServiceCall();
    assert(activation.method === 'StartServiceByName', 'activation method');
    assert(activation.name === BUS_NAME, 'activation name');
    assert(activation.flags === 0, 'activation flags');
    assert(activation.interfaceName === 'org.freedesktop.DBus', 'activation interface');
    assert(ACTIVATE_RETRY_MS >= 2000 && ACTIVATE_RETRY_MS <= 10000, 'activation retry');
    const windowStart = startWindowCall();
    assert(windowStart.method === 'StartServiceByName', 'window activation method');
    assert(windowStart.name === WINDOW_APP_ID, 'window activation name');
    assert(windowStart.flags === 0, 'window activation flags');
    assert(clipOpenPlan({bridgeOwned: false, windowOwned: true, retried: false}) === 'bridge-down',
        'a dead bridge stays down');
    assert(clipOpenPlan({bridgeOwned: true, windowOwned: false, retried: false}) === 'activate-window',
        'a dead window is started');
    assert(clipOpenPlan({bridgeOwned: true, windowOwned: false, retried: true}) === 'open',
        'one retry opens');
    assert(clipOpenPlan({bridgeOwned: true, windowOwned: true, retried: false}) === 'open',
        'an owned window opens');
    assert(openWindowKey(undefined) === null, 'a call with no intent is ignored');
    assert(openWindowKey(null) === '', 'null opens the main window');
    assert(openWindowKey('') === '', 'an empty key opens the main window');
    assert(openWindowCall(openWindowKey('')).args[0] === '',
        'Open TetherBot uses the main-window key');
    assert(openWindowKey('bots') === 'bots', 'a page key is kept');
    assert(openWindowDispatch({inFlight: false}) === 'send', 'the first open is sent');
    assert(openWindowDispatch({inFlight: true}) === 'queue', 'a second press waits');
    assert(windowServicePlan({owned: false, activating: false}) === 'start',
        'a missing window starts');
    assert(windowServicePlan({owned: true, activating: false}) === 'skip',
        'an owned window is not started again');
    assert(windowServicePlan({owned: false, activating: true}) === 'skip',
        'one activation is enough');
    assert(openWindowResult({opened: true, bridgeOwned: true, attempt: 0}) === 'done',
        'an open window is done');
    assert(openWindowResult({opened: false, bridgeOwned: false, attempt: 0}) === 'done',
        'a dead bridge stays quiet');
    assert(openWindowResult({opened: false, bridgeOwned: true, attempt: 0}) === 'retry',
        'one failure tries again');
    assert(openWindowResult({opened: false, bridgeOwned: true, attempt: 1}) === 'error',
        'the second failure is the menu line');
    assert(OPEN_WINDOW_ERROR === "Couldn't open TetherBot.", 'open failure line');

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
    assert(menu.bots.length === 1, 'a healthy second bot stays off the popup');
    assert(menu.botSummary.text === '2 bots · primary needs attention', 'summary names the bot');
    assert(menu.botSummary.tone === 'warn', 'needs attention is amber');
    assert(menu.asks[0].botLabel === 'primary', 'ask names its bot');
    const notesOnly = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'notes', summary: '', last_seen: 0, routes: {outbound: false}}],
        items: [],
        queueLength: 0,
        nowMs: NOW,
    });
    assert(notesOnly.botSummary === null, 'one bot has no summary line');
    assert(notesOnly.bots[0].lastSeen === 'last seen unknown', 'missing last seen');
    assert(notesOnly.bots[0].nextRun === '', 'missing next run');
    const healthy = compactBotSection([
        {name: 'Primary', bot: 'primary', state: 'idle', openAsks: 0},
        {name: 'Notes', bot: 'notes', state: 'working', openAsks: 0},
        {name: 'Other', bot: 'other', state: 'idle', openAsks: 0},
    ]);
    assert(healthy.summary.text === '3 bots · all ok', 'healthy bots are one line');
    assert(healthy.rows.length === 0, 'healthy bots have no rows');
    const pending = compactBotSection([
        {name: 'Primary', bot: 'primary', state: 'idle', openAsks: 2},
        {name: 'Notes', bot: 'notes', state: 'idle', openAsks: 0},
    ]);
    assert(pending.rows.length === 1, 'an open ask keeps that bot row');
    assert(pending.summary.text === '2 bots · Primary needs attention', 'one problem names the bot');
    assert(pending.summary.tone === 'warn', 'an open ask is a warning');
    const broken = compactBotSection([
        {name: 'Primary', bot: 'primary', state: 'error', openAsks: 0},
        {name: 'Notes', bot: 'notes', state: 'idle', openAsks: 0},
    ]);
    assert(broken.summary.tone === 'error', 'a bot error stays red');
    const bridgeDown = compactBotSection([
        {name: 'Primary', bot: 'primary', state: 'failed_closed', openAsks: 0},
        {name: 'Notes', bot: 'notes', state: 'needs_you', openAsks: 0},
    ]);
    assert(bridgeDown.summary.tone === 'error', 'a bridge failure stays red');
    assert(summaryTone([
        {name: 'Primary', state: 'needs_you', openAsks: 0},
        {name: 'Notes', state: 'idle', openAsks: 0},
    ]) === 'warn', 'needs_you is amber');
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
    assert(labels.join(',') === 'Approve,Veto,Snooze 1 h,Snooze until tomorrow', 'notify buttons');
    assert(!notified.actions.some(action => action.id === 'open_chat'), 'no open chat button');
    assert(notified.actions[0].key === 'primary/sample-01', 'notify key');
    const sample = {
        id: 'sample-01',
        title: 'Finish the open checks',
        updated_at: '2026-10-17T11:40:00+00:00',
        source: {bot: 'primary'},
    };
    const seen = noticeKey(sample, 'new');
    assert(seen && seen === noticeKey(JSON.stringify(sample), 'new'), 'one token for one item');
    assert(noticeKey(sample, 'due_soon') !== seen, 'a later nudge is a different token');
    assert(noticeKey({title: 'Accepted'}, 'action_result') === '', 'a result with no key is not deduped');
    const listedChat = notificationModel({
        id: 'sample-01',
        title: 'Hello',
        actions: ['open_chat', 'approve'],
        source: {bot: 'primary'},
    }, 'new');
    assert(!listedChat.actions.some(action => action.id === 'open_chat'), 'listed open_chat is not a button');
    assert(listedChat.actions.some(action => action.id === 'approve'), 'approve stays on the notification');

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
    assert(failed.actions.length === 0, 'delivery has no chat button');

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
                priority: {label: 'High priority', tone: 'red'},
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
    assert(rich.todos[0].chips.priority === 'High priority', 'priority chip');
    assert(rich.todos[0].chips.priorityTone === 'red', 'priority tone');
    const order = chipSequence(rich.todos[0].chips, '1h', 'Primary');
    assert(order.map(chip => chip.text).join('|') ===
        'Primary|Due Sat 10/17 15:00|High priority|@home|@errand|@wool|+1|1h',
    'chip order');
    assert(order.map(chip => chip.tone).join('|') ===
        'neutral|amber|red|teal|blue|green|neutral|neutral', 'chip tones');
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
    assert(undone.todos[0].undoFraction > 0, 'undo bar starts full');

    const stayed = presentTodos(
        [
            {key: 'a', title: 'A'},
            {key: 'c', title: 'C'},
        ],
        [{
            key: 'b',
            until: NOW + 5000,
            index: 1,
            row: {key: 'b', title: 'B'},
        }],
        NOW
    );
    assert(stayed.todos.map(row => row.key).join(',') === 'a,b,c', 'undo stays where it was');
    assert(stayed.todos[1].undoFraction === 1, 'a new undo has the full window');

    const shared = shareUndoWindow([
        {key: 'a', until: NOW + 1000, sent: false, index: 0, after: 'b', row: {key: 'a', title: 'A'}},
        {key: 'b', until: NOW + 1000, sent: false, index: 1, after: 'c', row: {key: 'b', title: 'B'}},
    ], NOW + 4000);
    assert(shared[0].until === shared[1].until, 'one shared window');
    assert(shared[0].until === NOW + 4000 + 5000, 'a new done restarts it');
    const together = presentTodos([{key: 'c', title: 'C'}], shared, NOW + 4000);
    assert(together.todos.map(row => row.key).join(',') === 'a,b,c', 'both pending rows stay');
    assert(together.todos[0].undoFraction === 1, 'the first bar restarts full');
    assert(together.todos[1].undoFraction === 1, 'the second bar matches it');
    assert(dueUndoKeys(shared, NOW + 4000 + 5000).join(',') === 'a,b', 'they send together');
    assert(dueUndoKeys(shared.filter(hold => hold.key !== 'a'), NOW + 4000 + 5000).join(',') === 'b', 'undo drops one row');
    const early = menuClosePlan(shared, NOW + 4000);
    assert(early.send.length === 0, 'closing early sends nothing');
    assert(early.keep.map(hold => hold.key).join(',') === 'a,b', 'undo stays available');
    const ended = menuClosePlan(shared, NOW + 4000 + 5000);
    assert(ended.send.join(',') === 'a,b', 'the bar ending sends the batch');
    assert(ended.keep.length === 0, 'a finished batch is not kept');
    const kept = menuClosePlan(shared.filter(hold => hold.key !== 'a'), NOW + 4000);
    assert(kept.send.length === 0, 'undo removes that row from the close batch');
    assert(kept.keep.map(hold => hold.key).join(',') === 'b', 'the other row is still held');
    assert(nextUndoDelay(shared, NOW + 4000) === 5000, 'the shared window is the next expiry');
    assert(undoFraction(NOW + 5000, NOW + 4000) === 0.2, 'the bar matches the time left');

    const pinned = presentTodos(
        [{key: 'c', title: 'C'}],
        [{key: 'a', until: NOW, sent: true, index: 0, row: {key: 'a', title: 'A'}}],
        NOW,
        true
    );
    assert(pinned.todos.map(row => row.key).join(',') === 'a,c', 'hover keeps the expired row');
    assert(pinned.todos[0].undo === false, 'the expired button is gone');
    assert(pinned.todos[0].layoutHold === true, 'the row keeps its place');
    const hidden = presentTodos(
        [
            {key: 'a', title: 'A'},
            {key: 'c', title: 'C'},
        ],
        [],
        NOW,
        false,
        ['a']
    );
    assert(hidden.todos.map(row => row.key).join(',') === 'c', 'a sent row stays out of the list');

    const filtered = JSON.parse(todoFilter(' @home due:today '));
    assert(filtered.kinds.join(',') === 'todo', 'search stays on todos');
    assert(filtered.query === '@home due:today', 'search query');
    assert(filtered.include_snoozed === false, 'search hides snoozed');
    const asksKept = mergeTodoSearch(
        [ask(), {key: 'primary/todo-1', kind: 'todo', title: 'Old', status: 'open'}],
        [{key: 'primary/todo-9', kind: 'todo', title: 'Found', status: 'open'}]
    );
    assert(asksKept.length === 2, 'search keeps asks');
    assert(asksKept[0].kind === 'ask', 'ask stays first');
    assert(asksKept[1].title === 'Found', 'searched todo replaces the list');

    assert(openWindowCall('primary/rich').args[0] === 'primary/rich', 'open one item');
    assert(openWindowCall('').args[0] === '', 'open the list');
    assert(undoCall('primary/todo-1').method === 'Undo', 'undo method');
    assert(PROXY_METHODS.includes('OpenWindowRemote'), 'open window method');
    assert(PROXY_METHODS.includes('UndoRemote'), 'undo remote');

    const runningTimer = {
        state: 'running',
        item_key: 'primary/q4-budget',
        item_title: 'Draft Q4 grant budget',
        accumulated_s: 0,
        running_since: NOW / 1000 - (3600 + 42 * 60 + 10),
    };
    const withTime = indicatorView({
        running: true,
        state: 'ok',
        items: [ask()],
        timer: runningTimer,
        nowMs: NOW,
    });
    assert(withTime.mark === 'dot', 'approval outranks the timer');
    assert(withTime.text === '1:42', 'time shows beside the dot');
    assert(withTime.accessibleName ===
        'TetherBot: timer running, 1 hour 42 minutes. an ask is waiting',
    'timer and approval name');
    const overdueItem = {
        key: 'primary/fair',
        kind: 'todo',
        title: 'Order banner for the fair',
        status: 'open',
        due: '2026-10-16',
        owner: 'user',
        actions: ['done'],
    };
    const botTodo = {...overdueItem, key: 'primary/bot', owner: 'bot'};
    const overdueOnly = indicatorView({
        running: true,
        state: 'ok',
        items: [overdueItem, botTodo, overdueItem],
        nowMs: NOW,
    });
    assert(overdueOnly.mark === 'ring', 'open todos use the red badge');
    assert(overdueOnly.iconFile === 'base' && overdueOnly.overlay === 'red', 'the todo dot sits on the symbolic face');
    assert(overdueOnly.text === '', 'open todos add no toolbar number');
    assert(overdueCount([overdueItem, botTodo], NOW) === 1, 'bot todos are not overdue');
    assert(overdueOnly.accessibleName === 'TetherBot: open todos', 'open todo name');
    const plainTodo = indicatorView({
        running: true,
        state: 'ok',
        items: [{
            key: 'primary/bag',
            kind: 'todo',
            title: 'Pack the bag',
            status: 'open',
            owner: 'user',
            actions: ['done'],
        }],
        nowMs: NOW,
    });
    assert(plainTodo.mark === 'ring', 'a todo that is not overdue still marks the icon');
    assert(plainTodo.overlay === 'red', 'a plain todo adds the red dot');
    assert(plainTodo.text === '', 'a plain todo adds no number');
    const needy = indicatorView({
        running: true,
        state: 'ok',
        items: [],
        bots: [{name: 'notes', state: 'needs_you', open_asks: 0}],
        nowMs: NOW,
    });
    assert(needy.mark === 'dot', 'a bot that needs attention uses the dot');
    assert(needy.overlay === 'blue' && needy.iconFile === 'base', 'attention keeps the symbolic face');
    assert(needy.text === '', 'attention adds no number');
    assert(needy.accessibleName === 'TetherBot: a bot needs attention', 'attention name');
    const bothMarks = indicatorView({
        running: true,
        state: 'ok',
        items: [{
            key: 'primary/bag',
            kind: 'todo',
            title: 'Pack the bag',
            status: 'open',
            actions: ['done'],
        }],
        bots: [{name: 'notes', state: 'needs_you', open_asks: 0}],
        nowMs: NOW,
    });
    assert(bothMarks.mark === 'dot', 'attention outranks open todos');
    assert(bothMarks.overlay === 'blue', 'an ask keeps the blue dot');
    assert(bothMarks.text === '', 'the toolbar still has no count');
    const staleFeed = indicatorView({
        running: true,
        state: 'degraded',
        reason: 'feed is stale',
        items: [],
        nowMs: NOW,
    });
    assert(staleFeed.mark === null, 'a stale feed stays in the popup');
    const paused = indicatorView({
        running: true,
        state: 'ok',
        timer: {
            state: 'paused',
            item_title: 'Email venue about deposit',
            accumulated_s: 25 * 60 + 3,
            running_since: null,
        },
        nowMs: NOW,
    });
    assert(paused.showPause === true, 'paused shows pause bars');
    assert(paused.textStyle === 'paused', 'paused time is dimmed');
    assert(paused.text === '25m', 'paused time');
    assert(paused.accessibleName ===
        'TetherBot: timer paused at 25 minutes, Email venue about deposit',
    'paused name');
    const warned = indicatorView({
        running: true,
        state: 'ok',
        items: [ask()],
        timer: {...runningTimer, warning: 'clock_backward'},
        nowMs: NOW,
    });
    assert(warned.mark === 'dot', 'approval outranks the triangle');
    assert(warned.text === '--:--', 'a warning hides the number');
    const warnedAlone = indicatorView({
        running: true,
        state: 'ok',
        timer: {...runningTimer, warning: 'over_limit'},
        nowMs: NOW,
    });
    assert(warnedAlone.mark === 'triangle', 'clock warning is the triangle');
    assert(warnedAlone.accessibleName === 'TetherBot: timer needs a check', 'warning name');
    const negative = indicatorView({
        running: true,
        state: 'ok',
        timer: {...runningTimer, running_since: NOW / 1000 + 50, warning: null},
        nowMs: NOW,
    });
    assert(negative.text === '--:--', 'negative math is dashes');
    assert(elapsedSeconds(runningTimer, NOW / 1000) === 3600 + 42 * 60 + 10, 'elapsed math');
    const block = timerModel({
        running: true,
        timer: runningTimer,
        nowMs: NOW,
    });
    assert(block.kind === 'running', 'running block');
    assert(block.actions.join(',') === 'Pause,Stop,Edit start', 'running actions');
    const editing = timerModel({
        running: true,
        timer: runningTimer,
        nowMs: NOW,
        editingStart: true,
    });
    assert(editing.kind === 'edit-start', 'edit start');
    assert(editing.actions.join(',') === '-1m,-5m,-15m,-30m,Cancel', 'quick shifts');
    assert(editing.time === '1:42:10', 'edit start shows the clock');
    const loose = timerModel({
        running: true,
        timer: {...runningTimer, item_key: '', item_title: ''},
        nowMs: NOW,
    });
    assert(loose.actions.includes('Add to a todo'), 'a running timer can be attached');
    assert(block.subject === 'Draft Q4 grant budget', 'timer subject');
    const stopped = timerModel({
        running: true,
        timer: {
            state: 'idle',
            undo: {
                kind: 'undo',
                until: NOW / 1000 + 4,
                timer_id: 'tm-1',
                item_title: 'Draft Q4 grant budget',
                recorded_s: 3600 + 42 * 60 + 10,
            },
        },
        nowMs: NOW,
    });
    assert(stopped.kind === 'undo', 'stop undo');
    assert(stopped.title === 'Recorded 1:42:10 on Draft Q4 grant budget', 'recorded line');
    const standalone = timerModel({
        running: true,
        timer: {
            state: 'stopped',
            accumulated_s: 41 * 60,
            timer_id: 'tm-2',
            undo: {
                kind: 'undo',
                until: NOW / 1000 + 4,
                timer_id: 'tm-2',
                recorded_s: 41 * 60,
            },
        },
        nowMs: NOW,
    });
    assert(standalone.kind === 'stopped', 'stopped stays in the popup');
    assert(standalone.title === 'Stopped 41m', 'stopped title');
    assert(standalone.actions.join(',') === 'Add to a todo,Dismiss', 'assign or dismiss');
    assert(standalone.undo && standalone.undo.action === 'Undo', 'undo after stop');
    const picking = timerModel({
        running: true,
        assigning: true,
        timer: {
            state: 'stopped',
            accumulated_s: 41 * 60,
            timer_id: 'tm-2',
        },
        nowMs: NOW,
    });
    assert(picking.actions.join(',') === 'Cancel', 'pick can cancel');
    const faded = timerModel({
        running: true,
        timer: {state: 'stopped', accumulated_s: 41 * 60, timer_id: 'tm-2'},
        nowMs: NOW,
    });
    assert(faded.kind === 'stopped', 'a faded prompt keeps the stopped time');
    assert(faded.undo === null, 'undo is gone after five seconds');
    const stoppedBar = indicatorView({
        running: true,
        state: 'ok',
        timer: {state: 'stopped', accumulated_s: 5 * 60},
        nowMs: NOW,
    });
    assert(stoppedBar.text === '5m', 'stopped top bar');
    assert(stoppedBar.showPause === false, 'stopped has no pause bars');
    assert(stoppedBar.textStyle === 'paused', 'stopped time is dimmed');
    const downBlock = timerModel({running: false, nowMs: NOW});
    assert(downBlock.kind === 'down', 'bridge down block');
    assert(downBlock.body.includes('Saved time is safe'), 'saved time copy');
    const timedMenu = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: [{
            key: 'primary/q4-budget',
            kind: 'todo',
            title: 'Draft Q4 grant budget',
            status: 'open',
            actions: ['done'],
            time_tracked_s: 3600 + 42 * 60,
            source: {bot: 'primary'},
        }],
        queueLength: 0,
        nowMs: NOW,
        timer: runningTimer,
    });
    assert(timedMenu.todos[0].timing === true, 'the timed row says timing');
    assert(timedMenu.todos[0].tracked === '1:42 tracked', 'tracked chip on the row');
    assert(timedMenu.todos[0].pick === false, 'a tied row is not a pick target');
    const pickMenu = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: [{
            key: 'primary/q4-budget',
            kind: 'todo',
            title: 'Draft Q4 grant budget',
            status: 'open',
            actions: ['done'],
            source: {bot: 'primary'},
        }],
        queueLength: 0,
        nowMs: NOW,
        timer: {state: 'stopped', accumulated_s: 60},
        assigning: true,
    });
    assert(pickMenu.todos[0].pick === true, 'a todo row is the pick target');
    assert(pickMenu.todos[0].canStart === true, 'the row can still start later');
    const sendingItem = {
        key: 'primary/q4-budget',
        kind: 'todo',
        title: 'Draft Q4 grant budget',
        status: 'open',
        actions: ['done'],
        source: {bot: 'primary'},
        local: {acted: {action: 'done', action_id: 'a-1'}, sending: 'retry'},
    };
    const sendingMenu = menuModel({
        running: true,
        state: 'ok',
        reason: '',
        bots: [{name: 'primary', routes: {outbound: true}}],
        items: [sendingItem],
        queueLength: 1,
        nowMs: NOW,
    });
    assert(sendingMenu.todos.length === 1, 'a retrying done stays in the menu');
    assert(sendingMenu.todos[0].sending === true, 'the row is sending');
    assert(sendingMenu.todos[0].canSendDone === false, 'done waits for the retry');
    const stillShown = presentTodos(
        sendingMenu.todos,
        [],
        NOW,
        false,
        ['primary/q4-budget']
    );
    assert(stillShown.todos.length === 1, 'a sending row is not hidden');
    assert(actionResultNotice('queued_retry', true) === null, 'a retry is not an error');
    const parkedNotice = actionResultNotice('parked', true);
    assert(parkedNotice.title === "Couldn't send Done. Try again.", 'park tells the user to retry');
    assert(parkedNotice.body === "Couldn't send Done. Try again.", 'park body');
    assert(actionResultNotice('dropped', true).title === "Couldn't send Done. Try again.", 'a dropped done says to retry');
    assert(actionResultNotice('parked', false).title === 'Action failed', 'another park stays a failure');
    assert(actionResultNotice('accepted', true).title === 'Accepted', 'accept stays accepted');
    assert(actionResultNotice('rejected_key', true).title === 'Action failed', 'a rejected key stays a failure');
    const runningLoose = {state: 'running', item_key: '', item_title: ''};
    assert(keepAssigning(true, runningLoose) === true, 'pick stays while choosing a todo');
    assert(keepAssigning(true, {state: 'stopped'}) === true, 'a stopped timer stays pickable');
    assert(keepAssigning(true, runningTimer) === false, 'a tied timer leaves pick mode');
    assert(keepAssigning(false, runningLoose) === false, 'cancel stays cancelled');
    const pickedRow = pickMenu.todos[0];
    const attachClick = todoActivation(pickedRow);
    assert(attachClick.method === 'AssignTimer', 'a picked row attaches');
    assert(attachClick.args[0] === 'primary/q4-budget', 'the click carries the todo key');
    const openClick = todoActivation({...pickedRow, pick: false});
    assert(openClick.method === 'OpenWindow', 'a normal row opens the window');
    const botClick = botRowCall();
    assert(botClick.method === 'OpenWindow' && botClick.args[0] === 'bots', 'a bot row opens the bots tab');
    assert(approvalCount([ask({actions: ['veto']})], NOW) === 0, 'veto alone is not approval');
    assert(panelIcon('dot').file === 'base' && panelIcon('dot').overlay === 'blue', 'ask badge');
    assert(panelIcon('ring').file === 'base' && panelIcon('ring').overlay === 'red', 'todo badge');
    const corner = badgeBox(16, 16);
    assert(corner.span === 4, 'the badge is a quarter of the icon');
    assert(corner.x === 12 && corner.y === 12, 'the badge sits in the bottom-right');
    assert(corner.x + corner.span === 16 && corner.y + corner.span === 16, 'the badge stays inside the icon');
    assert(badgeBox(0, 16).span === 0, 'an unsized icon draws no badge');
    assert(panelIcon('slash').file === 'slash' && panelIcon('slash').overlay === '', 'slash stays symbolic');
    assert(panelIcon('triangle').file === 'triangle' && panelIcon('triangle').overlay === '', 'triangle stays symbolic');
    assert(panelIcon(null).file === 'base' && panelIcon(null).overlay === '', 'a clear face has no overlay');
    assert(WINDOW_APP_ID === 'io.github.grokkinggrok.TetherBot', 'window app id');
    assert(isMainWindow({gtkId: WINDOW_APP_ID}), 'the app id is the main window');
    assert(isMainWindow({wmClass: 'tetherbot-window', title: 'TetherBot'}), 'the startup class counts');
    assert(isMainWindow({title: 'TetherBot'}) === false, 'settings shares the title');
    assert(isMainWindow({wmClass: 'org.gnome.Shell', title: 'TetherBot'}) === false, 'the shell window stays put');
    assert(isMainWindow({gtkId: WINDOW_APP_ID, title: 'Edit clip'}) === false, 'an editor is not the main window');
    assert(isMainWindow({gtkId: WINDOW_APP_ID, title: 'Tag clip'}) === false, 'a tag editor is not the main window');
    assert(isMainWindow({gtkId: WINDOW_APP_ID, title: 'Make a todo with context'}) === false, 'a context editor is not the main window');
    assert(isClipEditor({gtkId: WINDOW_APP_ID, title: 'Edit clip'}), 'the editor shares the app id');
    assert(isClipEditor({wmClass: 'tetherbot-window', title: 'Tag clip'}), 'the startup class can be the editor');
    assert(isClipEditor({wmClass: 'TetherBot', title: 'Make a todo with context'}), 'the wm class can be the editor');
    assert(isClipEditor({title: 'Edit clip'}) === false, 'a title alone is not the editor');
    assert(isClipEditor({wmClass: 'org.gnome.Shell', title: 'Edit clip'}) === false, 'the shell window is not the editor');
    const area = {x: 0, y: 40, width: 1000, height: 800};
    const frame = {width: 480, height: 320};
    const placed = clipEditorFrame(area, frame, {x: 100, y: 200});
    assert(placed.x === 100 && placed.y === 200, 'the editor opens at the pointer');
    const shifted = clipEditorFrame(area, frame, {x: 900, y: 700});
    assert(shifted.x === 520 && shifted.y === 520, 'the editor shifts back onto the work area');
    const clamped = clipEditorFrame(area, frame, {x: -10, y: 0});
    assert(clamped.x === 0 && clamped.y === 40, 'the editor stays inside the work area');
    const huge = clipEditorFrame(area, {width: 2000, height: 2000}, {x: 100, y: 200});
    assert(huge.x === 0 && huge.y === 40, 'a large editor keeps the work area origin');
    const parked = topRightFrame({x: 0, y: 29, width: 1920, height: 1171}, {width: 1280, height: 800});
    assert(parked.x === 640 && parked.y === 29, 'opens at the upper right of the work area');
    assert(parked.width === 1280 && parked.height === 800, 'a short window keeps its height');
    const wide = topRightFrame({x: 0, y: 29, width: 1920, height: 1171}, {width: 1520, height: 900});
    assert(wide.x === 400 && wide.y === 29, 'a wider window still opens at the upper right');
    assert(wide.width === 1520 && wide.height === 900, 'a wider window keeps its size');
    const tall = topRightFrame({x: 10, y: 40, width: 1000, height: 700}, {width: 1280, height: 900});
    assert(tall.x === 10 && tall.y === 40, 'a wide window stays inside the work area');
    assert(tall.height === 700, 'a tall window stops at the work area');
}

if (typeof process !== 'undefined' && process.argv[1] && process.argv[1].endsWith('view_checks.js'))
    runViewChecks();
