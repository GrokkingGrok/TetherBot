// SPDX-License-Identifier: GPL-2.0-or-later
// node extension/clip_inline_checks.js

import {
    CLIP_TAG_MAX,
    ClipEditorSlot,
    TAG_LIMIT_LINE,
    TAG_NAME_LINE,
    addTagChip,
    historyTags,
    mergeKnownTags,
    normalizeTagName,
    planEditorPress,
    selectedTagCount,
    tagChips,
    tagTone,
    tagsPayload,
    toggleTagChip,
} from './clip_inline.js';

let failed = 0;

function assert(cond, message) {
    if (!cond) {
        failed += 1;
        console.error(`FAIL ${message}`);
    }
}

function same(actual, expected, message) {
    const a = JSON.stringify(actual);
    const b = JSON.stringify(expected);
    assert(a === b, `${message}: ${a} !== ${b}`);
}

// Tag names.
assert(normalizeTagName('  work   notes ') === 'work notes', 'whitespace collapses');
assert(normalizeTagName('   ') === '', 'blank is ignored');
assert(normalizeTagName('') === '', 'empty is ignored');
assert(normalizeTagName(null) === '', 'non-string is ignored');
assert(normalizeTagName('a'.repeat(40)) === 'a'.repeat(40), '40 characters is kept');
assert(normalizeTagName('a'.repeat(41)) === '', '41 characters is refused');
assert(normalizeTagName('bad\u0007bell') === '', 'control characters are refused');
assert(normalizeTagName('naïve') === 'naïve', 'non-ascii is kept');

// Chip state comes from GetTags, other clips, and the clip's own tags.
const chips = tagChips({
    known: [{tag: 'zeta', count: 2, color: 'teal'}, {tag: 'Work', count: 1, color: 'blue'}],
    clipTags: [{name: 'work', color: 'green'}, {name: 'later', color: 'pink'}],
    otherTags: [{name: 'alpha', color: 'red'}, {name: 'LATER', color: 'gray'}],
});
same(
    chips.map(chip => [chip.name, chip.selected]),
    [['work', true], ['later', true], ['alpha', false], ['zeta', false]],
    'clip tags come first and are selected, the rest are sorted and deduped'
);
assert(chips[0].color === 'green', "the clip's own color wins");
same(tagChips({}), [], 'no tags gives no chips');
same(tagChips({clipTags: 'nope', known: null}), [], 'bad input gives no chips');

// GetTags can arrive after the user changed a chip.
const toggled = toggleTagChip(chips, 'later').chips;
const merged = mergeKnownTags(toggled, [{tag: 'new-one', color: 'orange'}, {tag: 'WORK'}]);
same(
    merged.map(chip => [chip.name, chip.selected]),
    [['work', true], ['later', false], ['alpha', false], ['zeta', false], ['new-one', false]],
    'a late GetTags keeps the choices and adds new tags'
);
assert(chips[1].selected === true, 'toggling does not change the input');

// New tag… on Enter.
let added = addTagChip(chips, '  Alpha ');
assert(added.added === 'alpha', 'an existing tag is matched without case');
assert(added.chips.find(chip => chip.name === 'alpha').selected, 'the matched chip is selected');
assert(added.chips.length === chips.length, 'no duplicate chip is added');
added = addTagChip(chips, 'fresh  idea');
assert(added.added === 'fresh idea', 'a new tag is trimmed');
same(added.chips.at(-1), {name: 'fresh idea', color: '', selected: true}, 'a new tag is selected');
added = addTagChip(chips, '   ');
assert(added.added === '' && added.error === '' && added.chips.length === chips.length,
    'an empty tag is ignored');
added = addTagChip(chips, 'x'.repeat(41));
assert(added.added === '' && added.error === TAG_NAME_LINE, 'a long tag shows a line');

// The bridge keeps up to eight tags.
let full = [];
for (let index = 0; index < CLIP_TAG_MAX; index++)
    full = addTagChip(full, `t${index}`).chips;
assert(selectedTagCount(full) === CLIP_TAG_MAX, 'eight tags fit');
const over = addTagChip(full, 'ninth');
assert(over.added === '' && over.error === TAG_LIMIT_LINE, 'a ninth tag shows the limit');
full.push({name: 'spare', color: '', selected: false});
const blocked = toggleTagChip(full, 'spare');
assert(blocked.error === TAG_LIMIT_LINE && !blocked.chips.at(-1).selected, 'a ninth chip stays off');
const freed = toggleTagChip(full, 't0');
assert(freed.error === '' && selectedTagCount(freed.chips) === CLIP_TAG_MAX - 1, 'a chip turns off');

