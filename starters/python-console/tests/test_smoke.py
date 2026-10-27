"""Starter smoke test: construct, edit, command, error and dispose.

Run it with ``python -m unittest discover -s tests -v``. It also checks
that the installed VMx version equals the exact pin in requirements.txt, so a
partial upgrade fails here first.
"""

from __future__ import annotations

import re
import unittest
from importlib.metadata import version
from pathlib import Path

import vmx
from vmx import ConstructionStatus, PropertyChangedMessage, StatusTransitionError

from notes_app.notes import InMemoryNoteStore, NotebookApp, NoteConflictError, NoteModel

ROOT = Path(__file__).resolve().parents[1]
SEED = (
    NoteModel(id="1", title="Groceries", body="Milk, eggs"),
    NoteModel(id="2", title="Ideas", body="Write a starter"),
)


class StarterSmokeTest(unittest.TestCase):
    def test_installed_version_equals_the_requirements_pin(self) -> None:
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        match = re.search(r"^vmx==(\S+)$", text, re.MULTILINE)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(vmx.__version__, match.group(1))
        self.assertEqual(version("vmx"), match.group(1))

    def test_construct_edit_command_error_and_dispose(self) -> None:
        store = InMemoryNoteStore()
        app = NotebookApp(store, SEED)
        changes: list[str] = []
        subscription = app.hub.messages.subscribe(
            lambda message: (
                changes.append(message.property_name)
                if isinstance(message, PropertyChangedMessage)
                else None
            )
        )
        notes = []
        try:
            # Construct: the first construct() builds and constructs the children.
            self.assertFalse(app.save_current.can_execute())
            app.start()
            notes = list(app.notebook)
            self.assertTrue(app.notebook.is_constructed)
            self.assertEqual(len(notes), 2)
            self.assertTrue(all(note.is_constructed for note in notes))
            current = app.notebook.current
            self.assertIsNotNone(current)
            assert current is not None
            self.assertEqual(current.model.id, "1")

            # Edit: assigning a new model publishes a change on the hub.
            app.rename_current("Groceries for Monday")
            self.assertEqual(current.modeled_hint, "Groceries for Monday")
            self.assertIn("model", changes)

            # Command: the predicate tracks the title, and the task saves the note.
            app.rename_current("   ")
            self.assertFalse(app.save_current.can_execute())
            app.rename_current("Groceries for Monday")
            self.assertTrue(app.save_current.can_execute())
            app.save_current.execute()
            saved = store.get("1")
            self.assertEqual(saved.title if saved else None, "Groceries for Monday")

            # Error: the store error propagates to the caller of execute().
            app.select("2")
            app.rename_current("Groceries for Monday")
            with self.assertRaises(NoteConflictError):
                app.save_current.execute()
            self.assertIsNone(store.get("2"))

            # Recover: fix the title and save again.
            app.rename_current("Ideas for Monday")
            app.save_current.execute()
            self.assertEqual(len(store), 2)
        finally:
            subscription.dispose()
            app.dispose()

        # Dispose: terminal for every VM and the command; idempotent for the app.
        self.assertIs(app.notebook.status, ConstructionStatus.DISPOSED)
        self.assertTrue(all(note.status is ConstructionStatus.DISPOSED for note in notes))
        self.assertFalse(app.save_current.can_execute())
        with self.assertRaises(StatusTransitionError):
            app.notebook.construct()
        app.dispose()


if __name__ == "__main__":
    unittest.main()
