from __future__ import annotations

import html
import os
import re
from pathlib import Path

from scripts.docs.links import (
    HtmlLinkAttribute,
    MarkdownLink,
    find_html_link_attributes,
    find_markdown_links,
    is_forbidden,
)
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


def _markdown_destination(target: str, *, angled: bool) -> str:
    if angled or any(character.isspace() or character in "()" for character in target):
        escaped = target.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>")
        return f"<{escaped}>"
    return target


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

    def markdown_form(link: MarkdownLink, target: str) -> str:
        destination = _markdown_destination(
            target,
            angled=link.angled_destination,
        )
        return f"{'!' if link.image else ''}[{link.label}]({destination}{link.title_suffix})"

    def wiki_alias_safe(link: MarkdownLink) -> bool:
        return not any(character in link.label for character in "]|\r\n")

    def rewrite_markdown_link(link: MarkdownLink) -> str:
        target = html.unescape(link.target)
        if not target:
            return markdown_form(link, target)
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
                return _bare_link(link.label, target, image=link.image)
            if surface == "wiki" and mapped.startswith("wiki:"):
                if link.title_suffix or not wiki_alias_safe(link):
                    return markdown_form(link, mapped[5:])
                return f"[[{link.label}|{mapped[5:]}]]"
            return markdown_form(link, mapped)

        mapped = _mapped_target(
            target,
            current_source=current_source,
            current_output=current_output,
            source_map=source_map,
            surface=surface,
            repo_root=selected_root,
        )
        if mapped is None:
            return _bare_link(link.label, target, image=link.image)
        if mapped.startswith("wiki:"):
            if link.title_suffix or not wiki_alias_safe(link):
                return markdown_form(link, mapped[5:])
            return f"[[{link.label}|{mapped[5:]}]]"
        return markdown_form(link, mapped)

    text = markdown
    for link in reversed(find_markdown_links(markdown)):
        replacement = rewrite_markdown_link(link)
        text = f"{text[: link.start]}{replacement}{text[link.end :]}"

    def replace_html_link_attribute(attribute: HtmlLinkAttribute) -> str:
        target = html.unescape(attribute.target)
        mapped = _mapped_target(
            target,
            current_source=current_source,
            current_output=current_output,
            source_map=source_map,
            surface=surface,
            repo_root=selected_root,
        )
        if mapped is None:
            return "" if is_forbidden(target, surface) else text[attribute.start : attribute.end]
        if mapped.startswith("wiki:"):
            mapped = mapped[5:]
        else:
            mapped_path, suffix = _split_url_bits(mapped)
            converted_page = False
            if mapped_path == "index.md" or mapped_path.endswith("/index.md"):
                mapped_path = mapped_path.removesuffix("index.md")
                converted_page = True
            elif mapped_path.endswith(".md"):
                mapped_path = f"{mapped_path.removesuffix('.md')}/"
                converted_page = True
            if converted_page and current_output.name != "index.md":
                # MkDocs serves non-index pages at directory URLs. Raw HTML hrefs
                # resolve in the browser from that extra page directory, unlike
                # Markdown links which MkDocs rewrites from the source file path.
                mapped_path = f"../{mapped_path}"
            mapped = f"{mapped_path}{suffix}"
        escaped = html.escape(mapped, quote=True)
        quote = attribute.quote or '"'
        return f"{attribute.attribute}{attribute.separator}{quote}{escaped}{quote}"

    for attribute in reversed(find_html_link_attributes(text)):
        replacement = replace_html_link_attribute(attribute)
        text = f"{text[: attribute.start]}{replacement}{text[attribute.end :]}"
    if surface == "wiki":
        text = ASSET_PREFIX_RE.sub(r"assets/diagrams/\g<asset>", text)
    return text
