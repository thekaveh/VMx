"""NotebookModel — pure-data record for a notebook node."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotebookModel:
    """Immutable notebook record.

    ``parent_id`` is ``None`` for root notebooks. Identifiers are stable
    strings (mirrors the C# / TS flavors so cross-language parity audits
    compare identically).

    ``is_readonly`` (default ``False``) marks a notebook whose notes cannot
    be created or edited via the UI. When the currently-bound notebook is
    readonly :class:`CapabilityActionsVM` disables the *Add Note* action.
    """

    id: str
    name: str
    parent_id: str | None
    is_readonly: bool = False
