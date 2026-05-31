"""NotebookModel — pure-data record for a notebook node."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotebookModel:
    """Immutable notebook record.

    ``parent_id`` is ``None`` for root notebooks. Identifiers are stable
    strings (mirrors the C# / TS flavors so cross-language parity audits
    compare identically).
    """

    id: str
    name: str
    parent_id: str | None
