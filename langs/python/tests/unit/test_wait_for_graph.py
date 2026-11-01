"""Unit tests for the container membership wait-for graph (#1059)."""

from __future__ import annotations

from vmx._wait_for_graph import _WaitForGraph


def test_a_wait_that_closes_a_cycle_is_refused() -> None:
    graph = _WaitForGraph()
    x, z = object(), object()
    graph.acquire(x, 1)
    graph.acquire(z, 2)

    assert graph.try_begin_wait(z, 1)
    assert not graph.try_begin_wait(x, 2)
    assert not graph.is_waiting_for_testing(2)


def test_a_cycle_through_a_third_thread_is_refused() -> None:
    graph = _WaitForGraph()
    x, y, z = object(), object(), object()
    graph.acquire(x, 1)
    graph.acquire(y, 2)
    graph.acquire(z, 3)

    assert graph.try_begin_wait(y, 1)
    assert graph.try_begin_wait(z, 2)
    assert not graph.try_begin_wait(x, 3)


def test_a_released_resource_no_longer_closes_a_cycle() -> None:
    # The owner is looked up when the cycle is checked, so a stale wait on a
    # released resource does not count (#736).
    graph = _WaitForGraph()
    x, z = object(), object()
    graph.acquire(x, 1)
    graph.acquire(z, 2)
    assert graph.try_begin_wait(z, 1)
    graph.release(z)

    assert graph.try_begin_wait(x, 2)


def test_an_ended_wait_no_longer_closes_a_cycle() -> None:
    graph = _WaitForGraph()
    x, z = object(), object()
    graph.acquire(x, 1)
    graph.acquire(z, 2)
    assert graph.try_begin_wait(z, 1)
    graph.end_wait(1)

    assert not graph.is_waiting_for_testing(1)
    assert graph.try_begin_wait(x, 2)


def test_a_wait_on_an_unowned_resource_is_recorded() -> None:
    graph = _WaitForGraph()

    assert graph.try_begin_wait(object(), 1)
    assert graph.is_waiting_for_testing(1)
