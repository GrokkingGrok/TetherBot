// SPDX-License-Identifier: GPL-2.0-or-later
//
// UI preferences only. "Set up keys…" calls RequestSecretEntry on the
// bridge. This process never receives a secret and never displays one.

import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import {
    POLL_MAX,
    POLL_MIN,
    UNDO_MAX,
    UNDO_MIN,
    botChoices,
    effectivePollSeconds,
    effectiveUndoSeconds,
    idList,
    keyButtonLabel,
    rememberExpansion,
    sameBotList,
    setupSlots,
} from './prefs_model.js';
import {BUS_NAME, OBJECT_PATH, startServiceCall} from './view.js';

export default class TetherBotPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        this._sizeWindow(window);
        this._installSpinCss();
        this._expandedBots = [];
        this._botChoices = [];
        this._spinEdited = new Set();
        this._spins = new Map();
        this._configPoll = null;
        this._showingSpin = false;
        this._userExpand = false;
        this._applyingExpand = false;
        this._applyingBots = false;
        let settings = null;
        try {
            settings = this.getSettings();
        } catch (error) {
            settings = null;
        }
        const page = new Adw.PreferencesPage({
            title: 'TetherBot',
            icon_name: 'dialog-information-symbolic',
        });
        window.add(page);
        if (!settings) {
            page.add(new Adw.PreferencesGroup({
                title: 'Settings',
                description: 'The settings schema is not compiled yet. Install the extension, then open this window again.',
            }));
            return;
        }
        this._settings = settings;
        this._window = window;
        this._buildFeed(page, settings);
        this._keys = new Adw.PreferencesGroup({
            title: 'Keys',
            description: 'Keys stay in the desktop secret service. A stored key is never shown here.',
        });
        this._keyRows = [];
        page.add(this._keys);
        this._bots = new Adw.PreferencesGroup({
            title: 'Bots',
            description: 'Hidden bots stay out of the popup and the window. Notifications are per bot.',
        });
        this._botRows = [];
        page.add(this._bots);
        this._bridge = null;
        window.connect('notify::is-active', () => {
            if (window.is_active)
                this._loadSetup();
        });
        this._startBridge();
    }

    _buildFeed(page, settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Feed',
            description: 'The poll interval is how often the desktop checks the feed. Undo applies to the popup and the window.',
        });
        group.add(this._spin(
            settings,
            'poll-seconds',
            'Check the feed',
            'Seconds between checks. 60 to 900. The default is 120.',
            POLL_MIN,
            POLL_MAX,
            10,
        ));
        group.add(this._spin(
            settings,
            'undo-seconds',
            'Undo timer',
            'Seconds before Done is sent. 2 to 30. The default is 5.',
            UNDO_MIN,
            UNDO_MAX,
            1,
        ));
        page.add(group);
    }

    _sizeWindow(window) {
        if (!window)
            return;
        if (typeof window.set_default_size === 'function')
            window.set_default_size(720, 820);
        if ('default_width' in window)
            window.default_width = 720;
        if ('default_height' in window)
            window.default_height = 820;
    }

    _installSpinCss() {
        if (this._spinCss)
            return;
        let display = null;
        try {
            display = Gdk.Display.get_default();
        } catch (error) {
            display = null;
        }
        if (!display)
            return;
        const css = '.tetherbot-seconds spinbutton { min-width: 8em; }';
        const provider = new Gtk.CssProvider();
        try {
            if (typeof provider.load_from_string === 'function')
                provider.load_from_string(css);
            else
                provider.load_from_data(new TextEncoder().encode(css));
        } catch (error) {
            return;
        }
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
        this._spinCss = provider;
    }

    _spin(settings, key, title, subtitle, lower, upper, step) {
        const adjustment = new Gtk.Adjustment({
            lower,
            upper,
            step_increment: step,
            page_increment: step * 6,
        });
        adjustment.lower = lower;
        adjustment.upper = upper;
        adjustment.step_increment = step;
        const shown = this._secondsFor(key);
        adjustment.value = shown;
        const row = new Adw.SpinRow({
            title,
            subtitle,
            adjustment,
            css_classes: ['tetherbot-seconds'],
        });
        if (typeof row.set_digits === 'function')
            row.set_digits(0);
        this._widenSpin(row);
        this._showSpin(row, shown);
        this._spins.set(key, row);
        row.adjustment.connect('value-changed', () => {
            if (this._showingSpin)
                return;
            const value = Math.round(row.adjustment.value);
            if (value <= 0)
                return;
            this._spinEdited.add(key);
            if (settings.get_int(key) !== value)
                settings.set_int(key, value);
            this._reloadBridge();
        });
        return row;
    }

    _secondsFor(key) {
        const stored = this._userSeconds(key);
        if (key === 'poll-seconds')
            return effectivePollSeconds(stored, this._configPoll);
        return effectiveUndoSeconds(stored);
    }

    _userSeconds(key) {
        const settings = this._settings;
        if (!settings || typeof settings.get_user_value !== 'function')
            return null;
        let variant = null;
        try {
            variant = settings.get_user_value(key);
        } catch (error) {
            variant = null;
        }
        if (!variant)
            return null;
        let value = null;
        try {
            value = typeof variant.unpack === 'function' ? variant.unpack() : null;
        } catch (error) {
            value = null;
        }
        if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0)
            return null;
        return value;
    }

    _showSpin(row, value) {
        this._showingSpin = true;
        try {
            if (typeof row.set_value === 'function')
                row.set_value(value);
            else if (row.adjustment)
                row.adjustment.value = value;
        } finally {
            this._showingSpin = false;
        }
    }

    _widenSpin(row) {
        const visit = widget => {
            if (!widget)
                return;
            if (widget instanceof Gtk.SpinButton && typeof widget.set_width_chars === 'function')
                widget.set_width_chars(4);
            let child = typeof widget.get_first_child === 'function' ? widget.get_first_child() : null;
            while (child) {
                visit(child);
                child = typeof child.get_next_sibling === 'function' ? child.get_next_sibling() : null;
            }
        };
        visit(row);
    }

    _startBridge() {
        const call = startServiceCall();
        let session = null;
        try {
            session = Gio.DBus.session;
        } catch (error) {
            session = null;
        }
        if (!session) {
            this._showKeysMessage('The session bus is not available.');
            return;
        }
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
            () => this._openProxy(),
        );
    }

    _openProxy() {
        let xml = '';
        try {
            const file = this.dir.get_child('io.github.grokkinggrok.TetherBot1.xml');
            const [, bytes] = file.load_contents(null);
            xml = new TextDecoder().decode(bytes);
        } catch (error) {
            this._showKeysMessage('The bridge interface did not load.');
            return;
        }
        const Wrapper = Gio.DBusProxy.makeProxyWrapper(xml);
        new Wrapper(
            Gio.DBus.session,
            BUS_NAME,
            OBJECT_PATH,
            (proxy, error) => {
                if (error || !proxy) {
                    this._showKeysMessage('The bridge is not running. Start it, then open Settings again.');
                    return;
                }
                this._bridge = proxy;
                this._loadSetup();
            },
            null,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START,
        );
    }

    _loadSetup() {
        if (!this._bridge || !this._bridge.GetSetupRemote)
            return;
        this._bridge.GetSetupRemote((result, error) => {
            if (error || !result)
                return;
            let payload = null;
            try {
                payload = JSON.parse(result[0]);
            } catch (parseError) {
                return;
            }
            this._fillKeys(setupSlots(payload));
            const configPoll = payload && typeof payload.poll_seconds === 'number'
                ? payload.poll_seconds
                : null;
            if (configPoll !== this._configPoll) {
                this._configPoll = configPoll;
                const poll = this._spins.get('poll-seconds');
                if (poll && !this._spinEdited.has('poll-seconds'))
                    this._showSpin(poll, this._secondsFor('poll-seconds'));
            }
            this._applyBots(botChoices(
                payload && Array.isArray(payload.bots) ? payload.bots : [],
                this._settings.get_strv('hidden-bots'),
                this._settings.get_strv('muted-bots'),
            ));
        });
    }

    _fillKeys(slots) {
        this._clear(this._keys, this._keyRows);
        if (!slots.length) {
            const empty = new Adw.ActionRow({
                title: 'No webhook slots yet',
                subtitle: 'A slot appears here after a bot names one in the bridge config.',
            });
            this._keys.add(empty);
            this._keyRows.push(empty);
        }
        for (const slot of slots) {
            const title = slot.kind === 'github-token' ? 'GitHub token' : slot.slot;
            const who = slot.bots.length ? `Used by ${slot.bots.join(', ')}. ` : '';
            const row = new Adw.ActionRow({
                title,
                subtitle: `${who}A stored key is not shown.`,
            });
            const button = new Gtk.Button({
                label: keyButtonLabel(slot.stored),
                valign: Gtk.Align.CENTER,
            });
            button.connect('clicked', () => this._requestKeys(slot.slot));
            row.add_suffix(button);
            row.activatable_widget = button;
            this._keys.add(row);
            this._keyRows.push(row);
        }
    }

    _showKeysMessage(text) {
        this._clear(this._keys, this._keyRows);
        const row = new Adw.ActionRow({title: text});
        this._keys.add(row);
        this._keyRows.push(row);
        this._botChoices = [];
        this._clear(this._bots, this._botRows);
        const bots = new Adw.ActionRow({
            title: 'Bot list needs the bridge',
            subtitle: 'Show, hide, and notifications apply once the bridge is running.',
        });
        this._bots.add(bots);
        this._botRows.push(bots);
    }

    _applyBots(bots) {
        if (sameBotList(this._botChoices, bots) && this._botRows.some(row => row._botName)) {
            this._retitleBots(bots);
            return;
        }
        this._fillBots(bots);
    }

    _retitleBots(bots) {
        const titles = new Map(bots.map(bot => [bot.name, bot.displayName]));
        for (const row of this._botRows) {
            const title = titles.get(row._botName);
            if (title && row.title !== title)
                row.title = title;
        }
    }

    _fillBots(bots) {
        this._applyingBots = true;
        this._botChoices = bots.map(bot => ({name: bot.name, displayName: bot.displayName}));
        this._clear(this._bots, this._botRows);
        if (!bots.length) {
            const empty = new Adw.ActionRow({
                title: 'No bots yet',
                subtitle: 'A bot appears here after its feed is read.',
            });
            this._bots.add(empty);
            this._botRows.push(empty);
            this._applyingBots = false;
            return;
        }
        const hidden = new Set(this._settings.get_strv('hidden-bots'));
        const muted = new Set(this._settings.get_strv('muted-bots'));
        const expanded = new Set(this._expandedBots);
        for (const bot of bots) {
            const block = new Adw.ExpanderRow({
                title: bot.displayName,
                expanded: expanded.has(bot.name),
            });
            block._botName = bot.name;
            if ('selectable' in block)
                block.selectable = false;
            this._keepExpanded(block, bot.name);
            const show = new Adw.SwitchRow({
                title: 'Show in the popup and the window',
                active: !hidden.has(bot.name),
            });
            show.connect('notify::active', () => {
                if (this._applyingBots)
                    return;
                this._settings.set_strv('hidden-bots', idList(
                    this._settings.get_strv('hidden-bots'),
                    bot.name,
                    show.active,
                ));
                this._reloadBridge();
            });
            const notify = new Adw.SwitchRow({
                title: 'Notifications',
                active: !muted.has(bot.name),
            });
            notify.connect('notify::active', () => {
                if (this._applyingBots)
                    return;
                this._settings.set_strv('muted-bots', idList(
                    this._settings.get_strv('muted-bots'),
                    bot.name,
                    notify.active,
                ));
                this._reloadBridge();
            });
            block.add_row(show);
            block.add_row(notify);
            this._bots.add(block);
            this._botRows.push(block);
        }
        this._applyingBots = false;
    }

    _keepExpanded(row, name) {
        const note = () => {
            this._userExpand = true;
            this._expandedBots = rememberExpansion(this._expandedBots, name, Boolean(row.expanded));
            this._userExpand = false;
        };
        const header = this._expanderHeader(row);
        const markUser = () => {
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                note();
                return GLib.SOURCE_REMOVE;
            });
        };
        if (header) {
            try {
                header.connect('activated', markUser);
            } catch (error) {
                row.connect('activate', markUser);
            }
        } else {
            row.connect('activate', markUser);
        }
        row.connect('notify::expanded', () => {
            if (this._userExpand || this._applyingExpand)
                return;
            const want = (this._expandedBots || []).includes(name);
            if (row.expanded === want)
                return;
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (this._userExpand)
                    return GLib.SOURCE_REMOVE;
                const still = (this._expandedBots || []).includes(name);
                if (row.expanded !== still) {
                    this._applyingExpand = true;
                    row.expanded = still;
                    this._applyingExpand = false;
                }
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _expanderHeader(row) {
        let found = null;
        const visit = widget => {
            if (!widget || found)
                return;
            const classes = typeof widget.get_css_classes === 'function'
                ? widget.get_css_classes()
                : [];
            if (widget !== row && classes.includes('header'))
                found = widget;
            let child = typeof widget.get_first_child === 'function' ? widget.get_first_child() : null;
            while (child && !found) {
                visit(child);
                child = typeof child.get_next_sibling === 'function' ? child.get_next_sibling() : null;
            }
        };
        visit(row);
        return found;
    }

    _requestKeys(slot) {
        if (!this._bridge || !this._bridge.RequestSecretEntryRemote)
            return;
        this._bridge.RequestSecretEntryRemote(slot, () => {});
    }

    _reloadBridge() {
        if (!this._bridge || !this._bridge.ReloadSettingsRemote)
            return;
        this._bridge.ReloadSettingsRemote(() => {});
    }

    _clear(group, rows) {
        for (const row of rows)
            group.remove(row);
        rows.length = 0;
    }
}
