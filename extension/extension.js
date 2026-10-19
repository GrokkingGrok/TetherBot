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
    indicatorView,
    menuModel,
    startServiceCall,
    mergeTodoSearch,
    notificationModel,
    openWindowCall,
    performCall,
    snoozeCall,
    snoozeIso,
    todoFilter,
    undoCall,
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
        this._undoSources = [];
        this._Proxy = null;
        this._seenBridge = false;
        this._activationFailed = false;
        this._activatePending = false;
        this._activateRetried = false;
        this._activateSource = 0;

        this._indicator = new PanelMenu.Button(0.0, 'TetherBot', false);
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            icon_name: 'network-offline-symbolic',
            style_class: 'system-status-icon tetherbot-indicator tetherbot-dimmed',
        });
        this._badge = new St.Label({
            text: '',
            style_class: 'tetherbot-badge',
            visible: false,
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._badge);
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
        this._badge = null;
        this._search = null;
        this._Proxy = null;
        for (const id of this._undoSources || [])
            GLib.source_remove(id);
        this._undoSources = [];
        if (this._activateSource) {
            GLib.source_remove(this._activateSource);
            this._activateSource = 0;
        }
        this._undoHolds = [];
        this._bots = [];
        this._items = [];
        this._searched = null;
    }

    _buildMenu() {
        this._banner = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._indicator.menu.addMenuItem(this._banner);
        this._botSection = new PopupMenu.PopupMenuSection();
        this._askSection = new PopupMenu.PopupMenuSection();
        this._todoSection = new PopupMenu.PopupMenuSection();
        this._indicator.menu.addMenuItem(this._botSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addMenuItem(this._askSection);
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
        });
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
        const view = indicatorView({
            running: this._running,
            state: this._state,
            counts: this._counts,
            activationFailed: this._activationFailed,
        });
        const classes = ['system-status-icon', 'tetherbot-indicator'];
        if (view.dimmed)
            classes.push('tetherbot-dimmed');
        else if (view.attention)
            classes.push('tetherbot-attention');
        this._icon.icon_name = view.iconName;
        this._icon.style_class = classes.join(' ');
        this._badge.text = view.badge > 0 ? String(view.badge) : '';
        this._badge.visible = view.badge > 0;
        this._indicator.accessible_name = view.accessibleName;

        const model = menuModel({
            running: this._running,
            state: this._state,
            reason: this._reason,
            bots: this._bots,
            items: mergeTodoSearch(this._items, this._searched),
            queueLength: this._queueLength,
            nowMs: Date.now(),
            undoHolds: this._undoHolds,
            activationFailed: this._activationFailed,
        });
        this._banner.label.text = model.banner;
        this._banner.visible = Boolean(model.banner);
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
            return;
        }
        this._fillBots(model.bots);
        this._fillAsks(model.asks);
        this._fillTodos(model.todos, model.moreLabel);
        const reason = model.footer.reason ? `: ${model.footer.reason}` : '';
        this._footer.label.text = `${model.footer.state}${reason} · Queued ${model.footer.queueLength}`;
        this._footer.visible = true;
    }

    _fillBots(rows) {
        this._botSection.removeAll();
        this._botSection.addMenuItem(sectionTitle('Bots'));
        if (rows.length === 0) {
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
        item.connect('activate', () => this._openChat(row.bot));
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
        const meta = [row.bot, row.due].filter(Boolean).join(' · ');
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
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
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
            style_class: 'tetherbot-title',
            x_align: Clutter.ActorAlign.START,
            x_expand: true,
        });
        if (title.clutter_text)
            title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        title.connect('clicked', () => this._openWindow(row.key));
        const heading = new St.BoxLayout({x_expand: true});
        if (row.chips && row.chips.priority) {
            heading.add_child(chipLabel(row.chips.priority, row.chips.priorityTone));
        }
        heading.add_child(title);
        text.add_child(heading);
        if (row.chips)
            text.add_child(this._chipRow(row.chips));
        else {
            const meta = [row.bot, row.due].filter(Boolean).join(' · ');
            text.add_child(new St.Label({text: meta, style_class: 'tetherbot-subtle'}));
        }
        top.add_child(text);
        if (row.undo) {
            top.add_child(this._actionButton('Undo', () => this._undo(row.key), false));
        } else if (row.canSendDone) {
            top.add_child(this._actionButton('Done', () => this._markDone(row), false));
        }
        box.add_child(top);
        item.add_child(box);
        return item;
    }

    _chipRow(chips) {
        const row = new St.BoxLayout({style_class: 'tetherbot-chips'});
        if (chips.due)
            row.add_child(chipLabel(chips.due, chips.dueTone));
        for (const tag of chips.tags || [])
            row.add_child(chipLabel(tag.label, tag.tone));
        if (chips.extra > 0)
            row.add_child(chipLabel(`+${chips.extra}`, 'neutral'));
        return row;
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

    _markDone(row) {
        if (!row || !row.key)
            return;
        const until = Date.now() + UNDO_MS;
        this._undoHolds = (this._undoHolds || []).filter(hold => hold.key !== row.key);
        this._undoHolds.push({key: row.key, row, until});
        const source = GLib.timeout_add(GLib.PRIORITY_DEFAULT, UNDO_MS, () => {
            const now = Date.now();
            this._undoHolds = (this._undoHolds || []).filter(hold => hold.until > now);
            if (this._enabled)
                this._render();
            return GLib.SOURCE_REMOVE;
        });
        this._undoSources.push(source);
        this._perform('done', row.key);
        this._render();
    }

    _undo(key) {
        this._undoHolds = (this._undoHolds || []).filter(hold => hold.key !== key);
        if (this._proxy && key) {
            const call = undoCall(key);
            this._proxy.UndoRemote(...call.args, () => this._refresh());
        }
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
        this._proxy.PerformActionRemote(...call.args, () => {});
    }

    _openChat(bot) {
        if (!this._proxy || !bot)
            return;
        this._proxy.OpenChatRemote(bot, () => {});
    }

    _sync() {
        if (!this._proxy)
            return;
        this._proxy.SyncNowRemote(() => this._refresh());
    }

    _showNotification(payload, reason) {
        let model;
        try {
            model = notificationModel(payload, reason);
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
        } else if (action.id === 'open_chat') {
            this._openChat(action.bot);
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
