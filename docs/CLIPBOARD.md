# Clipboard paste on GNOME Wayland

This note is an investigation of paste-into-app. Clipboard history phase 1 is built, and Batch J copies an image back onto the clipboard with its original type. The phased plan is in [ROADMAP.md](ROADMAP.md). The question here is whether TetherBot should paste straight into the active window, the way Clipboard Indicator's "Paste on select" does. It does not. Batch J copy-back still does not paste into the focused window. The user pastes with the shortcut that application already uses.

The source read for this note is [Clipboard Indicator](https://github.com/Tudmotu/gnome-shell-extension-clipboard-indicator) (`clipboard-indicator@tudmotu.com`), `extension.js` and `keyboard.js` on the default branch.

## What Paste on select does

The setting is a boolean, Paste on select. When it is on, choosing a history row (click, Enter, or keypad Enter) does not stop at putting that row on the clipboard. It also tries to paste.

The sequence in `#pasteItem` is:

1. Close the menu.
2. Remember the row that was current, then write the chosen entry onto the clipboard.
3. After 50 ms, inject a key chord from a virtual keyboard.
4. After another 50 ms, write the remembered row back onto the clipboard.

The virtual keyboard is a Clutter device. `keyboard.js` asks the default seat for `Clutter.InputDeviceType.KEYBOARD_DEVICE` and sends each press and release with `notify_keyval`. The timestamp is the current event time in microseconds.

Which chord depends on the shell input method's content purpose:

- A terminal purpose sends Ctrl+Shift+Insert.
- Anything else sends Shift+Insert.

That matches the project's own description: paste from the menu is Shift+Insert for programs and Ctrl+Shift+Insert for terminals. The same file lists a known limit: pasting from the menu does not work for every application.

On Wayland this is allowed because the code runs in gnome-shell, which is the compositor. A normal application cannot forge key events for another client. The shell can. The event is still only a key. Nothing in this path asks the focused application to paste.

## Why a text editor accepts it

A GTK text view treats Shift+Insert as paste. After the shell menu closes, focus usually returns to that window inside the 50 ms wait, so the chord lands in the widget the user was typing in. The widget then reads the clipboard, which step 2 has just filled.

## Why it fails in other applications

Three separate things have to be true, and any one of them fails the paste.

**The application has to honor that chord.** Shift+Insert is not a paste request. A GTK editor honors it. A lot of other text inputs do not. An Electron chat composer is a common case: the page handles Ctrl+V (sometimes Ctrl+Shift+V) and ignores Shift+Insert, even when the window has focus. The shell never learns that the key was discarded.

**The focused surface at 50 ms has to be the one the user meant.** The key goes to whichever client is focused when the timeout fires. Focus that follows the pointer is a real suspect. With sloppy or mouse focus, opening the menu moves the pointer to the top bar. When the menu closes, the pointer is often still there, or over a different window, so the chord is delivered to the wrong client or to none. Click-to-focus hides this, which is why the same row can paste in one session and miss in another.

**The application's own text input has to be ready.** A GTK editor is focused again as soon as the menu is gone. An Electron window can be focused at the compositor while its composer is not. Fifty milliseconds is enough for a simple editor and short for a chat app that restores focus inside the page. If the key arrives early, the shell still has it, or the page has it and the composer does not. The following timeout then puts the previous clipboard text back, so a late read pastes the wrong entry.

The project already records the outcome: pasting from the menu does not work for every application. The 50 ms clipboard restore is part of the same function, so a slow target can also paste the entry that was current before the click.

## Recommendation

Drop direct paste into the active window.

A Paste action in the clipboard plan should put the chosen text on the clipboard and stop there. The user pastes with the shortcut the target application already honors. That works in a GTK editor and in an Electron composer, and it does not depend on focus following the pointer or on a fixed delay.

Do not add a Clutter virtual keyboard, and do not send Shift+Insert or Ctrl+V from the extension. A later phase can revisit this only if there is a Wayland path that means "paste" rather than "type a key", and even then it should be off by default. There is no such path in the mechanism above.

Phase 1 reads the clipboard for local history. Batch J also keeps copied images in the state directory. [privacy.md](privacy.md) describes that. The captured text and the image files stay on this machine, and they are not written to the feed.

Phase 4 adds three send buttons on a text row, in the panel menu and on the Clipboard page: Make a todo, Make a todo with context, and Tell me more. One click sends. There is no confirm dialog. The row then shows Sent, or Not sent with the reason. Images and hidden passwords keep those buttons dimmed. The text leaves only when one of those buttons is pressed, and only as a webhook post from the bridge to the primary bot. The extension does not open a socket. The text is not written to the feed, to `desktop/*`, to the outbox, or to a log. [PROTOCOL.md](PROTOCOL.md) describes the `clip` object.
