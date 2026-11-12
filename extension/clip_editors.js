// SPDX-License-Identifier: GPL-2.0-or-later
//
// St widgets for the inline clip editors in the panel clipboard menu,
// GNOME Shell 50 and 51. The extension passes the bridge calls in as callbacks.
// Nothing here opens or messages the TetherBot window.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {
    PRIMARY_BOT,
    addTagChip,
    contextEffort,
    editShortcut,
    effortTitle,
    mergeKnownTags,
    tagTone,
    toggleTagChip,
} from './clip_inline.js';

const EDIT_KEYS = new Map([
    [Clutter.KEY_Return, 'enter'],
    [Clutter.KEY_KP_Enter, 'enter'],
    [Clutter.KEY_ISO_Enter, 'enter'],
    [Clutter.KEY_a, 'a'],
    [Clutter.KEY_A, 'a'],
    [Clutter.KEY_c, 'c'],
    [Clutter.KEY_C, 'c'],
    [Clutter.KEY_v, 'v'],
    [Clutter.KEY_V, 'v'],
    [Clutter.KEY_x, 'x'],
    [Clutter.KEY_X, 'x'],
]);

function editorButton(label, onClick) {
    const button = new St.Button({
        label,
        style_class: 'button tetherbot-inline-button',
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
            style_class: `tetherbot-inline-editor ${styleClass}`,
        });
        this.box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            style_class: 'tetherbot-inline-box',
            x_expand: true,
        });
        this.item.add_child(this.box);
        this.box.add_child(new St.Label({
            text: heading,
            style_class: 'tetherbot-inline-heading',
        }));
        this._error = new St.Label({
            text: '',
            style_class: 'tetherbot-inline-error',
            visible: false,
        });
        this._actions = new St.BoxLayout({
            style_class: 'tetherbot-inline-actions',
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
        super('tetherbot-inline-tags', 'Tags');
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
            style_class: 'tetherbot-inline-hint',
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
            style_class: 'tetherbot-inline-tag-entry',
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

// One bot is chosen. Send hands the choice to the extension, which calls
// SendClipboard the same way the window's context popover does.
export class ContextEditor extends InlineEditor {
    constructor({bots, effort, onSend, onCancel}) {
        super('tetherbot-inline-context', 'Make a todo with context');
        const level = contextEffort(effort);
        const effortRow = new St.BoxLayout({style_class: 'tetherbot-clip-effort'});
        effortRow.add_child(new St.Label({text: 'Effort:'}));
        effortRow.add_child(new St.Label({
            text: effortTitle(level),
            style_class: `tetherbot-effort-${level}`,
        }));
        this.box.add_child(effortRow);
        this._bot = bots.includes(PRIMARY_BOT) ? PRIMARY_BOT : bots[0] || PRIMARY_BOT;
        this._botButtons = new Map();
        const flow = new St.Widget({
            layout_manager: new Clutter.FlowLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                column_spacing: 6,
                row_spacing: 6,
                snap_to_grid: false,
            }),
            style_class: 'tetherbot-clip-chips',
            x_expand: true,
        });
        for (const bot of bots) {
            const button = new St.Button({
                label: bot,
                style_class: 'tetherbot-tag-chip tetherbot-bot-chip',
                can_focus: true,
                reactive: true,
                track_hover: true,
                toggle_mode: false,
            });
            button.accessible_name = bot;
            button.connect('clicked', () => this._pick(bot));
            this._botButtons.set(bot, button);
            flow.add_child(button);
        }
        const flowBox = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        flowBox.add_child(flow);
        this.box.add_child(new St.ScrollView({
            style_class: 'tetherbot-clip-chips-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            x_expand: true,
            child: flowBox,
        }));
        const send = editorButton('Send', () => onSend(this._bot));
        this._focusTarget = send;
        this._finish([editorButton('Cancel', onCancel), send]);
        this._pick(this._bot);
    }

    get bot() {
        return this._bot;
    }

    _pick(bot) {
        if (this._destroyed || !this._botButtons.has(bot))
            return;
        this._bot = bot;
        for (const [name, button] of this._botButtons)
            button.checked = name === bot;
    }
}

