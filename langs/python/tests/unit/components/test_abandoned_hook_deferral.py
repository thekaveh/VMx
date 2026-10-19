"""A lifecycle hook that defers completion and then raises abandons the deferral."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.lifecycle import ConstructionStatus
from vmx.services import MessageHub, RxDispatcher


class DeferThenRaiseVM(_ComponentVMBase):
    def __init__(self) -> None:
        super().__init__(
            name="defer-then-raise",
            hint="",
            hub=MessageHub(),  # type: ignore[arg-type]
            dispatcher=RxDispatcher.immediate(),
        )
        self.mode = "defer-then-raise"
        self.deferrals: list[Future[None]] = []

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    def _on_construct(self) -> None:
        if self.mode == "plain":
            return
        deferral: Future[None] = Future()
        self.deferrals.append(deferral)
        self._complete_lifecycle_hook_after(deferral)
        if self.mode == "defer-then-raise":
            raise ValueError("hook failed after deferring")


def _failed_vm() -> DeferThenRaiseVM:
    vm = DeferThenRaiseVM()
    with pytest.raises(ValueError, match="after deferring"):
        vm.construct()
    assert vm.status is ConstructionStatus.DESTRUCTED
    return vm


def test_abandoned_caller_future_is_dropped_not_cancelled() -> None:
    # The subclass owns this future: VMx drops it but does not cancel it, so a
    # worker that resolves it later does not fail, and the VM is unaffected.
    vm = _failed_vm()
    deferral = vm.deferrals[0]
    assert not deferral.cancelled()

    deferral.set_result(None)

    assert vm.status is ConstructionStatus.DESTRUCTED


def test_next_plain_construct_is_not_captured_by_stale_deferral() -> None:
    vm = _failed_vm()
    vm.mode = "plain"
    vm.construct()
    assert vm.status is ConstructionStatus.CONSTRUCTED


def test_next_deferring_construct_is_accepted_and_settles() -> None:
    vm = _failed_vm()
    vm.mode = "defer"
    vm.construct()
    assert vm.status is ConstructionStatus.CONSTRUCTING
    vm.deferrals[1].set_result(None)
    assert vm.status is ConstructionStatus.CONSTRUCTED


class ChildWalkThenRaiseVM(DeferThenRaiseVM):
    def __init__(self, child: DeferThenRaiseVM) -> None:
        super().__init__()
        self.child = child
        self.after_calls = 0

    def _on_construct(self) -> None:
        def after() -> None:
            self.after_calls += 1

        self._complete_lifecycle_hook_after(
            self._transition_children([self.child], construct=True, after=after)
        )
        raise ValueError("hook failed after deferring")


def test_abandoned_child_walk_never_runs_after() -> None:
    child = DeferThenRaiseVM()
    child.mode = "defer"
    vm = ChildWalkThenRaiseVM(child)
    with pytest.raises(ValueError, match="after deferring"):
        vm.construct()

    child.deferrals[0].set_result(None)

    assert child.status is ConstructionStatus.CONSTRUCTED
    assert vm.after_calls == 0
    assert vm.status is ConstructionStatus.DESTRUCTED
