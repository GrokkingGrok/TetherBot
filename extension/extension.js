// SPDX-License-Identifier: GPL-2.0-or-later
//
// GNOME Shell 50, ESM. This file may talk to the bridge only through the
// session bus. Do not import Soup, open a socket, spawn a network process,
// or store a secret here.

import Clutter from 'gi://Clutter';
import Gdk from 'gi://Gdk?version=4.0';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk?version=4.0';
import Meta from 'gi://Meta';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {
    BUS_NAME,
    ITEM_FILTER,
    OBJECT_PATH,
    PROXY_SIGNALS,
    ACTIVATE_RETRY_MS,
    UNDO_MS,
    dueUndoKeys,
    menuClosePlan,
    nextUndoDelay,
    noticeKey,
    shareUndoWindow,
    undoFraction,
    elapsedSeconds,
    formatElapsed,
    badgeBox,
    indicatorView,
    topBarWidthSample,
    botLabels,
    keepAssigning,
    menuModel,
    parseSetTime,
    parseStartClock,
    timerModel,
    todoActivation,
    startServiceCall,
    mergeTodoSearch,
    notificationModel,
    botRowCall,
    openWindowCall,
    performCall,
    snoozeCall,
    snoozeIso,
    todoFilter,
    isMainWindow,
    topRightFrame,
} from './view.js';
import {
    DEFAULT_EXCLUDED_APPS,
    LOOKALIKE_SKIP,
    MENU_LIMIT,
    classifyClipboard,
    imageLabel,
    imageWithinCap,
    lookalikeMode,
    menuLabel,
    pickImageMime,
} from './clipboard.js';

function _windowIdentity(metaWindow) {
    let gtkId;
    let wmClass;
    let title;
    try {
        gtkId = metaWindow.gtk_application_id || '';
        if (!gtkId && metaWindow.get_gtk_application_id)
            gtkId = metaWindow.get_gtk_application_id() || '';
    } catch {
        gtkId = '';
    }
    try {
        wmClass = metaWindow.get_wm_class ? metaWindow.get_wm_class() || '' : metaWindow.wm_class || '';
    } catch {
        wmClass = '';
    }
    try {
        title = metaWindow.get_title ? metaWindow.get_title() || '' : metaWindow.title || '';
    } catch {
        title = '';
    }
    return {gtkId, wmClass, title};
}

function _frameRect(metaWindow) {
    try {
        const frame = metaWindow.get_frame_rect ? metaWindow.get_frame_rect() : metaWindow.get_frame_rect;
        if (!frame)
            return null;
        return {x: frame.x, y: frame.y, width: frame.width, height: frame.height};
    } catch {
        return null;
    }
}

function _workArea(metaWindow) {
    try {
        let monitor = 0;
        if (metaWindow.get_monitor)
            monitor = metaWindow.get_monitor();
        const workspace = (metaWindow.get_workspace && metaWindow.get_workspace()) ||
            global.workspace_manager.get_active_workspace();
        if (!workspace || !workspace.get_work_area_for_monitor)
            return null;
        const area = workspace.get_work_area_for_monitor(monitor);
        if (!area)
            return null;
        return {x: area.x, y: area.y, width: area.width, height: area.height};
    } catch {
        return null;
    }
}

