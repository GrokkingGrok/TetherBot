// SPDX-License-Identifier: GPL-2.0-or-later
//
// Popup and notification mapping. This file imports nothing, so a GJS
// test can run it without GNOME Shell. The extension sends the calls.

export const WINDOW_APP_ID = 'io.github.grokkinggrok.TetherBot';
export const BUS_NAME = 'io.github.grokkinggrok.TetherBot1';
export const OBJECT_PATH = '/io/github/grokkinggrok/TetherBot1';
export const ITEM_FILTER = '{"include_snoozed":false}';
export const UPDATE_MESSAGE = 'This feed uses a newer protocol. Update TetherBot.';
export const BRIDGE_DOWN = 'Bridge not running';
export const ACTIVATE_RETRY_MS = 4000;

export function isMainWindow({gtkId, wmClass, title} = {}) {
    // Settings uses the same title inside gnome-shell, so the title alone
    // is not enough. The main window is the GTK application id.
    if (gtkId === WINDOW_APP_ID)
        return true;
    const wm = String(wmClass || '');
    if (wm === WINDOW_APP_ID || wm === 'TetherBot' || wm === 'tetherbot' || wm === 'tetherbot-window')
        return true;
    return title === 'TetherBot' && /tether/i.test(wm) && !/shell|extension/i.test(wm);
}

export function topRightFrame(area, frame) {
    // Upper-right of the work area. A window taller than that area is
    // shortened so the last row is not past the bottom of the screen.
    const width = Math.max(0, Math.round(frame && frame.width || 0));
    let height = Math.max(0, Math.round(frame && frame.height || 0));
    const limit = Math.max(0, Math.round(area && area.height || 0));
    if (limit > 0 && height > limit)
        height = limit;
    const originX = Math.round(area && area.x || 0);
    const room = Math.max(0, Math.round(area && area.width || 0));
    let x = originX + room - width;
    if (width > room)
        x = originX;
    return {
        x,
        y: Math.round(area && area.y || 0),
        width,
        height,
    };
}

export function startServiceCall() {
    return {
        destination: 'org.freedesktop.DBus',
        path: '/org/freedesktop/DBus',
        interfaceName: 'org.freedesktop.DBus',
        method: 'StartServiceByName',
        name: BUS_NAME,
        flags: 0,
    };
}

export const PROXY_METHODS = [
    'GetItemsRemote',
    'PerformActionRemote',
    'SnoozeRemote',
    'OpenChatRemote',
    'SyncNowRemote',
    'RequestSecretEntryRemote',
    'ReloadSettingsRemote',
    'MarkSeenRemote',
    'OpenWindowRemote',
    'UndoRemote',
    'GetTimerRemote',
    'StartTimerRemote',
    'PauseTimerRemote',
    'ResumeTimerRemote',
    'StopTimerRemote',
    'UndoStopTimerRemote',
    'ResolveTimerWarningRemote',
    'AssignStoppedTimerRemote',
    'AdjustTimerStartRemote',
    'SetTimerStartRemote',
    'AssignTimerRemote',
    'DismissTimerRemote',
    'OfferClipboardRemote',
    'OfferClipboardImageRemote',
    'GetClipboardRemote',
    'GetClipboardImageRemote',
    'DeleteClipboardRemote',
    'ClearClipboardRemote',
    'NoteClipboardRemote',
    'PinClipboardRemote',
    'SetClipboardTagsRemote',
    'EditClipboardRemote',
];

export const PROXY_SIGNALS = [
    'ItemsChanged',
    'NotificationRequested',
    'ActionResult',
    'StateChanged',
    'TimerChanged',
    'ClipboardChanged',
];

export const TODO_LIMIT = 8;
export const UNDO_MS = 5000;

