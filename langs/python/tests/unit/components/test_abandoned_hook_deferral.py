"""A lifecycle hook that defers completion and then raises abandons the deferral."""

from __future__ import annotations

import logging
from collections.abc import Iterator
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


class CancellableWalkVM(DeferThenRaiseVM):
    """Defers construction to a child walk whose future a test may cancel."""

    def __init__(self, child: DeferThenRaiseVM, cancel_in_after: bool) -> None:
        super().__init__()
        self.child = child
        self.cancel_in_after = cancel_in_after
        self.after_calls = 0
        self.seal_calls = 0
        self.walk: Future[None] | None = None

    def _children(self) -> Iterator[DeferThenRaiseVM]:
        yield self.child
        if not self.cancel_in_after:
            # #745: cancelled after advance() passed its loop check.
            assert self.walk is not None
            self.walk.cancel()

    def _on_construct(self) -> None:
        def after() -> None:
            self.after_calls += 1
            if self.cancel_in_after:
                assert self.walk is not None
                self.walk.cancel()

        def seal() -> None:
            # The commit step must never run for a cancelled walk.
            self.seal_calls += 1

        self.walk = self._transition_container_children(
            self._children(), construct=True, after=after, seal=seal
        )
        self._complete_lifecycle_hook_after(self.walk)


@pytest.mark.parametrize("cancel_in_after", [False, True])
def test_cancelled_child_walk_completes_nothing_after_its_loop_check(
    cancel_in_after: bool, caplog: pytest.LogCaptureFixture
) -> None:
    child = DeferThenRaiseVM()
    child.mode = "defer"
    vm = CancellableWalkVM(child, cancel_in_after)
    vm.construct()
    assert vm.status is ConstructionStatus.CONSTRUCTING

    with caplog.at_level(logging.ERROR):
        child.deferrals[0].set_result(None)

    assert vm.walk is not None and vm.walk.cancelled()
    assert vm.after_calls == (1 if cancel_in_after else 0)
    assert vm.seal_calls == 0
    assert vm.status is ConstructionStatus.DESTRUCTED
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
