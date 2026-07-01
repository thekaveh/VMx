"""FORM-016..023 — FormVM declarative validation."""

from __future__ import annotations

import dataclasses

import pytest

from vmx.forms import FormVM


@dataclasses.dataclass(frozen=True)
class Model:
    name: str
    value: int


async def persist(_: Model) -> None:
    pass


@pytest.mark.conformance("FORM-016")
def test_FORM_016_field_validator_populates_field_error() -> None:
    sut = FormVM(
        Model("", 1),
        persist,
        validators={"name": lambda m: "required" if not m.name else None},
    )
    assert sut.field_error("name") == "required"
    assert sut.errors == {"name": "required"}


@pytest.mark.conformance("FORM-017")
def test_FORM_017_model_validator_populates_errors() -> None:
    sut = FormVM(Model("x", -1), persist, model_validator=lambda m: {"value": "negative"})
    assert sut.errors == {"value": "negative"}


@pytest.mark.conformance("FORM-018")
def test_FORM_018_is_valid_reflects_errors() -> None:
    sut = FormVM(Model("", 1), persist, validators={"name": lambda m: "required"})
    assert sut.is_valid is False


@pytest.mark.conformance("FORM-019")
async def test_FORM_019_invalid_form_blocks_approval() -> None:
    persisted: list[Model] = []

    async def record(model: Model) -> None:
        persisted.append(model)

    sut = FormVM(Model("", 1), record, validators={"name": lambda m: "required"})
    assert sut.approve_command.can_execute() is False
    await sut.approve_async()
    assert persisted == []


@pytest.mark.conformance("FORM-020")
def test_FORM_020_validation_reruns_after_model_mutation() -> None:
    sut = FormVM(
        Model("", 1),
        persist,
        validators={"name": lambda m: "required" if not m.name else None},
    )
    sut.set_model(Model("ok", 1))
    assert sut.errors == {}
    assert sut.is_valid is True


@pytest.mark.conformance("FORM-021")
def test_FORM_021_errors_changed_fires_only_on_effective_changes() -> None:
    sut = FormVM(
        Model("", 1),
        persist,
        validators={"name": lambda m: "required" if not m.name else None},
    )
    seen: list[dict[str, str]] = []
    sut.errors_changed.subscribe(lambda e: seen.append(e))
    sut.set_model(Model("", 2))
    sut.set_model(Model("ok", 2))
    assert seen == [{}]


@pytest.mark.conformance("FORM-022")
def test_FORM_022_builder_registers_validators_immutably() -> None:
    base = FormVM.builder().initial(Model("", 1)).persister(persist)
    with_validator = base.validator("name", lambda m: "required")
    assert base is not with_validator
    assert with_validator.build().field_error("name") == "required"


@pytest.mark.conformance("FORM-023")
def test_FORM_023_clearing_errors_enables_approval_when_other_gates_pass() -> None:
    sut = FormVM(
        Model("", 1),
        persist,
        strict=True,
        validators={"name": lambda m: "required" if not m.name else None},
    )
    sut.set_model(Model("ok", 2))
    assert sut.approve_command.can_execute() is True
