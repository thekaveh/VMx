"""Checked-snippet markers, the pages that carry them, and guide sections.

Standard library only, so tools/tests can import it without the docs toolchain.
scripts/docs/check_docs.py compares each marked fence with its source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

CHECKED_SNIPPET_RE = re.compile(
    r"^<!-- checked-snippet: (?P<path>[^#\s]+)(?:#(?P<region>[\w-]+))? -->$"
)
# An opening fence: any indent here; the caller allows up to three spaces past
# the marker's own indent (CommonMark, including inside a list item).
FENCE_OPEN_RE = re.compile(r"^(?P<indent> *)(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")


class CheckedSnippet(NamedTuple):
    line: int
    path: str
    region: str | None
    language: str
    # The fence content with its indentation removed, or None when no fence
    # follows the marker.
    body: str | None

    @property
    def source(self) -> str:
        """The marker target as written: path or path#region."""
        return f"{self.path}#{self.region}" if self.region else self.path


def checked_snippet_pages(repo_root: Path) -> list[Path]:
    """The pages the checked-snippet gate scans: the docs, the generated site and
    wiki, and the READMEs that the registries publish."""
    pages = [
        page
        for root in (
            repo_root / "docs/content",
            repo_root / "generated/site",
            repo_root / "generated/wiki",
        )
        for page in sorted(path for path in root.rglob("*.md") if path.is_file())
    ]
    for pattern in (
        "packages/*/README.md",
        "langs/*/README.md",
        "langs/csharp/packaging/*/README.md",
    ):
        pages.extend(sorted(repo_root.glob(pattern)))
    return pages


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _closes(line: str, fence: str, base: int) -> bool:
    """A closing fence: the opener's character, at least as long, with up to
    three spaces past the container indent and nothing else on the line."""
    stripped = line.strip()
    return (
        base <= _indent(line) <= base + 3
        and len(stripped) >= len(fence)
        and set(stripped) == {fence[0]}
    )


def _dedent(line: str, width: int) -> str:
    return line[min(width, _indent(line)) :]


def checked_snippets(markdown: str) -> list[CheckedSnippet]:
    """Every checked-snippet marker in a page, with the fence that follows it."""
    lines = markdown.splitlines()
    found: list[CheckedSnippet] = []
    for index, line in enumerate(lines):
        marker = CHECKED_SNIPPET_RE.match(line.strip())
        if marker is None:
            continue
        base = _indent(line)
        body = None
        language = ""
        opener = index + 1
        while opener < len(lines) and not lines[opener].strip():
            opener += 1
        fence = FENCE_OPEN_RE.match(lines[opener]) if opener < len(lines) else None
        if fence is not None and base <= len(fence.group("indent")) <= base + 3:
            language = (fence.group("info").split() or [""])[0]
            mark = fence.group("fence")
            closing = next(
                (end for end in range(opener + 1, len(lines)) if _closes(lines[end], mark, base)),
                None,
            )
            if closing is not None:
                width = len(fence.group("indent"))
                content = (_dedent(text, width) for text in lines[opener + 1 : closing])
                body = "\n".join(content) + "\n"
        found.append(
            CheckedSnippet(index + 1, marker.group("path"), marker.group("region"), language, body)
        )
    return found


def markdown_section(markdown: str, heading: str) -> str | None:
    """The text after `heading` up to the next level-two heading, or None when
    the page has no such heading."""
    if heading not in markdown:
        return None
    return markdown.split(heading, 1)[1].split("\n## ", 1)[0]