export default class TetherBotExtension extends Extension {
    enable() {
        this._enabled = true;
        this._installIconTheme();
        this._proxy = null;
        this._proxySignals = [];
        this._source = null;
        this._running = false;
        this._state = '';
        this._reason = '';
        this._counts = {asks: 0, todos: 0};
        this._bots = [];
        this._items = [];
        this._queueLength = 0;
        this._query = '';
        this._searched = null;
        this._undoHolds = [];
        this._hiddenDone = new Set();
        this._shownNotices = new Set();
        this._menuOpen = false;
        this._undoSources = [];
        this._undoSource = 0;
        this._undoPaintSource = 0;
        this._undoBars = [];
        this._todoPointer = false;
        this._Proxy = null;
        this._seenBridge = false;
        this._activationFailed = false;
        this._activatePending = false;
        this._activateRetried = false;
        this._activateSource = 0;
        this._timer = null;
        this._timerError = '';
        this._switchAsk = null;
        this._settingTime = false;
        this._editingStart = false;
        this._setHint = '';
        this._assigning = false;
        this._assignBusy = false;
        this._tickSource = 0;
        this._promptSource = 0;
        this._syncLabelSource = 0;
        this._inTick = false;
        this._timerTimeLabel = null;
        this._timeEntry = null;

        this._indicator = new PanelMenu.Button(0.0, 'TetherBot', false);
        this._indicator.add_style_class_name('tetherbot-panel');
        const box = new St.BoxLayout({
            style_class: 'panel-status-menu-box',
            x_expand: false,
        });
        this._icon = new St.Icon({
            style_class: 'system-status-icon tetherbot-indicator tetherbot-dimmed',
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._mark = new St.Widget({
            style_class: 'tetherbot-badge',
            visible: false,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.END,
            x_expand: false,
            y_expand: false,
        });
        this._face = new St.Widget({
            layout_manager: new Clutter.FixedLayout(),
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
            x_expand: false,
            y_expand: false,
        });
        this._face.add_child(this._icon);
        this._face.add_child(this._mark);
        this._badge = '';
        this._overlay = '';
        this._icon.connect('notify::height', () => this._layoutMark());
        this._icon.connect('notify::width', () => this._layoutMark());
        this._pause = new St.BoxLayout({
            style_class: 'tetherbot-pause',
            visible: false,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._pause.add_child(new St.Widget({style_class: 'tetherbot-pause-bar'}));
        this._pause.add_child(new St.Widget({style_class: 'tetherbot-pause-bar'}));
        this._time = new St.Label({
            text: '',
            style_class: 'tetherbot-time',
            visible: false,
            x_expand: false,
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._face);
        box.add_child(this._pause);
        box.add_child(this._time);
        this._indicator.add_child(box);
        this._buildMenu();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._buildClipboardIndicator();

        try {
            const xmlFile = this.dir.get_child('io.github.grokkinggrok.TetherBot1.xml');
            const [, bytes] = xmlFile.load_contents(null);
            this._Proxy = Gio.DBusProxy.makeProxyWrapper(new TextDecoder().decode(bytes));
        } catch {
            console.debug('TetherBot: interface XML did not load');
            this._Proxy = null;
        }

        this._settings = null;
        this._settingsId = 0;
        this._undoSpan = 0;
        try {
            this._settings = this.getSettings();
            this._settingsId = this._settings.connect('changed', () => {
                this._reloadBridgeSettings();
            });
        } catch {
            this._settings = null;
            this._settingsId = 0;
        }
        this._watchClipboard();

        this._watchedWindows = new Map();
        this._mainWindows = new Map();
        this._displayWindowId = 0;
        this._trackMainWindow();

        this._nameWatch = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._onNameAppeared(),
            () => this._onNameVanished()
        );
        this._render();
    }

    disable() {
        this._flushDue(true);
        this._enabled = false;
        if (this._nameWatch) {
            Gio.bus_unwatch_name(this._nameWatch);
            this._nameWatch = 0;
        }
        this._dropProxy();
        if (this._source) {
            this._source.destroy();
            this._source = null;
        }
        this._unwatchClipboard();
        this._indicator?.destroy();
        this._indicator = null;
        this._clipIndicator?.destroy();
        this._clipIndicator = null;
        this._clipSection = null;
        this._icon = null;
        this._pause = null;
        this._time = null;
        this._timerTimeLabel = null;
        this._timeEntry = null;
        this._search = null;
        this._Proxy = null;
        for (const id of this._undoSources || [])
            GLib.source_remove(id);
        this._undoSources = [];
        if (this._undoSource) {
            GLib.source_remove(this._undoSource);
            this._undoSource = 0;
        }
        if (this._undoPaintSource) {
            GLib.source_remove(this._undoPaintSource);
            this._undoPaintSource = 0;
        }
        this._undoBars = [];
        this._todoPointer = false;
        if (this._tickSource) {
            GLib.source_remove(this._tickSource);
            this._tickSource = 0;
        }
        if (this._promptSource) {
            GLib.source_remove(this._promptSource);
            this._promptSource = 0;
        }
        if (this._syncLabelSource) {
            GLib.source_remove(this._syncLabelSource);
            this._syncLabelSource = 0;
        }
        if (this._activateSource) {
            GLib.source_remove(this._activateSource);
            this._activateSource = 0;
        }
        if (this._settings && this._settingsId)
            this._settings.disconnect(this._settingsId);
        this._forgetMainWindows();
        this._settings = null;
        this._settingsId = 0;
        this._undoSpan = 0;
        this._undoHolds = [];
        this._hiddenDone = new Set();
        this._shownNotices = new Set();
        this._menuOpen = false;
        this._bots = [];
        this._items = [];
        this._searched = null;
    }

    _trackMainWindow() {
        this._displayWindowId = global.display.connect('window-created', (_display, metaWindow) => {
            this._watchMainWindow(metaWindow);
        });
        const actors = global.get_window_actors ? global.get_window_actors() : [];
        for (const actor of actors) {
            const metaWindow = actor.meta_window || (actor.get_meta_window && actor.get_meta_window());
            if (metaWindow)
                this._watchMainWindow(metaWindow);
        }
    }

    _forgetMainWindows() {
        if (this._displayWindowId) {
            global.display.disconnect(this._displayWindowId);
            this._displayWindowId = 0;
        }
        for (const [metaWindow, state] of this._mainWindows || [])
            this._disconnectWindow(metaWindow, state);
        this._mainWindows = new Map();
        for (const [metaWindow, state] of this._watchedWindows || [])
            this._disconnectWindow(metaWindow, state);
        this._watchedWindows = new Map();
    }

    _disconnectWindow(metaWindow, state) {
        for (const id of state.signals || []) {
            try {
                metaWindow.disconnect(id);
            } catch {
                // The window may already be gone.
            }
        }
        if (state.signals)
            state.signals.length = 0;
        if (state.placeIdle) {
            GLib.source_remove(state.placeIdle);
            state.placeIdle = 0;
        }
    }

    _watchMainWindow(metaWindow) {
        if (!metaWindow || !this._enabled)
            return;
        if (this._mainWindows.has(metaWindow) || this._watchedWindows.has(metaWindow))
            return;
        const state = {signals: []};
        const drop = () => {
            this._disconnectWindow(metaWindow, state);
            this._watchedWindows.delete(metaWindow);
        };
        const consider = () => {
            if (!this._enabled || !isMainWindow(_windowIdentity(metaWindow)))
                return;
            drop();
            this._adoptMainWindow(metaWindow);
        };
        this._watchedWindows.set(metaWindow, state);
        for (const name of ['shown', 'notify::title', 'notify::gtk-application-id', 'notify::wm-class']) {
            try {
                state.signals.push(metaWindow.connect(name, consider));
            } catch {
                // This Shell build has no such signal.
            }
        }
        try {
            state.signals.push(metaWindow.connect('unmanaged', drop));
        } catch {
            // Nothing to undo if the window cannot tell us it closed.
        }
        consider();
    }

    _adoptMainWindow(metaWindow) {
        if (!this._enabled || this._mainWindows.has(metaWindow))
            return;
        const state = {moved: false, placing: false, placed: null, until: 0, signals: [], placeIdle: 0};
        this._mainWindows.set(metaWindow, state);
        const noteMove = () => {
            if (state.placing || !state.placed)
                return;
            const frame = _frameRect(metaWindow);
            if (frame && frame.x === state.placed.x && frame.y === state.placed.y)
                return;
            state.moved = true;
        };
        const noteSize = () => {
            if (!this._enabled || state.moved || !state.until)
                return;
            if (GLib.get_monotonic_time() > state.until)
                return;
            this._placeMainWindow(metaWindow, state);
        };
        try {
            state.signals.push(metaWindow.connect('position-changed', noteMove));
        } catch {
            // Placement still runs once; we just cannot tell a later drag apart.
        }
        try {
            state.signals.push(metaWindow.connect('size-changed', noteSize));
        } catch {
            // The first placement still uses the size at map.
        }
        try {
            state.signals.push(metaWindow.connect('unmanaged', () => {
                this._disconnectWindow(metaWindow, state);
                this._mainWindows.delete(metaWindow);
            }));
        } catch {
            // The map entry is dropped on disable.
        }
        this._placeMainWindow(metaWindow, state);
    }

    _placeMainWindow(metaWindow, state) {
        if (!state.until)
            state.until = GLib.get_monotonic_time() + 1500 * 1000;
        const frame = _frameRect(metaWindow);
        const area = _workArea(metaWindow);
        if (!frame || !area || frame.width < 1 || frame.height < 1)
            return;
        const next = topRightFrame(area, frame);
        if (state.placed && state.placed.x === next.x && state.placed.y === next.y &&
            state.placed.width === next.width && state.placed.height === next.height)
            return;
        state.placing = true;
        state.placed = next;
        try {
            if (metaWindow.move_resize_frame)
                metaWindow.move_resize_frame(true, next.x, next.y, next.width, next.height);
            else if (metaWindow.move_frame)
                metaWindow.move_frame(true, next.x, next.y);
        } catch {
            console.debug('TetherBot: could not place the window');
        }
        if (state.placeIdle)
            GLib.source_remove(state.placeIdle);
        state.placeIdle = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            state.placeIdle = 0;
            state.placing = false;
            return GLib.SOURCE_REMOVE;
        });
    }

    _buildMenu() {
        this._banner = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._indicator.menu.addMenuItem(this._banner);
        this._timerSection = new PopupMenu.PopupMenuSection();
        this._askSection = new PopupMenu.PopupMenuSection();
        this._todoSection = new PopupMenu.PopupMenuSection();
        this._botSection = new PopupMenu.PopupMenuSection();
        this._indicator.menu.addMenuItem(this._timerSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._searchItem = new PopupMenu.PopupBaseMenuItem({reactive: false});
        this._search = new St.Entry({
            hint_text: 'Search todos',
            style_class: 'tetherbot-search',
            can_focus: true,
            x_expand: true,
        });
        this._search.clutter_text.connect('text-changed', () => {
            this._query = this._search.text || '';
            this._refreshSearch();
        });
        this._searchItem.add_child(this._search);
        this._indicator.menu.addMenuItem(this._searchItem);
        this._indicator.menu.addMenuItem(this._todoSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addMenuItem(this._askSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addMenuItem(this._botSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._openItem = new PopupMenu.PopupMenuItem('Open TetherBot');
        this._openItem.connect('activate', () => this._openWindow(''));
        this._indicator.menu.addMenuItem(this._openItem);
        this._footer = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._indicator.menu.addMenuItem(this._footer);
        this._syncItem = new PopupMenu.PopupMenuItem('Sync now');
        this._syncItem.connect('activate', () => this._sync());
        this._indicator.menu.addMenuItem(this._syncItem);
        const settings = new PopupMenu.PopupMenuItem('Settings');
        settings.connect('activate', () => this.openPreferences());
        this._indicator.menu.addMenuItem(settings);
        this._indicator.menu.connect('open-state-changed', (_menu, open) => {
            this._menuOpen = open;
            if (open) {
                this._requestBridge();
                return;
            }
            // The bar owns the send. Closing early keeps every unsent Done
            // so Undo still works until that shared window ends.
            this._todoPointer = false;
            const plan = menuClosePlan(this._undoHolds, Date.now());
            if (plan.send.length)
                this._flushDue(false);
            const keep = new Set(plan.keep.map(hold => hold.key));
            this._undoHolds = (this._undoHolds || []).filter(hold => hold && keep.has(hold.key));
            this._armUndoTimer();
            this._refresh();
        });
        this._watchTodoPointer();
    }

    _onNameAppeared() {
        if (!this._enabled)
            return;
        this._seenBridge = true;
        this._running = true;
        this._activationFailed = false;
        this._clearActivateTimer();
        this._ensureProxy();
        this._render();
    }

    _onNameVanished() {
        if (!this._enabled)
            return;
        this._running = false;
        this._dropProxy();
        this._state = '';
        this._reason = '';
        this._counts = {asks: 0, todos: 0};
        this._bots = [];
        this._items = [];
        this._queueLength = 0;
        if (this._seenBridge) {
            this._activationFailed = true;
            this._render();
            return;
        }
        this._requestBridge();
        this._render();
    }

    _requestBridge() {
        if (!this._enabled || this._running || this._activatePending)
            return;
        const call = startServiceCall();
        let session;
        try {
            session = Gio.DBus.session;
        } catch {
            session = null;
        }
        if (!session) {
            this._activationFailed = true;
            this._scheduleActivate();
            this._render();
            return;
        }
        this._activatePending = true;
        this._activationFailed = false;
        try {
            session.call(
                call.destination,
                call.path,
                call.interfaceName,
                call.method,
                new GLib.Variant('(su)', [call.name, call.flags]),
                new GLib.VariantType('(u)'),
                Gio.DBusCallFlags.NONE,
                5000,
                null,
                (connection, result) => this._onActivateResult(connection, result)
            );
        } catch {
            this._activatePending = false;
            this._activationFailed = true;
            this._scheduleActivate();
            this._render();
        }
    }

    _onActivateResult(connection, result) {
        this._activatePending = false;
        if (!this._enabled)
            return;
        try {
            connection.call_finish(result);
            if (!this._running)
                this._scheduleActivate();
        } catch {
            this._activationFailed = true;
            this._scheduleActivate();
        }
        this._render();
    }

    _scheduleActivate() {
        if (!this._enabled || this._activateSource || this._activateRetried || this._seenBridge)
            return;
        this._activateRetried = true;
        this._activateSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ACTIVATE_RETRY_MS, () => {
            this._activateSource = 0;
            if (this._enabled && !this._running)
                this._requestBridge();
            return GLib.SOURCE_REMOVE;
        });
    }

    _clearActivateTimer() {
        if (!this._activateSource)
            return;
        GLib.source_remove(this._activateSource);
        this._activateSource = 0;
    }

    _ensureProxy() {
        if (this._proxy || !this._Proxy)
            return;
        this._proxy = new this._Proxy(
            Gio.DBus.session,
            BUS_NAME,
            OBJECT_PATH,
            (proxy, error) => {
                if (!this._enabled || error || proxy !== this._proxy)
                    return;
                this._bindProxy();
                this._reloadBridgeSettings();
                this._refresh();
                this._loadClipboard();
                this._captureClipboard();
            },
            null,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START
        );
    }

    _bindProxy() {
        this._dropProxySignals();
        for (const name of PROXY_SIGNALS) {
            const id = this._proxy.connectSignal(name, (_proxy, _sender, params) => {
                this._onSignal(name, params);
            });
            this._proxySignals.push(id);
        }
        this._propId = this._proxy.connect('g-properties-changed', () => {
            if (!this._enabled)
                return;
            this._readProperties();
            this._render();
        });
    }

    _dropProxySignals() {
        const proxy = this._proxy;
        if (proxy) {
            for (const id of this._proxySignals)
                proxy.disconnectSignal(id);
            if (this._propId) {
                proxy.disconnect(this._propId);
                this._propId = 0;
            }
        }
        this._proxySignals = [];
    }

    _dropProxy() {
        this._dropProxySignals();
        this._proxy = null;
    }

    _onSignal(name, params) {
        if (!this._enabled || !this._proxy)
            return;
        if (!Array.isArray(params))
            params = [];
        if (name === 'ClipboardChanged') {
            this._loadClipboard();
            return;
        }
        if (name === 'StateChanged') {
            this._state = params[0] || '';
            this._reason = params[1] || '';
            this._render();
            this._refresh();
        } else if (name === 'ItemsChanged') {
            this._refresh();
        } else if (name === 'NotificationRequested') {
            this._showNotification(params[0], params[1]);
        } else if (name === 'TimerChanged') {
            this._applyTimerJson(params[0]);
            this._refreshItems();
        } else if (name === 'ActionResult') {
            const result = params[1] || '';
            this._showNotification({
                title: result === 'accepted' ? 'Accepted' : 'Action failed',
                body: result,
            }, 'action_result');
            this._refresh();
        }
    }

    _readProperties() {
        if (!this._proxy)
            return;
        this._state = this._proxy.State || '';
        this._reason = this._proxy.StateReason || '';
        this._queueLength = Number(this._proxy.QueueLength || 0);
        this._counts = unpackCounts(this._proxy.Counts);
        // g-properties-changed calls this, so a Bots update repaints the row.
        const bots = this._proxy.Bots || '[]';
        try {
            const parsed = JSON.parse(bots);
            this._bots = Array.isArray(parsed) ? parsed : [];
        } catch {
            this._bots = [];
        }
    }

    _refresh() {
        this._readProperties();
        this._render();
        if (!this._proxy)
            return;
        this._refreshItems();
        this._proxy.GetTimerRemote((result, error) => {
            if (!this._enabled || error || !result)
                return;
            this._applyTimerJson(result[0]);
        });
    }

    _refreshItems() {
        if (!this._proxy)
            return;
        this._proxy.GetItemsRemote(ITEM_FILTER, (result, error) => {
            if (!this._enabled || error || !result)
                return;
            try {
                const parsed = JSON.parse(result[0]);
                this._items = Array.isArray(parsed) ? parsed : [];
            } catch {
                return;
            }
            this._render();
            if ((this._query || '').trim())
                this._refreshSearch();
        });
    }

    _refreshSearch() {
        if (!this._enabled)
            return;
        const query = (this._query || '').trim();
        if (!query) {
            this._searched = null;
            this._render();
            return;
        }
        if (!this._proxy)
            return;
        this._proxy.GetItemsRemote(todoFilter(query), (result, error) => {
            if (!this._enabled || (this._query || '').trim() !== query)
                return;
            if (error || !result)
                return;
            try {
                const parsed = JSON.parse(result[0]);
                this._searched = Array.isArray(parsed) ? parsed : [];
            } catch {
                return;
            }
            this._render();
        });
    }

    _render() {
        if (!this._indicator)
            return;
        this._undoBars = [];
        const nowMs = Date.now();
        this._forgetHidden(this._items);
        this._assigning = keepAssigning(this._assigning, this._timer);
        const view = this._paintIndicator(nowMs);
        const labels = botLabels(this._bots);
        const block = timerModel({
            running: this._running,
            activationFailed: this._activationFailed,
            timer: this._timer,
            nowMs,
            switchAsk: this._switchAsk,
            settingTime: this._settingTime,
            editingStart: this._editingStart,
            assigning: this._assigning,
            error: this._timerError,
            labels,
        });
        this._fillTimer(block);
        const model = menuModel({
            running: this._running,
            state: this._state,
            reason: this._reason,
            bots: this._bots,
            items: mergeTodoSearch(this._items, this._searched),
            queueLength: this._queueLength,
            nowMs,
            undoHolds: this._undoHolds,
            pinExpired: this._todoPointer,
            hiddenKeys: this._hiddenDone ? [...this._hiddenDone] : [],
            activationFailed: this._activationFailed,
            timer: this._timer,
            assigning: this._assigning,
        });
        this._banner.label.text = model.banner;
        this._banner.visible = Boolean(model.banner);
        this._syncTick(view);
        this._syncItem.setSensitive(this._running);
        if (this._searchItem)
            this._searchItem.visible = Boolean(model.footer);
        if (this._openItem)
            this._openItem.visible = Boolean(model.footer);
        if (!model.footer) {
            this._botSection.removeAll();
            this._askSection.removeAll();
            this._todoSection.removeAll();
            this._footer.visible = false;
            this._finishUndoChrome();
            return;
        }
        this._fillBots(model.bots, model.botSummary);
        this._fillAsks(model.asks);
        this._fillTodos(model.todos, model.moreLabel);
        const reason = model.footer.reason ? `: ${model.footer.reason}` : '';
        this._footer.label.text = `${model.footer.state}${reason} · Queued ${model.footer.queueLength}`;
        this._footer.visible = true;
        this._finishUndoChrome();
    }

    _paintIndicator(nowMs) {
        const view = indicatorView({
            running: this._running,
            state: this._state,
            reason: this._reason,
            activationFailed: this._activationFailed,
            items: this._items,
            bots: this._bots,
            timer: this._timer,
            nowMs,
        });
        const classes = ['system-status-icon', 'tetherbot-indicator'];
        if (view.dimmed && view.iconFile !== 'slash')
            classes.push('tetherbot-dimmed');
        this._icon.style_class = classes.join(' ');
        this._syncIcon(view.iconFile);
        this._syncOverlay(view.overlay);
        const timeClass = ['tetherbot-time'];
        if (view.textStyle === 'paused')
            timeClass.push('tetherbot-time-paused');
        this._time.style_class = timeClass.join(' ');
        this._time.text = view.text;
        const sample = topBarWidthSample(view.text);
        this._time.style = sample ? `min-width: ${sample.length}ch;` : '';
        this._time.visible = Boolean(view.text);
        this._pause.visible = view.showPause;
        if (this._indicator.accessible_name !== view.accessibleName)
            this._indicator.accessible_name = view.accessibleName;
        this._indicator.tooltip_text = view.accessibleName;
        return view;
    }

    _forgetHidden(items) {
        if (!this._hiddenDone || this._hiddenDone.size === 0)
            return;
        const present = new Set();
        for (const item of items || []) {
            if (item && typeof item.key === 'string')
                present.add(item.key);
        }
        for (const key of this._hiddenDone) {
            if (!present.has(key))
                this._hiddenDone.delete(key);
        }
    }

    _syncIcon(kind) {
        if (!this._icon)
            return;
        const badge = kind === 'slash' || kind === 'triangle' ? kind : 'base';
        if (this._badge === badge && this._icon.gicon)
            return;
        this._badge = badge;
        const name = badge === 'base' ? 'face-symbolic.svg' : `face-${badge}-symbolic.svg`;
        const file = this.dir.get_child(`icons/${name}`);
        this._icon.gicon = Gio.FileIcon.new(file);
    }

    _syncOverlay(kind) {
        this._overlay = kind === 'red' || kind === 'blue' ? kind : '';
        this._layoutMark();
    }

    _layoutMark() {
        if (!this._mark)
            return;
        if (!this._overlay) {
            this._mark.hide();
            return;
        }
        const height = this._icon ? this._icon.height : 0;
        const width = this._icon && this._icon.width > 0 ? this._icon.width : 0;
        const box = badgeBox(width, height);
        this._mark.style_class = this._overlay === 'blue'
            ? 'tetherbot-badge tetherbot-badge-blue'
            : 'tetherbot-badge tetherbot-badge-red';
        if (!box.span) {
            this._mark.hide();
            return;
        }
        this._mark.style = `width:${box.span}px;height:${box.span}px;`;
        const layout = this._face && this._face.layout_manager;
        if (layout && typeof layout.child_set_property === 'function') {
            layout.child_set_property(this._face, this._mark, 'x', box.x);
            layout.child_set_property(this._face, this._mark, 'y', box.y);
            layout.child_set_property(this._face, this._mark, 'width', box.span);
            layout.child_set_property(this._face, this._mark, 'height', box.span);
        }
        this._mark.show();
    }

    _syncTick(view) {
        const want = Boolean(
            view && view.textStyle === 'run' && view.text && view.text !== '--:--' && this._running
        );
        if (want) {
            if (!this._tickSource) {
                this._tickSource = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
                    return this._onTick();
                });
            }
            return;
        }
        if (this._tickSource && !this._inTick) {
            GLib.source_remove(this._tickSource);
            this._tickSource = 0;
        }
    }

    _onTick() {
        if (!this._enabled || !this._indicator) {
            this._tickSource = 0;
            return GLib.SOURCE_REMOVE;
        }
        this._inTick = true;
        const view = this._paintIndicator(Date.now());
        this._inTick = false;
        if (this._timerTimeLabel && this._timer)
            this._timerTimeLabel.text = formatElapsed(elapsedSeconds(this._timer, Date.now() / 1000));
        if (view.textStyle !== 'run' || !view.text || view.text === '--:--') {
            this._tickSource = 0;
            return GLib.SOURCE_REMOVE;
        }
        return GLib.SOURCE_CONTINUE;
    }

    _fillBots(rows, summary) {
        this._botSection.removeAll();
        this._botSection.addMenuItem(sectionTitle('Bots'));
        if (summary && summary.text) {
            const item = new PopupMenu.PopupMenuItem(summary.text);
            if (summary.tone === 'error')
                item.add_style_class_name('tetherbot-bot-alert');
            else if (summary.tone === 'warn')
                item.add_style_class_name('tetherbot-bot-warn');
            item.connect('activate', () => this._openWindow('bots'));
            this._botSection.addMenuItem(item);
        }
        if (rows.length === 0 && !summary) {
            this._botSection.addMenuItem(sectionTitle('No bots'));
            return;
        }
        for (const row of rows)
            this._botSection.addMenuItem(this._botRow(row));
    }

    _botRow(row) {
        const item = new PopupMenu.PopupBaseMenuItem();
        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        const title = new St.BoxLayout();
        const dot = new St.Label({
            text: '●',
            style_class: `tetherbot-dot tetherbot-dot-${row.state || 'unknown'}`,
        });
        title.add_child(dot);
        title.add_child(new St.Label({text: ` ${row.name}`}));
        box.add_child(title);
        const detail = [row.summary, row.lastSeen, row.nextRun].filter(Boolean).join(' · ');
        box.add_child(new St.Label({text: detail, style_class: 'tetherbot-subtle'}));
        item.add_child(box);
        const call = botRowCall();
        item.connect('activate', () => this._openWindow(call.args[0]));
        return item;
    }

    _fillAsks(rows) {
        this._askSection.removeAll();
        this._askSection.addMenuItem(sectionTitle('Asks'));
        if (rows.length === 0) {
            this._askSection.addMenuItem(sectionTitle('No asks'));
            return;
        }
        for (const row of rows)
            this._askSection.addMenuItem(this._askRow(row));
    }

    _askRow(row) {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const box = new St.BoxLayout({x_expand: true});
        const text = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        text.add_child(new St.Label({text: row.title}));
        const meta = [row.botLabel || row.bot, row.due].filter(Boolean).join(' · ');
        text.add_child(new St.Label({text: meta, style_class: 'tetherbot-subtle'}));
        box.add_child(text);
        for (const action of row.actions) {
            const label = action === 'approve' ? 'Approve' : 'Veto';
            box.add_child(this._actionButton(label, () => this._perform(action, row.key)));
        }
        item.add_child(box);
        return item;
    }

    _fillTodos(rows, moreLabel) {
        this._todoSection.removeAll();
        this._todoSection.addMenuItem(sectionTitle('Todos'));
        if (rows.length === 0)
            this._todoSection.addMenuItem(sectionTitle('No todos'));
        for (const row of rows)
            this._todoSection.addMenuItem(this._todoRow(row));
        if (moreLabel) {
            const more = new PopupMenu.PopupMenuItem(moreLabel);
            more.connect('activate', () => this._openWindow(''));
            this._todoSection.addMenuItem(more);
        }
    }

    _todoRow(row) {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: Boolean(row.pick)});
        item.track_hover = true;
        item.connect('enter-event', () => {
            this._todoPointer = true;
            return Clutter.EVENT_PROPAGATE;
        });
        item.connect('leave-event', () => {
            GLib.idle_add(() => {
                if (!this._enabled)
                    return GLib.SOURCE_REMOVE;
                this._todoPointer = this._pointerOverTodos();
                if (!this._todoPointer)
                    this._releasePinnedUndos();
                return GLib.SOURCE_REMOVE;
            });
            return Clutter.EVENT_PROPAGATE;
        });
        if (row.pick)
            item.add_style_class_name('tetherbot-pick-row');
        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        const top = new St.BoxLayout({x_expand: true});
        const text = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        const title = new St.Button({
            label: row.title,
            style_class: row.pick ? 'tetherbot-title tetherbot-pick' : 'tetherbot-title',
            x_align: Clutter.ActorAlign.START,
            x_expand: true,
            accessible_name: row.pick ? `Add time to ${row.title}` : row.title,
        });
        if (title.clutter_text)
            title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        title.connect('clicked', () => this._activateTodo(row));
        if (row.pick)
            item.connect('activate', () => this._activateTodo(row));
        const heading = new St.BoxLayout({x_expand: true});
        if (row.chips && row.chips.priority)
            heading.add_child(chipLabel(row.chips.priority, row.chips.priorityTone));
        heading.add_child(title);
        text.add_child(heading);
        if (row.chips) {
            text.add_child(this._chipRow(row.chips, row.tracked, row.botLabel));
        } else {
            const meta = [row.botLabel || row.bot, row.due].filter(Boolean).join(' · ');
            text.add_child(new St.Label({text: meta, style_class: 'tetherbot-subtle'}));
            if (row.tracked)
                text.add_child(this._chipRow({}, row.tracked));
        }
        top.add_child(text);
        if (row.timing) {
            top.add_child(new St.Label({
                text: 'Timing',
                style_class: 'tetherbot-timing',
                y_align: Clutter.ActorAlign.CENTER,
            }));
        } else if (row.canStart && !row.pick) {
            top.add_child(this._playButton(row));
        }
        if (row.undo)
            top.add_child(this._undoButton(row.undoUntil, () => this._undo(row.key)));
        else if (row.canSendDone)
            top.add_child(this._actionButton('Done', () => this._markDone(row), false));
        box.add_child(top);
        item.add_child(box);
        return item;
    }

    _chipRow(chips, tracked, botLabel) {
        const row = new St.BoxLayout({style_class: 'tetherbot-chips'});
        if (botLabel)
            row.add_child(chipLabel(botLabel, 'neutral'));
        if (chips.due)
            row.add_child(chipLabel(chips.due, chips.dueTone));
        for (const tag of chips.tags || [])
            row.add_child(chipLabel(tag.label, tag.tone));
        if (chips.extra > 0)
            row.add_child(chipLabel(`+${chips.extra}`, 'neutral'));
        if (tracked)
            row.add_child(chipLabel(tracked, 'neutral'));
        return row;
    }

    _playButton(row) {
        const button = new St.Button({
            icon_name: 'media-playback-start-symbolic',
            style_class: 'tetherbot-play',
            can_focus: true,
            accessible_name: `Start timer: ${row.title}`,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.connect('clicked', () => this._startTimer(row.key));
        return button;
    }

    _fillTimer(block) {
        this._timerSection.removeAll();
        this._timerTimeLabel = null;
        if (!block || block.kind === 'hidden')
            return;
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        if (block.kind === 'running' || block.kind === 'paused') {
            const head = new St.BoxLayout({x_expand: true});
            if (block.kind === 'paused')
                head.add_child(pauseBars(true));
            head.add_child(new St.Label({
                text: block.kind === 'paused' ? 'Paused' : 'Timer running',
                y_align: Clutter.ActorAlign.CENTER,
            }));
            box.add_child(head);
            const time = new St.Label({text: block.time || '', style_class: 'tetherbot-clock'});
            this._timerTimeLabel = time;
            box.add_child(time);
            const subject = new St.BoxLayout({
                style_class: 'tetherbot-timer-subject',
                x_align: Clutter.ActorAlign.START,
                x_expand: true,
            });
            if (block.bot) {
                const chip = chipLabel(block.bot, 'neutral');
                chip.y_align = Clutter.ActorAlign.CENTER;
                subject.add_child(chip);
            }
            const title = new St.Label({
                text: block.subject || '',
                y_align: Clutter.ActorAlign.CENTER,
                x_align: Clutter.ActorAlign.START,
                x_expand: true,
            });
            if (title.clutter_text)
                title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            subject.add_child(title);
            box.add_child(subject);
            if (block.assigning) {
                box.add_child(new St.Label({
                    text: 'Choose a todo',
                    style_class: 'tetherbot-subtle',
                }));
            }
            box.add_child(this._timerActions(block.actions || []));
        } else if (block.kind === 'stopped') {
            box.add_child(new St.Label({text: block.title || 'Stopped'}));
            if (block.undo)
                box.add_child(this._undoButton(block.undo.untilMs, () => this._undoStop()));
            if (block.assigning) {
                box.add_child(new St.Label({
                    text: 'Choose a todo',
                    style_class: 'tetherbot-subtle',
                }));
            } else {
                box.add_child(new St.Label({
                    text: 'Not on a todo yet',
                    style_class: 'tetherbot-subtle',
                }));
            }
            box.add_child(this._timerActions(block.actions || []));
        } else if (block.kind === 'edit-start') {
            const row = new St.BoxLayout({
                x_expand: true,
                style_class: 'tetherbot-edit-row',
                y_align: Clutter.ActorAlign.CENTER,
            });
            for (const label of ['-5m', '-15m', '-30m'])
                row.add_child(this._actionButton(label, () => this._timerAction(label), false));
            const entry = new St.Entry({
                hint_text: 'HH:MM',
                style_class: 'tetherbot-edit-entry',
                can_focus: true,
            });
            this._timeEntry = entry;
            if (entry.clutter_text)
                entry.clutter_text.connect('activate', () => this._submitStartClock());
            row.add_child(entry);
            row.add_child(this._actionButton('Set', () => this._submitStartClock(), false));
            const cancel = new St.Button({
                icon_name: 'window-close-symbolic',
                style_class: 'tetherbot-icon-button',
                can_focus: true,
                accessible_name: 'Cancel',
            });
            cancel.connect('clicked', () => {
                this._editingStart = false;
                this._setHint = '';
                this._render();
            });
            row.add_child(cancel);
            box.add_child(row);
            if (this._setHint)
                box.add_child(new St.Label({text: this._setHint, style_class: 'tetherbot-subtle'}));
        } else if (block.kind === 'warning') {
            box.add_child(new St.Label({text: block.title}));
            box.add_child(new St.Label({
                text: block.body || '',
                style_class: 'tetherbot-subtle',
            }));
            box.add_child(this._timerActions(block.actions || []));
        } else if (block.kind === 'set') {
            box.add_child(new St.Label({text: block.title || 'Set time'}));
            const entry = new St.Entry({
                hint_text: block.hint || 'H:MM',
                style_class: 'tetherbot-search',
                can_focus: true,
                x_expand: true,
            });
            this._timeEntry = entry;
            if (this._setHint) {
                box.add_child(new St.Label({
                    text: this._setHint,
                    style_class: 'tetherbot-subtle',
                }));
            }
            const row = new St.BoxLayout({x_expand: true});
            row.add_child(entry);
            row.add_child(this._actionButton('Set', () => this._submitSetTime(), false));
            row.add_child(this._actionButton('Cancel', () => {
                this._settingTime = false;
                this._render();
            }, false));
            box.add_child(row);
        } else if (block.kind === 'switch' || block.kind === 'undo' || block.kind === 'assign') {
            const row = new St.BoxLayout({x_expand: true});
            row.add_child(new St.Label({text: block.title, x_expand: true}));
            if (block.kind === 'switch') {
                row.add_child(this._timerActions(block.actions || []));
            } else if (block.action) {
                const press = () => this._timerAction(block.action);
                if (block.kind === 'undo')
                    row.add_child(this._undoButton(block.untilMs, press));
                else
                    row.add_child(this._actionButton(block.action, press, false));
            }
            box.add_child(row);
            if (block.kind === 'assign' && block.assigning) {
                box.add_child(new St.Label({
                    text: 'Choose a todo',
                    style_class: 'tetherbot-subtle',
                }));
            }
        } else if (block.kind === 'idle') {
            const row = new St.BoxLayout({x_expand: true});
            row.add_child(new St.Label({text: block.title, x_expand: true}));
            row.add_child(this._actionButton(block.action, () => this._startTimer(''), false));
            box.add_child(row);
        } else {
            box.add_child(new St.Label({text: block.title || ''}));
            if (block.body) {
                box.add_child(new St.Label({
                    text: block.body,
                    style_class: 'tetherbot-subtle',
                }));
            }
        }
        item.add_child(box);
        this._timerSection.addMenuItem(item);
    }

    _timerActions(labels) {
        const row = new St.BoxLayout();
        for (const label of labels)
            row.add_child(this._actionButton(label, () => this._timerAction(label), false));
        return row;
    }

    _timerAction(label) {
        if (label === 'Pause') {
            this._timerCall('PauseTimerRemote');
        } else if (label === 'Resume') {
            this._timerCall('ResumeTimerRemote');
        } else if (label === 'Stop') {
            this._timerCall('StopTimerRemote');
        } else if (label === 'Undo') {
            this._undoStop();
        } else if (label === 'Add to a todo') {
            this._assigning = true;
            this._editingStart = false;
            this._render();
        } else if (label === 'Dismiss') {
            this._timerCall('DismissTimerRemote');
        } else if (label === 'Edit start') {
            this._editingStart = true;
            this._assigning = false;
            this._setHint = '';
            this._render();
        } else if (label === '-5m') {
            this._adjustStart(-300);
        } else if (label === '-15m') {
            this._adjustStart(-900);
        } else if (label === '-30m') {
            this._adjustStart(-1800);
        } else if (label === 'Keep') {
            this._resolveWarning('keep', 0);
        } else if (label === 'Discard') {
            this._resolveWarning('discard', 0);
        } else if (label === 'Set time...') {
            this._settingTime = true;
            this._render();
        } else if (label === 'Switch') {
            this._confirmSwitch();
        } else if (label === 'Cancel') {
            this._switchAsk = null;
            this._assigning = false;
            this._editingStart = false;
            this._setHint = '';
            this._render();
        }
    }

    _startTimer(key) {
        const state = this._timer && this._timer.state;
        const holding = state === 'running' || state === 'paused' || state === 'stopped';
        const current = holding ? String(this._timer.item_key || '') : '';
        if (holding && current !== String(key || '')) {
            this._switchAsk = {
                key: key || '',
                title: this._timer.item_title || 'Timer',
                discard: state === 'stopped',
            };
            this._settingTime = false;
            this._editingStart = false;
            this._assigning = false;
            this._render();
            return;
        }
        if (holding)
            return;
        this._switchAsk = null;
        this._timerCall('StartTimerRemote', [key || '']);
    }

    _confirmSwitch() {
        const ask = this._switchAsk;
        const timer = this._timer;
        if (!ask || !this._proxy)
            return;
        this._switchAsk = null;
        const startNext = () => {
            this._proxy.StartTimerRemote(ask.key || '', (_started, error) => {
                this._afterTimerWrite(error);
            });
        };
        if (timer && timer.state === 'stopped') {
            this._proxy.DismissTimerRemote((_result, error) => {
                if (!this._enabled)
                    return;
                if (error) {
                    this._noteTimerError(error);
                    return;
                }
                startNext();
            });
            return;
        }
        const tied = Boolean(timer && timer.item_key);
        this._proxy.StopTimerRemote((_result, error) => {
            if (!this._enabled)
                return;
            if (error) {
                this._noteTimerError(error);
                return;
            }
            if (tied) {
                startNext();
                return;
            }
            this._proxy.DismissTimerRemote((_dismissed, dismissError) => {
                if (!this._enabled)
                    return;
                if (dismissError) {
                    this._noteTimerError(dismissError);
                    return;
                }
                startNext();
            });
        });
    }

    _undoStop() {
        const id = this._timer && this._timer.undo ? this._timer.undo.timer_id || '' : '';
        if (!this._proxy)
            return;
        this._proxy.UndoStopTimerRemote(id, (_result, error) => this._afterTimerWrite(error));
    }

    _activateTodo(row) {
        const action = todoActivation(row);
        if (!action)
            return;
        if (action.method === 'AssignTimer')
            this._assignTo(action.args[0]);
        else
            this._openWindow(action.args[0]);
    }

    _assignTo(key) {
        if (!this._proxy || !key || this._assignBusy)
            return;
        this._assignBusy = true;
        this._assigning = false;
        this._proxy.AssignTimerRemote(key, (_result, error) => {
            this._assignBusy = false;
            this._afterTimerWrite(error);
        });
    }

    _adjustStart(delta) {
        if (!this._proxy)
            return;
        this._editingStart = false;
        this._proxy.AdjustTimerStartRemote(delta, (_result, error) => {
            this._afterTimerWrite(error);
        });
    }

    _submitStartClock() {
        const started = parseStartClock(this._timeEntry ? this._timeEntry.text : '', Date.now());
        if (started === null) {
            this._setHint = 'Use HH:MM';
            this._editingStart = true;
            this._render();
            return;
        }
        if (!this._proxy)
            return;
        this._editingStart = false;
        this._setHint = '';
        this._proxy.SetTimerStartRemote(started, (_result, error) => {
            this._afterTimerWrite(error);
        });
    }

    _submitSetTime() {
        const seconds = parseSetTime(this._timeEntry ? this._timeEntry.text : '');
        if (seconds === null) {
            this._setHint = 'Use H:MM, with minutes from 00 to 59';
            this._settingTime = true;
            this._render();
            return;
        }
        this._setHint = '';
        this._settingTime = false;
        this._resolveWarning('set', seconds);
    }

    _resolveWarning(choice, seconds) {
        if (!this._proxy)
            return;
        this._proxy.ResolveTimerWarningRemote(choice, seconds, (_result, error) => {
            this._afterTimerWrite(error);
        });
    }

    _timerCall(method, args = []) {
        if (!this._proxy || typeof this._proxy[method] !== 'function')
            return;
        this._proxy[method](...args, (_result, error) => this._afterTimerWrite(error));
    }

    _noteTimerError(error) {
        const text = error && error.message ? String(error.message) : '';
        const safe = /future|24 hour|already on a todo|no timer|not found/i.test(text);
        this._timerError = safe ? text : 'Could not save the timer';
        this._render();
    }

    _afterTimerWrite(error) {
        if (!this._enabled)
            return;
        if (error) {
            this._noteTimerError(error);
            return;
        }
        this._timerError = '';
        if (!this._proxy)
            return;
        this._proxy.GetTimerRemote((result, readError) => {
            if (!this._enabled || readError || !result)
                return;
            this._applyTimerJson(result[0]);
        });
        this._refreshItems();
    }

    _applyTimerJson(raw) {
        let parsed;
        try {
            parsed = JSON.parse(raw || '{}');
        } catch {
            parsed = {state: 'idle', read_error: 'The saved timer could not be read'};
        }
        this._timer = parsed && typeof parsed === 'object' ? parsed : {state: 'idle'};
        if (this._timer.read_error)
            this._timerError = '';
        const state = this._timer.state;
        const canPick = state === 'stopped' ||
            ((state === 'running' || state === 'paused') && !this._timer.item_key);
        if (!canPick)
            this._assigning = false;
        if (this._timer.state === 'running' || this._timer.state === 'paused')
            this._switchAsk = null;
        this._schedulePrompt();
        if (this._enabled)
            this._render();
    }

    _schedulePrompt() {
        if (this._promptSource) {
            GLib.source_remove(this._promptSource);
            this._promptSource = 0;
        }
        const undo = this._timer && this._timer.undo;
        if (!undo || !(Number(undo.until) > 0))
            return;
        const bridgeNow = Number(this._timer.now) || Date.now() / 1000;
        const remain = Math.max(0, (Number(undo.until) - bridgeNow) * 1000);
        this._promptSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.ceil(remain) + 50, () => {
            this._promptSource = 0;
            if (this._enabled)
                this._render();
            return GLib.SOURCE_REMOVE;
        });
    }

    _undoButton(until, callback) {
        const button = new St.Button({
            style_class: 'button tetherbot-undo',
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Undo',
        });
        const bin = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            x_expand: false,
            y_expand: true,
        });
        const bar = new St.Widget({
            style_class: 'tetherbot-undo-bar',
            x_align: Clutter.ActorAlign.CENTER,
            y_expand: true,
        });
        const label = new St.Label({
            text: 'Undo',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        bin.add_child(bar);
        bin.add_child(label);
        button.x_expand = false;
        button.set_child(bin);
        button.connect('clicked', () => callback());
        this._undoBars.push({bar, until: Number(until) || 0});
        return button;
    }

    _actionButton(label, callback, closeMenu = true) {
        const button = new St.Button({
            label,
            style_class: 'button tetherbot-action',
            can_focus: true,
        });
        button.connect('clicked', () => {
            callback();
            if (closeMenu)
                this._indicator.menu.close();
        });
        return button;
    }

    _undoWindowMs() {
        const settings = this._settings;
        if (!settings || typeof settings.get_int !== 'function')
            return UNDO_MS;
        const seconds = settings.get_int('undo-seconds');
        if (!Number.isFinite(seconds) || seconds < 2 || seconds > 30)
            return UNDO_MS;
        return seconds * 1000;
    }

    _reloadBridgeSettings() {
        if (!this._proxy || !this._proxy.ReloadSettingsRemote)
            return;
        this._proxy.ReloadSettingsRemote(() => {
            if (this._enabled)
                this._refresh();
        });
    }

    _markDone(row) {
        if (!row || !row.key)
            return;
        const index = Number.isFinite(row.index) ? row.index : 0;
        const after = typeof row.after === 'string' ? row.after : '';
        const holds = (this._undoHolds || []).filter(hold => hold.key !== row.key);
        holds.push({key: row.key, row, until: 0, index, after, sent: false});
        this._undoSpan = this._undoWindowMs();
        this._undoHolds = shareUndoWindow(holds, Date.now(), this._undoSpan);
        this._armUndoTimer();
        this._render();
    }

    _flushDue(force = false) {
        const now = Date.now();
        const pending = (this._undoHolds || []).filter(hold => hold && !hold.sent && hold.key);
        const keys = force ? pending.map(hold => hold.key) : dueUndoKeys(pending, now);
        if (!keys.length)
            return;
        if (!this._hiddenDone)
            this._hiddenDone = new Set();
        for (const key of keys) {
            const hold = (this._undoHolds || []).find(item => item && item.key === key);
            if (!hold || hold.sent)
                continue;
            hold.sent = true;
            hold.until = now;
            this._hiddenDone.add(key);
            this._perform('done', key);
        }
    }

    _armUndoTimer() {
        if (this._undoSource) {
            GLib.source_remove(this._undoSource);
            this._undoSource = 0;
        }
        const delay = nextUndoDelay(this._undoHolds, Date.now());
        if (!delay)
            return;
        const wait = Math.max(1, Math.ceil(delay));
        this._undoSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, wait, () => {
            this._undoSource = 0;
            if (!this._enabled)
                return GLib.SOURCE_REMOVE;
            this._expireBatch();
            return GLib.SOURCE_REMOVE;
        });
    }

    _expireBatch() {
        const due = dueUndoKeys(this._undoHolds, Date.now()).length > 0;
        this._flushDue(false);
        if (!this._pointerOverTodos())
            this._undoHolds = (this._undoHolds || []).filter(hold => hold && !hold.sent && hold.until > Date.now());
        this._armUndoTimer();
        if (!this._enabled)
            return;
        if (due)
            this._refresh();
        else
            this._render();
    }

    _releasePinnedUndos() {
        const now = Date.now();
        const before = (this._undoHolds || []).length;
        this._undoHolds = (this._undoHolds || []).filter(hold => hold && !hold.sent && hold.until > now);
        if (this._undoHolds.length !== before && this._enabled)
            this._render();
        this._armUndoTimer();
    }

    _watchTodoPointer() {
        const box = this._todoSection && (this._todoSection.box || this._todoSection.actor);
        if (!box || typeof box.connect !== 'function')
            return;
        box.reactive = true;
        box.track_hover = true;
    }

    _pointerOverTodos() {
        if (!this._menuOpen)
            return false;
        const box = this._todoSection && (this._todoSection.box || this._todoSection.actor);
        if (!box)
            return false;
        if (box.hover)
            return true;
        if (typeof box.get_first_child !== 'function')
            return false;
        let child = box.get_first_child();
        while (child) {
            if (child.hover)
                return true;
            child = child.get_next_sibling ? child.get_next_sibling() : null;
        }
        return false;
    }

    _finishUndoChrome() {
        this._paintUndoBars();
        this._armUndoPaint();
    }

    _paintUndoBars() {
        const now = Date.now();
        for (const entry of this._undoBars || []) {
            const fraction = undoFraction(entry.until, now, this._undoSpan || this._undoWindowMs());
            const parent = entry.bar.get_parent();
            const width = parent ? parent.get_width() : 0;
            entry.bar.width = width > 0 ? Math.max(0, Math.round(width * fraction)) : 0;
            entry.bar.visible = fraction > 0;
        }
    }

    _armUndoPaint() {
        const now = Date.now();
        const holds = this._undoHolds || [];
        const timerUntil = this._timer && this._timer.undo ? Number(this._timer.undo.until) * 1000 : 0;
        const active = holds.length > 0 || timerUntil > now;
        if (!active) {
            if (this._undoPaintSource) {
                GLib.source_remove(this._undoPaintSource);
                this._undoPaintSource = 0;
            }
            return;
        }
        if (this._undoPaintSource)
            return;
        this._undoPaintSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            if (!this._enabled) {
                this._undoPaintSource = 0;
                return GLib.SOURCE_REMOVE;
            }
            this._todoPointer = this._pointerOverTodos();
            this._paintUndoBars();
            const clock = Date.now();
            if (dueUndoKeys(this._undoHolds, clock).length)
                this._expireBatch();
            else if (!this._todoPointer && (this._undoHolds || []).some(hold => hold && hold.sent))
                this._releasePinnedUndos();
            const stillHeld = (this._undoHolds || []).length > 0;
            const undo = this._timer && this._timer.undo;
            const timerLive = Boolean(undo && Number(undo.until) * 1000 > Date.now());
            if (!stillHeld && !timerLive) {
                this._undoPaintSource = 0;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _undo(key) {
        this._undoHolds = (this._undoHolds || []).filter(hold => hold.key !== key);
        this._armUndoTimer();
        this._render();
    }

    _openWindow(key) {
        if (!this._proxy)
            return;
        const call = openWindowCall(key);
        this._proxy.OpenWindowRemote(...call.args, () => {});
        this._indicator?.menu.close();
    }

    _perform(action, key) {
        if (!this._proxy || !key)
            return;
        const call = performCall(action, key);
        this._proxy.PerformActionRemote(...call.args, (_result, error) => {
            if (!this._enabled || !error || action !== 'done' || !this._hiddenDone)
                return;
            this._hiddenDone.delete(key);
            this._render();
        });
    }

    _sync() {
        if (!this._proxy || !this._running)
            return;
        this._armSyncLabel('Syncing…');
        this._proxy.SyncNowRemote((_result, error) => {
            if (!this._enabled)
                return;
            if (error) {
                this._armSyncLabel('Sync now');
                return;
            }
            this._refresh();
            this._armSyncLabel('Updated', 2500);
        });
    }

    _armSyncLabel(text, revertMs = 0) {
        if (this._syncLabelSource) {
            GLib.source_remove(this._syncLabelSource);
            this._syncLabelSource = 0;
        }
        if (this._syncItem && this._syncItem.label)
            this._syncItem.label.text = text;
        if (!revertMs)
            return;
        this._syncLabelSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, revertMs, () => {
            this._syncLabelSource = 0;
            if (this._enabled && this._syncItem && this._syncItem.label)
                this._syncItem.label.text = 'Sync now';
            return GLib.SOURCE_REMOVE;
        });
    }

    _showNotification(payload, reason) {
        let model;
        try {
            model = notificationModel(payload, reason, botLabels(this._bots));
        } catch {
            return;
        }
        const source = this._ensureSource();
        if (!source)
            return;
        const token = noticeKey(payload, reason);
        if (token) {
            if (!this._shownNotices)
                this._shownNotices = new Set();
            if (this._shownNotices.has(token))
                return;
            this._shownNotices.add(token);
        }
        const notification = new MessageTray.Notification({
            source,
            title: model.title,
            body: model.body,
            urgency: MessageTray.Urgency.NORMAL,
        });
        for (const action of model.actions)
            notification.addAction(action.label, () => this._runNotificationAction(action));
        source.addNotification(notification);
    }

    _runNotificationAction(action) {
        if (!this._proxy)
            return;
        if (action.id === 'approve' || action.id === 'veto' || action.id === 'done') {
            this._perform(action.id, action.key);
        } else if (action.id === 'snooze-hour' || action.id === 'snooze-tomorrow') {
            const which = action.id === 'snooze-hour' ? 'hour' : 'tomorrow';
            const call = snoozeCall(action.key, snoozeIso(which, new Date()));
            this._proxy.SnoozeRemote(...call.args, () => {});
        } else if (action.id === 'request_secret') {
            this._proxy.RequestSecretEntryRemote(action.slot || '', () => {});
        }
    }

    _ensureSource() {
        if (this._source)
            return this._source;
        const source = new MessageTray.Source({
            title: 'TetherBot',
            iconName: 'dialog-information-symbolic',
        });
        source.policy = new MessageTray.NotificationApplicationPolicy('tetherbot');
        try {
            Main.messageTray.add(source);
        } catch {
            console.debug('TetherBot: notification source was not added');
            return null;
        }
        source.connect('destroy', () => {
            if (this._source === source)
                this._source = null;
        });
        this._source = source;
        return source;
    }

    _buildClipboardIndicator() {
        this._clipEntries = [];
        this._clipPinHold = false;
        this._clipIndicator = new PanelMenu.Button(0.0, 'Clipboard', false);
        this._clipIndicator.add_style_class_name('tetherbot-clipboard');
        const clipFile = this.dir.get_child('icons/clipboard-symbolic.svg');
        const icon = new St.Icon({
            gicon: Gio.FileIcon.new(clipFile),
            style_class: 'system-status-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._clipIndicator.add_child(icon);
        this._clipIndicator.accessible_name = 'Clipboard';
        this._clipIndicator.tooltip_text = 'Clipboard';
        this._clipSection = new PopupMenu.PopupMenuSection();
        this._clipIndicator.menu.addMenuItem(this._clipSection);
        this._clipIndicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const clearItem = new PopupMenu.PopupMenuItem('Clear history');
        clearItem.connect('activate', () => this._clearClipboard());
        this._clipIndicator.menu.addMenuItem(clearItem);
        const openItem = new PopupMenu.PopupMenuItem('Open clipboard');
        openItem.connect('activate', () => this._openClipboardWindow());
        this._clipIndicator.menu.addMenuItem(openItem);
        this._fillClipboardMenu();
        Main.panel.addToStatusArea(`${this.uuid}-clipboard`, this._clipIndicator, 1);
    }

    _watchClipboard() {
        this._clipSelection = null;
        this._clipOwnerId = 0;
        try {
            this._clipSelection = global.display.get_selection();
            this._clipOwnerId = this._clipSelection.connect('owner-changed', (_selection, type) => {
                this._onClipboardOwner(type);
            });
        } catch {
            this._clipSelection = null;
            this._clipOwnerId = 0;
        }
        this._captureClipboard();
    }

    _unwatchClipboard() {
        const selection = this._clipSelection;
        if (selection && this._clipOwnerId) {
            try {
                selection.disconnect(this._clipOwnerId);
            } catch {
                // The selection owner is already gone with the shell.
            }
        }
        this._clipSelection = null;
        this._clipOwnerId = 0;
    }

    _onClipboardOwner(type) {
        let clipboardType;
        try {
            clipboardType = Meta.SelectionType.SELECTION_CLIPBOARD;
        } catch {
            clipboardType = 1;
        }
        if (type !== clipboardType)
            return;
        // Copying an image back changes the owner. Ignore that echo.
        if (this._clipboardEchoing())
            return;
        this._captureClipboard();
    }

    _captureClipboard() {
        if (!this._enabled)
            return;
        this._clipToken = (this._clipToken || 0) + 1;
        const token = this._clipToken;
        const options = this._clipboardOptions();
        const mimes = this._clipboardMimes();
        const wmClass = this._focusedClass();
        const decision = classifyClipboard({
            text: null,
            mimes,
            wmClass,
            enabled: options.enabled,
            excluded: options.excluded,
            lookalike: options.lookalike,
        });
        if (
            decision === 'skipped-sensitive' ||
            decision === 'skipped-app' ||
            decision === 'skipped-disabled'
        ) {
            this._noteClipboard(mimes, wmClass, decision);
            return;
        }
        const imageMime = pickImageMime(mimes);
        if (imageMime && decision !== 'needs-text') {
            this._captureClipboardImage(token, mimes, wmClass, imageMime, options);
            return;
        }
        if (decision !== 'needs-text') {
            this._noteClipboard(mimes, wmClass, decision);
            return;
        }
        let clipboard;
        try {
            clipboard = St.Clipboard.get_default();
        } catch {
            clipboard = null;
        }
        if (!clipboard)
            return;
        clipboard.get_text(St.ClipboardType.CLIPBOARD, (_clip, text) => {
            if (!this._enabled || token !== this._clipToken)
                return;
            const current = this._clipboardOptions();
            const result = classifyClipboard({
                text,
                mimes,
                wmClass,
                enabled: current.enabled,
                excluded: current.excluded,
                lookalike: current.lookalike,
            });
            this._noteClipboard(mimes, wmClass, result);
            if (result !== 'stored' && result !== 'stored-masked')
                return;
            if (!this._proxy || !this._proxy.OfferClipboardRemote)
                return;
            const meta = JSON.stringify({mimes, wm_class: wmClass});
            this._proxy.OfferClipboardRemote(text, meta, () => {
                if (this._enabled)
                    this._loadClipboard();
            });
        });
    }

    _captureClipboardImage(token, mimes, wmClass, imageMime, options) {
        if (options.images !== true) {
            this._noteClipboard(mimes, wmClass, 'skipped-images-off');
            return;
        }
        let clipboard;
        try {
            clipboard = St.Clipboard.get_default();
        } catch {
            clipboard = null;
        }
        if (!clipboard || typeof clipboard.get_content !== 'function') {
            this._noteClipboard(mimes, wmClass, 'skipped-image-bad');
            return;
        }
        try {
            clipboard.get_content(St.ClipboardType.CLIPBOARD, imageMime, (_clip, bytes) => {
                if (!this._enabled || token !== this._clipToken)
                    return;
                const read = imageBytes(bytes);
                if (read.result !== 'ok') {
                    this._noteClipboard(mimes, wmClass, read.result);
                    return;
                }
                const current = this._clipboardOptions();
                if (current.enabled !== true) {
                    this._noteClipboard(mimes, wmClass, 'skipped-disabled');
                    return;
                }
                if (current.images !== true) {
                    this._noteClipboard(mimes, wmClass, 'skipped-images-off');
                    return;
                }
                if (!this._proxy || !this._proxy.OfferClipboardImageRemote) {
                    this._noteClipboard(mimes, wmClass, 'skipped-image-bad');
                    return;
                }
                let payload = read.data;
                const meta = JSON.stringify({mimes, wm_class: wmClass, mime: imageMime});
                try {
                    this._proxy.OfferClipboardImageRemote(payload, meta, () => {
                        payload = null;
                        if (this._enabled)
                            this._loadClipboard();
                    });
                } catch {
                    this._noteClipboard(mimes, wmClass, 'skipped-image-bad');
                }
            });
        } catch {
            this._noteClipboard(mimes, wmClass, 'skipped-image-bad');
        }
    }

    _clipboardOptions() {
        const settings = this._settings;
        if (!settings) {
            return {
                enabled: true,
                excluded: DEFAULT_EXCLUDED_APPS,
                lookalike: LOOKALIKE_SKIP,
                images: true,
            };
        }
        let enabled;
        let excluded = DEFAULT_EXCLUDED_APPS;
        let lookalike;
        let images;
        try {
            enabled = settings.get_boolean('clipboard-enabled') === true;
        } catch {
            enabled = true;
        }
        try {
            const list = settings.get_strv('clipboard-excluded-apps');
            if (Array.isArray(list))
                excluded = list;
        } catch {
            excluded = DEFAULT_EXCLUDED_APPS;
        }
        try {
            lookalike = lookalikeMode(settings.get_string('clipboard-lookalike'));
        } catch {
            lookalike = LOOKALIKE_SKIP;
        }
        try {
            images = settings.get_boolean('clipboard-images') === true;
        } catch {
            images = true;
        }
        return {enabled, excluded, lookalike, images};
    }

    _noteClipboard(mimes, wmClass, result) {
        if (!this._proxy || !this._proxy.NoteClipboardRemote)
            return;
        const meta = JSON.stringify({mimes, wm_class: wmClass, result});
        try {
            this._proxy.NoteClipboardRemote(meta, () => {});
        } catch {
            // An older bridge has no note method. The text stays here.
        }
    }

    _clipboardMimes() {
        try {
            const selection = this._clipSelection || global.display.get_selection();
            const type = Meta.SelectionType.SELECTION_CLIPBOARD;
            if (selection && selection.get_mimetypes)
                return selection.get_mimetypes(type) || [];
        } catch {
            return [];
        }
        return [];
    }

    _focusedClass() {
        try {
            const win = global.display.focus_window;
            if (!win)
                return '';
            if (win.get_wm_class)
                return win.get_wm_class() || '';
            return win.wm_class || '';
        } catch {
            return '';
        }
    }

    _loadClipboard() {
        if (!this._enabled || !this._proxy || !this._proxy.GetClipboardRemote)
            return;
        this._proxy.GetClipboardRemote('', (result, error) => {
            if (!this._enabled || error || !result)
                return;
            let parsed;
            try {
                const raw = result[0];
                parsed = JSON.parse(typeof raw === 'string' ? raw : '[]');
            } catch {
                parsed = [];
            }
            this._clipEntries = Array.isArray(parsed) ? parsed : [];
            this._fillClipboardMenu();
        });
    }

    _fillClipboardMenu() {
        if (!this._clipSection)
            return;
        this._clipSection.removeAll();
        const entries = Array.isArray(this._clipEntries) ? this._clipEntries : [];
        const shown = entries.filter(entry => {
            if (!entry)
                return false;
            if (entry.kind === 'image')
                return true;
            return typeof entry.text === 'string';
        });
        const pinned = shown.filter(entry => entry.pinned === true);
        const regular = shown.filter(entry => entry.pinned !== true).slice(0, MENU_LIMIT);
        this._clipSection.addMenuItem(new PopupMenu.PopupMenuItem('Pinned', {reactive: false}));
        this._appendClipboardRows(pinned);
        this._clipSection.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        if (!pinned.length && !regular.length) {
            const empty = new PopupMenu.PopupMenuItem('Nothing copied yet', {reactive: false});
            this._clipSection.addMenuItem(empty);
            return;
        }
        this._appendClipboardRows(regular);
    }

    _appendClipboardRows(entries) {
        for (const entry of entries) {
            const isImage = entry?.kind === 'image';
            if (!entry || (!isImage && typeof entry.text !== 'string'))
                continue;
            const masked = entry.masked === true;
            const pinned = entry.pinned === true;
            const item = new PopupMenu.PopupBaseMenuItem();
            item.track_hover = true;
            const row = new St.BoxLayout({
                style_class: 'tetherbot-clip-row',
                y_align: Clutter.ActorAlign.CENTER,
                x_expand: true,
            });
            const textBox = new St.BoxLayout({
                style_class: 'tetherbot-clip-text',
                y_align: Clutter.ActorAlign.CENTER,
                x_expand: true,
            });
            const label = new St.Label({
                text: isImage
                    ? imageLabel(entry.mime, entry.size)
                    : menuLabel(masked ? '' : entry.text, masked),
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            if (label.clutter_text) {
                label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
                label.clutter_text.line_wrap = false;
            }
            if (isImage) {
                const thumb = this._clipThumb(entry);
                if (thumb)
                    textBox.add_child(thumb);
            }
            textBox.add_child(label);
            const dots = clipDots(entry.tags);
            if (dots.get_n_children() > 0)
                textBox.add_child(dots);
            row.add_child(textBox);
            const editTip = isImage ? 'Images are not edited' : 'Edit';
            const tagTip = masked ? 'Hidden passwords are not tagged' : 'Tag';
            let searchTip = 'Search the web';
            if (isImage)
                searchTip = 'Images are not searched';
            else if (masked)
                searchTip = 'Hidden passwords are not searched';
            let sendBlocked = '';
            if (isImage)
                sendBlocked = 'Images are not sent';
            else if (masked)
                sendBlocked = 'Hidden passwords are not sent';
            const sendTip = name => sendBlocked || name;
            const canSend = !sendBlocked;
            const copyBack = () => {
                if (isImage)
                    this._recopyImage(entry.id);
                else
                    this._recopyClipboard(entry.text);
            };
            const columns = [
                ['document-edit-symbolic', editTip, !masked && !isImage, () => {
                    this._openClipAction('clip-edit', entry.id);
                }],
                ['view-pin-symbolic', pinned ? 'Unpin' : 'Pin', true, () => {
                    this._pinClipboard(entry.id, !pinned);
                }],
                ['tetherbot-tag-symbolic', tagTip, !masked, () => {
                    this._openClipAction('clip-tag', entry.id);
                }],
                ['edit-copy-symbolic', 'Copy', true, copyBack],
                ['system-search-symbolic', searchTip, !masked && !isImage, () => {
                    this._searchClipboard(entry.id);
                }],
                ['tetherbot-check-symbolic', sendTip('Make a todo'), canSend, () => {
                    this._sendClipboard(entry.id, 'clip-todo', label);
                }],
                ['tetherbot-square-check-symbolic', sendTip('Make a todo with context'), canSend, () => {
                    this._sendClipboard(entry.id, 'clip-todo-context', label);
                }],
                ['tetherbot-circle-help-symbolic', sendTip('Tell me more'), canSend, () => {
                    this._sendClipboard(entry.id, 'clip-ask', label);
                }],
                ['edit-delete-symbolic', 'Delete', true, () => this._deleteClipboard(entry.id)],
            ];
            const actions = new St.BoxLayout({
                style_class: 'tetherbot-clip-actions',
                y_align: Clutter.ActorAlign.CENTER,
                x_expand: false,
                reactive: true,
            });
            const holdClipClick = () => {
                this._clipPinHold = true;
                GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    this._clipPinHold = false;
                    return GLib.SOURCE_REMOVE;
                });
            };
            actions.connect('button-press-event', () => {
                holdClipClick();
                return Clutter.EVENT_PROPAGATE;
            });
            actions.connect('button-release-event', () => {
                holdClipClick();
                return Clutter.EVENT_STOP;
            });
            columns.forEach(([iconName, tip, enabled, onPress], index) => {
                if (index > 0) {
                    actions.add_child(new St.Widget({
                        style_class: 'tetherbot-clip-sep',
                        y_align: Clutter.ActorAlign.CENTER,
                    }));
                }
                const button = this._clipIconButton(iconName, tip, enabled);
                if (enabled) {
                    button.connect('button-press-event', () => {
                        holdClipClick();
                        onPress();
                        return Clutter.EVENT_STOP;
                    });
                }
                actions.add_child(button);
            });
            row.add_child(actions);
            item.add_child(row);
            item.connect('activate', () => {
                if (this._clipPinHold) {
                    this._clipPinHold = false;
                    return;
                }
                copyBack();
            });
            this._clipSection.addMenuItem(item);
            this._fitClipboardRow(textBox, actions);
        }
    }

    _installIconTheme() {
        try {
            const display = Gdk.Display.get_default();
            if (!display)
                return;
            const theme = Gtk.IconTheme.get_for_display(display);
            const path = this.dir.get_child('icons').get_path();
            const current = theme.get_search_path() || [];
            if (!current.includes(path))
                theme.add_search_path(path);
        } catch {
            console.debug('TetherBot: icon theme path was not added');
        }
    }

    _fitClipboardRow(textBox, actions) {
        // The icon cluster keeps its natural width. The label uses what remains,
        // and the row stays inside the work area so the icons are not pushed off.
        let budget = 0;
        try {
            const monitor = Main.layoutManager.findIndexForActor(this._clipIndicator);
            const area = Main.layoutManager.getWorkAreaForMonitor(monitor);
            if (area && area.width)
                budget = area.width;
        } catch {
            budget = 0;
        }
        if (!(budget > 0))
            return;
        let icons;
        try {
            const [, natural] = actions.get_preferred_width(-1);
            icons = natural || 0;
        } catch {
            icons = 0;
        }
        if (!(icons >= 40))
            return;
        const textMax = Math.max(72, Math.floor(budget - icons - 96));
        textBox.style = `max-width: ${textMax}px;`;
    }

    _menuIcon(iconName, styleClass) {
        // The shell looks up icon names in its own theme, not the GTK search
        // path the window uses. Our files end in -symbolic.svg, so St still
        // recolors them.
        const styleClassName = styleClass || '';
        if (typeof iconName === 'string' && iconName.startsWith('tetherbot-')) {
            try {
                const file = this.dir.get_child(
                    `icons/hicolor/scalable/actions/${iconName}.svg`);
                if (file.query_exists(null)) {
                    return new St.Icon({
                        gicon: Gio.FileIcon.new(file),
                        icon_size: 16,
                        style_class: styleClassName,
                    });
                }
            } catch {
                console.debug('TetherBot: menu icon file was not used');
            }
        }
        return new St.Icon({
            icon_name: iconName,
            icon_size: 16,
            style_class: styleClassName,
        });
    }

    _clipIconButton(iconName, name, enabled) {
        const icon = this._menuIcon(iconName, '');
        let buttonClass = 'popup-menu-item-button tetherbot-clip-action';
        if (!enabled)
            buttonClass += ' tetherbot-clip-off';
        const button = new St.Button({
            style_class: buttonClass,
            child: icon,
            can_focus: enabled,
            reactive: enabled,
            track_hover: enabled,
            x_expand: false,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.accessible_name = name;
        button.tooltip_text = name;
        return button;
    }

    _sendClipboard(entryId, action, label) {
        if (!entryId || !this._proxy || !this._proxy.SendClipboardRemote) {
            this._showClipResult(label, 'Not sent: Bridge not running');
            return;
        }
        this._proxy.SendClipboardRemote(entryId, action, 'primary', (result, error) => {
            if (!this._enabled)
                return;
            if (error) {
                const reason = error.message ? String(error.message) : 'Could not send';
                this._showClipResult(label, `Not sent: ${reason}`);
                return;
            }
            const value = Array.isArray(result) ? result[0] : result;
            if (value === 'sent')
                this._showClipResult(label, 'Sent');
            else
                this._showClipResult(label, 'Not sent');
        });
    }

    _showClipResult(label, message) {
        if (!label)
            return;
        const previous = label.text;
        label.text = message;
        const source = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2000, () => {
            try {
                if (label.text === message)
                    label.text = previous;
            } catch {
                // The row was rebuilt.
            }
            return GLib.SOURCE_REMOVE;
        });
        label._clipResultSource = source;
    }

    _clipThumb(entry) {
        const thumbPath = typeof entry.thumb === 'string' ? entry.thumb : '';
        const imagePath = typeof entry.path === 'string' ? entry.path : '';
        const shown = thumbPath || imagePath;
        if (!shown)
            return null;
        try {
            const file = Gio.File.new_for_path(shown);
            if (thumbPath) {
                const painted = clipThumbActor(file);
                if (painted)
                    return painted;
            }
            return new St.Icon({
                gicon: new Gio.FileIcon({file}),
                icon_size: 48,
                style_class: 'tetherbot-clip-thumb',
                y_align: Clutter.ActorAlign.CENTER,
            });
        } catch {
            return null;
        }
    }

    _pinClipboard(entryId, pinned) {
        if (!entryId || !this._proxy || !this._proxy.PinClipboardRemote)
            return;
        this._proxy.PinClipboardRemote(entryId, pinned === true, () => {
            if (this._enabled)
                this._loadClipboard();
        });
    }

    _deleteClipboard(entryId) {
        if (!entryId || !this._proxy || !this._proxy.DeleteClipboardRemote)
            return;
        this._proxy.DeleteClipboardRemote(entryId, () => {
            if (this._enabled)
                this._loadClipboard();
        });
    }

    _recopyClipboard(text) {
        if (typeof text !== 'string' || !text)
            return;
        try {
            St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
        } catch {
            console.debug('TetherBot: clipboard was not written');
        }
        this._clipIndicator?.menu.close();
    }

    _recopyImage(entryId) {
        if (!entryId || !this._proxy || !this._proxy.GetClipboardImageRemote) {
            Main.notify('TetherBot', 'That image is not available');
            this._clipIndicator?.menu.close();
            return;
        }
        this._proxy.GetClipboardImageRemote(entryId, (result, error) => {
            if (!this._enabled)
                return;
            if (error || !result || result.length < 2) {
                Main.notify('TetherBot', 'That image is not available');
                return;
            }
            const mime = result[0];
            const data = result[1];
            if (typeof mime !== 'string' || !mime.startsWith('image/') || !data) {
                Main.notify('TetherBot', 'Could not copy the image');
                return;
            }
            try {
                this._armClipboardEcho();
                St.Clipboard.get_default().set_content(
                    St.ClipboardType.CLIPBOARD,
                    mime,
                    clipboardBytes(data)
                );
            } catch {
                console.debug('TetherBot: image was not written');
                Main.notify('TetherBot', 'Could not copy the image');
            }
        });
        this._clipIndicator?.menu.close();
    }

    _armClipboardEcho() {
        try {
            this._clipEchoUntil = GLib.get_monotonic_time() + 1500000;
        } catch {
            this._clipEchoUntil = 0;
        }
    }

    _clipboardEchoing() {
        if (typeof this._clipEchoUntil !== 'number' || !this._clipEchoUntil)
            return false;
        try {
            return GLib.get_monotonic_time() < this._clipEchoUntil;
        } catch {
            return false;
        }
    }

    _clearClipboard() {
        if (!this._proxy || !this._proxy.ClearClipboardRemote)
            return;
        this._proxy.ClearClipboardRemote(() => {
            if (this._enabled)
                this._loadClipboard();
        });
        this._clipIndicator?.menu.close();
    }

    _openClipboardWindow() {
        if (!this._proxy)
            return;
        const call = openWindowCall('clipboard');
        this._proxy.OpenWindowRemote(...call.args, () => {});
        this._clipIndicator?.menu.close();
    }

    _openClipAction(action, entryId) {
        if (!this._proxy || !entryId)
            return;
        const call = openWindowCall(`${action}:${entryId}`);
        this._proxy.OpenWindowRemote(...call.args, () => {});
        this._clipIndicator?.menu.close();
    }

    _searchClipboard(entryId) {
        if (!entryId || !this._proxy || !this._proxy.SearchClipboardRemote)
            return;
        this._proxy.SearchClipboardRemote(entryId, () => {});
        this._clipIndicator?.menu.close();
    }
}

function imageBytes(bytes) {
    if (!bytes || typeof bytes.get_size !== 'function')
        return {result: 'skipped-image-bad', data: null};
    let size;
    try {
        const raw = bytes.get_size();
        size = typeof raw === 'number' ? raw : Number(raw);
    } catch {
        return {result: 'skipped-image-bad', data: null};
    }
    if (!Number.isFinite(size))
        return {result: 'skipped-image-bad', data: null};
    if (size === 0)
        return {result: 'skipped-empty', data: null};
    if (!imageWithinCap(size))
        return {result: 'skipped-image-large', data: null};
    let data;
    try {
        data = typeof bytes.get_data === 'function' ? bytes.get_data() : null;
    } catch {
        data = null;
    }
    if (data && typeof data.toArray === 'function')
        data = data.toArray();
    if (!data || (typeof data.length === 'number' && data.length === 0))
        return {result: data ? 'skipped-empty' : 'skipped-image-bad', data: null};
    return {result: 'ok', data};
}

function clipboardBytes(data) {
    if (data && typeof data.get_data === 'function' && typeof data.get_size === 'function')
        return data;
    if (data && typeof data.toArray === 'function')
        return GLib.Bytes.new(data.toArray());
    return GLib.Bytes.new(data);
}

function clipThumbActor(file) {
    try {
        const cache = St.TextureCache.get_default();
        let paintScale = 1;
        try {
            paintScale = St.ThemeContext.get_for_stage(global.stage).scale_factor || 1;
        } catch {
            paintScale = 1;
        }
        const actor = cache.load_file_async(file, 48, 48, paintScale, 1);
        if (!actor)
            return null;
        const box = new St.Widget({
            style_class: 'tetherbot-clip-thumb',
            width: 48,
            height: 48,
            y_align: Clutter.ActorAlign.CENTER,
            clip_to_allocation: true,
        });
        box.add_child(actor);
        return box;
    } catch {
        return null;
    }
}

function sectionTitle(text) {
    return new PopupMenu.PopupMenuItem(text, {reactive: false});
}

function pauseBars(large) {
    const box = new St.BoxLayout({
        style_class: large ? 'tetherbot-pause tetherbot-pause-lg' : 'tetherbot-pause',
        y_align: Clutter.ActorAlign.CENTER,
    });
    box.add_child(new St.Widget({style_class: 'tetherbot-pause-bar'}));
    box.add_child(new St.Widget({style_class: 'tetherbot-pause-bar'}));
    return box;
}

function chipLabel(text, tone) {
    return new St.Label({
        text,
        style_class: `tetherbot-chip tetherbot-tone-${tone || 'neutral'}`,
    });
}

const CLIP_DOT_TONES = {
    red: true,
    orange: true,
    yellow: true,
    green: true,
    teal: true,
    blue: true,
    purple: true,
    pink: true,
    gray: true,
};

function clipDots(tags) {
    const box = new St.BoxLayout({
        y_align: Clutter.ActorAlign.CENTER,
        style_class: 'tetherbot-clip-dots',
    });
    const list = Array.isArray(tags) ? tags : [];
    for (const tag of list) {
        if (!tag || typeof tag.name !== 'string' || !tag.name)
            continue;
        const tone = CLIP_DOT_TONES[tag.color] ? tag.color : 'gray';
        const dot = new St.Widget({
            style_class: `tetherbot-clip-dot tetherbot-clip-dot-${tone}`,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: tag.name,
        });
        dot.tooltip_text = tag.name;
        box.add_child(dot);
    }
    return box;
}

function unpackCounts(value) {
    if (!value)
        return {asks: 0, todos: 0};
    if (typeof value.deep_unpack === 'function')
        return value.deep_unpack();
    if (typeof value.deepUnpack === 'function')
        return value.deepUnpack();
    return value;
}
