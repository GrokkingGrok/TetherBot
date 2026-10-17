# Prompt B: paste into a coding agent on your machine

Use this when the daemon and `tetherbotctl` exist. On the pre-alpha scaffold the agent should stop at the first missing command instead of inventing one.

```text
Help me install TetherBot on this Fedora 44 / GNOME 50 machine. Rules: never print,
log, echo, or commit a secret; never ask me to paste a token or webhook key into this
chat; never put a token in a git remote URL; store secrets only in the desktop secret
service through tetherbotctl. Explain each command before you run it, and stop and ask
if something fails.

Steps:
1. Check prerequisites: python3 (3.13+), python3-gobject, the Secret-1 typelib
   (libsecret), git, gnome-shell version. Install anything missing with the system
   package manager after I confirm.
2. Clone this TetherBot repository into a directory I choose and run
   scripts/install.sh (without --enable). Show me what it installed.
3. Webhook key: tell me to open my bot's "Desktop actions" routine in Grok Bot (bot
   details, Routines, the routine, Webhook) and then run
   `tetherbotctl secret set <bot>-actions` in my own terminal so I paste the URL
   and key there myself. Then set [bots.<bot>] webhook_slot in
   ~/.config/tetherbot/config.toml.
4. Optional repo: ask whether I want bot-to-desktop updates. If yes, walk me through
   making a fine-grained GitHub token limited to my one private data repo (Contents
   read and write, Metadata read, 90-day expiry). I store it myself with
   `tetherbotctl secret set github-token`. Configure the github-poller adapter with a
   plain https remote, run `tetherbotctl repo setup`, which clones it and sets the
   credential helper on that clone only, and confirm with
   `git -C <clone> config --get-all credential.helper` and
   `git -C <clone> remote get-url origin` that no token appears.
5. Enable: `tetherbotctl enable webhook` (and `enable repo` if set up), then
   `systemctl --user enable --now tetherbot`. Show `tetherbotctl status` and
   the last 50 lines of `journalctl --user -u tetherbot`. Confirm no secret shows
   up in them.
6. Ask before running `tetherbotctl webhook test <bot>`, since it starts a real
   bot run.
7. Install the extension, then tell me to log out and back in (Wayland needs that)
   and enable UUID tetherbot@grokkinggrok.github.io.
8. Finish with a short summary: what is enabled, where config lives, and how to undo
   it (scripts/uninstall.sh).
```
