"""Liveness bound for tests that wait on another thread or event loop."""

from __future__ import annotations

HANG_GUARD: float = 30.0
"""The bound, in seconds, for a wait that is expected to succeed (#546, #1074).

A slow or oversubscribed runner can delay a thread by seconds, so short
deadlines fail without any wrong behavior. A passing wait returns as soon as
its condition holds, so the bound costs nothing; it only stops a hang.

Use it for positive waits: ``Event.wait``, ``Thread.join``, ``Barrier.wait``,
``Future.result`` and ``asyncio.wait_for`` calls whose success the test
expects. An outer wait that must outlive inner ``HANG_GUARD`` waits, such as a
join on a thread that waits itself, uses a multiple of the bound, so the
inner failure is the one reported. A blocking hold that a main-thread positive
wait must time out before also uses a multiple, so a regression cannot pass
because the hold expired first.

A negative window asserts that something did *not* happen, such as
``assert not done.wait(0.05)``. It keeps its short span, because its full
duration elapses on every passing run.
"""
