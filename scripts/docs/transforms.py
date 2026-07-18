from __future__ import annotations

import html
import os
import re
from pathlib import Path

from scripts.docs.links import MARKDOWN_LINK_RE, is_forbidden
from scripts.docs.manifest import Manifest, Section

ASSET_PREFIX_RE = re.compile(r"(?P<prefix>(?:\.\./)+)assets/diagrams/(?P<asset>[^)\s]+)")
HTML_HREF_RE = re.compile(r'href="(?P<target>[^"]+)"')


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


def _split_url_bits(target: str) -> tuple[str, str]:
    cuts = [position for marker in ("?", "#") if (position := target.find(marker)) >= 0]
    cut = min(cuts, default=len(target))
    return target[:cut], target[cut:]


def _strip_url_bits(target: str) -> str:
    return _split_url_bits(target)[0]


def _repo_blob_to_path(target: str) -> Path | None:
    prefix = "https://github.com/thekaveh/VMx/blob/main/"
    if not target.startswith(prefix):
        return None
    return Path(target[len(prefix) :])


def _mapped_target(
    target: str,
    *,
    current_source: Path,
    current_output: Path,
    source_map: dict[Path, Path],
    surface: str,
    repo_root: Path,
) -> str | None:
    clean, suffix = _split_url_bits(target)
    if clean.endswith(".ipynb"):
        return None

    if repo_path := _repo_blob_to_path(clean):
        if repo_path not in source_map:
            return None
        mapped = source_map[repo_path]
        return f"wiki:{mapped.stem}{suffix}" if surface == "wiki" else f"{mapped}{suffix}"

    if clean.startswith(("http://", "https://", "mailto:")):
        return target
    if (not clean and suffix.startswith("#")) or "assets/diagrams/" in clean:
        return target
    if clean.endswith("/"):
        sibling_page = f"{clean.rstrip('/')}.md"
        sibling_candidate = (repo_root / current_source.parent / sibling_page).resolve()
        try:
            sibling_canonical = sibling_candidate.relative_to(repo_root.resolve())
        except ValueError:
            sibling_canonical = Path()
        clean = sibling_page if sibling_canonical in source_map else f"{clean}index.md"
    elif not clean.endswith(".md"):
        return None

    candidate = (repo_root / current_source.parent / clean).resolve()
    try:
        canonical = candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if canonical not in source_map:
        return None

    mapped = source_map[canonical]
    if surface == "wiki":
        return f"wiki:{mapped.stem}{suffix}"
    rel = os.path.relpath(mapped, start=current_output.parent)
    return f"{rel.replace(os.sep, '/')}{suffix}"


def rewrite_for_surface(
    markdown: str,
    *,
    surface: str,
    current_source: Path,
    current_output: Path,
    source_map: dict[Path, Path],
    repo_root: Path | None = None,
) -> str:
    selected_root = (repo_root or Path.cwd()).resolve()

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
                repo_root=selected_root,
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
            repo_root=selected_root,
        )
        if mapped is None:
            return _bare_link(label, target, image=image)
        if mapped.startswith("wiki:"):
            return f"[[{label}|{mapped[5:]}]]"
        return f"{'!' if image else ''}[{label}]({mapped})"

    text = MARKDOWN_LINK_RE.sub(replace, markdown)

    def replace_html_href(match: re.Match[str]) -> str:
        target = html.unescape(match.group("target"))
        mapped = _mapped_target(
            target,
            current_source=current_source,
            current_output=current_output,
            source_map=source_map,
            surface=surface,
            repo_root=selected_root,
        )
        if mapped is None:
            return match.group(0)
        if mapped.startswith("wiki:"):
            mapped = mapped[5:]
        else:
            mapped_path, suffix = _split_url_bits(mapped)
            if mapped_path.endswith("/index.md"):
                mapped_path = mapped_path.removesuffix("index.md")
            elif mapped_path.endswith(".md"):
                mapped_path = f"{mapped_path.removesuffix('.md')}/"
            mapped = f"{mapped_path}{suffix}"
        return f'href="{mapped}"'

    text = HTML_HREF_RE.sub(replace_html_href, text)
    if surface == "wiki":
        text = ASSET_PREFIX_RE.sub(r"assets/diagrams/\g<asset>", text)
    return text
