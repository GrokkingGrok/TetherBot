# SPDX-License-Identifier: GPL-2.0-or-later
"""Store diff, notify dedupe, snooze, and expiry."""

from datetime import timedelta

from tests.helpers import NOW, make_item

from tetherbot.store import ItemStore


def test_diff_adds_updates_and_removes():
    store = ItemStore()
    first = store.replace_origin("feed", [make_item()], now=NOW)
    assert first.diff.added == ("primary/sample-01",)
    assert [notice.reason for notice in first.notifications] == ["new"]

    again = store.replace_origin("feed", [make_item()], now=NOW)
    assert again.diff.added == ()
    assert again.diff.updated == ()
    assert again.notifications == ()

    changed = store.replace_origin(
        "feed",
        [make_item(title="Approve the sample", updated_at="2026-10-17T12:05:00+00:00")],
        now=NOW,
    )
    assert changed.diff.updated == ("primary/sample-01",)
    assert [notice.reason for notice in changed.notifications] == ["changed"]

    cleared = store.replace_origin("feed", [], now=NOW)
    assert cleared.diff.removed == ("primary/sample-01",)
    assert store.items() == ()


def test_same_revision_does_not_notify_twice():
    store = ItemStore()
    store.replace_origin("feed", [make_item(title="First title")], now=NOW)
    edited = store.replace_origin("feed", [make_item(title="Second title")], now=NOW)
    assert edited.diff.updated == ("primary/sample-01",)
    assert edited.notifications == ()


def test_unknown_kind_is_stored_without_a_notification_button():
    store = ItemStore()
    store.replace_origin("feed", [make_item(kind="surprise", actions=["approve"])], now=NOW)
    stored = store.get("primary/sample-01")
    assert stored is not None
    assert stored.actionable is False


def test_snooze_suppresses_until_it_expires():
    store = ItemStore()
    store.replace_origin("feed", [make_item()], now=NOW)
    assert store.snooze("primary/sample-01", NOW + timedelta(hours=1), now=NOW)
    held = store.replace_origin(
        "feed",
        [make_item(updated_at="2026-10-17T12:10:00+00:00")],
        now=NOW + timedelta(minutes=5),
    )
    assert held.notifications == ()
    assert store.counts(now=NOW + timedelta(minutes=5))["asks"] == 0
    released = store.refresh(NOW + timedelta(hours=2))
    assert [notice.reason for notice in released.notifications] == ["changed"]
    assert store.get("primary/sample-01").snoozed_until is None
    assert store.counts(now=NOW + timedelta(hours=2))["asks"] == 1


def test_expires_at_marks_the_item_and_skips_notification():
    store = ItemStore()
    update = store.replace_origin(
        "feed",
        [make_item(expires_at="2026-10-17T11:00:00+00:00", due=None)],
        now=NOW,
    )
    assert update.notifications == ()
    stored = store.get("primary/sample-01")
    assert stored is not None
    assert stored.status == "expired"
    assert store.counts(now=NOW)["asks"] == 0


def test_due_soon_is_deduped():
    store = ItemStore()
    first = store.replace_origin("feed", [make_item(due="2026-10-17", notify=False)], now=NOW)
    assert [notice.reason for notice in first.notifications] == ["due_soon"]
    second = store.refresh(NOW + timedelta(minutes=5))
    assert second.notifications == ()
    later = store.replace_origin("feed", [make_item(due="2026-10-20", notify=False)], now=NOW)
    assert later.notifications == ()


def test_other_origin_is_kept_and_conflicts_are_reported():
    store = ItemStore()
    store.replace_origin("feed", [make_item()], now=NOW)
    conflict = store.replace_origin("fake", [make_item(origin="fake")], now=NOW)
    assert conflict.errors == ("primary/sample-01: already owned by feed",)
    assert store.get("primary/sample-01").origin == "feed"
    store.replace_origin("fake", [make_item(id="other-01", origin="fake", due=None)], now=NOW)
    removed = store.replace_origin("feed", [], now=NOW)
    assert removed.diff.removed == ("primary/sample-01",)
    assert store.get("primary/other-01") is not None


def test_cache_reloads_without_notifying_again(tmp_path):
    path = tmp_path / "items.json"
    store = ItemStore(path)
    store.replace_origin("feed", [make_item(due=None)], now=NOW)
    reloaded = ItemStore(path)
    assert reloaded.load_error is None
    assert reloaded.get("primary/sample-01").title == "Approve the sample"
    again = reloaded.replace_origin("feed", [make_item(due=None)], now=NOW)
    assert again.notifications == ()


def test_corrupt_cache_is_kept_until_a_good_snapshot(tmp_path):
    path = tmp_path / "items.json"
    path.write_text("{", encoding="utf-8")
    original = path.read_bytes()
    store = ItemStore(path)
    assert store.load_error is not None
    assert store.items() == ()
    assert path.read_bytes() == original
    store.replace_origin("feed", [make_item(due=None)], now=NOW)
    assert ItemStore(path).get("primary/sample-01") is not None
