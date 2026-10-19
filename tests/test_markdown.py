# SPDX-License-Identifier: GPL-2.0-or-later
"""Markdown subset: structure only, no GTK and no fetched images."""

from tetherbot.markdown import render


def _text(source: str) -> str:
    return "".join(run.text for run in render(source))


def _hrefs(source: str) -> set[str]:
    return {run.href for run in render(source) if run.href}


def test_headings_bold_italic_and_code():
    runs = render("# Title\n\nA **bold** and *slanted* word with `code`.")
    assert any(run.text == "Title" and "h1" in run.tags for run in runs)
    assert any(run.text == "bold" and "bold" in run.tags for run in runs)
    assert any(run.text == "slanted" and "italic" in run.tags for run in runs)
    assert any(run.text == "code" and "code" in run.tags for run in runs)
    assert not any(run.text.startswith("#") for run in runs)
    second = render("## Next\n### Smaller")
    assert any("h2" in run.tags for run in second)
    assert any("h3" in run.tags for run in second)


def test_fenced_code_is_not_scanned_for_marks():
    source = "```\n**not bold**\n[skip](https://example.test/x)\n```"
    runs = render(source)
    block = next(run for run in runs if "codeblock" in run.tags)
    assert "**not bold**" in block.text
    assert _hrefs(source) == set()


def test_lists_quotes_and_task_boxes():
    source = "- milk\n1. eggs\n- [ ] open\n- [x] shut\n> a quote"
    runs = render(source)
    assert any(run.text == "• " and "bullet" in run.tags for run in runs)
    assert any(run.text == "1. " and "number" in run.tags for run in runs)
    assert any(run.text == "☐ " and "task" in run.tags for run in runs)
    assert any(run.text == "☑ " and "task-done" in run.tags for run in runs)
    assert any(run.text == "a quote" and "quote" in run.tags for run in runs)
    assert "☐" in _text(source) and "☑" in _text(source)


def test_links_are_http_only_and_images_are_alt_text():
    source = (
        "See [the note](https://example.test/note) "
        "and [nope](javascript:alert(1)) "
        "plus ![cat](https://example.test/cat.png)."
    )
    assert _hrefs(source) == {"https://example.test/note"}
    visible = _text(source)
    assert "the note" in visible
    assert "nope" in visible
    assert "cat" in visible
    assert "example.test/cat.png" not in visible
    assert "javascript:" not in visible
    assert "<img" not in visible


def test_raw_html_stays_text():
    source = "A <b>tag</b> and &amp; stay as typed."
    visible = _text(source)
    assert "<b>tag</b>" in visible
    assert "&amp;" in visible
    assert _hrefs(source) == set()


def test_item_key_underscores_are_not_italic():
    visible = _text("Keep item_key and use _yes_.")
    assert "item_key" in visible
    runs = render("Keep item_key and use _yes_.")
    assert any(run.text == "yes" and "italic" in run.tags for run in runs)
    assert not any("italic" in run.tags and "item" in run.text for run in runs)
