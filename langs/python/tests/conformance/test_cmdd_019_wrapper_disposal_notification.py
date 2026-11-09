"""CMDD-019 — a wrapper command notifies its own subscribers once at disposal (#1459).

Disposing a live ``CompositeCommand``, ``DecoratorCommand`` or
``ConfirmationDecoratorCommand`` sends exactly one ``can_execute_changed``
notification to the wrapper's subscribers. A second ``dispose()`` sends
nothing, and a subscriber of the inner command receives nothing. Per
spec/04-commands.md §8.4 and ADR-0222.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.commands import (
    AsyncRelayCommand,
    CompositeCommand,
    ConfirmationDecoratorCommand,
    DecoratorCommand,
    RelayCommand,
)
from vmx.commands.protocols import Command


async def _confirm() -> bool:
    return True


async def _noop() -> None:
    return None


_WRAPPERS: list[
    tuple[
        str, Callable[[Command], CompositeCommand | DecoratorCommand | ConfirmationDecoratorCommand]
    ]
] = [
    ("composite", lambda inner: CompositeCommand(inner)),
    ("decorator", lambda inner: DecoratorCommand(inner)),
    ("confirmation", lambda inner: ConfirmationDecoratorCommand(inner, _confirm)),
]


@pytest.mark.conformance("CMDD-019")
@pytest.mark.parametrize("wrap", [w[1] for w in _WRAPPERS], ids=[w[0] for w in _WRAPPERS])
def test_wrapper_disposal_notifies_wrapper_subscribers_once(
    wrap: Callable[[Command], CompositeCommand | DecoratorCommand | ConfirmationDecoratorCommand],
) -> None:
    inner = RelayCommand.builder().task(lambda: None).build()
    wrapper = wrap(inner)
    wrapper_seen: list[None] = []
    inner_seen: list[None] = []
    wrapper.can_execute_changed.subscribe(wrapper_seen.append)
    inner.can_execute_changed.subscribe(inner_seen.append)

    wrapper.dispose()
    wrapper.dispose()

    assert len(wrapper_seen) == 1
    assert inner_seen == []
    assert wrapper.can_execute() is False


@pytest.mark.conformance("CMDD-019")
@pytest.mark.parametrize("wrap", [w[1] for w in _WRAPPERS], ids=[w[0] for w in _WRAPPERS])
def test_wrapper_stream_passes_the_inner_completion_through(
    wrap: Callable[[Command], CompositeCommand | DecoratorCommand | ConfirmationDecoratorCommand],
) -> None:
    inner = AsyncRelayCommand.builder().task(_noop).build()
    wrapper = wrap(inner)
    seen: list[None] = []
    completed: list[bool] = []
    wrapper.can_execute_changed.subscribe(
        on_next=seen.append, on_completed=lambda: completed.append(True)
    )

    inner.dispose()

    assert completed == [True]
    wrapper.dispose()
