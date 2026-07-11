"""FORM-024..029 — declarative reset-after-approval conformance."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from vmx.forms.form_vm import FormVM


@dataclass
class Model:
    value: str
    nested: list[int] | None = None


async def _noop(_: Model) -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-024")
async def test_form_024_reset_order_and_approved_payload() -> None:
    order: list[str] = []

    async def persist(model: Model) -> None:
        order.append(f"persist:{model.value}")

    form = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(persist)
        .reset_on_approved(
            lambda model: (order.append(f"reset:{model.value}"), Model(f"reset:{model.value}"))[1]
        )
        .build()
    )

    def approved(model: Model) -> None:
        order.append(f"approved:{model.value}")
        assert form.model == Model("reset:edited")
        assert form.snapshot == Model("reset:edited")
        assert not form.is_dirty

    form.on_approved.subscribe(approved)
    form.set_model(Model("edited"))
    await form.approve_async()

    assert order == ["persist:edited", "reset:edited", "approved:edited"]


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-025")
async def test_form_025_snapshot_validation_and_strict_integration() -> None:
    snapshots: list[Model] = []

    def snapshot(model: Model) -> Model:
        snapshots.append(model)
        return Model(model.value, list(model.nested or []))

    form = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(_noop)
        .strict(True)
        .snapshotter(snapshot)
        .validator("value", lambda model: "required" if not model.value else None)
        .reset_on_approved(lambda _: Model("", [1]))
        .build()
    )
    snapshots.clear()
    form.set_model(Model("edited"))
    await form.approve_async()

    assert len(snapshots) == 2
    assert form.model == Model("", [1])
    assert form.snapshot == form.model
    assert form.model is not form.snapshot
    assert form.model.nested is not form.snapshot.nested
    assert form.field_error("value") == "required"
    assert not form.is_dirty
    assert not form.approve_command.can_execute()


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-026")
async def test_form_026_reset_failure_is_atomic_and_singly_observed() -> None:
    boom = RuntimeError("reset failed after persistence")
    persisted: list[Model] = []
    approved: list[Model] = []
    direct_errors: list[BaseException] = []

    async def persist(model: Model) -> None:
        persisted.append(model)

    def fail(_: Model) -> Model:
        raise boom

    direct = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(persist)
        .reset_on_approved(fail)
        .build()
    )
    direct.set_model(Model("edited"))
    direct.on_approved.subscribe(approved.append)
    direct.approve_errors.subscribe(direct_errors.append)

    with pytest.raises(RuntimeError) as caught:
        await direct.approve_async()
    assert caught.value is boom
    assert persisted == [Model("edited")]
    assert direct.model == Model("edited")
    assert direct.snapshot == Model("initial")
    assert direct.is_dirty
    assert approved == []
    assert direct_errors == []

    command_errors: list[BaseException] = []
    command = (
        FormVM.builder().initial(Model("initial")).persister(_noop).reset_on_approved(fail).build()
    )
    command.set_model(Model("edited"))
    observed = asyncio.Event()

    def observe_command_error(error: BaseException) -> None:
        command_errors.append(error)
        observed.set()

    command.approve_errors.subscribe(observe_command_error)
    command.approve_command.execute()
    await asyncio.wait_for(observed.wait(), timeout=1)
    assert command_errors == [boom]


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-027")
async def test_form_027_reset_skipped_without_successful_approval() -> None:
    reset_inputs: list[Model] = []

    def reset(model: Model) -> Model:
        reset_inputs.append(model)
        return model

    invalid = (
        FormVM.builder()
        .initial(Model(""))
        .persister(_noop)
        .validator("value", lambda model: "required" if not model.value else None)
        .reset_on_approved(reset)
        .build()
    )
    await invalid.approve_async()

    async def fail(_: Model) -> None:
        raise RuntimeError("persist failed")

    failed = (
        FormVM.builder().initial(Model("initial")).persister(fail).reset_on_approved(reset).build()
    )
    with pytest.raises(RuntimeError):
        await failed.approve_async()

    async def cancel(_: Model) -> None:
        raise asyncio.CancelledError

    cancelled = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(cancel)
        .reset_on_approved(reset)
        .build()
    )
    with pytest.raises(asyncio.CancelledError):
        await cancelled.approve_async()

    denied = (
        FormVM.builder().initial(Model("initial")).persister(_noop).reset_on_approved(reset).build()
    )
    denied.set_model(Model("edited"))
    denied.deny_command.execute()
    assert reset_inputs == []


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-028")
async def test_form_028_disposal_during_persistence_suppresses_reset() -> None:
    gate = asyncio.Event()
    reset_inputs: list[Model] = []
    approved: list[Model] = []

    async def persist(_: Model) -> None:
        await gate.wait()

    form = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(persist)
        .reset_on_approved(lambda model: (reset_inputs.append(model), model)[1])
        .build()
    )
    form.set_model(Model("edited"))
    form.on_approved.subscribe(approved.append)
    task = asyncio.create_task(form.approve_async())
    await asyncio.sleep(0)
    form.dispose()
    gate.set()
    await task

    assert reset_inputs == []
    assert form.model == Model("edited")
    assert form.snapshot == Model("initial")
    assert approved == []


@pytest.mark.asyncio
@pytest.mark.conformance("FORM-029")
async def test_form_029_reset_wins_racing_model_mutation() -> None:
    gate = asyncio.Event()
    persisted: list[Model] = []
    reset_inputs: list[Model] = []
    approved: list[Model] = []

    async def persist(model: Model) -> None:
        persisted.append(model)
        await gate.wait()

    form = (
        FormVM.builder()
        .initial(Model("initial"))
        .persister(persist)
        .reset_on_approved(
            lambda model: (reset_inputs.append(model), Model(f"reset:{model.value}"))[1]
        )
        .build()
    )
    form.on_approved.subscribe(approved.append)
    form.set_model(Model("approved"))
    task = asyncio.create_task(form.approve_async())
    await asyncio.sleep(0)
    form.set_model(Model("racing"))
    gate.set()
    await task

    assert persisted == [Model("approved")]
    assert reset_inputs == [Model("approved")]
    assert approved == [Model("approved")]
    assert form.model == Model("reset:approved")
    assert form.snapshot == Model("reset:approved")
    assert not form.is_dirty
