from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.common.html_re import HTML_TAG_RE as COMMONMARK_HTML_TAG_RE

AUTOLINK_RE = re.compile(
    r"<(?P<target>"
    r"[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*"
    r"|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    r")>"
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
    r"""<(?P<tag>script|style|textarea|title|xmp|iframe|noembed|noframes)\b"""
    r"""(?:\s+(?:"[^"]*"|'[^']*'|[^"'<>])*)?\s*>"""
    r"""(?P<body>.*?)</(?P=tag)\s*>""",
    re.IGNORECASE | re.DOTALL,
)
COMMONMARK_HTML_INLINE_RE = re.compile(
    COMMONMARK_HTML_TAG_RE.pattern.removeprefix("^"),
    COMMONMARK_HTML_TAG_RE.flags,
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
    title_suffix: str = ""
    angled_destination: bool = False


@dataclass(frozen=True)
class HtmlLinkAttribute:
    start: int
    end: int
    attribute: str
    separator: str
    quote: str
    target: str


def _is_backslash_escaped(text: str, index: int) -> bool:
    backslashes = 0
    while index > 0 and text[index - 1] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _closure_lookaheads(text: str) -> tuple[dict[str, list[bool]], list[bool]]:
    escaped = [False] * len(text)
    index = 0
    while index + 1 < len(text):
        if text[index] == "\\":
            escaped[index + 1] = True
            index += 2
        else:
            index += 1

    paragraph_breaks = {match.end() for match in re.finditer(r"\n[ \t]*\n", text)}
    paragraph_ids: list[int] = []
    paragraph = 0
    for index in range(len(text)):
        if index in paragraph_breaks:
            paragraph += 1
        paragraph_ids.append(paragraph)

    next_nonspace = [len(text)] * len(text)
    following = len(text)
    for index in range(len(text) - 1, -1, -1):
        next_nonspace[index] = following
        if not text[index].isspace():
            following = index

    quote_ahead: dict[str, list[bool]] = {}
    for quote in ('"', "'"):
        ahead = [False] * (len(text) + 1)
        first_closes_by_paragraph: dict[int, bool] = {}
        for index in range(len(text) - 1, -1, -1):
            paragraph = paragraph_ids[index]
            ahead[index] = first_closes_by_paragraph.get(paragraph, False)
            after = next_nonspace[index]
            if text[index] == quote and not escaped[index]:
                first_closes_by_paragraph[paragraph] = (
                    after < len(text) and paragraph_ids[after] == paragraph and text[after] == ")"
                )
        quote_ahead[quote] = ahead

    angle_ahead = [False] * (len(text) + 1)
    found = False
    for index in range(len(text) - 1, -1, -1):
        if text[index] in {"\n", "<"} and not escaped[index]:
            found = False
        elif text[index] == ">" and not escaped[index]:
            found = True
        angle_ahead[index] = found
    return quote_ahead, angle_ahead


def _balanced_pairs(
    text: str,
    *,
    opener: str,
    closer: str,
    markdown_parentheses: bool = False,
    candidate_openers: set[int] | None = None,
) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    quote: str | None = None
    quote_closes = False
    angled = False
    angle_closes = False
    quote_lookahead: dict[str, list[bool]] = {}
    angle_lookahead: list[bool] = []
    if markdown_parentheses:
        quote_lookahead, angle_lookahead = _closure_lookaheads(text)
    index = 0
    while index < len(text):
        character = text[index]
        if (
            markdown_parentheses
            and stack
            and candidate_openers is not None
            and index in candidate_openers
            and ((quote is not None and not quote_closes) or (angled and not angle_closes))
        ):
            stack.clear()
            quote = None
            quote_closes = False
            angled = False
            angle_closes = False
        if markdown_parentheses and stack and character == "\n":
            next_content = index + 1
            while next_content < len(text) and text[next_content] in " \t":
                next_content += 1
            blank_line = next_content < len(text) and text[next_content] == "\n"
            invalid_multiline_state = angled or (quote is not None and not quote_closes)
            if blank_line or invalid_multiline_state:
                stack.clear()
                quote = None
                quote_closes = False
                angled = False
                angle_closes = False
        if character == "\\":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
                quote_closes = False
            index += 1
            continue
        if angled:
            if character == ">":
                angled = False
                angle_closes = False
            index += 1
            continue
        if (
            markdown_parentheses
            and stack
            and character in {'"', "'"}
            and index > 0
            and text[index - 1].isspace()
        ):
            quote = character
            quote_closes = quote_lookahead[quote][index + 1]
        elif markdown_parentheses and stack and character == "<":
            angled = True
            angle_closes = angle_lookahead[index + 1]
        elif character == opener and (
            not markdown_parentheses
            or stack
            or candidate_openers is None
            or index in candidate_openers
        ):
            stack.append(index)
        elif character == closer and stack:
            pairs[stack.pop()] = index
        index += 1
    return pairs


def _destination_parts(
    markdown: str,
    open_paren: int,
    close_paren: int,
) -> tuple[str, str, bool] | None:
    index = open_paren + 1
    while index < close_paren and markdown[index].isspace():
        index += 1
    if index >= close_paren:
        return "", markdown[index:close_paren], False

    angled = markdown[index] == "<"
    if angled:
        destination_start = index + 1
        destination_end = destination_start
        while destination_end < close_paren:
            if markdown[destination_end] == "\\":
                destination_end += 2
                continue
            if markdown[destination_end] == ">":
                break
            destination_end += 1
        if destination_end >= close_paren:
            return None
        suffix_start = destination_end + 1
    else:
        destination_start = index
        destination_end = index
        depth = 0
        while destination_end < close_paren:
            character = markdown[destination_end]
            if character == "\\":
                destination_end += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            elif character.isspace() and depth == 0:
                break
            destination_end += 1
        suffix_start = destination_end

    raw_target = markdown[destination_start:destination_end]
    target = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", raw_target)
    return target, markdown[suffix_start:close_paren], angled


def _is_single_commonmark_link(fragment: str, *, image: bool) -> bool:
    parsed = MarkdownIt("commonmark").parseInline(fragment)
    if len(parsed) != 1 or parsed[0].children is None:
        return False
    children = parsed[0].children
    if image:
        return len(children) == 1 and children[0].type == "image"
    return (
        len(children) >= 2 and children[0].type == "link_open" and children[-1].type == "link_close"
    )


def _commonmark_autolink_target(fragment: str) -> str | None:
    parsed = MarkdownIt("commonmark").parseInline(fragment)
    if len(parsed) != 1 or parsed[0].children is None:
        return None
    children = parsed[0].children
    if (
        len(children) != 3
        or children[0].type != "link_open"
        or children[1].type != "text"
        or children[2].type != "link_close"
        or children[0].markup != "autolink"
    ):
        return None
    return children[0].attrGet("href")


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

    html_inline_mask = [False] * len(markdown)
    inline_html_matches: list[re.Match[str]] = []
    for candidate in re.finditer("<", markdown):
        if mask[candidate.start()] or _is_backslash_escaped(markdown, candidate.start()):
            continue
        inline_html = COMMONMARK_HTML_INLINE_RE.match(markdown, candidate.start())
        if inline_html is None:
            continue
        inline_html_matches.append(inline_html)
        start, end = inline_html.span()
        html_inline_mask[start:end] = [True] * (end - start)

    cursor = 0
    while cursor < len(markdown):
        if mask[cursor] or html_inline_mask[cursor]:
            cursor += 1
            continue
        if markdown[cursor] == "`":
            if _is_backslash_escaped(markdown, cursor):
                cursor += 1
                continue
            end_of_run = cursor
            while end_of_run < len(markdown) and markdown[end_of_run] == "`":
                end_of_run += 1
            marker = markdown[cursor:end_of_run]
            close = end_of_run
            while (close := markdown.find(marker, close)) >= 0:
                if (
                    (close == 0 or markdown[close - 1] != "`")
                    and (
                        close + len(marker) == len(markdown) or markdown[close + len(marker)] != "`"
                    )
                    and not any(mask[end_of_run:close])
                ):
                    break
                close += 1
            if close >= 0:
                end = close + len(marker)
                mask[cursor:end] = [True] * (end - cursor)
                cursor = end
                continue
            cursor = end_of_run
            continue
        cursor += 1

    for inline_html in inline_html_matches:
        if not inline_html.group(0).startswith("<!--"):
            continue
        start, end = inline_html.span()
        if mask[start]:
            continue
        mask[start:end] = [True] * (end - start)

    for raw_text in HTML_RAW_TEXT_RE.finditer(markdown):
        if _is_backslash_escaped(markdown, raw_text.start()) or any(
            mask[raw_text.start() : raw_text.start("body")]
        ):
            continue
        start, end = raw_text.span("body")
        mask[start:end] = [True] * (end - start)
    return mask


def _masked_markdown(markdown: str, *, html: bool = False) -> str:
    mask = _markdown_code_and_comment_mask(markdown)
    if html:
        lines = markdown.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        for token in MarkdownIt("commonmark").parse(markdown):
            if token.type != "html_block" or token.map is None:
                continue
            start, end = token.map
            mask[offsets[start] : offsets[end]] = [True] * (offsets[end] - offsets[start])
        for candidate in re.finditer("<", markdown):
            if mask[candidate.start()] or _is_backslash_escaped(markdown, candidate.start()):
                continue
            inline_html = COMMONMARK_HTML_INLINE_RE.match(markdown, candidate.start())
            if inline_html is None:
                continue
            start, end = inline_html.span()
            mask[start:end] = [True] * (end - start)
    return "".join(
        "\n" if character == "\n" else " " if masked else character
        for character, masked in zip(markdown, mask, strict=True)
    )


def find_markdown_links(markdown: str) -> list[MarkdownLink]:
    """Return inline Markdown links outside code, comments, and raw-text HTML."""
    masked = _masked_markdown(markdown, html=True)
    label_ends = _balanced_pairs(masked, opener="[", closer="]")
    candidate_openers = {
        label_end + 1
        for label_end in label_ends.values()
        if label_end + 1 < len(masked) and masked[label_end + 1] == "("
    }
    destination_ends = _balanced_pairs(
        masked,
        opener="(",
        closer=")",
        markdown_parentheses=True,
        candidate_openers=candidate_openers,
    )

    links: list[MarkdownLink] = []
    cursor = 0
    while cursor < len(masked):
        bracket = masked.find("[", cursor)
        if bracket < 0:
            break
        cursor = bracket + 1
        if _is_backslash_escaped(masked, bracket):
            continue

        label_end = label_ends.get(bracket)
        if label_end is None or label_end + 1 >= len(masked) or masked[label_end + 1] != "(":
            continue
        # CommonMark limits link labels to 999 characters. Besides enforcing
        # that contract, this bounds validation work for adversarial nesting.
        if label_end - bracket - 1 > 999:
            continue
        close_paren = destination_ends.get(label_end + 1)
        if close_paren is None:
            continue

        image_marker = bracket - 1
        image = image_marker >= 0 and masked[image_marker] == "!"
        if image and _is_backslash_escaped(masked, image_marker):
            image = False
        start = image_marker if image else bracket
        end = close_paren + 1
        fragment = markdown[start:end]
        if not _is_single_commonmark_link(fragment, image=image):
            continue
        destination = _destination_parts(markdown, label_end + 1, close_paren)
        if destination is None:
            continue
        target, title_suffix, angled_destination = destination
        links.append(
            MarkdownLink(
                start=start,
                end=end,
                label=markdown[bracket + 1 : label_end],
                target=target,
                image=image,
                title_suffix=title_suffix,
                angled_destination=angled_destination,
            )
        )
        cursor = end
    return links


def find_html_link_attributes(markdown: str) -> list[HtmlLinkAttribute]:
    """Return link-bearing attributes from actual HTML tags outside Markdown code."""
    mask = _markdown_code_and_comment_mask(markdown)
    attributes: list[HtmlLinkAttribute] = []
    for tag in HTML_TAG_RE.finditer(markdown):
        if _is_backslash_escaped(markdown, tag.start()) or any(mask[tag.start() : tag.end()]):
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
    masked = _masked_markdown(markdown, html=True)
    links.extend(find_reference_links(markdown))
    for match in AUTOLINK_RE.finditer(masked):
        if _is_backslash_escaped(masked, match.start()):
            continue
        target = _commonmark_autolink_target(markdown[match.start() : match.end()])
        if target is not None:
            links.append(Link(match.group("target"), target))
    return links


def find_reference_links(markdown: str) -> list[Link]:
    """Return CommonMark reference definitions, including container-nested ones."""
    if not any("[" in line and "]:" in line for line in markdown.splitlines()):
        return []
    environment: dict[str, object] = {}
    MarkdownIt("commonmark").parse(markdown, environment)
    references = environment.get("references")
    if not isinstance(references, dict):
        return []

    links: list[Link] = []
    for label, definition in references.items():
        if not isinstance(label, str) or not isinstance(definition, dict):
            continue
        target = definition.get("href")
        if isinstance(target, str):
            links.append(Link(label, target))
    return links


def _normalized_http_target(target: str) -> tuple[str, str] | None:
    decoded = html.unescape(target.strip())
    for _ in range(3):
        unquoted = unquote(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    parsed = urlsplit(decoded)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        return None
    return parsed.hostname.lower(), parsed.path.rstrip("/")


def _path_is_at_or_below(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def is_forbidden(target: str, surface: str) -> bool:
    normalized = _normalized_http_target(target)
    if normalized is None:
        return False
    host, path = normalized
    is_repo = host == "github.com" and _path_is_at_or_below(path, "/thekaveh/VMx")
    is_wiki = host == "github.com" and _path_is_at_or_below(path, "/thekaveh/VMx/wiki")
    is_site = host == "thekaveh.github.io" and _path_is_at_or_below(path, "/VMx")
    if surface == "site":
        return is_repo
    if surface == "wiki":
        return is_site or is_repo
    if surface == "repo":
        return is_site or is_wiki
    raise ValueError(f"unknown surface: {surface}")
