# SPDX-License-Identifier: GPL-2.0-or-later
"""Schema version gate.

An unknown major version fails closed. Callers keep the last good items
and surface ``SchemaDecision.message``. This module does not guess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tetherbot import SCHEMA_MAJOR, SCHEMA_NAME


@dataclass(frozen=True)
class SchemaDecision:
    accepted: bool
    message: str = ""


def supported_versions() -> dict[str, tuple[int, ...]]:
    """Schemas this scaffold knows. Adapters may pass a narrower map."""

    return {SCHEMA_NAME: (SCHEMA_MAJOR,)}


def check_schema(
    schema: object,
    *,
    source: str,
    supported: Mapping[str, Sequence[int]] | None = None,
) -> SchemaDecision:
    """Accept ``name/<major>`` and ``name/<major>.<minor>`` when the major is known.

    A higher major, an unknown name, or a value that is not a schema string
    is rejected. Minor numbers inside a known major are accepted.
    """

    table = supported if supported is not None else supported_versions()
    rendered = schema if isinstance(schema, str) else repr(schema)
    reject = SchemaDecision(
        accepted=False,
        message=f"{source}: unsupported schema {rendered}, update tetherbot",
    )
    if not isinstance(schema, str):
        return reject
    name, separator, rest = schema.partition("/")
    if not separator or not name or not rest:
        return reject
    major_text = rest.split(".", 1)[0]
    if not major_text.isdigit():
        return reject
    major = int(major_text)
    allowed = table.get(name)
    if allowed is None or major not in allowed:
        return reject
    return SchemaDecision(accepted=True)
