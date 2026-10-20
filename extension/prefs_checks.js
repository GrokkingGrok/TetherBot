// SPDX-License-Identifier: GPL-2.0-or-later
//
// Run with `node extension/prefs_checks.js`.

import {
    POLL_DEFAULT,
    POLL_MAX,
    POLL_MIN,
    UNDO_DEFAULT,
    UNDO_MAX,
    UNDO_MIN,
    botChoices,
    idList,
    keyButtonLabel,
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

console.log('prefs checks ok');