export function undoFraction(untilMs, nowMs, windowMs = UNDO_MS) {
    const until = Number(untilMs);
    const now = Number(nowMs);
    const span = Number(windowMs);
    if (!Number.isFinite(until) || !Number.isFinite(now) || !Number.isFinite(span) || span <= 0)
        return 0;
    const remain = until - now;
    if (remain <= 0)
        return 0;
    if (remain >= span)
        return 1;
    return remain / span;
}

export function nextUndoDelay(holds, nowMs) {
    let soonest = 0;
    const now = Number(nowMs);
    for (const hold of holds || []) {
        if (!hold || hold.sent || !(hold.until > now))
            continue;
        const remain = hold.until - now;
        if (!soonest || remain < soonest)
            soonest = remain;
    }
    return soonest;
}

export function shareUndoWindow(holds, nowMs, windowMs = UNDO_MS) {
    const until = Number(nowMs) + Number(windowMs);
    return (holds || []).map(hold => {
        if (!hold || hold.sent)
            return hold;
        return {...hold, until};
    });
}

export function menuClosePlan(holds, nowMs) {
    const pending = [];
    for (const hold of holds || []) {
        if (!hold || hold.sent || typeof hold.key !== 'string' || !hold.key)
            continue;
        pending.push(hold);
    }
    const send = dueUndoKeys(pending, nowMs);
    const sending = new Set(send);
    const now = Number(nowMs);
    const keep = pending.filter(hold => !sending.has(hold.key) && Number(hold.until) > now);
    return {send, keep};
}

export function dueUndoKeys(holds, nowMs) {
    const now = Number(nowMs);
    const keys = [];
    for (const hold of holds || []) {
        if (!hold || hold.sent || typeof hold.key !== 'string' || !hold.key)
            continue;
        if (!(Number(hold.until) > now))
            keys.push(hold.key);
    }
    return keys;
}

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

export function formatElapsed(seconds) {
    const whole = Math.floor(Number(seconds));
    if (!Number.isFinite(whole) || whole < 0)
        return '--:--';
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const secs = whole % 60;
    const pad = value => String(value).padStart(2, '0');
    if (hours >= 1)
        return `${hours}:${pad(minutes)}:${pad(secs)}`;
    return `${minutes}:${pad(secs)}`;
}

export function formatTopBar(seconds) {
    const whole = Math.floor(Number(seconds));
    if (!Number.isFinite(whole) || whole < 0)
        return '--:--';
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    if (hours >= 1)
        return `${hours}:${String(minutes).padStart(2, '0')}`;
    return `${minutes}m`;
}

export function topBarWidthSample(text) {
    if (typeof text !== 'string' || !text)
        return '';
    const minutes = /^(\d+)m$/.exec(text);
    if (minutes)
        return `${'8'.repeat(minutes[1].length)}m`;
    const clock = /^(\d+):(\d{2})$/.exec(text);
    if (clock)
        return `${'8'.repeat(clock[1].length)}:88`;
    if (text === '--:--')
        return '88:88';
    return text;
}

export function formatTracked(seconds) {
    const whole = Math.floor(Number(seconds) || 0);
    if (whole <= 0)
        return '';
    if (whole >= 3600) {
        const hours = Math.floor(whole / 3600);
        const minutes = Math.floor((whole % 3600) / 60);
        return `${hours}:${String(minutes).padStart(2, '0')} tracked`;
    }
    return `${formatElapsed(whole)} tracked`;
}

export function elapsedSeconds(timer, nowSec) {
    if (!timer || typeof timer !== 'object')
        return 0;
    const accumulated = Number(timer.accumulated_s) || 0;
    if (timer.state === 'running' && timer.running_since != null) {
        const since = Number(timer.running_since);
        if (Number.isFinite(since))
            return accumulated + (nowSec - since);
    }
    return accumulated;
}

export function parseSetTime(text) {
    const match = /^(\d+):([0-5]\d)$/.exec(String(text || '').trim());
    if (!match)
        return null;
    return Number(match[1]) * 3600 + Number(match[2]) * 60;
}

