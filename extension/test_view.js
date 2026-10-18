// SPDX-License-Identifier: GPL-2.0-or-later
//
// gjs -m extension/test_view.js
// Builds the D-Bus proxy class from the shipped XML and checks the menu mapping.
// It does not open a session bus and does not import GNOME Shell.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {BUS_NAME, OBJECT_PATH, PROXY_METHODS} from './view.js';
import {runViewChecks} from './view_checks.js';

const fileUrl = import.meta.url.startsWith('file://')
    ? decodeURIComponent(import.meta.url.slice('file://'.length))
    : import.meta.url;
const here = GLib.path_get_dirname(fileUrl);
const xmlFile = Gio.File.new_for_path(GLib.build_filenamev([
    here,
    'io.github.grokkinggrok.TetherBot1.xml',
]));
const [, bytes] = xmlFile.load_contents(null);
const xml = new TextDecoder().decode(bytes);
if (!xml.includes('interface name="io.github.grokkinggrok.TetherBot1"'))
    throw new Error('shipped XML is not the TetherBot interface');

if (typeof Gio.DBusProxy.prototype.connectSignal !== 'function')
    throw new Error('connectSignal is missing');
if (typeof Gio.DBusProxy.prototype.disconnectSignal !== 'function')
    throw new Error('disconnectSignal is missing');

const Wrapper = Gio.DBusProxy.makeProxyWrapper(xml);
const proxy = new Wrapper(
    Gio.DBus.session,
    BUS_NAME,
    OBJECT_PATH,
    null,
    null,
    Gio.DBusProxyFlags.DO_NOT_AUTO_START,
);
for (const name of PROXY_METHODS) {
    if (typeof proxy[name] !== 'function')
        throw new Error(`proxy wrapper is missing ${name}`);
}
const id = proxy.connectSignal('StateChanged', () => {});
proxy.disconnectSignal(id);

runViewChecks();
