"""Unit tests for the process-wide wait-for graph (#1059, #1155, #1157, #1181)."""

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


def test_a_hub_edge_and_a_membership_edge_close_a_cycle_in_either_order() -> None:
    # One graph holds both kinds of edge, so a cycle across them is refused
    # whichever wait comes last (#1157, ADR-0172).
    for hub_edge_first in (True, False):
        graph = _WaitForGraph()
        hub, gate = object(), object()
        graph.acquire(gate, 1)

        if hub_edge_first:
            assert graph.try_begin_owner_wait(hub, owner=2, caller=1)
            assert not graph.try_begin_wait(gate, 2)
        else:
            assert graph.try_begin_wait(gate, 2)
            assert not graph.try_begin_owner_wait(hub, owner=2, caller=1)


def test_an_owner_wait_on_the_caller_itself_is_refused() -> None:
    graph = _WaitForGraph()

    assert not graph.try_begin_owner_wait(object(), owner=1, caller=1)
    assert not graph.is_waiting_for_testing(1)


def test_release_waiters_drops_only_edges_to_former_owners() -> None:
    graph = _WaitForGraph()
    hub, other_hub = object(), object()
    assert graph.try_begin_owner_wait(hub, owner=10, caller=1)
    assert graph.try_begin_owner_wait(hub, owner=20, caller=2)
    assert graph.try_begin_owner_wait(other_hub, owner=10, caller=3)

    graph.release_waiters(hub, [20])

    assert not graph.is_waiting_for_testing(1)
    assert graph.is_waiting_for_testing(2)
    assert graph.is_waiting_for_testing(3)
    # The released edge no longer closes a cycle; the kept edges still do.
    assert graph.try_begin_owner_wait(object(), owner=1, caller=10)
    graph.end_wait(10)
    assert not graph.try_begin_owner_wait(object(), owner=2, caller=20)


def test_release_waiters_keeps_resource_named_edges() -> None:
    graph = _WaitForGraph()
    gate = object()
    graph.acquire(gate, 2)
    assert graph.try_begin_wait(gate, 1)

    graph.release_waiters(gate, [])

    assert graph.is_waiting_for_testing(1)
