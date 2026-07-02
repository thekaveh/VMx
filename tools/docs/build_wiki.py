#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

WIKI_LINK_RE = re.compile(r"\[\[(?:(?P<label>[^\]|]+)\|)?(?P<page>[^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
DIAGRAM_ASSET_RE = re.compile(r"(?:\.\./)+assets/diagrams/(?P<asset>[^)\s]+)")


def flattened_name(source: Path, root: Path) -> str:
    rel = source.relative_to(root)
    if source.name in {"Home.md", "_Sidebar.md", "_Footer.md"}:
        return source.name
    stem_parts = [*rel.with_suffix("").parts]
    return "-".join(stem_parts) + ".md"


def collect_pages(source_root: Path) -> dict[str, Path]:
    pages: dict[str, Path] = {}
    for path in sorted(source_root.rglob("*.md")):
        flat = flattened_name(path, source_root)
        if flat in pages:
            raise ValueError(f"duplicate flattened wiki page {flat}: {pages[flat]} and {path}")
        pages[flat] = path
    return pages


def rewrite_links(text: str, available_stems: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group("label")
        page = match.group("page").strip()

        if page.startswith(("http://", "https://")):
            return match.group(0)

        candidate = page[:-3] if page.endswith(".md") else page
        candidate = candidate.replace("/", "-")
        if candidate not in available_stems:
            raise ValueError(f"wiki link points to missing page: {page}")

        return f"[[{label}|{candidate}]]" if label else f"[[{candidate}]]"

    return WIKI_LINK_RE.sub(replace, text)


def rewrite_diagram_asset_links(text: str) -> str:
    return DIAGRAM_ASSET_RE.sub(r"assets/diagrams/\g<asset>", text)


def validate_markdown_links(text: str, source: Path) -> None:
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group("target").strip()
        target_path = target.split("#", 1)[0].split("?", 1)[0]
        if not target_path or target_path.startswith(("http://", "https://", "mailto:")):
            continue
        if target_path.endswith(".md"):
            raise ValueError(
                f"{source}: markdown link points to source markdown file {target}; "
                "use a wiki link or public URL"
            )


def build(source_root: Path, output_root: Path) -> list[Path]:
    pages = collect_pages(source_root)
    stems = {Path(name).stem for name in pages}
    if "Home" not in stems or "_Sidebar" not in stems:
        raise ValueError("docs/wiki must include Home.md and _Sidebar.md")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    written: list[Path] = []
    for flat_name, source in pages.items():
        text = source.read_text(encoding="utf-8")
        validate_markdown_links(text, source)
        text = rewrite_links(text, stems)
        text = rewrite_diagram_asset_links(text)
        target = output_root / flat_name
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="docs/wiki")
    parser.add_argument("--out", default="docs/_build/wiki")
    args = parser.parse_args()

    written = build(Path(args.source), Path(args.out))
    print(f"wrote {len(written)} wiki page(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
