from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

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
HTML_RAW_TEXT_RE = re.compile(
    r"""<(?P<tag>script|style|pre|textarea|title|xmp|iframe|noembed|noframes)\b"""
    r"""(?:\s+(?:"[^"]*"|'[^']*'|[^"'<>])*)?\s*>"""
    r"""(?P<body>.*?)</(?P=tag)\s*>""",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Link:
    label: str
    target: str
    image: bool = False


@dataclass(frozen=True)
class MarkdownLink:
    start: int
    end: int
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
    lines = markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type not in {"fence", "code_block"} or token.map is None:
            continue
        start, end = token.map
        mask[offsets[start] : offsets[end]] = [True] * (offsets[end] - offsets[start])

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

    for raw_text in HTML_RAW_TEXT_RE.finditer(markdown):
        if any(mask[raw_text.start() : raw_text.start("body")]):
            continue
        start, end = raw_text.span("body")
        mask[start:end] = [True] * (end - start)
    return mask


def _masked_markdown(markdown: str) -> str:
    mask = _markdown_code_and_comment_mask(markdown)
    return "".join(
        "\n" if character == "\n" else " " if masked else character
        for character, masked in zip(markdown, mask, strict=True)
    )


def find_markdown_links(markdown: str) -> list[MarkdownLink]:
    """Return inline Markdown links outside code, comments, and raw-text HTML."""
    return [
        MarkdownLink(
            start=match.start(),
            end=match.end(),
            label=match.group("label"),
            target=match.group("target"),
            image=bool(match.group("image")),
        )
        for match in MARKDOWN_LINK_RE.finditer(_masked_markdown(markdown))
    ]


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
    links = [Link(link.label, link.target, link.image) for link in find_markdown_links(markdown)]
    links.extend(
        Link(match.group("label"), match.group("target"))
        for match in MARKDOWN_REFERENCE_LINK_RE.finditer(_masked_markdown(markdown))
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
