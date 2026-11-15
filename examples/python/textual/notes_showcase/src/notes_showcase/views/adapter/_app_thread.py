"""Hand a widget update to the Textual App thread.

Textual widgets change on the App thread only (``docs/content/integration/textual.md``).
A binding records the thread, the running loop and a copy of the context when it is
made. A change from that thread runs at once. A change from any other thread is queued
on the recorded loop with ``call_soon_threadsafe``, in the recorded context, so the
widget write and the VM read both run on the App thread. With no running loop at bind
time (plain pytest), every call runs inline.

This is the contract of issue #1669 step 2. The notification toast of issue #1642 uses
the same helper.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Callable


class AppThreadHandoff:
    """Run widget updates on the thread that created this hand-off."""

    def __init__(self) -> None:
        self._thread = threading.get_ident()
        self._context = contextvars.copy_context()
        self._loop: asyncio.AbstractEventLoop | None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._disposed = False

    def run(self, update: Callable[[], None]) -> None:
        """Run *update* now on the bind thread, or queue it on the bind loop."""
        if self._disposed:
            return
        if self._loop is None or threading.get_ident() == self._thread:
            update()
            return
        try:
            self._loop.call_soon_threadsafe(self._run_queued, update, context=self._context)
        except RuntimeError:
            # The loop is closed, so the App has exited and nothing draws the widget.
            return

    def dispose(self) -> None:
        """Drop every update that has not run yet. Idempotent."""
        self._disposed = True

    def _run_queued(self, update: Callable[[], None]) -> None:
        # An update queued before dispose() writes nothing.
        if not self._disposed:
            update()
