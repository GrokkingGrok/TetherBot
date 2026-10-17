// SPDX-License-Identifier: GPL-2.0-or-later
//
// UI preferences only. A "Set up keys..." button, when it exists, calls
// the bridge method RequestSecretEntry. This process never sees the secret.

import Adw from 'gi://Adw';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class TetherBotPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const page = new Adw.PreferencesPage({
            title: 'TetherBot',
            icon_name: 'dialog-information-symbolic',
        });
        const group = new Adw.PreferencesGroup({
            title: 'Bridge',
            description: 'Preferences are not implemented yet.',
        });
        page.add(group);
        window.add(page);
    }
}
