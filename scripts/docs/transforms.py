from __future__ import annotations

import html
import os
import re
from pathlib import Path

from scripts.docs.links import MARKDOWN_LINK_RE, is_forbidden
from scripts.docs.manifest import Manifest, Section

ASSET_PREFIX_RE = re.compile(r"(?P<prefix>(?:\.\./)+)assets/diagrams/(?P<asset>[^)\s]+)")


def wiki_name(section: Section) -> str:
    if section.source and section.source.name == "index.md" and section.number == "1":
        return "Home.md"
    safe = re.sub(r"[^A-Za-z0-9]+", "-", section.label).strip("-")
    return f"{safe}.md"


def build_source_map(manifest: Manifest, surface: str) -> dict[Path, Path]:
    source_map: dict[Path, Path] = {}
    for section in manifest.pages():
        assert section.source is not None
        if surface == "site":
            source_map[section.source] = Path(*section.source.parts[2:])
        elif surface == "wiki":
            source_map[section.source] = Path(wiki_name(section))
        else:
            raise ValueError(f"unknown surface: {surface}")
    return source_map


def _bare_link(label: str, target: str, *, image: bool) -> str:
    if image:
        return label or Path(target).name
    return label or target


def _strip_url_bits(target: str) -> str:
    return target.split("#", 1)[0].split("?", 1)[0]


def _repo_blob_to_path(target: str) -> Path | None:
    prefix = "https://github.com/thekaveh/VMx/blob/main/"
    if not target.startswith(prefix):
        return None
    return Path(target[len(prefix) :].split("#", 1)[0])


def _mapped_target(
    target: str,
    *,
    current_source: Path,
    current_output: Path,
    source_map: dict[Path, Path],
    surface: str,
) -> str | None:
    clean = _strip_url_bits(target)
    if clean.endswith(".ipynb"):
        return None

    if repo_path := _repo_blob_to_path(target):
        return str(source_map[repo_path]) if repo_path in source_map else None

    if clean.startswith(("http://", "https://", "mailto:")):
        return target
    if not clean.endswith(".md"):
        if clean.startswith("#") or "assets/diagrams/" in clean:
            return target
        return None

    candidate = (current_source.parent / clean).resolve()
    repo_root = Path.cwd().resolve()
    try:
        canonical = candidate.relative_to(repo_root)
    except ValueError:
        return None
    if canonical not in source_map:
        return None

    mapped = source_map[canonical]
    if surface == "wiki":
        return f"wiki:{mapped.stem}"
    rel = os.path.relpath(mapped, start=current_output.parent)
    return rel.replace(os.sep, "/")


def rewrite_for_surface(
    markdown: str,
    *,
    surface: str,
    current_source: Path,
    current_output: Path,
    source_map: dict[Path, Path],
) -> str:
    def replace(match: re.Match[str]) -> str:
        image = bool(match.group("image"))
        label = match.group("label")
        target = html.unescape(match.group("target"))
        if is_forbidden(target, surface):
            mapped = _mapped_target(
                target,
                current_source=current_source,
                current_output=current_output,
                source_map=source_map,
                surface=surface,
            )
            if not mapped:
                return _bare_link(label, target, image=image)
            if surface == "wiki" and mapped.startswith("wiki:"):
                return f"[[{label}|{mapped[5:]}]]"
            return f"{'!' if image else ''}[{label}]({mapped})"

        mapped = _mapped_target(
            target,
            current_source=current_source,
            current_output=current_output,
            source_map=source_map,
            surface=surface,
        )
        if mapped is None:
            return _bare_link(label, target, image=image)
        if mapped.startswith("wiki:"):
            return f"[[{label}|{mapped[5:]}]]"
        return f"{'!' if image else ''}[{label}]({mapped})"

    text = MARKDOWN_LINK_RE.sub(replace, markdown)
    if surface == "wiki":
        text = ASSET_PREFIX_RE.sub(r"assets/diagrams/\g<asset>", text)
    return text
