from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    """Raised when the documentation manifest is invalid."""


@dataclass(frozen=True)
class Section:
    id: str
    number: str
    title: str
    source: Path | None = None
    children: tuple[Section, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"{self.number}. {self.title}"


@dataclass(frozen=True)
class Manifest:
    surfaces: tuple[str, ...]
    numbering: str
    sections: tuple[Section, ...]

    def pages(self) -> list[Section]:
        return [section for section in walk_sections(self.sections) if section.source is not None]


def walk_sections(sections: tuple[Section, ...]) -> list[Section]:
    items: list[Section] = []
    for section in sections:
        items.append(section)
        items.extend(walk_sections(section.children))
    return items


def _parse_section(raw: dict[str, Any], context: str) -> Section:
    try:
        section_id = str(raw["id"])
        number = str(raw["number"])
        title = str(raw["title"])
    except KeyError as exc:
        raise ManifestError(f"{context}: missing required key {exc.args[0]!r}") from exc

    source = Path(str(raw["source"])) if "source" in raw else None
    children_raw = raw.get("children", [])
    if source is not None and children_raw:
        raise ManifestError(
            f"{context}: section must be a source leaf or a children group, not both"
        )
    if source is None and not children_raw:
        raise ManifestError(f"{context}: section must define source or children")
    if not isinstance(children_raw, list):
        raise ManifestError(f"{context}.children: expected list")
    children = tuple(
        _parse_section(child, f"{context}.children[{index}]")
        for index, child in enumerate(children_raw)
    )
    return Section(section_id, number, title, source, children)


def parse_manifest(text: str) -> Manifest:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be a mapping")
    try:
        surfaces = tuple(str(item) for item in raw["surfaces"])
        numbering = str(raw["numbering"])
        sections_raw = raw["sections"]
    except KeyError as exc:
        raise ManifestError(f"missing required key {exc.args[0]!r}") from exc
    if surfaces != ("repo", "site", "wiki"):
        raise ManifestError("surfaces must be exactly: repo, site, wiki")
    if numbering != "baked":
        raise ManifestError("numbering must be baked")
    if not isinstance(sections_raw, list):
        raise ManifestError("sections must be a list")
    sections = tuple(
        _parse_section(section, f"sections[{index}]") for index, section in enumerate(sections_raw)
    )
    return Manifest(surfaces, numbering, sections)


def load_manifest(path: Path, repo_root: Path | None = None) -> Manifest:
    manifest = parse_manifest(path.read_text(encoding="utf-8"))
    root = repo_root or path.parent.parent
    seen_ids: set[str] = set()
    seen_sources: set[Path] = set()
    for section in walk_sections(manifest.sections):
        if section.id in seen_ids:
            raise ManifestError(f"duplicate section id: {section.id}")
        seen_ids.add(section.id)
        if section.source is None:
            continue
        source = root / section.source
        if not source.exists():
            raise ManifestError(f"{section.id}: missing source {section.source}")
        if section.source in seen_sources:
            raise ManifestError(f"duplicate source: {section.source}")
        seen_sources.add(section.source)
    return manifest
