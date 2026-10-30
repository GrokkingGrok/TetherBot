# SPDX-License-Identifier: GPL-2.0-or-later
"""Note drafts stay on disk without a window."""

import json
import stat
from pathlib import Path

from tetherbot import SCHEMA_VERSION
from tetherbot.note_drafts import read_note_drafts, write_note_drafts


def test_a_missing_draft_file_starts_empty(tmp_path: Path):
    path = tmp_path / "note-drafts.json"
    drafts, writable = read_note_drafts(path)
    assert drafts == {}
    assert writable is True


def test_drafts_round_trip_and_skip_a_secret(tmp_path: Path):
    path = tmp_path / "note-drafts.json"
    secret = "ghp_notarealtoken"
    write_note_drafts(
        path,
        {"primary/one": "bring the charger", "primary/two": secret},
        writable=True,
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw
    drafts, writable = read_note_drafts(path)
    assert writable is True
    assert drafts == {"primary/one": "bring the charger"}
    assert json.loads(raw)["schema"] == SCHEMA_VERSION


def test_a_corrupt_draft_file_is_replaced(tmp_path: Path):
    path = tmp_path / "note-drafts.json"
    path.write_text("{", encoding="utf-8")
    drafts, writable = read_note_drafts(path)
    assert drafts == {}
    assert writable is True
    write_note_drafts(path, {"primary/one": "still here"}, writable=True)
    assert read_note_drafts(path)[0] == {"primary/one": "still here"}


def test_an_unknown_draft_schema_is_left_untouched(tmp_path: Path):
    path = tmp_path / "note-drafts.json"
    original = '{"schema":"tetherbot/2","drafts":{"primary/one":"keep"}}\n'
    path.write_text(original, encoding="utf-8")
    drafts, writable = read_note_drafts(path)
    assert drafts == {}
    assert writable is False
    write_note_drafts(path, {"primary/one": "replaced"}, writable=False)
    assert path.read_text(encoding="utf-8") == original


def test_an_empty_draft_does_not_create_a_file(tmp_path: Path):
    path = tmp_path / "note-drafts.json"
    write_note_drafts(path, {}, writable=True)
    assert not path.exists()
