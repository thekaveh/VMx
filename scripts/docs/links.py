from __future__ import annotations

import re
from dataclasses import dataclass

REPO_URL = "https://github.com/thekaveh/VMx"
WIKI_URL = "https://github.com/thekaveh/VMx/wiki"
SITE_URL = "https://thekaveh.github.io/VMx"

MARKDOWN_LINK_RE = re.compile(
    r"(?P<image>!)?\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
MARKDOWN_REFERENCE_LINK_RE = re.compile(
    r"^ {0,3}\[(?P<label>[^\]]+)\]:\s*(?P<target>\S+)", re.MULTILINE
)


@dataclass(frozen=True)
class Link:
    label: str
    target: str
    image: bool = False


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
