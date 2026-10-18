# SPDX-License-Identifier: GPL-2.0-or-later
"""Secret sweep reports categories, never the value."""

from pathlib import Path

from tetherbot.sweep import report, scan

TOKEN = "ghp_" + ("e" * 36)


def test_scan_names_the_category_and_the_report_hides_the_value(tmp_path: Path):
    config = tmp_path / "config"
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    clone = tmp_path / "clone" / ".git"
    config.mkdir()
    state.mkdir()
    cache.mkdir()
    clone.mkdir(parents=True)
    (config / "config.toml").write_text('schema = "tetherbot/1"\n', encoding="utf-8")
    (state / "bridge.log").write_text("bridge ok\n", encoding="utf-8")
    (clone / "config").write_text(f"[remote]\nurl = {TOKEN}\n", encoding="utf-8")
    hits = scan(
        [TOKEN],
        {"config": config, "state": state, "cache": cache, "clone": clone},
        journal="nothing",
        dconf="nothing",
    )
    assert hits == ["clone"]
    text = report(hits)
    assert "match: clone" in text
    assert TOKEN not in text


def test_clean_tree_and_journal_match(tmp_path: Path):
    root = tmp_path / "state"
    root.mkdir()
    (root / "items.json").write_text("{}\n", encoding="utf-8")
    assert scan([TOKEN], {"state": root}, journal="", dconf="") == []
    assert scan([TOKEN], {"state": root}, journal=f"leaked {TOKEN}", dconf="") == ["journal"]
    assert "clean" in report([])
    assert TOKEN not in report(["journal"])
