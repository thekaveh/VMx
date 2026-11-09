"""ModalVM dismissal from other threads (issue #1323, spec/19 §3)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tests.liveness import HANG_GUARD
from vmx.dialogs import ModalVM


@pytest.mark.parametrize("debug", [False, True], ids=["default", "loop-debug"])
def test_worker_thread_dismiss_wakes_a_waiter_without_other_loop_activity(
    debug: bool,
) -> None:
    modal: ModalVM[str] = ModalVM("cancel")
    errors: list[BaseException] = []
    dismissed_at: list[float] = []

    def worker() -> None:
        time.sleep(0.2)
        try:
            dismissed_at.append(time.monotonic())
            modal.dismiss("ok")
        except BaseException as error:  # pragma: no cover - the defect path
            errors.append(error)

    async def main() -> tuple[str, float]:
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            # The HANG_GUARD timer is the only other loop activity, and it
            # fires long after the 1 s bound below.
            result = await asyncio.wait_for(modal.wait_result(), timeout=HANG_GUARD)
            return result, time.monotonic()
        finally:
            thread.join(timeout=HANG_GUARD)

    result, returned_at = asyncio.run(main(), debug=debug)

    assert errors == []
    assert result == "ok"
    assert returned_at - dismissed_at[0] < 1.0
    assert modal.is_dismissed
    assert modal.result == "ok"


def test_racing_dismiss_calls_keep_the_first_result() -> None:
    modal: ModalVM[int] = ModalVM(-1)
    count = 16
    barrier = threading.Barrier(count)

    def worker(value: int) -> None:
        barrier.wait(timeout=HANG_GUARD)
        modal.dismiss(value)

    async def main() -> int:
        waiter = asyncio.ensure_future(modal.wait_result())
        await asyncio.sleep(0)
        threads = [threading.Thread(target=worker, args=(value,)) for value in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=HANG_GUARD)
        return await asyncio.wait_for(waiter, timeout=HANG_GUARD)

    awaited = asyncio.run(main())
    first = modal.result

    assert first is not None
    assert awaited == first
    modal.dismiss(count + 1)
    modal.dispose()
    assert modal.result == first
    assert asyncio.run(modal.wait_result()) == first


def test_dismiss_before_any_loop_resolves_a_later_waiter_at_once() -> None:
    modal: ModalVM[str] = ModalVM("cancel")
    modal.dismiss("early")

    async def main() -> str:
        return await asyncio.wait_for(modal.wait_result(), timeout=HANG_GUARD)

    assert asyncio.run(main()) == "early"
    assert asyncio.run(main()) == "early"


def test_cancelled_waiter_is_released_and_others_still_resolve() -> None:
    modal: ModalVM[str] = ModalVM("cancel")

    async def main() -> str:
        cancelled = asyncio.ensure_future(modal.wait_result())
        kept = asyncio.ensure_future(modal.wait_result())
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        # White-box leak check: a cancelled waiter must leave the waiter list
        # before any dismissal, or an undismissed modal keeps it forever.
        # dismiss() clears the list, so this check has to run before it.
        assert len(modal._waiters) == 1
        modal.dismiss("ok")
        return await asyncio.wait_for(kept, timeout=HANG_GUARD)

    assert asyncio.run(main()) == "ok"
