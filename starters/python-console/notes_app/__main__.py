"""Run the notebook flow once: construct, edit, save, recover from an error, dispose.

Run it with ``python -m notes_app``. Replace this module with your own host
(CLI, Textual, Tkinter or a web handler).
"""

from __future__ import annotations

import vmx
from vmx import ConstructionStatus

from notes_app.notes import InMemoryNoteStore, NotebookApp, NoteConflictError, NoteModel


def main() -> None:
    store = InMemoryNoteStore()
    app = NotebookApp(
        store,
        [
            NoteModel(id="1", title="Groceries", body="Milk, eggs"),
            NoteModel(id="2", title="Ideas", body="Write a starter"),
        ],
    )
    try:
        print(f"VMx {vmx.__version__}")
        app.start()
        current = app.notebook.current
        print(
            f"constructed: {app.notebook.is_constructed}, "
            f"current: {current.model.title if current else None}"
        )

        app.rename_current("Groceries for Monday")
        app.save_current.execute()
        saved = store.get("1")
        print(f"saved: {saved.title if saved else None}")

        # Error path: the store rejects a duplicate title. `execute()` raises,
        # so the caller handles the error inline and the app keeps running.
        app.select("2")
        app.rename_current("Groceries for Monday")
        try:
            app.save_current.execute()
        except NoteConflictError as error:
            print(f"rejected: {error}")
            app.rename_current("Ideas for Monday")
            app.save_current.execute()
            fixed = store.get("2")
            print(f"saved after fix: {fixed.title if fixed else None}")
    finally:
        app.dispose()
        print(f"disposed: {app.notebook.status is ConstructionStatus.DISPOSED}")


if __name__ == "__main__":
    main()