// The SetClipboardTags payload.
same(
    JSON.parse(tagsPayload(toggleTagChip(chips, 'zeta').chips)),
    [{name: 'work', color: 'green'}, {name: 'later', color: 'pink'}, {name: 'zeta', color: 'teal'}],
    'the payload lists the selected chips in order'
);
same(JSON.parse(tagsPayload(addTagChip([], 'brand new').chips)), [{name: 'brand new'}],
    'a new tag leaves the color to the bridge');
assert(tagsPayload([]) === '[]', 'no chips clears the tags');

same(historyTags([{tags: [{name: 'a'}]}, {}, null, {tags: [{name: 'b'}]}]),
    [{name: 'a'}, {name: 'b'}], 'history tags come from every clip');
assert(tagTone('teal') === 'teal' && tagTone('chartreuse') === 'gray' && tagTone() === 'gray',
    'unknown colors are gray');

// One editor at a time.
assert(planEditorPress(null, 'tag', 'c-1') === 'open', 'first press opens');
assert(planEditorPress({kind: 'tag', id: 'c-1'}, 'tag', 'c-1') === 'keep', 'same press keeps');
assert(planEditorPress({kind: 'tag', id: 'c-1'}, 'edit', 'c-1') === 'replace', 'other kind replaces');
assert(planEditorPress({kind: 'tag', id: 'c-1'}, 'tag', 'c-2') === 'replace', 'other clip replaces');

function fakeMenu() {
    const log = {mounted: [], unmounted: [], rebuilds: 0, focus: 0, live: new Set()};
    const slot = new ClipEditorSlot({
        mount: (kind, entry, token) => {
            const handle = {
                kind, id: entry.id, token, focus: () => {
                    log.focus += 1;
                },
            };
            log.mounted.push(handle);
            log.live.add(handle);
            return handle;
        },
        unmount: handle => {
            log.unmounted.push(handle);
            log.live.delete(handle);
        },
        rebuild: () => {
            log.rebuilds += 1;
        },
    });
    return {slot, log};
}

{
    const {slot, log} = fakeMenu();
    const results = [];
    for (let press = 0; press < 5; press++)
        results.push(slot.press('tag', {id: 'c-1'}));
    same(results, ['open', 'keep', 'keep', 'keep', 'keep'], 'five fast Tag presses');
    assert(log.live.size === 1 && log.mounted.length === 1, 'five Tag presses leave one editor');
    assert(log.focus === 4, 'a repeated press refocuses the editor');
}

{
    const {slot, log} = fakeMenu();
    slot.press('tag', {id: 'c-1'});
    const first = slot.current.token;
    slot.press('tag', {id: 'c-2'});
    assert(log.live.size === 1 && slot.current.id === 'c-2', 'another clip replaces the editor');
    assert(!slot.isCurrent(first), 'the old token is stale');
    assert(slot.close(first) === false && slot.isOpen, 'a stale reply does not close the new editor');
    assert(slot.close() === true && !slot.isOpen && log.live.size === 0, 'close removes the editor');
    assert(slot.close() === false, 'closing twice is harmless');
}

{
    const {slot, log} = fakeMenu();
    assert(slot.requestRebuild() === 'now' && log.rebuilds === 1, 'no editor rebuilds now');
    slot.press('tag', {id: 'c-1'});
    assert(slot.requestRebuild() === 'deferred' && slot.requestRebuild() === 'deferred',
        'a copy during an edit waits');
    assert(log.rebuilds === 1 && log.live.size === 1, 'the editor survives a copy');
    slot.close();
    assert(log.rebuilds === 2, 'one rebuild runs after the editor closes');
    slot.press('tag', {id: 'c-1'});
    slot.close();
    assert(log.rebuilds === 2, 'no rebuild without a pending copy');
}

{
    const {slot, log} = fakeMenu();
    slot.press('tag', {id: 'c-1'});
    slot.requestRebuild();
    slot.dispose();
    assert(!slot.isOpen && log.live.size === 0 && log.rebuilds === 0, 'dispose drops the editor');
    assert(slot.press('tag', {}) === 'ignored' && !slot.isOpen, 'a clip without an id is ignored');
}

{
    const slot = new ClipEditorSlot({mount: () => null, unmount: () => {}, rebuild: () => {}});
    assert(slot.press('tag', {id: 'c-gone'}) === 'failed' && !slot.isOpen, 'a missing row opens nothing');
}

if (failed) {
    console.error(`${failed} failed`);
    process.exit(1);
}
console.log('clip inline checks passed');
