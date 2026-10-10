"""Client-scoped delivery: apply a binding's update on NiceGUI's loop, inside its page.

VMx publishes a change on the thread that made it. A NiceGUI element must be
touched on the server's event loop, and inside the client (browser page) that
owns it, so an update triggered by one page's event, or by a worker thread,
still lands in the right page.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from nicegui import Client, ui


# docs-snippet:start nicegui-delivery
class ClientDelivery:
    """Captured inside a page builder: the running loop, its thread, and the page's client."""

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.get_ident()
        self._client: Client = ui.context.client

    @property
    def client(self) -> Client:
        return self._client

    def run(self, update: Callable[[], None]) -> None:
        """Apply ``update`` now on the loop thread, or schedule it there from any other thread."""
        if threading.get_ident() == self._thread:
            self._apply(update)
            return
        try:
            self._loop.call_soon_threadsafe(self._apply, update)
        except RuntimeError:
            pass  # the server's loop has closed; there is no page left to update

    def _apply(self, update: Callable[[], None]) -> None:
        if self._client.is_deleted:
            return
        with self._client:
            update()
            # docs-snippet:end nicegui-delivery
