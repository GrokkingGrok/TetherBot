// SPDX-License-Identifier: GPL-2.0-or-later
//
// UI preferences only. "Set up keys…" calls RequestSecretEntry on the
// bridge. This process never receives a secret and never displays one.

import Adw from 'gi://Adw';
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
    idList,
    keyButtonLabel,
    setupSlots,
} from './prefs_model.js';
import {BUS_NAME, OBJECT_PATH, startServiceCall} from './view.js';

export default class TetherBotPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
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

    _spin(settings, key, title, subtitle, lower, upper, step) {
        const row = new Adw.SpinRow({
            title,
            subtitle,
            adjustment: new Gtk.Adjustment({
                value: settings.get_int(key),
                lower,
                upper,
                step_increment: step,
            }),
        });
        if (typeof row.set_digits === 'function')
            row.set_digits(0);
        row.adjustment.connect('value-changed', () => {
            const value = Math.round(row.adjustment.value);
            if (settings.get_int(key) !== value)
                settings.set_int(key, value);
            this._reloadBridge();
        });
        return row;
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
            this._fillBots(botChoices(
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
        this._clear(this._bots, this._botRows);
        const bots = new Adw.ActionRow({
            title: 'Bot list needs the bridge',
            subtitle: 'Show, hide, and notifications apply once the bridge is running.',
        });
        this._bots.add(bots);
        this._botRows.push(bots);
    }

    _fillBots(bots) {
        this._clear(this._bots, this._botRows);
        if (!bots.length) {
            const empty = new Adw.ActionRow({
                title: 'No bots yet',
                subtitle: 'A bot appears here after its feed is read.',
            });
            this._bots.add(empty);
            this._botRows.push(empty);
            return;
        }
        const hidden = new Set(this._settings.get_strv('hidden-bots'));
        const muted = new Set(this._settings.get_strv('muted-bots'));
        for (const bot of bots) {
            const block = new Adw.ExpanderRow({title: bot.displayName});
            const show = new Adw.SwitchRow({
                title: 'Show in the popup and the window',
                active: !hidden.has(bot.name),
            });
            show.connect('notify::active', () => {
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
