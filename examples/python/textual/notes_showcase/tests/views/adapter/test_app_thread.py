"""Unit tests for the App-thread hand-off (``views/adapter/_app_thread.py``, #1642, #1669)."""

from __future__ import annotations

import asyncio
import threading

from notes_showcase.views.adapter._app_thread import AppThreadHandoff


def _run_on_worker(target: object) -> list[BaseException]:
    """Run *target* on a worker thread and return any exception it raised."""
    errors: list[BaseException] = []

    def work() -> None:
        try:
            target()  # type: ignore[operator]
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    return errors


def test_with_no_loop_every_update_runs_inline() -> None:
    """Plain pytest has no loop: an update from a worker runs on that worker."""
    ran_on: list[int] = []
    handoff = AppThreadHandoff()

    errors = _run_on_worker(lambda: handoff.run(lambda: ran_on.append(threading.get_ident())))

    assert errors == []
    assert len(ran_on) == 1
    assert ran_on[0] != threading.get_ident()


async def test_an_update_from_the_bind_thread_runs_at_once() -> None:
    ran_on: list[int] = []
    handoff = AppThreadHandoff()

    handoff.run(lambda: ran_on.append(threading.get_ident()))

    assert ran_on == [threading.get_ident()]


async def test_an_update_from_a_worker_thread_is_queued_on_the_bind_thread() -> None:
    ran_on: list[int] = []
    handoff = AppThreadHandoff()

    errors = _run_on_worker(lambda: handoff.run(lambda: ran_on.append(threading.get_ident())))
    assert errors == []
    assert ran_on == []  # queued on the loop, not run on the worker

    await asyncio.sleep(0)
    assert ran_on == [threading.get_ident()]


async def test_an_update_queued_before_dispose_writes_nothing() -> None:
    ran_on: list[int] = []
    handoff = AppThreadHandoff()

    errors = _run_on_worker(lambda: handoff.run(lambda: ran_on.append(threading.get_ident())))
    assert errors == []
    handoff.dispose()

    await asyncio.sleep(0)
    assert ran_on == []


async def test_a_disposed_handoff_runs_nothing_from_the_bind_thread() -> None:
    ran_on: list[int] = []
    handoff = AppThreadHandoff()
    handoff.dispose()
    handoff.dispose()  # idempotent

    handoff.run(lambda: ran_on.append(threading.get_ident()))

    assert ran_on == []


def test_a_worker_update_after_the_loop_closes_is_dropped() -> None:
    """A closed loop means the App exited; the queued update is dropped, not raised."""

    async def bind() -> AppThreadHandoff:
        return AppThreadHandoff()

    loop = asyncio.new_event_loop()
    try:
        handoff = loop.run_until_complete(bind())
    finally:
        loop.close()

    ran_on: list[int] = []
    errors = _run_on_worker(lambda: handoff.run(lambda: ran_on.append(threading.get_ident())))

    assert errors == []
    assert ran_on == []
