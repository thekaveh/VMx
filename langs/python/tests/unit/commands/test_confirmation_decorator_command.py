"""Unit tests for ConfirmationDecoratorCommand — error channel (VMX-009).

The fire-and-forget ``execute()`` runs the confirm gate asynchronously, so it
cannot propagate the way the base ``RelayCommand``'s task does. Previously BOTH
a rejecting confirm delegate AND a throwing inner command were swallowed; they
must now be surfaced on the ``errors`` channel. Await ``execute_async()`` to
observe them inline.
"""

from __future__ import annotations

import asyncio

from vmx.commands import ConfirmationDecoratorCommand, RelayCommand


async def test_execute_surfaces_rejecting_confirm_on_error_channel() -> None:
    boom = RuntimeError("nope")

    async def confirm() -> bool:
        raise boom

    inner = RelayCommand.builder().task(lambda: None).build()
    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    errors: list[BaseException] = []
    cmd.errors.subscribe(errors.append)

    cmd.execute()  # fire-and-forget
    for _ in range(5):
        await asyncio.sleep(0)
        if errors:
            break

    assert errors == [boom], "rejecting confirm surfaced on errors, not swallowed"


async def test_execute_surfaces_throwing_inner_on_error_channel() -> None:
    boom = RuntimeError("inner boom")

    def _raise() -> None:
        raise boom

    inner = RelayCommand.builder().task(_raise).build()

    async def confirm() -> bool:
        return True

    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    errors: list[BaseException] = []
    cmd.errors.subscribe(errors.append)

    cmd.execute()  # fire-and-forget
    for _ in range(5):
        await asyncio.sleep(0)
        if errors:
            break

    assert errors == [boom], "throwing inner command surfaced on errors, not swallowed"


def test_errors_completes_on_dispose() -> None:
    inner = RelayCommand.builder().task(lambda: None).build()

    async def confirm() -> bool:
        return True

    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    completed: list[bool] = []
    cmd.errors.subscribe(on_completed=lambda: completed.append(True))

    cmd.dispose()
    assert len(completed) == 1, "errors observable completes on dispose"
