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
    FEED_RESET_KEYS,
    HISTORY_UNITS,
    botChoices,
    effectivePollSeconds,
    effectiveUndoSeconds,
    historySeconds,
    resetFeedSettings,
    SEARCH_FALLBACK_DEFAULT,
    searchFallback,
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
assert(historySeconds(true, 1, 'years') === 365 * 86400, 'one year is 365 days');
assert(historySeconds(false, 1, 'years') === null, 'history off keeps nothing');
assert(historySeconds(true, 2, 'hours') === 7200, 'two hours');
assert(historySeconds(true, 2, 'months') === 60 * 86400, 'a month is 30 days');
assert(historySeconds(true, 0, 'days') === 86400, 'a zero amount is one');
assert(historySeconds(true, 1, 'nope') === 365 * 86400, 'an unknown unit is years');
assert(HISTORY_UNITS.join(',') === 'hours,days,weeks,months,years', 'history units');
assert(!FEED_RESET_KEYS.includes('history-enabled'), 'reset does not clear history');
assert(!FEED_RESET_KEYS.includes('history-amount'), 'reset does not clear the amount');
assert(!FEED_RESET_KEYS.includes('history-unit'), 'reset does not clear the unit');
assert(!FEED_RESET_KEYS.includes('clipboard-enabled'), 'reset does not clear clipboard');
assert(!FEED_RESET_KEYS.includes('clipboard-limit'), 'reset does not clear the clipboard cap');
assert(!FEED_RESET_KEYS.includes('clipboard-excluded-apps'), 'reset does not clear skipped apps');
assert(!FEED_RESET_KEYS.includes('clipboard-lookalike'), 'reset does not clear password-like copies');
assert(!FEED_RESET_KEYS.includes('clipboard-search-fallback'), 'reset does not clear the search fallback');
assert(searchFallback(SEARCH_FALLBACK_DEFAULT) === SEARCH_FALLBACK_DEFAULT, 'the search fallback default is https');
assert(searchFallback('http://example.test/?q={searchTerms}') === null, 'the search fallback rejects http');
assert(searchFallback('https://example.test/search') === null, 'the search fallback needs a placeholder');

const kept = {
    hidden: ['notes'],
    muted: ['primary'],
    token: 'stored',
    cleared: [],
    reset(key) {
        this.cleared.push(key);
    },
};
const reset = resetFeedSettings(kept, 180);
assert(reset.touched.join(',') === 'poll-seconds,undo-seconds', 'reset touches the two feed keys');
assert(kept.cleared.join(',') === 'poll-seconds,undo-seconds', 'reset clears only those keys');
assert(kept.hidden.join(',') === 'notes', 'hidden bots stay');
assert(kept.muted.join(',') === 'primary', 'notification settings stay');
assert(kept.token === 'stored', 'a stored token stays');
assert(reset.poll === 180 && reset.undo === 5, 'reset shows config poll and the undo default');
const plain = resetFeedSettings(kept, null);
assert(plain.poll === 120 && plain.undo === 5, 'reset without config uses 120 and 5');

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
assert(prefsSource.includes('set_default_size(756, 820)'), 'prefs opens at 756 by 820');
assert(prefsSource.includes('Reset to defaults'), 'prefs has a reset button');
assert(prefsSource.includes('resetFeedSettings'), 'prefs resets through the feed helper');
assert(prefsSource.includes('sameBotList'), 'prefs keeps an unchanged bot list');
assert(prefsSource.includes('rememberExpansion'), 'prefs remembers which bot is expanded');
assert(prefsSource.includes('effectivePollSeconds'), 'prefs shows the effective poll');
assert(prefsSource.includes('effectiveUndoSeconds'), 'prefs shows the effective undo');
assert(prefsSource.includes('Keep completed todos'), 'prefs has the history toggle');
assert(prefsSource.includes('history-unit'), 'prefs stores the history unit');
assert(prefsSource.includes('Completed todos'), 'prefs has a completed-todo group');
assert(prefsSource.includes('Remember copied text'), 'prefs has the clipboard toggle');
assert(prefsSource.includes('clipboard-excluded-apps'), 'prefs stores skipped apps');
assert(prefsSource.includes('Password-like copies'), 'prefs has the password-like choice');
assert(prefsSource.includes('clipboard-lookalike'), 'prefs stores the password-like choice');
assert(prefsSource.includes('Search fallback'), 'prefs shows the search fallback');
assert(prefsSource.includes('clipboard-search-fallback'), 'prefs stores the search fallback');
assert(
    prefsSource.includes('1 month = 30 days, 1 year = 365 days'),
    'how many names a month and a year',
);
assert(
    !prefsSource.includes('A month is 30 days and a year is 365 days.'),
    'the completed-todo description does not repeat the units',
);

console.log('prefs checks ok');
