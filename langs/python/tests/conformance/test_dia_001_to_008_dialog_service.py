"""DIA-001..DIA-008 — VMx ``DialogService`` conformance tests.

Spec-canonical name is ``IDialogService``; Python flavor omits the
I-prefix per ADR-0009. See spec/19-dialogs.md and ADR-0029.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.commands.fluent import confirm as fluent_confirm
from vmx.commands.fluent import confirm_with_dialog_service
from vmx.commands.relay_command import RelayCommand
from vmx.dialogs import (
    DialogService,
    FileFilter,
    NotificationSeverity,
    NullDialogService,
)

# ---------------------------------------------------------------------------
# DIA-001 — PickFileToOpen contract
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DIA-001")
async def test_dia_001_pick_file_to_open_contract() -> None:
    """PickFileToOpen — optional filter/title; returns path or None on cancel."""
    sut = NullDialogService()

    # All parameters are optional.
    r1 = await sut.pick_file_to_open()
    r2 = await sut.pick_file_to_open(filter=None, title=None)
    r3 = await sut.pick_file_to_open(
        filter=FileFilter("Images", ["*.png", "*.jpg"]),
        title="Open image",
    )

    assert r1 is None
    assert r2 is None
    assert r3 is None


# ---------------------------------------------------------------------------
# DIA-002 — PickFileToSave contract
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DIA-002")
async def test_dia_002_pick_file_to_save_contract() -> None:
    """PickFileToSave — optional filter/title/suggested_name; returns path or None."""
    sut = NullDialogService()

    r1 = await sut.pick_file_to_save()
    r2 = await sut.pick_file_to_save(filter=None, title=None, suggested_name=None)
    r3 = await sut.pick_file_to_save(
        filter=FileFilter("Text files", ["*.txt"]),
        title="Save as",
        suggested_name="output.txt",
    )

    assert r1 is None
    assert r2 is None
    assert r3 is None


# ---------------------------------------------------------------------------
# DIA-003 — Confirm contract
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DIA-003")
async def test_dia_003_confirm_contract() -> None:
    """Confirm — message + optional title; returns bool (False on cancel)."""
    sut = NullDialogService()

    r1 = await sut.confirm("Are you sure?")
    r2 = await sut.confirm("Delete this item?", title="Confirm delete")

    # NullDialogService always returns False (safest default).
    assert r1 is False
    assert r2 is False

    # A test double scripted with the user's answer: confirm resolves True,
    # cancel/dismiss resolves False; title is optional.
    class ScriptedDialogService(DialogService):
        def __init__(self, answer: bool) -> None:
            self.answer = answer
            self.calls: list[tuple[str, str | None]] = []

        async def pick_file_to_open(
            self, filter: FileFilter | None = None, title: str | None = None
        ) -> str | None:
            return None

        async def pick_file_to_save(
            self,
            filter: FileFilter | None = None,
            title: str | None = None,
            suggested_name: str | None = None,
        ) -> str | None:
            return None

        async def confirm(self, message: str, title: str | None = None) -> bool:
            self.calls.append((message, title))
            return self.answer

        async def notify(
            self,
            message: str,
            title: str | None = None,
            severity: NotificationSeverity = NotificationSeverity.INFO,
        ) -> None:
            return None

    confirming = ScriptedDialogService(answer=True)
    assert await confirming.confirm("Proceed?") is True
    assert await confirming.confirm("Proceed?", title="Confirm") is True
    assert confirming.calls == [("Proceed?", None), ("Proceed?", "Confirm")]

    cancelling = ScriptedDialogService(answer=False)
    assert await cancelling.confirm("Proceed?") is False


# ---------------------------------------------------------------------------
# DIA-004 — Notify contract
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DIA-004")
async def test_dia_004_notify_contract() -> None:
    """Notify — message/title/severity; completes without error."""
    sut = NullDialogService()

    # Default severity (INFO).
    await sut.notify("Hello")

    # Explicit severities.
    await sut.notify("Info msg", severity=NotificationSeverity.INFO)
    await sut.notify("Warn msg", title="Warning", severity=NotificationSeverity.WARNING)
    await sut.notify("Err msg", title="Error", severity=NotificationSeverity.ERROR)


# ---------------------------------------------------------------------------
# DIA-005 — NullDialogService null-object behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DIA-005")
async def test_dia_005_null_dialog_service_behavior() -> None:
    """NullDialogService: pick_file_* returns None; confirm returns False; notify no-op."""
    sut = NullDialogService()

    assert await sut.pick_file_to_open() is None, "pick_file_to_open returns None per ADR-0017"
    assert await sut.pick_file_to_save() is None, "pick_file_to_save returns None per ADR-0017"
    assert (await sut.confirm("msg")) is False, "confirm returns False (safest default)"

    # Notify must complete without raising.
    await sut.notify("msg")


# ---------------------------------------------------------------------------
# DIA-006 — Reentrancy is implementation-defined
# ---------------------------------------------------------------------------


class _QueuingDialogService(DialogService):
    """Serialises concurrent Confirm calls via an asyncio queue."""

    def __init__(self) -> None:
        self._queue: list[asyncio.Future[bool]] = []

    async def pick_file_to_open(
        self, filter: FileFilter | None = None, title: str | None = None
    ) -> str | None:
        return None

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return None

    async def confirm(self, message: str, title: str | None = None) -> bool:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._queue.append(fut)
        return await fut

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        return None

    def complete_next(self, result: bool) -> None:
        self._queue.pop(0).set_result(result)


class _RejectingDialogService(DialogService):
    """Rejects reentrant Confirm calls immediately with False."""

    def __init__(self) -> None:
        self._active: asyncio.Future[bool] | None = None

    async def pick_file_to_open(
        self, filter: FileFilter | None = None, title: str | None = None
    ) -> str | None:
        return None

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return None

    async def confirm(self, message: str, title: str | None = None) -> bool:
        if self._active is not None:
            return False  # reentrant — reject immediately
        loop = asyncio.get_running_loop()
        self._active = loop.create_future()
        return await self._active

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        return None

    def complete_active(self, result: bool) -> None:
        if self._active is not None:
            self._active.set_result(result)
            self._active = None


@pytest.mark.conformance("DIA-006")
async def test_dia_006_reentrancy_implementation_defined() -> None:
    """Both queueing and immediate-rejecting implementations conform to the contract."""
    # --- Queueing implementation ---
    queuing = _QueuingDialogService()

    task1 = asyncio.ensure_future(queuing.confirm("first"))
    task2 = asyncio.ensure_future(queuing.confirm("second"))

    # Yield to let coroutines suspend and enter the queue.
    await asyncio.sleep(0)

    queuing.complete_next(True)
    queuing.complete_next(False)

    r1 = await task1
    r2 = await task2
    assert r1 is True, "first queued call resolved with True"
    assert r2 is False, "second queued call resolved with False"

    # --- Immediate-rejecting implementation ---
    rejecting = _RejectingDialogService()

    task_a = asyncio.ensure_future(rejecting.confirm("active"))
    await asyncio.sleep(0)  # let task_a suspend and register as active

    task_b = asyncio.ensure_future(rejecting.confirm("reentrant"))
    await asyncio.sleep(0)  # let task_b run to completion

    assert task_b.done(), "reentrant call completes immediately"
    assert (await task_b) is False, "reentrant call returns safe default False"

    rejecting.complete_active(True)
    assert (await task_a) is True, "first call still resolves normally"


# ---------------------------------------------------------------------------
# DIA-007 — Cancellation completes with safe default, does not throw
# ---------------------------------------------------------------------------


class _CancellationAwareDialogService(DialogService):
    """Opt-in cancellable dialog double for DIA-007.

    Each ``*_cancellable`` overload awaits a host answer (a future the test
    resolves) raced against a cancellation signal (an ``asyncio.Event``). A
    cancellation that fires before or during the dialog completes the awaitable
    with the safe default; an answered dialog returns the real (different)
    result, so the cancelled path is observably distinct.
    """

    def __init__(self) -> None:
        self.file_answer: asyncio.Future[str | None] | None = None
        self.confirm_answer: asyncio.Future[bool] | None = None

    async def pick_file_to_open(
        self, filter: FileFilter | None = None, title: str | None = None
    ) -> str | None:
        return None

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return None

    async def confirm(self, message: str, title: str | None = None) -> bool:
        return False

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        return None

    @staticmethod
    async def _race(answer: asyncio.Future[Any], cancel: asyncio.Event, default: Any) -> Any:
        if cancel.is_set():
            return default
        waiter = asyncio.ensure_future(cancel.wait())
        try:
            done, _ = await asyncio.wait({answer, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if answer in done and not cancel.is_set():
            return answer.result()
        return default

    async def pick_file_to_open_cancellable(self, cancel: asyncio.Event) -> str | None:
        self.file_answer = asyncio.get_running_loop().create_future()
        result: str | None = await self._race(self.file_answer, cancel, None)
        return result

    async def confirm_cancellable(self, message: str, cancel: asyncio.Event) -> bool:
        self.confirm_answer = asyncio.get_running_loop().create_future()
        result: bool = await self._race(self.confirm_answer, cancel, False)
        return result


@pytest.mark.conformance("DIA-007")
async def test_dia_007_cancellation_completes_with_safe_default() -> None:
    """Cancellation completes awaitable with safe default (None/False); no throw."""
    svc = _CancellationAwareDialogService()

    # Baseline (non-vacuity): an answered, non-cancelled dialog returns the real
    # result, which differs from the cancelled default.
    never = asyncio.Event()
    pick = asyncio.create_task(svc.pick_file_to_open_cancellable(never))
    await asyncio.sleep(0)
    assert svc.file_answer is not None
    svc.file_answer.set_result("/chosen.txt")
    assert await pick == "/chosen.txt"
    ask = asyncio.create_task(svc.confirm_cancellable("msg", never))
    await asyncio.sleep(0)
    assert svc.confirm_answer is not None
    svc.confirm_answer.set_result(True)
    assert await ask is True

    # Cancelled BEFORE the dialog → safe default, no raise.
    fired = asyncio.Event()
    fired.set()
    assert await svc.pick_file_to_open_cancellable(fired) is None
    assert await svc.confirm_cancellable("msg", fired) is False

    # Cancelled DURING the dialog → safe default, no raise.
    cancel_pick = asyncio.Event()
    pending_pick = asyncio.create_task(svc.pick_file_to_open_cancellable(cancel_pick))
    await asyncio.sleep(0)
    cancel_pick.set()
    assert await pending_pick is None, "cancelled pick_file_to_open returns None"

    cancel_confirm = asyncio.Event()
    pending_confirm = asyncio.create_task(svc.confirm_cancellable("msg", cancel_confirm))
    await asyncio.sleep(0)
    cancel_confirm.set()
    assert await pending_confirm is False, "cancelled confirm returns False"


# ---------------------------------------------------------------------------
# DIA-008 — ConfirmationDecoratorCommand integration
# ---------------------------------------------------------------------------


class _ControllableDialogService(DialogService):
    """Returns a pre-set next_result for confirm calls."""

    def __init__(self) -> None:
        self.next_result: bool = False

    async def pick_file_to_open(
        self, filter: FileFilter | None = None, title: str | None = None
    ) -> str | None:
        return None

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return None

    async def confirm(self, message: str, title: str | None = None) -> bool:
        return self.next_result

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        return None


@pytest.mark.conformance("DIA-008")
async def test_dia_008_confirmation_decorator_command_integration() -> None:
    """ConfirmationDecoratorCommand with dialogService.confirm constructs valid command graph."""
    dialog = _ControllableDialogService()
    inner_executed = False

    def _set_flag() -> None:
        nonlocal inner_executed
        inner_executed = True

    inner = RelayCommand.builder().task(_set_flag).build()

    # Wire via fluent helper.
    safe_cmd = fluent_confirm(inner, lambda: dialog.confirm("Proceed?"))

    assert isinstance(safe_cmd, ConfirmationDecoratorCommand), (
        "result is a ConfirmationDecoratorCommand"
    )
    assert safe_cmd.can_execute() is True, "delegates can_execute to inner"

    # When dialog returns False: inner must NOT execute.
    dialog.next_result = False
    await safe_cmd.execute_async()
    assert inner_executed is False, "inner not executed when confirm returns False"

    # When dialog returns True: inner MUST execute.
    dialog.next_result = True
    await safe_cmd.execute_async()
    assert inner_executed is True, "inner executed when confirm returns True"

    # Also exercise the dedicated confirm_with_dialog_service overload. Spec
    # DIA-008 explicitly covers both the lambda form above and this fluent
    # overload ("or the fluent innerCommand.Confirm(dialogService, prompt)").
    overload_executed = False

    def _set_overload_flag() -> None:
        nonlocal overload_executed
        overload_executed = True

    inner2 = RelayCommand.builder().task(_set_overload_flag).build()
    overload_cmd = confirm_with_dialog_service(inner2, dialog, "Proceed?")

    assert isinstance(overload_cmd, ConfirmationDecoratorCommand), (
        "overload result is a ConfirmationDecoratorCommand"
    )
    assert overload_cmd.can_execute() is True, "overload delegates can_execute to inner"

    dialog.next_result = False
    await overload_cmd.execute_async()
    assert overload_executed is False, "overload: inner not executed when confirm returns False"

    dialog.next_result = True
    await overload_cmd.execute_async()
    assert overload_executed is True, "overload: inner executed when confirm returns True"
