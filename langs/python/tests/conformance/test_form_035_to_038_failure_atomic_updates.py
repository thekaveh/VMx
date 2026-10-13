"""FORM-035..038 — FormVM model updates are failure-atomic.

Per spec/20-form-vm.md §5.4 and ADR-0144: ``set_model`` and deny run every
consumer callback before committing. A failing callback propagates unchanged
with the form untouched and nothing published, and a re-entrant commit or
disposal during preparation leaves the outer update committing and publishing
nothing.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class _Model:
    value: str


class _CallbackError(Exception):
    """A consumer callback failure."""


class _Fragile:
    """A model whose own ``__eq__`` raises when compared with one named value."""

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        value: str,
        explodes_against: str | None = None,
        failure: _CallbackError | None = None,
    ) -> None:
        self.value = value
        self.explodes_against = explodes_against
        self.failure = failure

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _Fragile):
            return NotImplemented
        for side, against in ((self, other), (other, self)):
            if side.explodes_against is not None and side.explodes_against == against.value:
                assert side.failure is not None
                raise side.failure
        return self.value == other.value

    def __repr__(self) -> str:
        return f"_Fragile({self.value!r})"


async def _persist(_: Any) -> None:
    return None


def _identity(model: Any) -> Any:
    return model


def _required(model: _Model) -> str | None:
    return "required" if not model.value else None


Counts = tuple[int, int, int, int]
NO_SIGNALS: Counts = (0, 0, 0, 0)
# RelayCommand.dispose raises one terminal can-execute notification, then
# completes; it is disposal, not an update publication.
TEARDOWN_EVENTS = ["can_execute", "can_execute_completed"]


class _Probe:
    """Counts every FormVM notification and captures its observable state.

    ``counts()`` is ``(errors_changed, can_execute_changed, model hub messages,
    FormRevertedMessage)``. Each model hub message records the form state its
    synchronous subscriber observed; ``events`` keeps every signal in order.
    """

    def __init__(self, form: FormVM[Any], hub: MessageHub[Any]) -> None:
        self._form = form
        self.events: list[str] = []
        self.errors_changed: list[dict[str, str]] = []
        self.can_execute_changed = 0
        self.model_messages: list[tuple[Any, dict[str, str], bool, bool, bool]] = []
        self.reverted = 0
        form.errors_changed.subscribe(self._on_errors)
        form.approve_command.can_execute_changed.subscribe(
            on_next=self._on_can_execute,
            on_completed=lambda: self.events.append("can_execute_completed"),
        )
        hub.messages.subscribe(self._on_message)

    def _on_errors(self, errors: dict[str, str]) -> None:
        self.events.append("errors")
        self.errors_changed.append(errors)

    def _on_can_execute(self, _: None) -> None:
        self.events.append("can_execute")
        self.can_execute_changed += 1

    def _on_message(self, message: Any) -> None:
        if getattr(message, "sender", None) is not self._form:
            return
        if isinstance(message, FormRevertedMessage):
            self.events.append("reverted")
            self.reverted += 1
        elif isinstance(message, PropertyChangedMessage) and message.property_name == "model":
            self.events.append("model")
            form = self._form
            self.model_messages.append(
                (
                    form.model,
                    form.errors,
                    form.is_dirty,
                    form.is_valid,
                    form.approve_command.can_execute(),
                )
            )

    def counts(self) -> Counts:
        return (
            len(self.errors_changed),
            self.can_execute_changed,
            len(self.model_messages),
            self.reverted,
        )

    def state(self) -> tuple[Any, ...]:
        form = self._form
        return (
            form.model,
            form.snapshot,
            form.errors,
            form.is_dirty,
            form.is_valid,
            form.approve_command.can_execute(),
        )

    def assert_unchanged(self, before: tuple[Any, ...], counts: Counts) -> None:
        after = self.state()
        # Same model and snapshot objects: nothing was installed or copied.
        assert after[0] is before[0]
        assert after[1] is before[1]
        assert after[2:] == before[2:]
        assert self.counts() == counts


def _strict_form(
    initial: Any,
    hub: MessageHub[Any],
    **options: Any,
) -> FormVM[Any]:
    options.setdefault("snapshotter", _identity)
    return FormVM(initial, _persist, hub=hub, strict=True, **options)


# ---------------------------------------------------------------------------
# FORM-035 — a failing field validator leaves the form unchanged
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-035")
def test_form_035_failing_field_validator_leaves_form_unchanged() -> None:
    boom = _CallbackError("field validator")
    calls: list[str] = []

    def validate(model: _Model) -> str | None:
        calls.append(model.value)
        if model.value == "boom":
            raise boom
        return _required(model)

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Model("initial"), hub, validators={"value": validate})
    probe = _Probe(form, hub)
    calls.clear()

    def fail_and_assert_unchanged(counts: Counts) -> None:
        before = probe.state()
        with pytest.raises(_CallbackError) as raised:
            form.set_model(_Model("boom"))
        assert raised.value is boom
        probe.assert_unchanged(before, counts)

    # The validator's first run after construction: clean, valid, and (strict)
    # not approvable. Installing the candidate would have made it approvable.
    fail_and_assert_unchanged(NO_SIGNALS)
    assert calls == ["boom"]

    # After earlier successful runs: dirty and valid ...
    form.set_model(_Model("draft"))
    assert probe.counts() == (0, 1, 1, 0)
    fail_and_assert_unchanged((0, 1, 1, 0))
    assert form.approve_command.can_execute()

    # ... and dirty and invalid.
    form.set_model(_Model(""))
    assert probe.counts() == (1, 2, 2, 0)
    fail_and_assert_unchanged((1, 2, 2, 0))
    assert form.errors == {"value": "required"}
    assert calls == ["boom", "draft", "boom", "", "boom"]

    # A later accepted candidate settles and publishes as FORM-030 requires.
    form.set_model(_Model("good"))
    assert probe.counts() == (2, 3, 3, 0)
    assert probe.errors_changed[-1] == {}
    assert probe.model_messages[-1] == (_Model("good"), {}, True, True, True)
    assert form.snapshot == _Model("initial")


# ---------------------------------------------------------------------------
# FORM-036 — model-validator, equality, and deny failures are atomic
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-036")
def test_form_036_failing_model_validator_is_atomic() -> None:
    boom = _CallbackError("model validator")

    def model_validator(model: _Model) -> dict[str, str | None]:
        if model.value == "boom":
            raise boom
        return {"value": "taken"} if model.value == "taken" else {}

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(
        _Model("initial"),
        hub,
        validators={"value": _required},
        model_validator=model_validator,
    )
    probe = _Probe(form, hub)

    form.set_model(_Model("taken"))
    assert probe.counts() == (1, 1, 1, 0)

    before = probe.state()
    with pytest.raises(_CallbackError) as raised:
        form.set_model(_Model("boom"))
    assert raised.value is boom
    probe.assert_unchanged(before, (1, 1, 1, 0))
    assert form.errors == {"value": "taken"}

    form.set_model(_Model("free"))
    assert probe.counts() == (2, 2, 2, 0)
    assert probe.model_messages[-1] == (_Model("free"), {}, True, True, True)


@pytest.mark.conformance("FORM-036")
def test_form_036_failing_model_equality_is_atomic() -> None:
    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Fragile("initial"), hub)
    probe = _Probe(form, hub)

    # The model's own __eq__ fails against the live model.
    live_failure = _CallbackError("equality against the live model")
    before = probe.state()
    with pytest.raises(_CallbackError) as raised:
        form.set_model(_Fragile("next", explodes_against="initial", failure=live_failure))
    assert raised.value is live_failure
    probe.assert_unchanged(before, NO_SIGNALS)

    form.set_model(_Fragile("edited"))
    assert probe.counts() == (0, 1, 1, 0)

    # It passes against the live model but fails in the dirty comparison
    # against the snapshot, after validation would have run.
    snapshot_failure = _CallbackError("equality against the snapshot")
    before = probe.state()
    with pytest.raises(_CallbackError) as raised:
        form.set_model(_Fragile("next", explodes_against="initial", failure=snapshot_failure))
    assert raised.value is snapshot_failure
    probe.assert_unchanged(before, (0, 1, 1, 0))
    assert form.model.value == "edited"

    form.set_model(_Fragile("fine"))
    assert probe.counts() == (0, 1, 2, 0)
    assert probe.model_messages[-1] == (_Fragile("fine"), {}, True, True, True)


@pytest.mark.conformance("FORM-036")
@pytest.mark.parametrize("failing", ["validator", "snapshotter"])
def test_form_036_failing_deny_preparation_is_atomic(failing: str) -> None:
    boom = _CallbackError(f"deny {failing}")
    armed = False

    def validate(model: _Model) -> str | None:
        if armed and failing == "validator" and model.value == "initial":
            raise boom
        return _required(model)

    def snapshotter(model: _Model) -> _Model:
        if armed and failing == "snapshotter":
            raise boom
        return model

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(
        _Model("initial"),
        hub,
        snapshotter=snapshotter,
        validators={"value": validate},
    )
    form.set_model(_Model(""))
    probe = _Probe(form, hub)
    armed = True

    before = probe.state()
    with pytest.raises(_CallbackError) as raised:
        form.deny_command.execute()
    assert raised.value is boom
    # Model keeps the edited value; neither FormRevertedMessage nor the model
    # message is published, and no errors/can-execute notification fires.
    probe.assert_unchanged(before, NO_SIGNALS)
    assert form.model == _Model("")
    assert form.errors == {"value": "required"}

    armed = False
    form.deny_command.execute()
    assert form.model == _Model("initial")
    assert not form.is_dirty
    assert probe.counts() == (1, 1, 1, 1)
    assert probe.model_messages[-1] == (_Model("initial"), {}, False, True, False)


# ---------------------------------------------------------------------------
# FORM-037 — a nested assignment from a validator wins
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-037")
def test_form_037_nested_set_model_from_validator_wins() -> None:
    form: FormVM[_Model] | None = None
    calls: list[str] = []
    nested = False

    def validate(model: _Model) -> str | None:
        nonlocal nested
        calls.append(model.value)
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            form.set_model(_Model(""))
        return _required(model)

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Model("initial"), hub, validators={"value": validate})
    probe = _Probe(form, hub)
    calls.clear()

    form.set_model(_Model("a"))

    # The nested assignment (b = "") ran its own preparation and committed;
    # the outer call validated "a" once and then committed nothing.
    assert calls == ["a", ""]
    assert probe.counts() == (1, 1, 1, 0)
    assert probe.model_messages == [(_Model(""), {"value": "required"}, True, False, False)]
    assert form.model == _Model("")
    assert form.errors == {"value": "required"}
    assert form.is_dirty
    assert not form.is_valid

    # A later edit settles normally.
    form.set_model(_Model("a"))
    assert form.model == _Model("a")
    assert probe.counts() == (2, 2, 2, 0)


def test_nested_deny_from_validator_supersedes_the_outer_assignment() -> None:
    form: FormVM[_Model] | None = None
    nested = False

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            form.deny_command.execute()
        return _required(model)

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Model("initial"), hub, validators={"value": validate})
    form.set_model(_Model("edited"))
    probe = _Probe(form, hub)

    form.set_model(_Model("a"))

    assert form.model == _Model("initial")
    assert not form.is_dirty
    assert probe.counts() == (0, 1, 1, 1)
    assert probe.model_messages == [(_Model("initial"), {}, False, True, False)]


def test_nested_approval_commit_from_validator_supersedes_the_outer_assignment() -> None:
    form: FormVM[_Model] | None = None
    approved: list[_Model] = []
    nested = False

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            asyncio.run(form.approve_async())
        return _required(model)

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Model("initial"), hub, validators={"value": validate})
    form.set_model(_Model("edited"))
    form.on_approved.subscribe(approved.append)
    probe = _Probe(form, hub)

    form.set_model(_Model("a"))

    # The approval captured and committed "edited"; the outer "a" is stale.
    assert approved == [_Model("edited")]
    assert form.model == _Model("edited")
    assert form.snapshot == _Model("edited")
    assert not form.is_dirty
    assert probe.counts() == (0, 2, 0, 0)


# ---------------------------------------------------------------------------
# FORM-038 — disposal during preparation commits nothing
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-038")
async def test_form_038_disposal_during_set_model_preparation_commits_nothing() -> None:
    form: FormVM[_Model] | None = None
    persisted: list[_Model] = []
    completed: list[str] = []

    def validate(model: _Model) -> str | None:
        if model.value == "dispose":
            assert form is not None
            form.dispose()
        return _required(model)

    async def persist(model: _Model) -> None:
        persisted.append(model)

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(
        _Model("initial"),
        persist,
        hub=hub,
        strict=True,
        snapshotter=_identity,
        validators={"value": validate},
    )
    form.set_model(_Model("edited"))
    probe = _Probe(form, hub)
    form.on_approved.subscribe(on_completed=lambda: completed.append("on_approved"))
    form.errors_changed.subscribe(on_completed=lambda: completed.append("errors_changed"))

    form.set_model(_Model("dispose"))  # returns without raising

    assert form.model == _Model("edited")
    assert form.snapshot == _Model("initial")
    # The deferred teardown ran when the admitted call ended. The only signal
    # is the approve command's terminal can-execute notification from that
    # teardown, delivered just before the stream completes.
    assert completed == ["on_approved", "errors_changed"]
    assert probe.events == TEARDOWN_EVENTS

    # The disposed form is inert (FORM-014).
    form.set_model(_Model("late"))
    form.deny_command.execute()
    form.approve_command.execute()
    await form.approve_async()
    assert persisted == []
    assert form.model == _Model("edited")
    assert probe.events == TEARDOWN_EVENTS


@pytest.mark.conformance("FORM-038")
def test_form_038_disposal_during_deny_preparation_commits_nothing() -> None:
    form: FormVM[_Model] | None = None
    armed = False

    def validate(model: _Model) -> str | None:
        if armed and model.value == "initial":
            assert form is not None
            form.dispose()
        return _required(model)

    hub: MessageHub[Any] = MessageHub()
    form = _strict_form(_Model("initial"), hub, validators={"value": validate})
    form.set_model(_Model("edited"))
    probe = _Probe(form, hub)
    armed = True

    form.deny_command.execute()  # returns without raising

    # Not reverted, and no FormRevertedMessage, model message, or update
    # notification; only the teardown's terminal can-execute signal.
    assert form.model == _Model("edited")
    assert probe.events == TEARDOWN_EVENTS

    armed = False
    form.deny_command.execute()
    form.set_model(_Model("late"))
    assert form.model == _Model("edited")
    assert probe.events == TEARDOWN_EVENTS


# ---------------------------------------------------------------------------
# Construction runs the same preparation (spec/20 §5.4)
# ---------------------------------------------------------------------------


def _raise(error: _CallbackError) -> Callable[[Any], Any]:
    def callback(_: Any) -> Any:
        raise error

    return callback


@pytest.mark.parametrize("failing", ["validators", "model_validator", "snapshotter"])
def test_construction_fails_when_a_preparation_callback_fails(failing: str) -> None:
    boom = _CallbackError(f"construction {failing}")
    callback = _raise(boom)
    option: Any = {"value": callback} if failing == "validators" else callback

    with pytest.raises(_CallbackError) as raised:
        FormVM(_Model("initial"), _persist, **{failing: option})

    assert raised.value is boom
