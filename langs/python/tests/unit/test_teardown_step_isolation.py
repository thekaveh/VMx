"""#449 regression — teardown runs every step when one of them raises.

``SearchableState``, ``TokenPagedComposition``, ``FilteredCompositeVM``,
``NotificationVM``, ``ConfirmationVM``, and ``DerivedProperty`` follow the shared
``_run_disposal_steps`` convention already used by ``FormVM`` and the component
base: every owned teardown step runs, the first failure is re-raised, and a
second ``dispose()`` is a no-op. Flavor-local repair; no new conformance ID.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any, NamedTuple

import pytest
from reactivex.subject import Subject
from reactivex.testing import TestScheduler

from vmx.capabilities.searchable_state import SearchableState
from vmx.collections.token_paged_composition import TokenPagedComposition
from vmx.components.component_vm import ComponentVM
from vmx.composites.composite_vm import CompositeVM
from vmx.composites.filtered_composite_vm import FilteredCompositeVM
from vmx.notifications import (
    ConfirmationVM,
    Notification,
    NotificationHub,
    NotificationType,
    NotificationVM,
)
from vmx.properties import DerivedProperty
from vmx.services.null_dispatcher import NULL_DISPATCHER
from vmx.services.null_message_hub import NULL_MESSAGE_HUB


class _Case(NamedTuple):
    name: str
    build: Callable[[], Any]
    steps: tuple[tuple[str, str], ...]


def _searchable_state() -> SearchableState[str]:
    return SearchableState(
        items=lambda: ["a"], predicate=lambda item, term: True, debounce_seconds=0
    )


def _token_paged_composition() -> TokenPagedComposition[int, str]:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([], None)

    return TokenPagedComposition(fetch_next=fetch)


def _filtered_composite_vm() -> FilteredCompositeVM[ComponentVM]:
    source: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("source")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: [])
        .build()
    )
    return FilteredCompositeVM(source)


def _notification_args() -> tuple[Notification, NotificationHub, TestScheduler]:
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "note")
    hub.post(notification)
    return notification, hub, TestScheduler()


def _notification_vm() -> NotificationVM:
    notification, hub, scheduler = _notification_args()
    return NotificationVM(
        notification,
        hub,
        scheduler,
        lifespan=timedelta(seconds=10),
        tick_interval=timedelta(seconds=1),
    )


def _confirmation_vm() -> ConfirmationVM:
    notification, hub, scheduler = _notification_args()
    return ConfirmationVM(
        notification,
        hub,
        scheduler,
        lifespan=timedelta(seconds=10),
        tick_interval=timedelta(seconds=1),
    )


def _derived_property() -> DerivedProperty[int]:
    return DerivedProperty(Subject[int]())


_NOTIFICATION_STEPS: tuple[tuple[str, str], ...] = (
    ("_timer_sub", "dispose"),
    ("_tick_sub", "dispose"),
    ("_pending_sub", "dispose"),
    ("_dismiss_command", "dispose"),
    ("_property_changed_subject", "on_completed"),
    ("_property_changed_subject", "dispose"),
)

_CASES: tuple[_Case, ...] = (
    _Case(
        "SearchableState",
        _searchable_state,
        (
            ("_subscription", "dispose"),
            ("_term_subject", "on_completed"),
            ("_term_subject", "dispose"),
            ("_filtered_subject", "on_completed"),
            ("_filtered_subject", "dispose"),
            ("_force_search", "on_completed"),
            ("_force_search", "dispose"),
        ),
    ),
    _Case(
        "TokenPagedComposition",
        _token_paged_composition,
        (
            ("_load_more_command", "dispose"),
            ("_refresh_command", "dispose"),
            ("_collection_changed", "on_completed"),
            ("_collection_changed", "dispose"),
            ("_property_changed", "on_completed"),
            ("_property_changed", "dispose"),
            ("_command_changed", "on_completed"),
            ("_command_changed", "dispose"),
        ),
    ),
    _Case(
        "FilteredCompositeVM",
        _filtered_composite_vm,
        (
            ("_subscription", "dispose"),
            ("_changed", "on_completed"),
            ("_changed", "dispose"),
        ),
    ),
    _Case("NotificationVM", _notification_vm, _NOTIFICATION_STEPS),
    _Case(
        "ConfirmationVM",
        _confirmation_vm,
        (("_approve_command", "dispose"), ("_reject_command", "dispose"), *_NOTIFICATION_STEPS),
    ),
    _Case(
        "DerivedProperty",
        _derived_property,
        (
            ("_subscription", "dispose"),
            ("_changes", "on_completed"),
            ("_changes", "dispose"),
        ),
    ),
)

_PARAMS = [
    pytest.param(case, index, id=f"{case.name}-{owner}.{method}")
    for case in _CASES
    for index, (owner, method) in enumerate(case.steps)
]


def _spy_steps(sut: object, case: _Case, failing_index: int, failure: BaseException) -> list[str]:
    """Record each owned teardown step; the step at ``failing_index`` runs and then raises."""
    ran: list[str] = []
    for index, (owner_name, method_name) in enumerate(case.steps):
        owner = getattr(sut, owner_name)
        assert owner is not None, f"{case.name}.{owner_name} must exist before dispose"
        original = getattr(owner, method_name)
        label = f"{owner_name}.{method_name}"

        def step(
            original: Callable[[], None] = original,
            label: str = label,
            fails: bool = index == failing_index,
        ) -> None:
            ran.append(label)
            original()
            if fails:
                raise failure

        setattr(owner, method_name, step)
    return ran


@pytest.mark.parametrize(("case", "failing_index"), _PARAMS)
async def test_teardown_runs_every_step_when_one_raises(case: _Case, failing_index: int) -> None:
    sut = case.build()
    boom = RuntimeError(f"{case.name} teardown step {failing_index} failed")
    ran = _spy_steps(sut, case, failing_index, boom)
    expected = [f"{owner}.{method}" for owner, method in case.steps]

    with pytest.raises(RuntimeError) as raised:
        sut.dispose()

    assert raised.value is boom
    assert ran == expected
    sut.dispose()  # a second dispose stays a no-op: nothing re-runs or raises
    assert ran == expected
