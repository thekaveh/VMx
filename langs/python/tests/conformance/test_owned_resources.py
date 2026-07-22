"""Owned-resource and public-hub conformance (DISP-007..013)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.services import MessageHub, RxDispatcher


class ProbeVM(_ComponentVMBase):
    def __init__(
        self,
        hub: MessageHub[object],
        on_dispose: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            name="probe",
            hint="",
            hub=hub,  # type: ignore[arg-type]
            dispatcher=RxDispatcher.immediate(),
        )
        self._on_dispose_callback = on_dispose

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    def register(self, resource: object) -> object:
        return self._own(resource)  # type: ignore[arg-type, no-any-return]

    def _on_dispose(self) -> None:
        if self._on_dispose_callback is not None:
            self._on_dispose_callback()


class DisposableProbe:
    def __init__(self, cleanup: Callable[[], None]) -> None:
        self._cleanup = cleanup

    def dispose(self) -> None:
        self._cleanup()


@pytest.mark.conformance("DISP-007")
def test_disp_007_owned_resources_are_cleaned_in_lifo_order() -> None:
    trace: list[str] = []
    vm = ProbeVM(MessageHub(), lambda: trace.append("hook"))
    vm.register(lambda: trace.append("callable"))
    vm.register(DisposableProbe(lambda: trace.append("disposable")))
    vm.register(lambda: trace.append("last"))

    vm.dispose()

    assert trace == ["hook", "last", "disposable", "callable"]


@pytest.mark.conformance("DISP-008")
def test_disp_008_repeated_dispose_cleans_each_resource_once() -> None:
    calls: list[None] = []
    vm = ProbeVM(MessageHub())
    vm.register(lambda: calls.append(None))
    vm.dispose()
    vm.dispose()
    assert len(calls) == 1


@pytest.mark.conformance("DISP-009")
def test_disp_009_cleanup_failure_is_swallowed_and_isolated() -> None:
    class CleanupAbort(BaseException):
        pass

    trace: list[str] = []
    vm = ProbeVM(MessageHub())
    vm.register(lambda: trace.append("first"))

    def fail() -> None:
        raise CleanupAbort("boom")

    vm.register(fail)
    vm.register(lambda: trace.append("last"))

    vm.dispose()

    assert trace == ["last", "first"]


@pytest.mark.conformance("DISP-010")
def test_disp_010_registration_after_dispose_cleans_immediately_once() -> None:
    calls: list[None] = []
    vm = ProbeVM(MessageHub())
    vm.dispose()
    vm.register(lambda: calls.append(None))
    vm.dispose()
    assert len(calls) == 1


@pytest.mark.conformance("DISP-011")
def test_disp_011_owned_resources_survive_reconstruct() -> None:
    calls: list[None] = []
    vm = ProbeVM(MessageHub())
    vm.register(lambda: calls.append(None))
    vm.construct()
    vm.reconstruct()
    assert calls == []
    vm.dispose()
    assert calls == [None]


@pytest.mark.conformance("DISP-012")
def test_disp_012_injected_hub_is_publicly_visible() -> None:
    hub: MessageHub[object] = MessageHub()
    vm = ProbeVM(hub)
    assert vm.hub is hub


@pytest.mark.conformance("DISP-013")
def test_disp_013_vm_disposal_does_not_dispose_injected_hub() -> None:
    hub: MessageHub[object] = MessageHub()
    vm = ProbeVM(hub)
    received: list[object] = []
    hub.messages.subscribe(received.append)
    vm.dispose()
    baseline = len(received)

    hub.send(object())

    assert len(received) == baseline + 1
