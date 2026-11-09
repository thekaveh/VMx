"""FORM-043 — an update raises the approve notification when its gates change.

Per spec/20-form-vm.md §5.2 and §5.3, and ADR-0196. An accepted unequal
``set_model`` or a deny raises ``approve_command.can_execute_changed`` exactly
once when it changes ``is_valid``, or ``is_dirty`` in strict mode, and
otherwise not. The rule compares the two inputs, not the computed
``can_execute()``. An approval in flight does not suppress the event.
"""

from __future__ import annotations

import dataclasses

import pytest

from vmx.forms import FormVM


@dataclasses.dataclass(frozen=True)
class _Model:
    value: str


def _rejects_bad(model: _Model) -> str | None:
    return "rejected" if model.value == "bad" else None


async def _noop(_: _Model) -> None:
    return None


class _Counter:
    def __init__(self, form: FormVM[_Model]) -> None:
        self.count = 0
        form.approve_command.can_execute_changed.subscribe(lambda _: self._bump())

    def _bump(self) -> None:
        self.count += 1


@pytest.mark.conformance("FORM-043")
def test_FORM_043_strict_updates_raise_once_per_gate_change() -> None:
    form = FormVM(_Model("snapshot"), _noop, strict=True, validators={"value": _rejects_bad})
    form.set_model(_Model("bad"))
    assert form.is_dirty and not form.is_valid
    counter = _Counter(form)

    form.set_model(_Model("snapshot"))
    assert counter.count == 1, "valid and clean: both gates changed, one event"
    assert form.approve_command.can_execute() is False

    form.set_model(_Model("a"))
    assert counter.count == 2, "valid and dirty: the dirty gate changed"
    assert form.approve_command.can_execute() is True

    form.set_model(_Model("b"))
    assert counter.count == 2, "still valid and dirty: no gate changed"
    form.dispose()


@pytest.mark.conformance("FORM-043")
def test_FORM_043_deny_raises_once_when_a_gate_changes() -> None:
    form = FormVM(_Model("snapshot"), _noop, strict=True, validators={"value": _rejects_bad})
    form.set_model(_Model("bad"))
    counter = _Counter(form)

    form.deny_command.execute()

    assert counter.count == 1, "deny restored a valid, clean model: one event"
    assert form.approve_command.can_execute() is False
    form.dispose()


@pytest.mark.conformance("FORM-043")
async def test_FORM_043_update_during_an_approval_raises_its_own_event() -> None:
    form: FormVM[_Model] | None = None
    counter: _Counter | None = None
    reads: list[tuple[int, int]] = []

    async def _persist(_: _Model) -> None:
        assert form is not None and counter is not None
        after_admission = counter.count
        form.set_model(_Model("bad"))
        reads.append((after_admission, counter.count))

    form = FormVM(_Model("snapshot"), _persist, validators={"value": _rejects_bad})
    counter = _Counter(form)
    assert form.is_valid

    await form.approve_async()

    assert len(reads) == 1, "the persister ran once"
    after_admission, persister_read = reads[0]
    assert after_admission == 1, "admission raised one event"
    assert persister_read == after_admission + 1, "the in-flight update raised one event"
    assert counter.count == persister_read + 1, "settlement raised one more event"
    form.dispose()
