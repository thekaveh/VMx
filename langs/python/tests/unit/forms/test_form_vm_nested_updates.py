"""Nested FormVM approvals start at the outermost update (spec/20 §5.4, ADR-0180)."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Coroutine
from typing import Any

import pytest

from vmx.forms import FormVM


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


class BoomError(Exception):
    """An observer failure."""


async def test_nested_approve_async_persists_after_the_outermost_update() -> None:
    events: list[str] = []
    coroutines: list[Coroutine[Any, Any, None]] = []
    form: FormVM[Model] | None = None

    async def persist(model: Model) -> None:
        events.append(f"persist {model.value}")

    def validate(model: Model) -> str | None:
        if model.value == "a" and not coroutines:
            assert form is not None
            # Run the coroutine to its first suspension: the call is admitted
            # here and waits for the outermost update to start it.
            coroutine = form.approve_async()
            coroutine.send(None)
            coroutines.append(coroutine)
            events.append("nested returned")
        return None

    form = FormVM(Model("initial"), persist, validators={"value": validate})
    form.set_model(Model("edited"))
    form.approve_command.can_execute_changed.subscribe(lambda _: events.append("can_execute"))

    form.set_model(Model("a"))
    events.append("outer returned")
    await asyncio.sleep(0)  # the start resolves the awaiter on this loop
    with pytest.raises(StopIteration):
        coroutines[0].send(None)

    assert events == [
        "nested returned",
        "can_execute",
        "outer returned",
        "persist edited",
        "can_execute",
    ]
    assert form.snapshot == Model("edited")
    assert form.model == Model("a")


def test_a_failing_admission_observer_releases_a_nested_approval() -> None:
    persisted: list[Model] = []
    notifications: list[None] = []
    form: FormVM[Model] | None = None
    nested = False

    async def persist(model: Model) -> None:
        persisted.append(model)

    def validate(model: Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            form.approve_command.execute()
        return None

    def fail_on_admission(value: None) -> None:
        notifications.append(value)
        if len(notifications) == 1:
            raise BoomError("admission observer")

    form = FormVM(Model("initial"), persist, validators={"value": validate})
    form.approve_command.can_execute_changed.subscribe(fail_on_admission)

    with pytest.raises(BoomError):
        form.set_model(Model("a"))

    # The admission edge and the release edge; the persister never starts.
    assert len(notifications) == 2
    assert persisted == []
    assert form.approve_command.can_execute()
    assert form.model == Model("a")
