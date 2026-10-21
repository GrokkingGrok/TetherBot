// SPDX-License-Identifier: GPL-2.0-or-later
//
// GNOME Shell 50, ESM. This file may talk to the bridge only through the
// session bus. Do not import Soup, open a socket, spawn a network process,
// or store a secret here.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
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
    nextUndoDelay,
    shareUndoWindow,
    undoFraction,
    elapsedSeconds,
    formatElapsed,
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
} from './view.js';

export default class TetherBotExtension extends Extension {
    enable() {
        this._enabled = true;
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
            style_class: 'tetherbot-mark',
            visible: false,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.END,
            x_expand: false,
            y_expand: false,
        });
        this._face = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._face.add_child(this._icon);
        this._face.add_child(this._mark);
        this._badge = '';
        this._overlay = '';
        this._icon.connect('notify::height', () => this._layoutMark());
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

        try {
            const xmlFile = this.dir.get_child('io.github.grokkinggrok.TetherBot1.xml');
            const [, bytes] = xmlFile.load_contents(null);
            this._Proxy = Gio.DBusProxy.makeProxyWrapper(new TextDecoder().decode(bytes));
        } catch (error) {
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
        } catch (error) {
            this._settings = null;
            this._settingsId = 0;
        }

        this._nameWatch = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._onNameAppeared(),
            () => this._onNameVanished(),
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
        this._indicator?.destroy();
        this._indicator = null;
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
        this._settings = null;
        this._settingsId = 0;
        this._undoSpan = 0;
        this._undoHolds = [];
        this._hiddenDone = new Set();
        this._bots = [];
        this._items = [];
        this._searched = null;
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
            if (open)
                this._requestBridge();
            else {
                this._todoPointer = false;
                this._flushDue(true);
                this._undoHolds = [];
                this._armUndoTimer();
                this._refresh();
            }
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
        let session = null;
        try {
            session = Gio.DBus.session;
        } catch (error) {
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
                (connection, result) => this._onActivateResult(connection, result),
            );
        } catch (error) {
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
        } catch (error) {
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
            },
            null,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START,
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
        } catch (error) {
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
            } catch (parseError) {
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
            } catch (parseError) {
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
        this._overlay = kind === 'dot' || kind === 'ring' ? kind : '';
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
        const dot = this._overlay === 'dot';
        const span = height > 0 ? Math.max(4, Math.round(height * (dot ? 0.34 : 0.42))) : 0;
        const stroke = height > 0 ? Math.max(1, Math.round(height * 0.1)) : 0;
        this._mark.style_class = dot
            ? 'tetherbot-mark tetherbot-mark-dot'
            : 'tetherbot-mark tetherbot-mark-ring';
        if (span)
            this._mark.style = dot
                ? `width:${span}px;height:${span}px;`
                : `width:${span}px;height:${span}px;border-width:${stroke}px;`;
        this._mark.show();
    }

    _syncTick(view) {
        const want = Boolean(
            view && view.textStyle === 'run' && view.text && view.text !== '--:--' && this._running,
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
            if (summary.tone === 'attention')
                item.add_style_class_name('tetherbot-bot-alert');
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
        if (row.chips && row.chips.priority) {
            heading.add_child(chipLabel(row.chips.priority, row.chips.priorityTone));
        }
        heading.add_child(title);
        text.add_child(heading);
        if (row.chips)
            text.add_child(this._chipRow(row.chips, row.tracked, row.botLabel));
        else {
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
        if (row.undo) {
            top.add_child(this._undoButton(row.undoUntil, () => this._undo(row.key)));
        } else if (row.canSendDone) {
            top.add_child(this._actionButton('Done', () => this._markDone(row), false));
        }
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
            if (block.undo) {
                box.add_child(this._undoButton(block.undo.untilMs, () => this._undoStop()));
            }
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
            if (block.kind === 'switch')
                row.add_child(this._timerActions(block.actions || []));
            else if (block.action) {
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
        if (label === 'Pause')
            this._timerCall('PauseTimerRemote');
        else if (label === 'Resume')
            this._timerCall('ResumeTimerRemote');
        else if (label === 'Stop')
            this._timerCall('StopTimerRemote');
        else if (label === 'Undo')
            this._undoStop();
        else if (label === 'Add to a todo') {
            this._assigning = true;
            this._editingStart = false;
            this._render();
        } else if (label === 'Dismiss')
            this._timerCall('DismissTimerRemote');
        else if (label === 'Edit start') {
            this._editingStart = true;
            this._assigning = false;
            this._setHint = '';
            this._render();
        } else if (label === '-5m')
            this._adjustStart(-300);
        else if (label === '-15m')
            this._adjustStart(-900);
        else if (label === '-30m')
            this._adjustStart(-1800);
        else if (label === 'Keep')
            this._resolveWarning('keep', 0);
        else if (label === 'Discard')
            this._resolveWarning('discard', 0);
        else if (label === 'Set time...') {
            this._settingTime = true;
            this._render();
        } else if (label === 'Switch')
            this._confirmSwitch();
        else if (label === 'Cancel') {
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
        let parsed = null;
        try {
            parsed = JSON.parse(raw || '{}');
        } catch (error) {
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
            x_align: Clutter.ActorAlign.START,
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
        } catch (error) {
            return;
        }
        const source = this._ensureSource();
        if (!source)
            return;
        const notification = new MessageTray.Notification({
            source,
            title: model.title,
            body: model.body,
            urgency: MessageTray.Urgency.NORMAL,
        });
        for (const action of model.actions) {
            notification.addAction(action.label, () => this._runNotificationAction(action));
        }
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
        } catch (error) {
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

function unpackCounts(value) {
    if (!value)
        return {asks: 0, todos: 0};
    if (typeof value.deep_unpack === 'function')
        return value.deep_unpack();
    if (typeof value.deepUnpack === 'function')
        return value.deepUnpack();
    return value;
}