export function parseStartClock(text, nowMs) {
    const match = /^(\d{1,2}):([0-5]\d)$/.exec(String(text || '').trim());
    if (!match)
        return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (hours > 23)
        return null;
    const now = new Date(nowMs);
    const start = new Date(now.getTime());
    start.setHours(hours, minutes, 0, 0);
    if (start.getTime() > nowMs)
        start.setDate(start.getDate() - 1);
    return Math.floor(start.getTime() / 1000);
}

function speakDuration(seconds) {
    const whole = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const hourText = hours === 1 ? '1 hour' : `${hours} hours`;
    const minuteText = minutes === 1 ? '1 minute' : `${minutes} minutes`;
    if (hours && minutes)
        return `${hourText} ${minuteText}`;
    if (hours)
        return hourText;
    return minuteText;
}

function authBroken(reason) {
    const text = String(reason || '').toLowerCase();
    return text.includes('keyring') || text.includes('rejected key') ||
        text.includes('routine not found') || text.includes('auth');
}

function isOverdue(due, nowMs) {
    if (typeof due !== 'string' || !due)
        return false;
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/.exec(due.trim());
    if (!match)
        return false;
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    const deadline = match[4] === undefined
        ? new Date(year, month, day, 23, 59, 59, 999)
        : new Date(year, month, day, Number(match[4]), Number(match[5]), 59, 999);
    return nowMs > deadline.getTime();
}

function visibleOpen(item, nowMs) {
    if (!item || item.status !== 'open' || snoozed(item, nowMs) || acted(item))
        return false;
    if (item.local && (item.local.done_locally || item.local.resolved))
        return false;
    return true;
}

function hasOpenAsk(items, nowMs) {
    return (items || []).some(item => visibleOpen(item, nowMs) && item.kind === 'ask');
}

function hasOpenTodo(items, nowMs) {
    return (items || []).some(item => visibleOpen(item, nowMs) && item.kind === 'todo');
}

function botsNeedAttention(bots) {
    for (const bot of bots || []) {
        if (!bot)
            continue;
        const asks = bot.openAsks !== undefined ? bot.openAsks : bot.open_asks;
        if (botNeedsAttention({state: bot.state, openAsks: asks}))
            return true;
    }
    return false;
}

export function approvalCount(items, nowMs) {
    let count = 0;
    for (const item of items || []) {
        if (!visibleOpen(item, nowMs) || item.kind !== 'ask')
            continue;
        if ((item.actions || []).includes('approve'))
            count += 1;
    }
    return count;
}

export function overdueCount(items, nowMs) {
    let count = 0;
    for (const item of items || []) {
        if (!visibleOpen(item, nowMs) || item.kind !== 'todo')
            continue;
        if (item.owner === 'bot' || !isOverdue(item.due, nowMs))
            continue;
        count += 1;
    }
    return count;
}

function timerActive(timer) {
    return Boolean(timer && (timer.state === 'running' || timer.state === 'paused'));
}

function timerShown(timer) {
    return Boolean(timerActive(timer) || (timer && timer.state === 'stopped'));
}

export function badgeBox(iconWidth, iconHeight) {
    const width = Number(iconWidth);
    const height = Number(iconHeight);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0)
        return {span: 0, x: 0, y: 0};
    const span = Math.max(3, Math.round(Math.max(width, height) * 0.25));
    return {
        span,
        x: Math.max(0, width - span),
        y: Math.max(0, height - span),
    };
}

export function panelIcon(mark) {
    if (mark === 'slash')
        return {file: 'slash', overlay: ''};
    if (mark === 'triangle')
        return {file: 'triangle', overlay: ''};
    if (mark === 'dot')
        return {file: 'base', overlay: 'blue'};
    if (mark === 'ring')
        return {file: 'base', overlay: 'red'};
    return {file: 'base', overlay: ''};
}

