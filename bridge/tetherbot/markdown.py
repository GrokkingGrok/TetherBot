# SPDX-License-Identifier: GPL-2.0-or-later
"""A small Markdown subset for todo bodies.

The window paints these runs with GtkTextTags. This module does not import
GTK, does not fetch images, and does not treat the text as HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

from tetherbot.window_query import safe_http_url


@dataclass(frozen=True)
class Run:
    """One slice of visible text."""

    text: str
    tags: tuple[str, ...] = ()
    href: str | None = None


def render(source: str) -> tuple[Run, ...]:
    """Turn a Markdown subset into tagged runs.

    Headings, bold, italic, inline code, fenced code, lists, task boxes,
    quotes, and ``http`` / ``https`` links. Images become their alt text.
    Anything else stays as characters.
    """

    if not isinstance(source, str) or not source:
        return ()
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    runs: list[Run] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _opening_fence(line)
        if fence is not None:
            char, count = fence
            index += 1
            body: list[str] = []
            while index < len(lines) and not _closing_fence(lines[index], char, count):
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            if body:
                runs.append(Run("\n".join(body), ("codeblock",)))
            runs.append(Run("\n"))
            continue
        if line.strip() == "":
            runs.append(Run("\n"))
            index += 1
            continue
        heading = _heading(line)
        if heading is not None:
            level, rest = heading
            tag = ("h1", "h2", "h3")[min(level, 3) - 1]
            runs.extend(_with_tag(inline(rest), tag))
            runs.append(Run("\n"))
            index += 1
            continue
        quoted = _quote(line)
        if quoted is not None:
            runs.extend(_with_tag(inline(quoted), "quote"))
            runs.append(Run("\n"))
            index += 1
            continue
        listed = _list_item(line)
        if listed is not None:
            kind, marker, rest = listed
            runs.append(Run(_LIST_PREFIX[kind].format(marker=marker), (kind,)))
            runs.extend(inline(rest))
            runs.append(Run("\n"))
            index += 1
            continue
        runs.extend(inline(line))
        runs.append(Run("\n"))
        index += 1
    return tuple(runs)


def inline(text: str) -> tuple[Run, ...]:
    """Parse inline marks in one line. Code is not scanned again."""

    runs: list[Run] = []
    buf: list[str] = []
    index = 0
    length = len(text)

    def flush() -> None:
        if buf:
            runs.append(Run("".join(buf)))
            buf.clear()

    while index < length:
        image = _image_at(text, index)
        if image is not None:
            label, end = image
            flush()
            if label:
                runs.append(Run(label))
            index = end
            continue
        if text[index] == "`":
            end = text.find("`", index + 1)
            if end != -1:
                flush()
                runs.append(Run(text[index + 1 : end], ("code",)))
                index = end + 1
                continue
        for marker in ("**", "__"):
            if text.startswith(marker, index):
                end = text.find(marker, index + 2)
                if end != -1:
                    flush()
                    runs.extend(_with_tag(inline(text[index + 2 : end]), "bold"))
                    index = end + 2
                    break
        else:
            marker = ""
        if marker:
            continue
        link = _link_at(text, index)
        if link is not None:
            label, url, end = link
            flush()
            href = safe_http_url(url)
            shown = label or (href or "")
            if shown:
                if href:
                    runs.append(Run(shown, ("link",), href))
                else:
                    runs.append(Run(shown))
            index = end
            continue
        italic = _italic_at(text, index)
        if italic is not None:
            inner, end = italic
            flush()
            runs.extend(_with_tag(inline(inner), "italic"))
            index = end
            continue
        buf.append(text[index])
        index += 1
    flush()
    return tuple(runs)


_LIST_PREFIX = {
    "bullet": "• ",
    "number": "{marker}. ",
    "task": "☐ ",
    "task-done": "☑ ",
}


def _with_tag(runs: tuple[Run, ...], tag: str) -> tuple[Run, ...]:
    return tuple(Run(run.text, run.tags + (tag,), run.href) for run in runs)


def _opening_fence(line: str) -> tuple[str, int] | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    stripped = line.lstrip(" ")
    if not stripped or stripped[0] not in "`~":
        return None
    char = stripped[0]
    count = 0
    for item in stripped:
        if item != char:
            break
        count += 1
    if count < 3:
        return None
    rest = stripped[count:]
    if char in rest:
        return None
    return char, count


def _closing_fence(line: str, char: str, count: int) -> bool:
    stripped = line.strip()
    return len(stripped) >= count and stripped != "" and set(stripped) == {char}


def _heading(line: str) -> tuple[int, str] | None:
    marks = 0
    for char in line:
        if char != "#":
            break
        marks += 1
    if marks < 1 or marks > 6 or len(line) <= marks or line[marks] != " ":
        return None
    return marks, line[marks + 1 :]


def _quote(line: str) -> str | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    stripped = line.lstrip(" ")
    if not stripped.startswith(">"):
        return None
    rest = stripped[1:]
    if rest.startswith(" "):
        rest = rest[1:]
    return rest


def _list_item(line: str) -> tuple[str, str, str] | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    stripped = line.lstrip(" ")
    if stripped[:2] in {"- ", "* ", "+ "}:
        rest = stripped[2:]
        task = _task(rest)
        if task is not None:
            return task
        return "bullet", "", rest
    number = _number_mark(stripped)
    if number is None:
        return None
    marker, rest = number
    return "number", marker, rest


def _task(rest: str) -> tuple[str, str, str] | None:
    if len(rest) < 4 or not rest.startswith("[") or rest[2:4] != "] ":
        return None
    box = rest[1]
    if box == " ":
        return "task", "", rest[4:]
    if box in {"x", "X"}:
        return "task-done", "", rest[4:]
    return None


def _number_mark(stripped: str) -> tuple[str, str] | None:
    digits = 0
    while digits < len(stripped) and stripped[digits].isdigit():
        digits += 1
    if digits == 0 or digits > 6:
        return None
    if digits + 1 >= len(stripped) or stripped[digits : digits + 2] != ". ":
        return None
    return stripped[:digits], stripped[digits + 2 :]


def _image_at(text: str, index: int) -> tuple[str, int] | None:
    if not text.startswith("![", index):
        return None
    parsed = _link_at(text, index + 1)
    if parsed is None:
        return None
    label, _url, end = parsed
    return label, end


def _link_at(text: str, index: int) -> tuple[str, str, int] | None:
    if index >= len(text) or text[index] != "[":
        return None
    close = text.find("]", index + 1)
    if close == -1 or close + 1 >= len(text) or text[close + 1] != "(":
        return None
    end = text.find(")", close + 2)
    if end == -1:
        return None
    label = text[index + 1 : close]
    url = text[close + 2 : end].strip()
    if "\n" in label or "\n" in url or not url:
        return None
    return label, url, end + 1


def _italic_at(text: str, index: int) -> tuple[str, int] | None:
    marker = text[index]
    if marker not in "*_":
        return None
    previous = text[index - 1] if index else ""
    if marker == "_" and previous and not previous.isspace() and previous not in "([{\"":
        return None
    if index + 1 >= len(text) or text[index + 1] in {marker, " "}:
        return None
    end = text.find(marker, index + 2)
    if end == -1 or text[end - 1] == " ":
        return None
    if end + 1 < len(text) and text[end + 1] == marker:
        return None
    if marker == "_" and end + 1 < len(text) and text[end + 1].isalnum():
        return None
    return text[index + 1 : end], end + 1
