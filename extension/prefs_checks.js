// SPDX-License-Identifier: GPL-2.0-or-later
//
// Run with `node extension/prefs_checks.js`.

import {readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

import {
    POLL_DEFAULT,
    POLL_MAX,
    POLL_MIN,
    UNDO_DEFAULT,
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

function assert(condition, message) {
    if (!condition)
        throw new Error(message);
}

assert(POLL_DEFAULT === 120 && POLL_MIN === 60 && POLL_MAX === 900, 'poll bounds');
assert(UNDO_DEFAULT === 5 && UNDO_MIN === 2 && UNDO_MAX === 30, 'undo bounds');
assert(keyButtonLabel(false) === 'Set up keys…', 'empty slot label');
assert(keyButtonLabel(true) === 'Replace keys…', 'stored slot label');
assert(idList(['notes'], 'notes', true).join(',') === '', 'showing a bot removes it');
assert(idList(['notes'], 'other', false).join(',') === 'notes,other', 'hiding adds a bot');

const parsed = setupSlots({
    slots: [
        {
            slot: 'primary-actions',
            kind: 'webhook',
            stored: true,
            bots: ['primary'],
            url: 'https://hooks.example/do-not-copy',
            key: 'do-not-copy',
        },
        {slot: 'github-token', kind: 'github-token', stored: false},
    ],
});
assert(parsed.length === 2, 'two slots');
assert(parsed[0].stored === true, 'stored flag');
assert(!Object.hasOwn(parsed[0], 'url'), 'url is not copied');
assert(!Object.hasOwn(parsed[0], 'key'), 'key is not copied');
assert(JSON.stringify(parsed).includes('do-not-copy') === false, 'secret text is dropped');

const bots = botChoices(
    [{name: 'primary', display_name: 'Primary'}],
    ['notes'],
    [],
);
assert(bots.map(bot => bot.name).join(',') === 'primary,notes', 'hidden bot stays listed');
assert(bots[0].displayName === 'Primary', 'display name is the label');

assert(effectivePollSeconds(null, null) === 120, 'poll default');
assert(effectivePollSeconds(0, null) === 120, 'poll zero is not a value');
assert(effectivePollSeconds(0, 180) === 180, 'a stored zero uses config');
assert(effectivePollSeconds(null, 180) === 180, 'config poll is shown');
assert(effectivePollSeconds(200, 180) === 200, 'a saved poll wins');
assert(effectivePollSeconds(10, 180) === 60, 'poll clamps up');
assert(effectivePollSeconds(null, 5000) === 900, 'config poll clamps down');
assert(effectiveUndoSeconds(0) === 5, 'undo zero is the default');
assert(effectiveUndoSeconds(null) === 5, 'undo default');
assert(effectiveUndoSeconds(1) === 2, 'undo clamps up');
assert(effectiveUndoSeconds(12) === 12, 'a saved undo is shown');
assert(effectiveUndoSeconds(90) === 30, 'undo clamps down');

let open = rememberExpansion([], 'primary', true);
assert(open.join(',') === 'primary', 'the user can expand a bot');
open = rememberExpansion(open, 'primary', null);
assert(open.join(',') === 'primary', 'focus does not collapse a bot');
open = rememberExpansion(open, 'notes', null);
assert(open.join(',') === 'primary', 'another row does not collapse a bot');
open = rememberExpansion(open, 'primary', false);
assert(open.join(',') === '', 'the user can collapse a bot');
const listed = [{name: 'primary'}, {name: 'notes'}];
assert(sameBotList(listed, [{name: 'primary'}, {name: 'notes'}]), 'the same bots are not rebuilt');
assert(!sameBotList(listed, [{name: 'primary'}]), 'a changed bot list is rebuilt');

const prefsSource = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), 'prefs.js'),
    'utf8',
);
assert(prefsSource.includes('set_default_size(720, 820)'), 'prefs opens at 720 by 820');
assert(prefsSource.includes('sameBotList'), 'prefs keeps an unchanged bot list');
assert(prefsSource.includes('rememberExpansion'), 'prefs remembers which bot is expanded');
assert(prefsSource.includes('effectivePollSeconds'), 'prefs shows the effective poll');
assert(prefsSource.includes('effectiveUndoSeconds'), 'prefs shows the effective undo');

console.log('prefs checks ok');
