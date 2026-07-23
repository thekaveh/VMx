from __future__ import annotations

import re
from dataclasses import dataclass

REPO_URL = "https://github.com/thekaveh/VMx"
WIKI_URL = "https://github.com/thekaveh/VMx/wiki"
SITE_URL = "https://thekaveh.github.io/VMx"

MARKDOWN_LINK_RE = re.compile(
    r"(?P<image>!)?\[(?P<label>[^\]\r\n]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
MARKDOWN_REFERENCE_LINK_RE = re.compile(
    r"^ {0,3}\[(?P<label>[^\]]+)\]:\s*(?P<target>\S+)", re.MULTILINE
)
HTML_TAG_RE = re.compile(
    r"""</?[A-Za-z][A-Za-z0-9:-]*"""
    r"""(?:\s+(?:"[^"]*"|'[^']*'|[^"'<>])*)?\s*/?>""",
    re.DOTALL,
)
HTML_LINK_ATTR_RE = re.compile(
    r"""(?P<attribute>(?<![-:\w])(?:href|src))(?P<separator>\s*=\s*)"""
    r"""(?:(?P<quote>["'])(?P<quoted_target>.*?)(?P=quote)"""
    r"""|(?P<unquoted_target>[^\s"'=<>`]+))""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Link:
    label: str
    target: str
    image: bool = False


@dataclass(frozen=True)
class HtmlLinkAttribute:
    start: int
    end: int
    attribute: str
    separator: str
    quote: str
    target: str


def _markdown_code_and_comment_mask(markdown: str) -> list[bool]:
    mask = [False] * len(markdown)
    offset = 0
    fence: tuple[str, int] | None = None
    for line in markdown.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        marker = re.match(r"(?P<marker>`{3,}|~{3,})", stripped)
        if fence is not None:
            mask[offset : offset + len(line)] = [True] * len(line)
            if (
                marker is not None
                and marker.group("marker")[0] == fence[0]
                and len(marker.group("marker")) >= fence[1]
                and not stripped[len(marker.group("marker")) :].strip()
            ):
                fence = None
        elif marker is not None:
            value = marker.group("marker")
            fence = (value[0], len(value))
            mask[offset : offset + len(line)] = [True] * len(line)
        elif line.startswith(("    ", "\t")):
            mask[offset : offset + len(line)] = [True] * len(line)
        offset += len(line)

    cursor = 0
    while cursor < len(markdown):
        if mask[cursor]:
            cursor += 1
            continue
        if markdown.startswith("<!--", cursor):
            end = markdown.find("-->", cursor + 4)
            end = len(markdown) if end < 0 else end + 3
            mask[cursor:end] = [True] * (end - cursor)
            cursor = end
            continue
        if markdown[cursor] == "`":
            end_of_run = cursor
            while end_of_run < len(markdown) and markdown[end_of_run] == "`":
                end_of_run += 1
            marker = markdown[cursor:end_of_run]
            close = markdown.find(marker, end_of_run)
            if close >= 0 and not any(mask[end_of_run:close]):
                end = close + len(marker)
                mask[cursor:end] = [True] * (end - cursor)
                cursor = end
                continue
        cursor += 1
    return mask


def find_html_link_attributes(markdown: str) -> list[HtmlLinkAttribute]:
    """Return link-bearing attributes from actual HTML tags outside Markdown code."""
    mask = _markdown_code_and_comment_mask(markdown)
    attributes: list[HtmlLinkAttribute] = []
    for tag in HTML_TAG_RE.finditer(markdown):
        if any(mask[tag.start() : tag.end()]):
            continue
        for match in HTML_LINK_ATTR_RE.finditer(tag.group(0)):
            quote = match.group("quote") or ""
            target = match.group("quoted_target")
            if target is None:
                target = match.group("unquoted_target")
            attributes.append(
                HtmlLinkAttribute(
                    start=tag.start() + match.start(),
                    end=tag.start() + match.end(),
                    attribute=match.group("attribute"),
                    separator=match.group("separator"),
                    quote=quote,
                    target=target,
                )
            )
    return attributes


def find_links(markdown: str) -> list[Link]:
    links = [
        Link(match.group("label"), match.group("target"), bool(match.group("image")))
        for match in MARKDOWN_LINK_RE.finditer(markdown)
    ]
    links.extend(
        Link(match.group("label"), match.group("target"))
        for match in MARKDOWN_REFERENCE_LINK_RE.finditer(markdown)
    )
    return links


def is_forbidden(target: str, surface: str) -> bool:
    normalized = target.rstrip("/")
    if surface == "site":
        return normalized.startswith(REPO_URL) or normalized.startswith(WIKI_URL)
    if surface == "wiki":
        return normalized.startswith(SITE_URL) or normalized.startswith(REPO_URL)
    if surface == "repo":
        return normalized.startswith(SITE_URL) or normalized.startswith(WIKI_URL)
    raise ValueError(f"unknown surface: {surface}")
