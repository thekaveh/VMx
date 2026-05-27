"""CompositeCommand — aggregates N inner commands.

See spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import reactivex as rx
from reactivex import Observable

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
        self._can_execute_changed: Observable[None]
        if not inner:
            self._can_execute_changed = rx.never()
        else:
            self._can_execute_changed = rx.merge(*(c.can_execute_changed for c in inner))

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._can_execute_changed

    def can_execute(self, parameter: Any = None) -> bool:
        return any(c.can_execute(parameter) for c in self._inner)

    def execute(self, parameter: Any = None) -> None:
        for c in self._inner:
            if c.can_execute(parameter):
                c.execute(parameter)

    def dispose(self) -> None:
        """Mark the composite as disposed. Idempotent.

        No internal subscriptions are held: ``can_execute_changed`` is a
        lazy ``rx.merge`` of the inner streams. Subscribers' own
        disposables tear down the merged subscription chain when they
        unsubscribe; the composite itself owns nothing to release.
        Provided for API symmetry with the C# IDisposable surface.
        """
        self._disposed = True
