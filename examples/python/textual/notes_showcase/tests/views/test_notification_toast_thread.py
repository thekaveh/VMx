"""An expiring notification updates the toast on the App thread (issue #1642).

The workspace is built inside the running loop, as ``__main__.main`` builds it,
so the notification timers run on that loop. The App runs on the same loop under
``run_test``, so ``threading.get_ident()`` in the test body is the App thread.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any

import pytest
from textual.widgets import Static
from vmx.notifications import Notification, NotificationHub, NotificationType

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.notifications_vm import NotificationsVM
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.app import NotesShowcaseApp


@pytest.mark.asyncio
async def test_an_expiring_notification_updates_the_toast_on_the_app_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_threads: list[int] = []
    original_sync = NotificationsVM._sync_from_pending

    def recording_sync(self: NotificationsVM, pending: list[Notification]) -> None:
        sync_threads.append(threading.get_ident())
        original_sync(self, pending)

    # Patch before construct_async: _on_construct binds the method it finds then.
    monkeypatch.setattr(NotificationsVM, "_sync_from_pending", recording_sync)

    hub = NotificationHub()
    repo = InMemoryNoteRepository(build_seed(), load_all_delay=0.0, load_notes_delay=0.0)
    workspace = (
        WorkspaceVM.builder()
        .repository(repo)
        .dialog_service(NullDialogService())
        .notification_hub(hub)
        .notification_lifespan(timedelta(milliseconds=50))
        .build()
    )
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)

    async with app.run_test(size=(160, 50)) as pilot:
        render = app.query_one("#notifications_render", Static)
        update_threads: list[int] = []
        original_update = render.update

        def recording_update(*args: Any, **kwargs: Any) -> None:
            update_threads.append(threading.get_ident())
            original_update(*args, **kwargs)

        # _assign looks up widget.update on each call, so an instance patch records it.
        render.update = recording_update  # type: ignore[method-assign]
        app_thread = threading.get_ident()

        hub.post(Notification(NotificationType.NOTIFICATION, "expire me"))
        visible = workspace.notifications.visible
        deadline = time.monotonic() + 2.0
        while visible.count > 0 and time.monotonic() < deadline:
            await pilot.pause(0.01)

        assert visible.count == 0, "the notification did not expire within 2 seconds"
        assert sync_threads, "the expiry never reached _sync_from_pending"
        assert set(sync_threads) == {app_thread}, (
            f"_sync_from_pending ran on threads {sorted(set(sync_threads))}, "
            f"not the App thread {app_thread}"
        )
        assert set(update_threads) == {app_thread}, (
            f"the toast update ran on threads {sorted(set(update_threads))}, "
            f"not the App thread {app_thread}"
        )
