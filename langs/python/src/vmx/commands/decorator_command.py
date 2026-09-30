"""DecoratorCommand — wraps a single inner command with pre/post + extra predicate.

See spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reactivex import Observable

from vmx.commands.protocols import Command


class DecoratorCommand:
    """Wraps a single inner command with optional pre/post actions and a
    can-execute gate."""

    def __init__(
        self,
        inner: Command,
        pre_execute: Callable[[], None] | None = None,
        post_execute: Callable[[], None] | None = None,
        extra_predicate: Callable[[], bool] | None = None,
    ) -> None:
        self._inner = inner
        self._pre = pre_execute
        self._post = post_execute
        self._extra = extra_predicate
        self._disposed = False

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._inner.can_execute_changed

    def can_execute(self, parameter: Any = None) -> bool:
        if self._disposed or not self._inner.can_execute(parameter):
            return False
        if self._extra is None:
            return not self._disposed
        try:
            allowed = self._extra()
        except Exception:
            return False
        # The extra predicate may dispose the decorator.
        return allowed and not self._disposed

    def execute(self, parameter: Any = None) -> None:
        if not self.can_execute(parameter):
            return
        if self._pre is not None:
            self._pre()
        try:
            # The pre-action may dispose the decorator: skip the inner command
            # but keep the admitted pre/post pair balanced (spec §8.4).
            if not self._disposed:
                self._inner.execute(parameter)
        finally:
            # post runs whether or not the inner raised, so that a "busy"
            # flag set in pre_execute always gets cleared.
            if self._post is not None:
                self._post()

    def dispose(self) -> None:
        """Make the decorator inert (spec §8.4, ADR-0134). Idempotent.

        The inner command stays owned by its creator. ``can_execute_changed``
        delegates lazily to the inner command, so the decorator owns no
        subscriptions to release.
        """
        self._disposed = True
