// SPDX-License-Identifier: GPL-2.0-or-later
//
// UUID placeholder: tetherbot@example.invalid
// TODO: confirm this UUID before the extension is published.
//
// GNOME Shell 50, ESM. This file may talk to the bridge only through the
// session bus. Do not import Soup, open a socket, spawn a network process,
// or store a secret here.

import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class TetherBotExtension extends Extension {
    enable() {
        // Empty top-bar indicator. Later milestones add the badge, popup,
        // and D-Bus proxy. Drop the actor in disable().
        this._indicator = new PanelMenu.Button(0.0, 'TetherBot', false);
        this._indicator.add_child(new St.Icon({
            icon_name: 'network-offline-symbolic',
            style_class: 'system-status-icon tetherbot-indicator',
        }));
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
