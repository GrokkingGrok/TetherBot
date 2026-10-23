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
    HISTORY_UNIT_LABELS,
    HISTORY_UNITS,
    effectivePollSeconds,
    effectiveUndoSeconds,
    historyAmount,
    historyUnit,
    resetFeedSettings,
    idList,
    keyButtonLabel,
    rememberExpansion,
    sameBotList,
    setupSlots,
} from './prefs_model.js';
import {clipboardLimit, excludedApps} from './clipboard.js';
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
        this._applyingHistory = false;
        this._applyingClipboard = false;
        this._showingClipboard = false;
        this._buildFeed(page, settings);
        this._buildHistory(page, settings);
        this._buildClipboard(page, settings);
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
        const reset = new Adw.ActionRow({
            title: 'Feed check and undo timer',
            subtitle: 'Reset puts those two back to the defaults. Completed-todo history, clipboard history, keys, and bots stay as they are.',
        });
        const button = new Gtk.Button({
            label: 'Reset to defaults',
            valign: Gtk.Align.CENTER,
        });
        button.connect('clicked', () => this._resetFeed(settings));
        reset.add_suffix(button);
        reset.activatable_widget = button;
        group.add(reset);
        page.add(group);
    }

    _buildHistory(page, settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Completed todos',
            description: 'Show done lists a completed todo for this long, whether it was closed on the desktop or by the bot. Dropped items are not listed. Older ones are hidden here only. A bot feed file is not changed.',
        });
        const enabled = new Adw.SwitchRow({
            title: 'Keep completed todos',
            subtitle: 'When this is off, Show done lists no completed todos.',
        });
        const amount = this._historyAmount(settings);
        const unit = this._historyUnit(settings);
        const applyEnabled = () => {
            const on = settings.get_boolean('history-enabled');
            this._applyingHistory = true;
            enabled.active = on;
            amount.set_sensitive(on);
            unit.set_sensitive(on);
            this._applyingHistory = false;
        };
        enabled.connect('notify::active', () => {
            if (this._applyingHistory)
                return;
            if (settings.get_boolean('history-enabled') !== enabled.active)
                settings.set_boolean('history-enabled', enabled.active);
            amount.set_sensitive(enabled.active);
            unit.set_sensitive(enabled.active);
        });
        settings.connect('changed::history-enabled', applyEnabled);
        applyEnabled();
        group.add(enabled);
        group.add(amount);
        group.add(unit);
        page.add(group);
    }

    _historyAmount(settings) {
        const adjustment = new Gtk.Adjustment({
            lower: 1,
            upper: 999,
            step_increment: 1,
            page_increment: 10,
        });
        adjustment.lower = 1;
        adjustment.upper = 999;
        adjustment.step_increment = 1;
        const shown = historyAmount(settings.get_int('history-amount'));
        adjustment.value = shown;
        const row = new Adw.SpinRow({
            title: 'How many',
            subtitle: 'How long to keep a completed todo. 1 to 999. The default is 1. 1 month = 30 days, 1 year = 365 days.',
            adjustment,
            css_classes: ['tetherbot-seconds'],
        });
        if (typeof row.set_digits === 'function')
            row.set_digits(0);
        this._widenSpin(row);
        this._showSpin(row, shown);
        row.adjustment.connect('value-changed', () => {
            if (this._showingSpin)
                return;
            const value = historyAmount(row.adjustment.value);
            if (settings.get_int('history-amount') !== value)
                settings.set_int('history-amount', value);
        });
        return row;
    }

    _historyUnit(settings) {
        const model = new Gtk.StringList();
        for (const label of HISTORY_UNIT_LABELS)
            model.append(label);
        const row = new Adw.ComboRow({
            title: 'Unit',
            subtitle: 'Hours, days, weeks, months, or years.',
            model,
        });
        const apply = () => {
            const index = HISTORY_UNITS.indexOf(historyUnit(settings.get_string('history-unit')));
            this._applyingHistory = true;
            row.selected = index < 0 ? HISTORY_UNITS.indexOf('years') : index;
            this._applyingHistory = false;
        };
        row.connect('notify::selected', () => {
            if (this._applyingHistory)
                return;
            const index = row.selected;
            if (index < 0 || index >= HISTORY_UNITS.length)
                return;
            const unit = HISTORY_UNITS[index];
            if (settings.get_string('history-unit') !== unit)
                settings.set_string('history-unit', unit);
        });
        settings.connect('changed::history-unit', apply);
        apply();
        return row;
    }

    _buildClipboard(page, settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Clipboard',
            description: 'Copied text stays on this machine. It is not written to the feed and it is not sent to a bot.',
        });
        const enabled = new Adw.SwitchRow({
            title: 'Remember copied text',
            subtitle: 'When this is off, new copies are not saved. Clear history removes what is already saved.',
        });
        const applyEnabled = () => {
            this._applyingClipboard = true;
            enabled.active = settings.get_boolean('clipboard-enabled');
            this._applyingClipboard = false;
        };
        enabled.connect('notify::active', () => {
            if (this._applyingClipboard)
                return;
            if (settings.get_boolean('clipboard-enabled') !== enabled.active)
                settings.set_boolean('clipboard-enabled', enabled.active);
        });
        settings.connect('changed::clipboard-enabled', applyEnabled);
        applyEnabled();
        group.add(enabled);
        group.add(this._clipboardLimit(settings));
        group.add(this._clipboardApps(settings));
        page.add(group);
    }

    _clipboardLimit(settings) {
        const adjustment = new Gtk.Adjustment({
            lower: 1,
            upper: 500,
            step_increment: 1,
            page_increment: 10,
        });
        adjustment.lower = 1;
        adjustment.upper = 500;
        adjustment.step_increment = 1;
        const shown = clipboardLimit(settings.get_int('clipboard-limit'));
        adjustment.value = shown;
        const row = new Adw.SpinRow({
            title: 'How many entries',
            subtitle: 'Plain text only. 1 to 500. The default is 50.',
            adjustment,
            css_classes: ['tetherbot-seconds'],
        });
        if (typeof row.set_digits === 'function')
            row.set_digits(0);
        this._widenSpin(row);
        this._showSpin(row, shown);
        row.adjustment.connect('value-changed', () => {
            if (this._showingSpin)
                return;
            const value = clipboardLimit(row.adjustment.value);
            if (settings.get_int('clipboard-limit') !== value)
                settings.set_int('clipboard-limit', value);
        });
        settings.connect('changed::clipboard-limit', () => {
            const value = clipboardLimit(settings.get_int('clipboard-limit'));
            this._showSpin(row, value);
        });
        return row;
    }

    _clipboardApps(settings) {
        const row = new Adw.EntryRow({
            title: 'Skip these apps',
        });
        const show = () => {
            const text = settings.get_strv('clipboard-excluded-apps').join(', ');
            this._showingClipboard = true;
            if (row.get_text() !== text)
                row.set_text(text);
            this._showingClipboard = false;
        };
        const save = () => {
            if (this._showingClipboard)
                return;
            const apps = excludedApps(row.get_text().split(','));
            const current = settings.get_strv('clipboard-excluded-apps');
            if (apps.join('\n') !== current.join('\n'))
                settings.set_strv('clipboard-excluded-apps', apps);
            show();
        };
        row.connect('apply', save);
        const focus = new Gtk.EventControllerFocus();
        focus.connect('leave', save);
        row.add_controller(focus);
        settings.connect('changed::clipboard-excluded-apps', show);
        show();
        return row;
    }

    _resetFeed(settings) {
        const next = resetFeedSettings(settings, this._configPoll);
        for (const key of next.touched)
            this._spinEdited.delete(key);
        const poll = this._spins.get('poll-seconds');
        const undo = this._spins.get('undo-seconds');
        if (poll)
            this._showSpin(poll, next.poll);
        if (undo)
            this._showSpin(undo, next.undo);
        this._reloadBridge();
    }

    _sizeWindow(window) {
        if (!window)
            return;
        if (typeof window.set_default_size === 'function')
            window.set_default_size(756, 820);
        if ('default_width' in window)
            window.default_width = 756;
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
