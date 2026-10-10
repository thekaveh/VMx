"""Run the NiceGUI Notes-Showcase: ``uv run python -m nicegui_notes``."""

from __future__ import annotations

from nicegui import app, ui

from nicegui_notes.host import NotesHost
from nicegui_notes.page import build_page


def main() -> None:
    host = NotesHost()
    host.install(app)

    async def root() -> None:
        await build_page(host)

    ui.run(root, title="VMx Notes", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
