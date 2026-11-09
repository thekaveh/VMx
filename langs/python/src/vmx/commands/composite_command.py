"""CompositeCommand — aggregates N inner commands.

See spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import reactivex as rx
from reactivex import Observable

from vmx.commands._disposal_signal import DisposalSignal
from vmx.commands.protocols import Command


class CompositeCommand:
    """Aggregates N inner commands.

    - ``can_execute()`` returns True iff at least one inner returns True.
    - ``execute()`` invokes every inner whose ``can_execute`` is True.
    - ``can_execute_changed`` fires when any inner's stream fires.
    """

    def __init__(self, *inner: Command) -> None:
        self._inner: Sequence[Command] = inner
        self._disposed = False
        self._disposal = DisposalSignal()
        merged: Observable[None] = (
            rx.never() if not inner else rx.merge(*(c.can_execute_changed for c in inner))
        )
        # One more notification at disposal (spec §8.4).
        self._can_execute_changed: Observable[None] = self._disposal.wrap(merged)

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._can_execute_changed

    def can_execute(self, parameter: Any = None) -> bool:
        if self._disposed:
            return False
        return any(c.can_execute(parameter) for c in self._inner) and not self._disposed

    def execute(self, parameter: Any = None) -> None:
        # A child may dispose the composite; no later child runs once disposal
        # is observed (spec §8.4, ADR-0134).
        for c in self._inner:
            if self._disposed:
                return
            if c.can_execute(parameter) and not self._disposed:
                c.execute(parameter)

    def dispose(self) -> None:
        """Make the composite inert (spec §8.4, ADR-0134). Idempotent.

        Notifies the composite's ``can_execute_changed`` subscribers once, so
        a binding re-reads ``can_execute``. The inner commands stay owned by
        their creator, and their own subscribers receive nothing. No internal
        subscriptions are held: ``can_execute_changed`` is a lazy
        ``rx.merge`` of the inner streams, which subscribers tear down when
        they unsubscribe.
        """
        if self._disposed:
            return
        self._disposed = True
        self._disposal.fire()
