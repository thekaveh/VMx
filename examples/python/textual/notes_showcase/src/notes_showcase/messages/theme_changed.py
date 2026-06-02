"""ThemeChangedMessage — emitted whenever ``ThemeVM`` adopts a new model.

Modelled on :class:`vmx.messages.PropertyChangedMessage` (same immutable-
dataclass / ``sender_object`` protocol shape) but carries both the prior and
the freshly-adopted :class:`~notes_showcase.models.theme_model.ThemeModel` so
adapters can diff without re-querying the VM.

See ``spec/proposals/2026-06-02-theme-vm-scenario.md`` §4 (``ThemeChanged``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from notes_showcase.models.theme_model import ThemeModel

TSender = TypeVar("TSender")


@dataclass(frozen=True, slots=True)
class ThemeChangedMessage(Generic[TSender]):
    """Immutable message published after a successful theme transition.

    Parameters
    ----------
    sender:
        Strongly-typed sender — typically the :class:`ThemeVM` instance.
    sender_name:
        Human-readable sender identifier (typically ``sender.name``).
    prev_theme:
        The model the VM held *before* the transition.
    curr_theme:
        The model the VM holds *after* the transition.
    """

    sender: TSender
    sender_name: str
    prev_theme: ThemeModel
    curr_theme: ThemeModel

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender

    @classmethod
    def create(
        cls,
        sender: TSender,
        sender_name: str,
        prev_theme: ThemeModel,
        curr_theme: ThemeModel,
    ) -> ThemeChangedMessage[TSender]:
        """Factory method — equivalent to direct construction."""
        return cls(
            sender=sender,
            sender_name=sender_name,
            prev_theme=prev_theme,
            curr_theme=curr_theme,
        )