// Multi-line Edit on a raw Clutter.Text, as QuickNotes does. St.Entry is one
// line only. activatable: false makes Enter insert a newline. Clutter.Text
// has no clipboard, so copy, cut, paste, and select all are done here.
export class EditEditor extends InlineEditor {
    constructor({text, onSave, onCancel}) {
        super('tetherbot-inline-edit', 'Edit');
        this._text = new Clutter.Text({
            text,
            editable: true,
            selectable: true,
            activatable: false,
            reactive: true,
            single_line_mode: false,
            line_wrap: true,
            line_wrap_mode: Pango.WrapMode.WORD_CHAR,
            x_expand: true,
        });
        this._text.set_selection(-1, -1);
        this._area = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            style_class: 'tetherbot-inline-text-area',
            reactive: true,
            x_expand: true,
        });
        this._area.add_child(this._text);
        this._scroll = new St.ScrollView({
            style_class: 'tetherbot-inline-text-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            x_expand: true,
            child: this._area,
        });
        this.box.add_child(new St.Bin({
            style_class: 'tetherbot-inline-text-frame',
            x_expand: true,
            child: this._scroll,
        }));
        this.box.add_child(new St.Label({
            text: 'Enter adds a line. Ctrl+Enter saves. Escape cancels.',
            style_class: 'tetherbot-inline-hint',
        }));
        this._area.connect('style-changed', () => this._syncStyle());
        this._area.connect('button-press-event', () => {
            this._text.grab_key_focus();
            return Clutter.EVENT_PROPAGATE;
        });
        this._bindEditKeys();
        this._text.connect('cursor-changed', () => this._keepCursorVisible());
        this._focusTarget = this._text;
        this._onSave = onSave;
        this._finish([
            editorButton('Cancel', onCancel),
            editorButton('Save', () => this._save()),
        ]);
    }

    get text() {
        return this._text.get_text();
    }

    _save() {
        this._onSave(this._text.get_text());
    }

    // Shell 51 delivers keys to Clutter.Text through its own key controller,
    // in the bubble phase. A capture controller on the text runs first, so
    // Ctrl+Enter and the clipboard keys are handled here. key-press-event
    // stays for Shell 50, and for a Shell where the controller is absent.
    // A capture handler that stops the event keeps the signal from running
    // it a second time.
    _bindEditKeys() {
        if (typeof Clutter.KeyController === 'function' &&
            Clutter.EventPhase &&
            typeof this._text.add_action_full === 'function') {
            const keys = new Clutter.KeyController();
            keys.connect('key-press', controller => {
                const [handling, symbol] = controller.get_key();
                if (!handling)
                    return Clutter.EVENT_PROPAGATE;
                const [, pressed, latched] = controller.get_state();
                const state = (pressed || 0) | (latched || 0);
                return this._onEditShortcut(symbol, state);
            });
            this._text.add_action_full(
                'tetherbot-inline-edit-keys',
                Clutter.EventPhase.CAPTURE,
                keys);
        }
        this._text.connect('key-press-event', (_actor, event) => {
            return this._onEditShortcut(event.get_key_symbol(), event.get_state());
        });
    }

    _onEditShortcut(symbol, state) {
        const ctrl = (state & Clutter.ModifierType.CONTROL_MASK) !== 0;
        const action = editShortcut(EDIT_KEYS.get(symbol) || '', ctrl);
        if (!action)
            return Clutter.EVENT_PROPAGATE;
        if (action === 'save')
            this._save();
        else if (action === 'copy')
            this._copySelection();
        else if (action === 'cut' && this._copySelection())
            this._text.delete_selection();
        else if (action === 'paste')
            this._paste();
        else if (action === 'select-all')
            this._text.set_selection(0, -1);
        return Clutter.EVENT_STOP;
    }

    _copySelection() {
        const selected = this._text.get_selection();
        if (!selected)
            return false;
        St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, selected);
        return true;
    }

    _paste() {
        St.Clipboard.get_default().get_text(St.ClipboardType.CLIPBOARD, (_clipboard, pasted) => {
            if (this._destroyed || typeof pasted !== 'string' || !pasted)
                return;
            this._text.delete_selection();
            let position = this._text.get_cursor_position();
            if (position < 0)
                position = [...this._text.get_text()].length;
            this._text.insert_text(pasted, position);
            const end = position + [...pasted].length;
            this._text.set_selection(end, end);
        });
    }

    _keepCursorVisible() {
        if (this._destroyed)
            return;
        const adjustment = this._scroll.vadjustment;
        if (!adjustment)
            return;
        try {
            const rect = this._text.get_cursor_rect();
            const top = this._text.y + rect.origin.y;
            adjustment.clamp_page(top, top + rect.size.height);
        } catch {
            // The text is not laid out yet.
        }
    }

    // Clutter.Text is not styled by St. Take the font and colors from the
    // area around it so the text follows the shell theme.
    _syncStyle() {
        if (this._destroyed)
            return;
        const node = this._area.get_theme_node();
        this._text.set_font_description(node.get_font());
        const color = node.get_foreground_color();
        this._text.set_color(color);
        this._text.set_cursor_color(color);
        const [hasSelection, selection] = node.lookup_color('-tetherbot-selection-color', false);
        if (hasSelection)
            this._text.set_selection_color(selection);
        const [hasSelected, selected] = node.lookup_color('-tetherbot-selected-text-color', false);
        if (hasSelected)
            this._text.set_selected_text_color(selected);
    }
}
