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

DIAGRAMS_SOURCE = Path("docs/assets/diagrams")
DIAGRAMS_OUTPUT = Path("assets/diagrams")
DIAGRAM_ASSET_SUFFIXES = (".html", ".svg", ".png", ".json")
TAB_RE = re.compile(r'^===\+? "(?P<label>[^"]*)"\s*$')
FENCE_OPEN_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")


def wiki_name(section: Section) -> str:
    if section.source and section.source.name == "index.md" and section.number == "1":
        return "Home.md"
    safe = re.sub(r"[^A-Za-z0-9]+", "-", section.label).strip("-")
    return f"{safe}.md"


def _closes_fence(line: str, fence: str) -> bool:
    stripped = line.strip()
    indent = len(line) - len(line.lstrip(" "))
    return indent <= 3 and len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def _dedent_panel_line(line: str) -> str:
    if not line.strip():
        return ""
    return line[1:] if line.startswith("\t") else line[4:]


def adapt_tabs_for_wiki(markdown: str) -> str:
    """Render MkDocs content tabs as native details blocks with dedented panels.

    GitHub's wiki has no tab syntax: it would print each ``=== "Label"`` line as
    text and its four-space-indented panel as a code block, with the panel's
    fences and links shown literally. Each panel becomes a ``<details>`` block;
    the first of a group is open, as the first MkDocs tab is selected.
    """
    lines = markdown.split("\n")
    output: list[str] = []
    fence: str | None = None
    in_tab_group = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if fence is not None:
            output.append(line)
            if _closes_fence(line, fence):
                fence = None
            index += 1
            continue
        opening = FENCE_OPEN_RE.match(line)
        tab = TAB_RE.match(line)
        if tab is None:
            if opening is not None:
                fence = opening.group("fence")
            if line.strip():
                in_tab_group = False
            output.append(line)
            index += 1
            continue
        end = index + 1
        while end < len(lines) and (
            not lines[end].strip() or lines[end].startswith(("    ", "\t"))
        ):
            end += 1
        while end > index + 1 and not lines[end - 1].strip():
            end -= 1
        panel = "\n".join(_dedent_panel_line(item) for item in lines[index + 1 : end])
        output.extend(
            (
                "<details>" if in_tab_group else "<details open>",
                f"<summary>{html.escape(tab.group('label'), quote=False)}</summary>",
                "",
                *adapt_tabs_for_wiki(panel.strip("\n")).split("\n"),
                "",
                "</details>",
            )
        )
        in_tab_group = True
        index = end
    return "\n".join(output)


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


def _projected_asset(clean: str, *, current_source: Path, repo_root: Path) -> Path | None:
    """Return where a canonical asset target lands in a generated surface.

    The target is resolved lexically, as GitHub resolves it, so a symlinked
    directory cannot make a path that is broken on GitHub look valid here.
    """
    canonical = Path(os.path.normpath(current_source.parent / clean))
    if canonical.is_absolute() or canonical.parts[:1] == ("..",):
        return None
    if not (repo_root / canonical).is_file():
        return None
    if canonical.parent == DIAGRAMS_SOURCE and canonical.suffix in DIAGRAM_ASSET_SUFFIXES:
        return DIAGRAMS_OUTPUT / canonical.name
    if canonical.parts[:1] == ("assets",):
        return canonical
    return None


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
    if not clean and suffix.startswith("#"):
        return target
    if asset := _projected_asset(clean, current_source=current_source, repo_root=repo_root):
        rel = os.path.relpath(asset, start=current_output.parent)
        return f"{rel.replace(os.sep, '/')}{suffix}"
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
    if surface == "wiki":
        markdown = adapt_tabs_for_wiki(markdown)

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
            asset = (
                surface == "site"
                and _projected_asset(
                    _strip_url_bits(target), current_source=current_source, repo_root=selected_root
                )
                is not None
            )
            if (converted_page or asset) and current_output.name != "index.md":
                # MkDocs serves non-index pages at directory URLs. Raw HTML hrefs
                # and srcs resolve in the browser from that extra page directory,
                # unlike Markdown links which MkDocs rewrites from the source file.
                mapped_path = f"../{mapped_path}"
            mapped = f"{mapped_path}{suffix}"
        escaped = html.escape(mapped, quote=True)
        quote = attribute.quote or '"'
        return f"{attribute.attribute}{attribute.separator}{quote}{escaped}{quote}"

    for attribute in reversed(find_html_link_attributes(text)):
        replacement = replace_html_link_attribute(attribute)
        text = f"{text[: attribute.start]}{replacement}{text[attribute.end :]}"
    return text
