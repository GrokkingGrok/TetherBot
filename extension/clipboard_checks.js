// SPDX-License-Identifier: GPL-2.0-or-later
// node extension/clipboard_checks.js

import {
    DEFAULT_EXCLUDED_APPS,
    classifyClipboard,
    clipboardLimit,
    menuLabel,
} from './clipboard.js';

let failed = 0;

function assert(cond, message) {
    if (!cond) {
        failed += 1;
        console.error(`FAIL ${message}`);
    }
}

const plain = {mimes: ['text/plain'], wmClass: 'gedit', enabled: true, excluded: DEFAULT_EXCLUDED_APPS};

assert(classifyClipboard({...plain, text: null}) === 'needs-text', 'plain text is read');
assert(classifyClipboard({...plain, text: 'hello'}) === 'stored', 'plain text is stored');
assert(
    classifyClipboard({
        text: null,
        mimes: ['text/plain', 'x-kde-passwordManagerHint'],
        wmClass: 'org.keepassxc.KeePassXC',
        enabled: true,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-sensitive',
    'a password-manager hint is skipped before the text is read',
);
assert(
    classifyClipboard({
        text: 'secret-value',
        mimes: ['text/plain', 'application/x-nspasteboard-concealed-type'],
        wmClass: 'gedit',
        enabled: true,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-sensitive',
    'a concealed type is skipped',
);
assert(
    classifyClipboard({
        text: null,
        mimes: ['text/plain'],
        wmClass: 'org.keepassxc.KeePassXC',
        enabled: true,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-app',
    'KeePassXC is excluded before the text is read',
);
assert(
    classifyClipboard({
        text: 'hello',
        mimes: ['text/plain'],
        wmClass: '1Password',
        enabled: true,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-app',
    'an excluded class matches ignoring case',
);
assert(
    classifyClipboard({
        text: 'hello',
        mimes: ['text/plain'],
        wmClass: 'gedit',
        enabled: false,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-disabled',
    'the toggle skips a new copy',
);
assert(
    classifyClipboard({
        text: 'hello',
        mimes: ['image/png'],
        wmClass: 'gedit',
        enabled: true,
        excluded: DEFAULT_EXCLUDED_APPS,
    }) === 'skipped-binary',
    'an image is not stored in phase 1',
);
assert(classifyClipboard({...plain, text: '   '}) === 'skipped-empty', 'blank text is skipped');
assert(clipboardLimit(0) === 50, 'a missing cap is 50');
assert(clipboardLimit(900) === 500, 'the cap stops at 500');
assert(menuLabel('one\ntwo').includes(' '), 'a menu label is one line');
assert(!menuLabel('one\ntwo').includes('\n'), 'a menu label has no newline');

if (failed) {
    console.error(`${failed} failed`);
    process.exit(1);
}
console.log('clipboard checks passed');
