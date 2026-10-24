# SPDX-License-Identifier: GPL-2.0-or-later
"""Field rules, the secret guard, and unknown kinds."""

import importlib.util
from pathlib import Path

import pytest

from tests.helpers import make_item
from tetherbot.model import SECRET_REPLACEMENT, Item, global_key, looks_like_secret, mask_secrets

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("feed_write", _ROOT / "tools" / "feed_write.py")
assert _SPEC is not None and _SPEC.loader is not None
_feed_write = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_feed_write)

_GREENHOUSE = "https://boards.greenhouse.io/example/jobs/412345678901"
_DRIVE = "https://drive.google.com/file/d/1abcdefghijklmnopqrstuvwxyz0123456789ABCD/view"
_HEX_PATH = "https://example.com/models/abcdef0123456789abcdef0123456789"
_LONG_NAME = "https://example.com/thisisaverylongfilenamewithoutanybreaksat"
_HEX_BLOB = "abcdef0123456789abcdef0123456789"


def test_global_key_and_fixture_shape():
    item = make_item(id="primary-20261017-01", example_extra=True)
    assert item.key == global_key("primary", "primary-20261017-01")
    assert item.extra == {"example_extra": True}
    assert item.actionable is True
    assert not hasattr(item, "example_extra")


def test_unknown_kind_is_kept_and_not_actionable():
    item = make_item(kind="surprise", actions=["approve"])
    assert item.kind == "surprise"
    assert item.actionable is False


def test_secret_guard_replaces_the_whole_field(caplog):
    caplog.set_level("INFO", logger="tetherbot")
    secret = "ghp_abcdefghijklmnopqrstuvwxyz"
    item = make_item(body=f"token {secret}")
    assert item.body == SECRET_REPLACEMENT
    assert item.title == "Approve the sample"
    assert item.redacted_fields == ("body",)
    assert secret not in caplog.text
    assert "redacted body on primary/sample-01" in caplog.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("body", "github_pat_123"),
        ("body", "sk-live"),
        ("amount", "AKIAIOSFODNN7EXAMPLE"),
        ("body", "call 555123456 now"),
        ("body", "abcdef0123456789abcdef0123456789"),
        ("body", "abcdEFGHijklMNOPqrstUVWXyz0123456789+/ab=="),
    ],
)
def test_secret_patterns(field: str, value: str):
    overrides = {"kind": "watch", "actions": []} if field == "amount" else {field: value}
    if field == "amount":
        overrides["amount"] = value
    item = make_item(**overrides)
    assert getattr(item, field) == SECRET_REPLACEMENT


def test_short_digits_and_ask_prefix_stay():
    item = make_item(title="Ask-me later", body="code 55512345")
    assert item.title == "Ask-me later"
    assert item.body == "code 55512345"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "NO"}, "item id"),
        ({"title": "two\nlines"}, "single line"),
        ({"title": "x" * 121}, "120"),
        ({"body": "y" * 1001}, "1000"),
        ({"status": "later"}, "status"),
        ({"created": "2026-10-17T11:40:00"}, "offset"),
        ({"priority": 4}, "priority"),
        ({"due": "tomorrow"}, "due"),
        ({"actions": ["pay"]}, "actions"),
        ({"notify": "yes"}, "notify"),
        ({"source": {"bot": "other"}}, "source.bot"),
        ({"links": [{"label": "docs", "url": "http://example.com"}]}, "https"),
        ({"amount": "$1"}, "amount"),
        ({"todo_kind": "task"}, "todo_kind"),
    ],
)
def test_field_rules_reject(overrides: dict, message: str):
    with pytest.raises((TypeError, ValueError), match=message):
        make_item(**overrides)


def test_bill_amount_and_https_link_are_kept():
    item = make_item(
        id="bill-01",
        kind="todo",
        todo_kind="bill",
        amount="~$10",
        actions=["done"],
        links=[{"label": "docs", "url": "https://example.com/doc"}],
        waiting={"on": "reply", "check_back": "2026-10-18"},
    )
    assert item.amount == "~$10"
    assert item.links[0]["url"].startswith("https://")
    assert item.waiting == {"on": "reply", "check_back": "2026-10-18"}


def test_waiting_on_secret_is_redacted():
    item = make_item(waiting={"on": "5551234567"})
    assert item.waiting is not None
    assert item.waiting["on"] == SECRET_REPLACEMENT
    assert "waiting.on" in item.redacted_fields


@pytest.mark.parametrize(
    "text",
    [
        _GREENHOUSE,
        f"See the role: {_GREENHOUSE}.",
        _DRIVE,
        f"({_DRIVE})",
        _HEX_PATH,
        _LONG_NAME,
        "http://example.com/jobs/412345678901",
        "https://example.com/file?id=" + _HEX_BLOB,
        "https://discord.com/channels/1234567890123/1234567890123",
        "https://example.slack.com/archives/C123456789/p1234567890123456",
        "https://en.wikipedia.org/wiki/Foo_(bar)",
    ],
)
def test_long_ids_in_normal_links_are_not_secrets(text: str):
    assert looks_like_secret(text) is False
    assert _feed_write.looks_like_secret(text) is False
    item = make_item(body=text)
    assert item.body == text


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/jobs/12?token=abc",
        "https://example.com/file?key=abc",
        "https://example.com/file?sig=abc",
        "https://example.com/file?Token=abc",
        "https://example.com/doc#access_token=abc",
        "https://user:pass@example.com/notes",
        "https://token@example.com/notes",
        "https://hooks.slack.com/services/T0/B0/notarealhook",
        "https://discord.com/api/webhooks/1/ab",
        "https://discordapp.com/api/webhooks/1/ab",
        "https://canary.discord.com/api/webhooks/1/ab",
        f"Notes {_GREENHOUSE} and also {_HEX_BLOB}",
        "https://example.com/ghp_abcdefghijklmnopqrstuvwxyz",
        "call 555123456 now",
        _HEX_BLOB,
    ],
)
def test_token_queries_userinfo_and_webhook_hosts_stay_secrets(text: str):
    assert looks_like_secret(text) is True
    assert _feed_write.looks_like_secret(text) is True


def test_mask_secrets_keeps_a_normal_link_and_hides_a_webhook():
    kept = mask_secrets(f"open {_DRIVE} today")
    assert _DRIVE in kept
    assert SECRET_REPLACEMENT not in kept
    hidden = mask_secrets("post https://hooks.slack.com/services/T0/B0/notarealhook now")
    assert "hooks.slack.com" not in hidden
    assert "notarealhook" not in hidden
    assert SECRET_REPLACEMENT in hidden
    userinfo = mask_secrets("see https://user:pass@example.com/notes")
    assert "user:pass" not in userinfo
    assert SECRET_REPLACEMENT in userinfo
    query = mask_secrets("see https://example.com/file?token=abc")
    assert "token=abc" not in query
    assert _HEX_BLOB not in mask_secrets(f"code {_HEX_BLOB}")


def test_cache_round_trip_keeps_local_state_and_extra():
    item = make_item(example_extra=True)
    item.snoozed_until = "2026-10-17T13:00:00+00:00"
    item.seen = True
    item.acted = {
        "action": "veto",
        "action_id": "a-veto1",
        "at": "2026-10-17T12:00:00+00:00",
    }
    item.resolved = "dropped"
    restored = Item.from_cache(item.to_cache())
    assert restored.extra == {"example_extra": True}
    assert restored.snoozed_until == item.snoozed_until
    assert restored.seen is True
    assert restored.acted == item.acted
    assert restored.resolved == "dropped"
    assert restored.key == item.key
