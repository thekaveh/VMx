from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Opener:
    tagline: str
    summary: str
    poster_source: Path
    poster_alt: str


def _required_text(data: object, key: str, *, context: str) -> str:
    if not isinstance(data, dict) or not isinstance(data.get(key), str):
        raise ValueError(f"{context}: '{key}' must be a non-empty string")
    value = data[key].strip()
    if not value:
        raise ValueError(f"{context}: '{key}' must be a non-empty string")
    return value


def load_opener(path: Path, repo_root: Path) -> Opener:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"{path}: unable to load opener contract: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path}: opener contract must be a mapping")

    tagline = _required_text(data, "tagline", context=str(path))
    summary = " ".join(_required_text(data, "summary", context=str(path)).split())
    word_count = len(summary.split())
    if not 100 <= word_count <= 150:
        raise ValueError(f"{path}: summary must contain 100-150 words; found {word_count}")

    poster = data.get("poster")
    poster_source = Path(_required_text(poster, "source", context=f"{path}: poster"))
    poster_alt = _required_text(poster, "alt", context=f"{path}: poster")
    if poster_source.is_absolute() or ".." in poster_source.parts:
        raise ValueError(f"{path}: poster source must be repository-relative")
    if not (repo_root / poster_source).is_file():
        raise ValueError(f"{path}: poster source does not exist: {poster_source}")

    return Opener(tagline, summary, poster_source, poster_alt)
