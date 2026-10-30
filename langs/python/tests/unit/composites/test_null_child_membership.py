"""A None or invalid child never leaves the membership transaction open.

Later adds and cross-thread disposal therefore still proceed (#1048).
"""

from __future__ import annotations

from threading import Thread
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

_KINDS = ("group", "composite")
_MUTATIONS = ("add", "insert", "setitem")


def _child(name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(MessageHub(), RxDispatcher.immediate()).build()


def _container(kind: str) -> Any:
    builder: Any = GroupVMBuilder() if kind == "group" else CompositeVMBuilder()
    return (
        builder.name(kind)
        .services(MessageHub(), RxDispatcher.immediate())
        .children(lambda: ())
        .build()
    )


def _add(container: Any, child: ComponentVM | None) -> None:
    # GroupVM exposes add; CompositeVM exposes append (add is its alias).
    container.add(child)


def _mutate_with_none(container: Any, mutation: str) -> None:
    if mutation == "add":
        _add(container, None)
    elif mutation == "insert":
        container.insert(0, None)
    else:
        container[0] = None


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("mutation", _MUTATIONS)
def test_none_child_is_rejected_without_changing_the_children(kind: str, mutation: str) -> None:
    container = _container(kind)
    seed = _child("seed")
    _add(container, seed)

    with pytest.raises(ValueError, match="child must not be None"):
        _mutate_with_none(container, mutation)

    assert list(container) == [seed]


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("mutation", _MUTATIONS)
def test_none_child_leaves_no_open_membership_transaction(kind: str, mutation: str) -> None:
    container = _container(kind)
    _add(container, _child("seed"))
    with pytest.raises(ValueError):
        _mutate_with_none(container, mutation)

    same_thread = _child("same-thread")
    _add(container, same_thread)
    other_thread = _child("other-thread")
    errors: list[BaseException] = []

    def run(action: Any) -> Thread:
        def target() -> None:
            try:
                action()
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=target, daemon=True)
        thread.start()
        return thread

    adder = run(lambda: _add(container, other_thread))
    adder.join(HANG_GUARD)
    assert not adder.is_alive()
    assert errors == []
    assert same_thread in container
    assert other_thread in container

    disposer = run(container.dispose)
    disposer.join(HANG_GUARD)
    assert not disposer.is_alive()
    assert errors == []


def _mutate_with_invalid(container: Any, mutation: str, seed: ComponentVM) -> None:
    if mutation == "add":
        _add(container, 42)
    elif mutation == "insert":
        container.insert(0, "x")
    elif mutation == "setitem":
        container[0] = object()
    else:
        # __getitem__ accepts a slice; __setitem__ does not.
        container[0:1] = [seed]


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("mutation", (*_MUTATIONS, "slice"))
def test_invalid_child_leaves_no_open_membership_transaction(kind: str, mutation: str) -> None:
    container = _container(kind)
    seed = _child("seed")
    _add(container, seed)
    with pytest.raises((AttributeError, TypeError)):
        _mutate_with_invalid(container, mutation, seed)
    assert list(container) == [seed]

    later = _child("later")
    _add(container, later)
    assert later in container

    disposer = Thread(target=container.dispose, daemon=True)
    disposer.start()
    disposer.join(HANG_GUARD)
    assert not disposer.is_alive()
