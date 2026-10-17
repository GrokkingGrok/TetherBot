# SPDX-License-Identifier: GPL-2.0-or-later
"""Decide which item changes deserve a notification.

Dedupe is by item key and ``updated_at`` for first sight and later edits.
A due-soon nudge is separate and fires once per key and due value. Snoozed
items produce nothing until the snooze has elapsed. ``delivery_failed`` is
emitted by the outbound route, not by this policy.

Date-only due values use the UTC date of ``now``. A clock time in ``due``
is read as UTC until the desktop timezone lands in config. That comparison
is the v0.1 rule for "due soon": within the next 24 hours, and not already
past.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tetherbot.model import Item, parse_iso8601

_DUE_SOON = timedelta(hours=24)


@dataclass(frozen=True)
class Notice:
    key: str
    reason: str
    dedupe: tuple[str, str, str]


class NotifyPolicy:
    def __init__(self, delivered: set[tuple[str, str, str]] | None = None) -> None:
        self.delivered = set(delivered or ())

    def consider(self, item: Item, *, now: datetime, seen_before: bool) -> list[Notice]:
        if _is_snoozed(item, now) or item.status != "open":
            return []
        notices: list[Notice] = []
        revision = (item.key, item.updated_at, "revision")
        if item.notify and revision not in self.delivered:
            reason = "changed" if seen_before else "new"
            notices.append(Notice(item.key, reason, revision))
        if item.due and _is_due_soon(item.due, now):
            due_token = (item.key, item.due, "due_soon")
            if due_token not in self.delivered:
                notices.append(Notice(item.key, "due_soon", due_token))
        return notices

    def mark(self, notices: list[Notice]) -> None:
        for notice in notices:
            self.delivered.add(notice.dedupe)


def _is_snoozed(item: Item, now: datetime) -> bool:
    if not item.snoozed_until:
        return False
    return parse_iso8601(item.snoozed_until, field_name="snoozed_until") > now


def _is_due_soon(due: str, now: datetime) -> bool:
    moment = now.astimezone(UTC)
    if " " in due:
        due_at = datetime.strptime(due, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        return timedelta(0) <= due_at - moment <= _DUE_SOON
    due_date = datetime.strptime(due, "%Y-%m-%d").date()
    return moment.date() <= due_date <= moment.date() + timedelta(days=1)