export function indicatorView({
    running,
    state = '',
    reason = '',
    activationFailed = true,
    items = [],
    bots = [],
    timer = null,
    nowMs = 0,
}) {
    if (!running && activationFailed === false) {
        return {
            mark: null,
            text: '',
            textStyle: 'run',
            showPause: false,
            dimmed: true,
            iconFile: 'base',
            overlay: '',
            accessibleName: 'TetherBot',
        };
    }
    const nowSec = nowMs / 1000;
    const slash = !running || state === 'unconfigured' || state === 'failed_closed' ||
        authBroken(reason);
    const active = timerActive(timer);
    const shown = timerShown(timer);
    const elapsed = shown ? elapsedSeconds(timer, nowSec) : 0;
    const warning = active && (Boolean(timer.warning) || elapsed < 0);
    const paused = active && timer.state === 'paused';
    const stopped = Boolean(timer && timer.state === 'stopped');
    const askWaiting = !slash && hasOpenAsk(items, nowMs);
    const botAttention = !slash && botsNeedAttention(bots);
    const openTodos = !slash && hasOpenTodo(items, nowMs);
    let mark = null;
    if (slash)
        mark = 'slash';
    else if (askWaiting || botAttention)
        mark = 'dot';
    else if (openTodos)
        mark = 'ring';
    else if (warning)
        mark = 'triangle';
    let text = '';
    let textStyle = 'run';
    if (!slash && warning) {
        text = '--:--';
        textStyle = 'warn';
    } else if (!slash && shown) {
        text = formatTopBar(elapsed);
        textStyle = paused || stopped ? 'paused' : 'run';
    }
    const title = timer && timer.item_title ? String(timer.item_title) : 'Timer';
    const spoken = speakDuration(elapsed);
    let accessibleName = 'TetherBot: all clear';
    if (slash)
        accessibleName = 'TetherBot: bridge not running';
    else if (warning)
        accessibleName = 'TetherBot: timer needs a check';
    else if (stopped)
        accessibleName = `TetherBot: timer stopped at ${spoken}`;
    else if (active && paused)
        accessibleName = `TetherBot: timer paused at ${spoken}, ${title}`;
    else if (active)
        accessibleName = `TetherBot: timer running, ${spoken}, ${title}`;
    let extra = '';
    if (!slash && mark === 'dot')
        extra = askWaiting ? 'an ask is waiting' : 'a bot needs attention';
    else if (!slash && mark === 'ring')
        extra = 'open todos';
    if (extra) {
        if (warning)
            accessibleName = `TetherBot: timer needs a check. ${extra}`;
        else if (stopped)
            accessibleName = `TetherBot: timer stopped at ${spoken}. ${extra}`;
        else if (active && paused)
            accessibleName = `TetherBot: timer paused at ${spoken}. ${extra}`;
        else if (active)
            accessibleName = `TetherBot: timer running, ${spoken}. ${extra}`;
        else
            accessibleName = `TetherBot: ${extra}`;
    }
    const chosen = panelIcon(mark);
    return {
        mark,
        text,
        textStyle,
        showPause: Boolean(!slash && paused && !warning),
        dimmed: slash,
        iconFile: chosen.file,
        overlay: chosen.overlay,
        accessibleName,
    };
}

function liveUndo(timer, nowSec) {
    const undo = timer && timer.undo;
    if (!undo || undo.kind !== 'undo' || !(Number(undo.until) > nowSec))
        return null;
    const recorded = formatElapsed(undo.recorded_s);
    const title = undo.item_title
        ? `Recorded ${recorded} on ${undo.item_title}`
        : `Stopped ${recorded}`;
    return {
        action: 'Undo',
        timerId: undo.timer_id || '',
        title,
        untilMs: Number(undo.until) * 1000,
    };
}

export function keepAssigning(assigning, timer) {
    if (!assigning || !timer || typeof timer !== 'object')
        return false;
    if (timer.state === 'stopped')
        return true;
    return (timer.state === 'running' || timer.state === 'paused') && !timer.item_key;
}

