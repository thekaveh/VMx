"""Composition root: one workspace for the whole app, owned by NiceGUI's lifespan.

NiceGUI owns the event loop (uvicorn's), so the host captures it in
``app.on_startup`` instead of creating one. Every page binds to the same
workspace, like a single-user desktop app opened in several tabs.

NiceGUI starts an async startup handler as a background task and does not
await it before serving pages, so a page awaits :meth:`NotesHost.ready` before
it reads the workspace. Shutdown handlers, by contrast, are awaited.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from nicegui import App, ui
from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from reactivex.abc import DisposableBase
from reactivex.scheduler import ThreadPoolScheduler
from vmx import RxDispatcher


def _seeded_repository() -> INoteRepository:
    return InMemoryNoteRepository(build_seed())


class NotesHost:
    """Builds the workspace on NiceGUI's running loop and tears it down at shutdown."""

    def __init__(self, repository: Callable[[], INoteRepository] = _seeded_repository) -> None:
        self._repository = repository
        self.dispatcher: RxDispatcher | None = None
        self.workspace: WorkspaceVM | None = None
        self.accepting = False
        self._started = asyncio.Event()
        self._pages: set[DisposableBase] = set()

    # docs-snippet:start nicegui-host
    def install(self, app: App) -> None:
        app.on_startup(self.start)
        app.on_shutdown(self.stop)

    async def start(self) -> None:
        # RxDispatcher.asyncio(loop) gives foreground work affinity to the
        # loop NiceGUI is already running; VMx neither runs nor closes it.
        try:
            self.dispatcher = RxDispatcher.asyncio(asyncio.get_running_loop())
            workspace = (
                WorkspaceVM.builder()
                .repository(self._repository())
                .dispatcher(self.dispatcher)
                .build()
            )
            # construct_async is the only background hook the host admits, and
            # it completes before any page can bind.
            await workspace.construct_async()
            self.workspace = workspace
            self.accepting = True
        finally:
            self._started.set()  # a failed start releases waiting pages too

    def adopt(self, page: DisposableBase) -> None:
        """Track a page's bindings so shutdown releases them before the workspace."""
        self._pages.add(page)
        ui.context.client.on_delete(lambda: self._pages.discard(page))

    async def ready(self) -> bool:
        """Wait until startup has finished; True when the workspace is accepting pages."""
        await self._started.wait()
        return self.accepting

    async def stop(self) -> None:
        # Shutdown order (Python asyncio dispatcher ownership): stop admitting
        # pages, release every page's subscriptions, dispose the workspace while
        # the loop still runs, then shut down the dispatcher's own thread pool
        # from outside that pool.
        self.accepting = False
        workspace, dispatcher = self.workspace, self.dispatcher
        self.workspace = None
        pages, self._pages = list(self._pages), set()
        try:
            for page in pages:
                page.dispose()
            if workspace is not None:
                workspace.dispose()
        finally:
            pool = dispatcher.background if dispatcher is not None else None
            if isinstance(pool, ThreadPoolScheduler):
                await asyncio.to_thread(pool.executor.shutdown, wait=True)
                # docs-snippet:end nicegui-host
