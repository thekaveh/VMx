from __future__ import annotations

import argparse
from pathlib import Path

from scripts.docs.check_docs import (
    ATX_HEADING_RE,
    NUMBER_PREFIX_RE,
    STANDALONE_NUMBERED_DOCS,
)
from scripts.docs.manifest import load_manifest


def number_descendant_headings(markdown: str, page_number: str | None) -> str:
    """Return Markdown with deterministic hierarchical H2-H6 prefixes."""
    counters = [0, 0, 0, 0, 0]
    output: list[str] = []
    fence: str | None = None

    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        stripped = content.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            output.append(line)
            continue
        if fence is not None:
            output.append(line)
            continue

        match = ATX_HEADING_RE.match(content)
        if match is None:
            output.append(line)
            continue
        level = len(match.group(1))
        depth = level - 2
        if depth > 0 and counters[depth - 1] == 0:
            raise ValueError(f"H{level} heading has no H{level - 1} parent: {content}")
        counters[depth] += 1
        for index in range(depth + 1, len(counters)):
            counters[index] = 0
        page_prefix = f"{page_number}." if page_number else ""
        number = page_prefix + ".".join(str(value) for value in counters[: depth + 1]) + "."
        title = match.group(2)
        while NUMBER_PREFIX_RE.match(title) is not None:
            title = NUMBER_PREFIX_RE.sub("", title, count=1)
        output.append(f"{match.group(1)} {number} {title}{ending}")

    return "".join(output)


def update_pages(repo_root: Path, *, write: bool) -> list[Path]:
    manifest = load_manifest(repo_root / "docs/manifest.yaml", repo_root)
    changed: list[Path] = []
    for section in manifest.pages():
        assert section.source is not None
        path = repo_root / section.source
        original = path.read_text(encoding="utf-8")
        numbered = number_descendant_headings(original, section.number)
        if numbered == original:
            continue
        changed.append(section.source)
        if write:
            path.write_text(numbered, encoding="utf-8")
    for relative_path in STANDALONE_NUMBERED_DOCS:
        path = repo_root / relative_path
        original = path.read_text(encoding="utf-8")
        numbered = number_descendant_headings(original, None)
        if numbered == original:
            continue
        changed.append(relative_path)
        if write:
            path.write_text(numbered, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changed = update_pages(Path(args.root).resolve(), write=args.write)
    for path in changed:
        print(path)
    return 0 if args.write or not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