export function todoActivation(row) {
    if (!row || !row.key)
        return null;
    if (row.pick)
        return {method: 'AssignTimer', args: [row.key]};
    return {method: 'OpenWindow', args: [row.key]};
}

export function timerModel({
    running,
    activationFailed = true,
    timer = null,
    nowMs = 0,
    switchAsk = null,
    settingTime = false,
    editingStart = false,
    assigning = false,
    error = '',
    labels = null,
}) {
    if (!running) {
        if (activationFailed === false)
            return {kind: 'hidden'};
        return {
            kind: 'down',
            title: 'Timer unavailable: bridge not running.',
            body: 'Saved time is safe on disk and keeps counting.',
        };
    }
    if (error)
        return {kind: 'error', title: error};
    if (timer && timer.read_error)
        return {kind: 'error', title: String(timer.read_error)};
    if (switchAsk) {
        const from = switchAsk.title || 'Timer';
        const title = switchAsk.discard
            ? 'Discard the stopped time and start this one?'
            : `Stop ${from} and start this one?`;
        return {
            kind: 'switch',
            title,
            actions: ['Switch', 'Cancel'],
            key: switchAsk.key || '',
        };
    }
    const nowSec = nowMs / 1000;
    const undo = liveUndo(timer, nowSec);
    if (timer && timer.state === 'stopped') {
        const elapsed = elapsedSeconds(timer, nowSec);
        return {
            kind: 'stopped',
            title: `Stopped ${formatTopBar(elapsed)}`,
            time: formatElapsed(elapsed),
            actions: assigning ? ['Cancel'] : ['Add to a todo', 'Dismiss'],
            timerId: timer.timer_id || '',
            assigning: Boolean(assigning),
            undo,
        };
    }
    if (undo && (!timer || timer.state === 'idle' || !timer.state)) {
        return {
            kind: 'undo',
            title: undo.title,
            action: 'Undo',
            timerId: undo.timerId,
            untilMs: undo.untilMs,
        };
    }
    if (timerActive(timer)) {
        const elapsed = elapsedSeconds(timer, nowSec);
        if (timer.warning || elapsed < 0) {
            if (settingTime)
                return {kind: 'set', title: 'Set time', hint: 'H:MM'};
            const saved = Math.max(0, Math.floor(Number(timer.accumulated_s) || 0));
            return {
                kind: 'warning',
                title: 'Timer needs a check',
                body: 'The clock moved backward, or the timer ran past 24 hours. ' +
                    `Saved time: ${formatElapsed(saved)}. It keeps counting until you choose.`,
                actions: ['Keep', 'Set time...', 'Discard'],
            };
        }
        if (editingStart) {
            return {
                kind: 'edit-start',
                title: 'Edit start',
                hint: 'HH:MM',
                actions: ['-5m', '-15m', '-30m', 'Cancel'],
            };
        }
        const subject = timer.item_title || (timer.item_key ? 'Timer' : '');
        const botIdFromTimer = timer.item_key ? String(timer.item_key).split('/')[0] : '';
        const named = labels && botIdFromTimer ? labels.get(botIdFromTimer) : '';
        const bot = named || botIdFromTimer;
        const actions = [timer.state === 'paused' ? 'Resume' : 'Pause', 'Stop', 'Edit start'];
        if (!timer.item_key && !assigning)
            actions.push('Add to a todo');
        if (assigning)
            actions.push('Cancel');
        return {
            kind: timer.state === 'paused' ? 'paused' : 'running',
            title: timer.state === 'paused' ? 'Paused' : 'Timer running',
            time: formatElapsed(elapsed),
            subject,
            bot,
            actions,
            assigning: Boolean(assigning),
        };
    }
    return {kind: 'idle', title: 'No timer running', action: 'Start timer'};
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

function bannerFor({running, activationFailed, state, reason}) {
    if (!running)
        return activationFailed ? BRIDGE_DOWN : '';
    if (needsUpdate(reason))
        return UPDATE_MESSAGE;
    if (!state || state === 'ok')
        return '';
    return reason || state;
}

const ATTENTION_STATES = new Set([
    'needs_you',
    'error',
    'degraded',
    'offline',
    'failed_closed',
    'unconfigured',
    'paused',
]);

const SUMMARY_ERROR_STATES = new Set([
    'error',
    'failed_closed',
    'unconfigured',
    'offline',
]);

export function botLabels(bots) {
    const labels = new Map();
    for (const bot of bots || []) {
        if (!bot || typeof bot.name !== 'string' || !bot.name)
            continue;
        const label = typeof bot.display_name === 'string' && bot.display_name
            ? bot.display_name
            : bot.name;
        labels.set(bot.name, label);
    }
    return labels;
}

export function botNeedsAttention(row) {
    if (!row)
        return false;
    if (ATTENTION_STATES.has(row.state))
        return true;
    return number(row.openAsks) > 0;
}

export function summaryTone(rows) {
    const attention = (Array.isArray(rows) ? rows : []).filter(botNeedsAttention);
    if (attention.some(row => SUMMARY_ERROR_STATES.has(row && row.state)))
        return 'error';
    if (attention.length > 0)
        return 'warn';
    return 'ok';
}

export function compactBotSection(rows) {
    const list = Array.isArray(rows) ? rows : [];
    if (list.length <= 1)
        return {summary: null, rows: list};
    const attention = list.filter(botNeedsAttention);
    const count = attention.length;
    let text = `${list.length} bots · all ok`;
    const tone = summaryTone(list);
    if (count === 1)
        text = `${list.length} bots · ${attention[0].name} needs attention`;
    else if (count > 1)
        text = `${list.length} bots · ${count} need attention`;
    return {
        summary: {text, tone, open: 'bots'},
        rows: attention,
    };
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
    pinExpired = false,
    hiddenKeys = [],
    activationFailed = true,
    timer = null,
    assigning = false,
}) {
    const banner = bannerFor({running, activationFailed, state, reason});
    if (!running) {
        return {
            banner,
            bots: [],
            botSummary: null,
            asks: [],
            todos: [],
            footer: null,
        };
    }
    const routes = new Map();
    const labels = new Map();
    const botRows = [];
    for (const bot of bots || []) {
        if (!bot || typeof bot.name !== 'string' || !bot.name)
            continue;
        routes.set(bot.name, Boolean(bot.routes && bot.routes.outbound));
        const label = typeof bot.display_name === 'string' && bot.display_name
            ? bot.display_name
            : bot.name;
        labels.set(bot.name, label);
        botRows.push({
            name: label,
            bot: bot.name,
            state: bot.state || '',
            summary: bot.summary || '',
            lastSeen: formatLastSeen(bot.last_seen, nowMs),
            nextRun: formatNextRun(bot.next_run, nowMs),
            openAsks: number(bot.open_asks),
            openTodos: number(bot.open_todos),
        });
    }
    const compact = compactBotSection(botRows);
    const asks = [];
    const todos = [];
    const timingKey = timerActive(timer) ? String(timer.item_key || '') : '';
    const picking = Boolean(assigning);
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
                botLabel: labels.get(bot) || item.display_name || bot,
                due: item.due || '',
                actions,
            });
        } else if (item.kind === 'todo') {
            const listed = (item.actions || []).includes('done');
            todos.push({
                key,
                title: item.title || key || 'Todo',
                bot,
                botLabel: labels.get(bot) || item.display_name || bot,
                due: item.due || '',
                canSendDone: listed && routes.get(bot) === true,
                chips: chipRow(item),
                tracked: formatTracked(item.time_tracked_s),
                timing: Boolean(timingKey) && timingKey === key,
                canStart: true,
                addToTimer: picking && !(timingKey && timingKey === key),
                pick: picking && !(timingKey && timingKey === key),
            });
        }
    }
    const presented = presentTodos(todos, undoHolds, nowMs, pinExpired, hiddenKeys);
    return {
        banner,
        bots: compact.rows,
        botSummary: compact.summary,
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

export function noticeKey(payload, reason) {
    let item = payload;
    if (typeof payload === 'string') {
        try {
            item = JSON.parse(payload);
        } catch (error) {
            return '';
        }
    }
    if (!item || typeof item !== 'object')
        return '';
    const key = itemKey(item);
    if (!key)
        return '';
    const updated = typeof item.updated_at === 'string' ? item.updated_at : '';
    return `${reason || ''}\0${key}\0${updated}`;
}

export function notificationModel(payload, reason, labels) {
    const item = typeof payload === 'string' ? JSON.parse(payload) : payload;
    if (!item || typeof item !== 'object')
        throw new Error('notification payload must be an object');
    const key = itemKey(item);
    const bot = botId(item);
    const label = labels && bot ? labels.get(bot) : '';
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
    }
    const title = item.title || 'TetherBot';
    return {
        title: label && label !== title ? `${label}: ${title}` : title,
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

export function botRowCall() {
    return openWindowCall('bots');
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

export function presentTodos(todos, holds, nowMs, pinExpired = false, hiddenKeys = []) {
    const hidden = new Set(hiddenKeys || []);
    const pending = new Map();
    for (const hold of holds || []) {
        if (!hold || typeof hold.key !== 'string' || !hold.row)
            continue;
        const live = !hold.sent && hold.until > nowMs;
        if (!live && !pinExpired)
            continue;
        pending.set(hold.key, hold);
    }
    const merged = [];
    const seen = new Set();
    for (const row of todos || []) {
        if (hidden.has(row.key) && !pending.has(row.key))
            continue;
        const hold = pending.get(row.key);
        if (hold) {
            merged.push(undoRow(row, hold, nowMs));
            seen.add(row.key);
        } else {
            merged.push({...row, undo: false, layoutHold: false, undoUntil: 0, undoFraction: 0});
        }
    }
    const missing = [];
    for (const [key, hold] of pending) {
        if (!seen.has(key))
            missing.push(hold);
    }
    placeHolds(merged, missing, nowMs);
    merged.forEach((row, index) => {
        row.index = index;
        const next = merged[index + 1];
        row.after = next && next.key ? next.key : '';
    });
    const shown = merged.slice(0, TODO_LIMIT);
    const more = merged.length > shown.length;
    return {
        todos: shown,
        moreLabel: more ? `Open TetherBot to see all ${merged.length}` : '',
    };
}

function placeHolds(merged, holds, nowMs) {
    const ordered = holds.slice().sort((a, b) => (Number(a.index) || 0) - (Number(b.index) || 0));
    const waiting = [];
    for (const hold of ordered) {
        if (!insertHold(merged, hold, nowMs))
            waiting.push(hold);
    }
    for (const hold of waiting) {
        if (!insertHold(merged, hold, nowMs)) {
            const at = Math.max(0, Math.min(Number(hold.index) || 0, merged.length));
            merged.splice(at, 0, undoRow(hold.row, hold, nowMs));
        }
    }
}

function insertHold(merged, hold, nowMs) {
    const after = typeof hold.after === 'string' ? hold.after : '';
    if (!after)
        return false;
    const at = merged.findIndex(item => item.key === after);
    if (at < 0)
        return false;
    merged.splice(at, 0, undoRow(hold.row, hold, nowMs));
    return true;
}

function undoRow(row, hold, nowMs) {
    const until = Number(hold.until) || 0;
    const live = !hold.sent && until > nowMs;
    return {
        ...row,
        undo: live,
        layoutHold: !live,
        canSendDone: false,
        undoUntil: live ? until : 0,
        undoFraction: live ? undoFraction(until, nowMs) : 0,
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
