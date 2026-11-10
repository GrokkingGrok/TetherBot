// SPDX-License-Identifier: GPL-2.0-or-later
//
// St widgets for the inline clip editors in the panel clipboard menu,
// GNOME Shell 50. The extension passes the bridge calls in as callbacks.
// Nothing here opens or messages the TetherBot window.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {
    addTagChip,
    mergeKnownTags,
    tagTone,
    toggleTagChip,
} from './clip_inline.js';

function editorButton(label, onClick) {
    const button = new St.Button({
        label,
        style_class: 'button tetherbot-clip-editor-button',
        can_focus: true,
        reactive: true,
        track_hover: true,
        x_expand: false,
    });
    button.connect('clicked', () => onClick());
    return button;
}

// One menu item that holds an editor. activate: false keeps Enter and
// clicks from activating the item, which would close the menu.
class InlineEditor {
    constructor(styleClass, heading) {
        this.item = new PopupMenu.PopupBaseMenuItem({
            reactive: true,
            activate: false,
            can_focus: false,
            hover: false,
            style_class: `tetherbot-clip-editor ${styleClass}`,
        });
        this.box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            style_class: 'tetherbot-clip-editor-box',
            x_expand: true,
        });
        this.item.add_child(this.box);
        this.box.add_child(new St.Label({
            text: heading,
            style_class: 'tetherbot-clip-editor-heading',
        }));
        this._error = new St.Label({
            text: '',
            style_class: 'tetherbot-clip-editor-error',
            visible: false,
        });
        this._actions = new St.BoxLayout({
            style_class: 'tetherbot-clip-editor-actions',
            x_align: Clutter.ActorAlign.END,
            x_expand: true,
        });
        this._buttons = [];
        this._focusTarget = null;
        this._focusSource = 0;
        this._returnFocus = null;
        this._returnFocusId = 0;
        this._destroyed = false;
        this.item.connect('destroy', () => this._forgetSources());
    }

    // Key focus goes back to the clip row when the editor closes, so the
    // menu keeps keyboard navigation.
    returnFocusTo(actor) {
        this._returnFocus = actor;
        this._returnFocusId = actor.connect('destroy', () => {
            this._returnFocus = null;
            this._returnFocusId = 0;
        });
    }

    _finish(buttons) {
        for (const button of buttons) {
            this._buttons.push(button);
            this._actions.add_child(button);
        }
        this.box.add_child(this._error);
        this.box.add_child(this._actions);
    }

    setError(text) {
        if (this._destroyed)
            return;
        this._error.text = text || '';
        this._error.visible = Boolean(text);
    }

    setBusy(busy) {
        if (this._destroyed)
            return;
        for (const button of this._buttons) {
            button.reactive = !busy;
            button.can_focus = !busy;
        }
    }

    focus() {
        if (this._destroyed || !this._focusTarget)
            return;
        this._focusTarget.grab_key_focus();
    }

    // The press that opened the editor is still being handled, so the
    // focus moves on the next idle.
    focusSoon() {
        if (this._destroyed || this._focusSource)
            return;
        this._focusSource = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._focusSource = 0;
            this.focus();
            return GLib.SOURCE_REMOVE;
        });
    }

    _forgetSources() {
        this._destroyed = true;
        if (this._focusSource) {
            GLib.source_remove(this._focusSource);
            this._focusSource = 0;
        }
        if (this._returnFocus && this._returnFocusId)
            this._returnFocus.disconnect(this._returnFocusId);
        this._returnFocusId = 0;
    }

    destroy() {
        if (this._destroyed)
            return;
        const stage = this.item.get_stage();
        const focus = stage ? stage.get_key_focus() : null;
        const hadFocus = focus !== null && this.item.contains(focus);
        const back = this._returnFocus;
        this._forgetSources();
        this._returnFocus = null;
        this.item.destroy();
        if (hadFocus && back && back.mapped)
            back.grab_key_focus();
    }
}

export class TagEditor extends InlineEditor {
    constructor({chips, onSave, onCancel}) {
        super('tetherbot-clip-tag-editor', 'Tags');
        this._chips = chips;
        this._chipButtons = new Map();
        this._flow = new St.Widget({
            layout_manager: new Clutter.FlowLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                column_spacing: 6,
                row_spacing: 6,
                snap_to_grid: false,
            }),
            style_class: 'tetherbot-clip-chips',
            x_expand: true,
        });
        const flowBox = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        flowBox.add_child(this._flow);
        this._empty = new St.Label({
            text: 'No tags yet',
            style_class: 'tetherbot-clip-editor-hint',
        });
        flowBox.add_child(this._empty);
        this.box.add_child(new St.ScrollView({
            style_class: 'tetherbot-clip-chips-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            x_expand: true,
            child: flowBox,
        }));
        this._entry = new St.Entry({
            hint_text: 'New tag…',
            style_class: 'tetherbot-clip-tag-entry',
            can_focus: true,
            x_expand: true,
        });
        this._entry.clutter_text.connect('activate', () => this._addTyped());
        this.box.add_child(this._entry);
        this._focusTarget = this._entry;
        this._onSave = onSave;
        this._finish([
            editorButton('Cancel', onCancel),
            editorButton('Save', () => this._save()),
        ]);
        this._render();
    }

    get chips() {
        return this._chips;
    }

    mergeKnown(known) {
        if (this._destroyed)
            return;
        this._chips = mergeKnownTags(this._chips, known);
        this._render();
    }

    _toggle(name) {
        const result = toggleTagChip(this._chips, name);
        this._chips = result.chips;
        this.setError(result.error);
        this._render();
    }

    _addTyped() {
        const result = addTagChip(this._chips, this._entry.get_text());
        this._chips = result.chips;
        this.setError(result.error);
        if (result.added)
            this._entry.set_text('');
        this._render();
        return result.error === '';
    }

    _save() {
        if (this._entry.get_text().trim() && !this._addTyped())
            return;
        this._onSave(this._chips);
    }

    _render() {
        if (this._destroyed)
            return;
        for (const chip of this._chips) {
            let button = this._chipButtons.get(chip.name);
            if (!button) {
                button = this._chipButton(chip);
                this._chipButtons.set(chip.name, button);
                this._flow.add_child(button);
            }
            button.checked = chip.selected === true;
        }
        this._empty.visible = this._chips.length === 0;
    }

    _chipButton(chip) {
        const content = new St.BoxLayout({y_align: Clutter.ActorAlign.CENTER});
        content.add_child(new St.Widget({
            style_class: `tetherbot-clip-dot tetherbot-clip-dot-${tagTone(chip.color)}`,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        content.add_child(new St.Label({
            text: chip.name,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        const button = new St.Button({
            child: content,
            style_class: 'tetherbot-tag-chip',
            can_focus: true,
            reactive: true,
            track_hover: true,
            toggle_mode: false,
        });
        button.accessible_name = chip.name;
        button.connect('clicked', () => this._toggle(chip.name));
        return button;
    }
}
