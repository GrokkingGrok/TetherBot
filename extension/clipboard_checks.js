// SPDX-License-Identifier: GPL-2.0-or-later
// node extension/clipboard_checks.js

import {
    CLIPBOARD_MASK_LABEL,
    DEFAULT_EXCLUDED_APPS,
    classifyClipboard,
    clipboardLimit,
    imageLabel,
    imageWithinCap,
    looksLikePassword,
    menuLabel,
    pickImageMime,
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
    'an image is not stored as text',
);
assert(pickImageMime(['image/png']) === 'image/png', 'a png offer is an image');
assert(pickImageMime(['image/jpeg', 'image/png']) === 'image/png', 'png wins over jpeg');
assert(pickImageMime(['text/html', 'image/jpeg']) === 'image/jpeg', 'html does not beat an image');
assert(pickImageMime(['text/plain', 'image/png']) === null, 'plain text wins over an image');
assert(pickImageMime(['UTF8_STRING', 'image/webp']) === null, 'UTF8_STRING wins over an image');
assert(pickImageMime(['image/jpg']) === 'image/jpeg', 'jpg is jpeg');
assert(imageWithinCap(1) === true, 'a small image is within the cap');
assert(imageWithinCap(10 * 1024 * 1024) === true, '10 MiB is within the cap');
assert(imageWithinCap((10 * 1024 * 1024) + 1) === false, 'over 10 MiB is rejected');
assert(imageWithinCap(0) === false, 'an empty image is rejected');
assert(imageLabel('image/png', 1258291) === 'Image · PNG · 1.2 MB', 'the image label names the type and size');
assert(classifyClipboard({...plain, text: '   '}) === 'skipped-empty', 'blank text is skipped');
assert(clipboardLimit(0) === 50, 'a missing cap is 50');
assert(clipboardLimit(900) === 500, 'the cap stops at 500');
assert(menuLabel('one\ntwo').includes(' '), 'a menu label is one line');
assert(!menuLabel('one\ntwo').includes('\n'), 'a menu label has no newline');
assert(menuLabel('aB3!xxxx', true) === CLIPBOARD_MASK_LABEL, 'a hidden row does not show the text');
assert(!menuLabel('aB3!xxxx', true).includes('aB3'), 'the mask hides the lookalike');

const chrome = [
    'text/plain',
    'text/plain;charset=utf-8',
    'UTF8_STRING',
    'STRING',
    'TEXT',
    'chromium/x-source-url',
];
assert(looksLikePassword('aB3!xxxx'), 'a mixed token looks like a password');
assert(looksLikePassword('C0rrect-Horse'), 'a mixed token with a hyphen looks like a password');
assert(looksLikePassword('Password1'), 'letters and a digit look like a password');
assert(!looksLikePassword('hello world'), 'a sentence is kept');
assert(!looksLikePassword('https://example.com/notes'), 'a URL is kept');
assert(!looksLikePassword('/home/user/notes'), 'a path is kept');
assert(!looksLikePassword('12345678'), 'digits are kept');
assert(!looksLikePassword('hello'), 'a short word is kept');
assert(!looksLikePassword('HelloWorld'), 'two letter classes are kept');
assert(!looksLikePassword('README.md'), 'a file name is kept');
assert(!looksLikePassword('User@example.com'), 'an email address is kept');
assert(!looksLikePassword('password1'), 'one letter class and a digit are kept');
assert(
    classifyClipboard({text: null, mimes: chrome, wmClass: 'google-chrome'}) === 'needs-text',
    'Chrome plain text is not a sensitive type',
);
assert(
    classifyClipboard({
        text: null,
        mimes: [...chrome, 'application/x-chromium-password-sensitive'],
        wmClass: 'google-chrome',
    }) === 'skipped-sensitive',
    'a chromium sensitive type is skipped before the text is read',
);
assert(
    classifyClipboard({text: 'aB3!xxxx', mimes: chrome, wmClass: 'Google-Chrome'}) === 'skipped-lookalike',
    'a Chrome password copy is a lookalike',
);
assert(
    classifyClipboard({
        text: 'aB3!xxxx',
        mimes: chrome,
        wmClass: 'google-chrome',
        lookalike: 'mask',
    }) === 'stored-masked',
    'mask mode keeps a lookalike hidden',
);
assert(
    classifyClipboard({text: 'hello world', mimes: chrome, wmClass: 'chromium'}) === 'stored',
    'ordinary Chrome text is stored',
);

if (failed) {
    console.error(`${failed} failed`);
    process.exit(1);
}
console.log('clipboard checks passed');
