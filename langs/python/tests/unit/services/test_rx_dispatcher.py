"""Unit tests for RxDispatcher.

Covers:
- Constructor stores foreground and background schedulers.
- ``immediate()`` factory returns a valid RxDispatcher with ImmediateScheduler.
- ``asyncio()`` factory returns a valid RxDispatcher with appropriate schedulers.
- RxDispatcher satisfies the Dispatcher Protocol structurally.
"""

from __future__ import annotations

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ImmediateScheduler, ThreadPoolScheduler
from reactivex.scheduler.eventloop import AsyncIOScheduler
from reactivex.testing import TestScheduler

from vmx.services.dispatcher import Dispatcher, RxDispatcher


def test_constructor_stores_schedulers() -> None:
    """Supplied schedulers are accessible via .foreground and .background."""
    fg = TestScheduler()
    bg = TestScheduler()
    d = RxDispatcher(foreground=fg, background=bg)

    assert d.foreground is fg
    assert d.background is bg


def test_immediate_factory_returns_rx_dispatcher() -> None:
    """immediate() returns an RxDispatcher with ImmediateScheduler for both."""
    d = RxDispatcher.immediate()

    assert isinstance(d, RxDispatcher)
    assert isinstance(d.foreground, ImmediateScheduler)
    assert isinstance(d.background, ImmediateScheduler)


def test_asyncio_factory_returns_rx_dispatcher() -> None:
    """asyncio() returns an RxDispatcher with AsyncIOScheduler fg + ThreadPoolScheduler bg."""
    d = RxDispatcher.asyncio()

    assert isinstance(d, RxDispatcher)
    assert isinstance(d.foreground, AsyncIOScheduler)
    assert isinstance(d.background, ThreadPoolScheduler)


def test_rx_dispatcher_satisfies_dispatcher_protocol() -> None:
    """RxDispatcher is structurally compatible with the Dispatcher Protocol."""
    d = RxDispatcher.immediate()
    assert isinstance(d, Dispatcher)


def test_foreground_and_background_are_scheduler_bases() -> None:
    """Both scheduler properties expose SchedulerBase instances."""
    d = RxDispatcher.immediate()
    assert isinstance(d.foreground, SchedulerBase)
    assert isinstance(d.background, SchedulerBase)
