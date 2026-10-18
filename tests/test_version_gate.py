# SPDX-License-Identifier: GPL-2.0-or-later
"""Schema version gate."""

from tetherbot.version_gate import check_schema


def test_known_major_and_minor_are_accepted():
    assert check_schema("tetherbot/1", source="feed").accepted
    assert check_schema("tetherbot/1.2", source="feed").accepted


def test_unknown_major_name_and_shape_fail_closed():
    major = check_schema("tetherbot/2", source="feed.json")
    assert not major.accepted
    assert major.message == "feed.json: unsupported schema tetherbot/2, update tetherbot"
    assert not check_schema("other/1", source="feed").accepted
    assert not check_schema(None, source="feed").accepted
    assert not check_schema("tetherbot", source="feed").accepted
