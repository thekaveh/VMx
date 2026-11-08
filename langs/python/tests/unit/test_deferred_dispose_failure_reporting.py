"""A deferred container dispose reports its failure after a successful operation (#1152).

``CompositeVM`` and ``GroupVM`` defer a ``dispose()`` that runs inside one of
their own membership transactions or current publications. When the guard
ends, the deferred dispose runs. Its failure propagates when the operation
itself succeeded, and is suppressed only when the operation already raised,
so the first failure stays the reported one (spec/06 §4.2, as in C#).

The success of the operation is an explicit flag. It does not depend on
``sys.exc_info()``, which also reports an exception that a caller frame is
handling: a call inside an ``except`` block or a container ``on_destruct``
hook (the child walk runs the hook inside ``except StopIteration:``) reports
the failure like a plain call.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
_DISPATCHER = RxDispatcher.immediate()
_SRC = Path(__file__).resolve().parents[2] / "src" / "vmx"


class _DisposeFailureError(RuntimeError):
    """Raised by an on_collection_changed completion observer during dispose()."""


def _raise_dispose_failure() -> None:
    raise _DisposeFailureError("dispose failure")


def _plain(action: Callable[[], object]) -> None:
    action()


def _inside_except(action: Callable[[], object]) -> None:
    try:
        raise KeyError("handled by the caller")
    except KeyError:
        action()


_CALLERS = [pytest.param(_plain, id="plain"), pytest.param(_inside_except, id="inside-except")]


def _child(hub: MessageHub[Any], name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, _DISPATCHER).build()


def _composite(
    hub: MessageHub[Any],
    children: list[ComponentVM],
    *,
    on_current_changed: Callable[[ComponentVM | None], None] | None = None,
) -> CompositeVM[ComponentVM]:
    builder = (
        CompositeVMBuilder[ComponentVM]()
        .name("composite")
        .services(hub, _DISPATCHER)
        .children(lambda: children)
    )
    if on_current_changed is not None:
        builder = builder.on_current_changed(on_current_changed)
    return builder.build()


def _group(hub: MessageHub[Any], children: list[ComponentVM]) -> GroupVM[ComponentVM]:
    group: GroupVM[ComponentVM] = (
        GroupVMBuilder[ComponentVM]()
        .name("group")
        .services(hub, _DISPATCHER)
        .children(lambda: children)
        .build()
    )
    return group


def _arm_collection_dispose(vm: CompositeVM[Any] | GroupVM[Any]) -> None:
    """Dispose *vm* from its own collection event; the dispose then fails."""
    vm.on_collection_changed.subscribe(
        on_next=lambda _event: vm.dispose(),
        on_completed=_raise_dispose_failure,
    )


def _arm_dispose_failure_only(vm: CompositeVM[Any]) -> None:
    vm.on_collection_changed.subscribe(on_completed=_raise_dispose_failure)


# ── Membership transactions ─────────────────────────────────────────────────

_COMPOSITE_OPERATIONS: dict[str, Callable[[CompositeVM[ComponentVM], ComponentVM], object]] = {
    "setitem": lambda vm, c: vm.__setitem__(0, c),
    "insert": lambda vm, c: vm.insert(0, c),
    "append": lambda vm, c: vm.append(c),
    "remove": lambda vm, _c: vm.remove(vm[0]),
    "remove_at": lambda vm, _c: vm.remove_at(0),
    "delitem": lambda vm, _c: vm.__delitem__(0),
    "clear": lambda vm, _c: vm.clear(),
}


@pytest.mark.parametrize("caller", _CALLERS)
@pytest.mark.parametrize("operation", sorted(_COMPOSITE_OPERATIONS))
def test_composite_operation_reports_the_deferred_dispose_failure(
    operation: str, caller: Callable[[Callable[[], object]], None]
) -> None:
    hub: MessageHub[Any] = MessageHub()
    vm = _composite(hub, [_child(hub, "a"), _child(hub, "b")])
    vm.construct()
    _arm_collection_dispose(vm)
    c = _child(hub, "c")

    with pytest.raises(_DisposeFailureError):
        caller(lambda: _COMPOSITE_OPERATIONS[operation](vm, c))

    assert vm.status is S.DISPOSED


_GROUP_OPERATIONS: dict[str, Callable[[GroupVM[ComponentVM], ComponentVM], object]] = {
    "setitem": lambda vm, c: vm.__setitem__(0, c),
    "insert": lambda vm, c: vm.insert(0, c),
    "add": lambda vm, c: vm.add(c),
}


@pytest.mark.parametrize("caller", _CALLERS)
@pytest.mark.parametrize("operation", sorted(_GROUP_OPERATIONS))
def test_group_operation_reports_the_deferred_dispose_failure(
    operation: str, caller: Callable[[Callable[[], object]], None]
) -> None:
    hub: MessageHub[Any] = MessageHub()
    vm = _group(hub, [_child(hub, "a"), _child(hub, "b")])
    vm.construct()
    _arm_collection_dispose(vm)
    c = _child(hub, "c")

    with pytest.raises(_DisposeFailureError):
        caller(lambda: _GROUP_OPERATIONS[operation](vm, c))

    assert vm.status is S.DISPOSED


@pytest.mark.parametrize("caller", _CALLERS)
@pytest.mark.parametrize("kind", ["composite", "group"])
def test_lazy_population_reports_the_deferred_dispose_failure(
    kind: str, caller: Callable[[Callable[[], object]], None]
) -> None:
    hub: MessageHub[Any] = MessageHub()
    children = [_child(hub, "a"), _child(hub, "b")]
    vm = _composite(hub, children) if kind == "composite" else _group(hub, children)
    _arm_collection_dispose(vm)

    # Without the explicit flag, the swallowed failure leaves the container
    # DISPOSED and construct() then fails with a StatusTransitionError.
    with pytest.raises(_DisposeFailureError):
        caller(vm.construct)

    assert vm.status is S.DISPOSED


@pytest.mark.parametrize("caller", _CALLERS)
@pytest.mark.parametrize("destination", ["composite", "group"])
def test_transfer_out_of_a_group_reports_the_source_dispose_failure(
    destination: str, caller: Callable[[Callable[[], object]], None]
) -> None:
    hub: MessageHub[Any] = MessageHub()
    x = _child(hub, "x")
    source = _group(hub, [x])
    source.construct()
    target: CompositeVM[ComponentVM] | GroupVM[ComponentVM] = (
        _composite(hub, []) if destination == "composite" else _group(hub, [])
    )
    target.construct()
    _arm_collection_dispose(source)

    with pytest.raises(_DisposeFailureError):
        caller(lambda: target.add(x))

    assert source.status is S.DISPOSED
    assert any(child is x for child in target.snapshot())


# ── Current publication ─────────────────────────────────────────────────────


@pytest.mark.parametrize("caller", _CALLERS)
def test_current_assignment_reports_the_deferred_dispose_failure(
    caller: Callable[[Callable[[], object]], None],
) -> None:
    hub: MessageHub[Any] = MessageHub()
    a, b = _child(hub, "a"), _child(hub, "b")
    holder: list[CompositeVM[ComponentVM]] = []
    vm = _composite(hub, [a, b], on_current_changed=lambda _value: holder[0].dispose())
    holder.append(vm)
    vm.construct()
    _arm_dispose_failure_only(vm)

    def select() -> None:
        vm.current = b

    with pytest.raises(_DisposeFailureError):
        caller(select)

    assert vm.status is S.DISPOSED


# ── Inside a container on_destruct hook ─────────────────────────────────────


def _hook_select(hub: MessageHub[Any]) -> tuple[Callable[[], None], _ComponentVMBase]:
    a, b = _child(hub, "a"), _child(hub, "b")
    holder: list[CompositeVM[ComponentVM]] = []
    target = _composite(hub, [a, b], on_current_changed=lambda _value: holder[0].dispose())
    holder.append(target)
    target.construct()
    _arm_dispose_failure_only(target)

    def select() -> None:
        target.current = b

    return select, target


def _hook_composite_append(hub: MessageHub[Any]) -> tuple[Callable[[], None], _ComponentVMBase]:
    target = _composite(hub, [])
    target.construct()
    _arm_collection_dispose(target)
    x = _child(hub, "x")
    return lambda: target.append(x), target


def _hook_group_add(hub: MessageHub[Any]) -> tuple[Callable[[], None], _ComponentVMBase]:
    target = _group(hub, [])
    target.construct()
    _arm_collection_dispose(target)
    x = _child(hub, "x")
    return lambda: target.add(x), target


_HookAction = Callable[[MessageHub[Any]], tuple[Callable[[], None], _ComponentVMBase]]
_HOOK_ACTIONS: dict[str, _HookAction] = {
    "composite-current": _hook_select,
    "composite-append": _hook_composite_append,
    "group-add": _hook_group_add,
}


@pytest.mark.parametrize("action", sorted(_HOOK_ACTIONS))
@pytest.mark.parametrize("owner_kind", ["composite", "group"])
def test_operation_inside_an_on_destruct_hook_reports_the_deferred_dispose_failure(
    owner_kind: str, action: str
) -> None:
    hub: MessageHub[Any] = MessageHub()
    operation, target = _HOOK_ACTIONS[action](hub)
    raised: list[BaseException] = []

    def on_destruct() -> None:
        try:
            operation()
        except BaseException as error:
            raised.append(error)

    owner_child = _child(hub, "owner-child")
    owner: CompositeVM[ComponentVM] | GroupVM[ComponentVM]
    if owner_kind == "composite":
        owner = (
            CompositeVMBuilder[ComponentVM]()
            .name("owner")
            .services(hub, _DISPATCHER)
            .children(lambda: [owner_child])
            .on_destruct(on_destruct)
            .build()
        )
    else:
        owner = (
            GroupVMBuilder[ComponentVM]()
            .name("owner")
            .services(hub, _DISPATCHER)
            .children(lambda: [owner_child])
            .on_destruct(on_destruct)
            .build()
        )
    owner.construct()

    owner.destruct()

    assert [type(error) for error in raised] == [_DisposeFailureError]
    assert target.status is S.DISPOSED
    assert owner.status is S.DESTRUCTED


# ── Controls: a failed operation keeps its own error ────────────────────────


class _CallbackError(ValueError):
    pass


@pytest.mark.parametrize("caller", _CALLERS)
def test_failed_current_callback_keeps_its_error_over_the_dispose_failure(
    caller: Callable[[Callable[[], object]], None],
) -> None:
    hub: MessageHub[Any] = MessageHub()
    a, b = _child(hub, "a"), _child(hub, "b")
    holder: list[CompositeVM[ComponentVM]] = []

    def dispose_then_raise(_value: ComponentVM | None) -> None:
        holder[0].dispose()
        raise _CallbackError("callback failure")

    vm = _composite(hub, [a, b], on_current_changed=dispose_then_raise)
    holder.append(vm)
    vm.construct()
    _arm_dispose_failure_only(vm)

    def select() -> None:
        vm.current = b

    with pytest.raises(_CallbackError):
        caller(select)

    assert vm.status is S.DISPOSED


@pytest.mark.parametrize("caller", _CALLERS)
@pytest.mark.parametrize("kind", ["composite", "group"])
def test_failed_collection_publication_keeps_its_error_over_the_dispose_failure(
    kind: str, caller: Callable[[Callable[[], object]], None]
) -> None:
    hub: MessageHub[Any] = MessageHub()
    vm: CompositeVM[ComponentVM] | GroupVM[ComponentVM] = (
        _composite(hub, []) if kind == "composite" else _group(hub, [])
    )
    vm.construct()

    def dispose_then_raise(_event: object) -> None:
        vm.dispose()
        raise _CallbackError("subscriber failure")

    vm.on_collection_changed.subscribe(
        on_next=dispose_then_raise, on_completed=_raise_dispose_failure
    )
    x = _child(hub, "x")

    with pytest.raises(_CallbackError):
        caller(lambda: vm.add(x))

    assert vm.status is S.DISPOSED


# ── Guard ───────────────────────────────────────────────────────────────────


def test_no_source_derives_an_operation_result_from_sys_exc_info() -> None:
    pattern = re.compile(r"sys\.exc_info\(\)\[0\]")
    matches = [
        f"{path.relative_to(_SRC)}:{number}"
        for path in sorted(_SRC.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert matches == []
