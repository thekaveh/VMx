"""View layer for the notes-showcase (Textual TUI).

Per scenario §6.1 / §8.1, the view layer owns:

* the **adapter** sub-package — the *only* code permitted to subscribe to a
  VM's hub. It translates VMx primitives (``PropertyChangedMessage``,
  ``RelayCommand``, ``CollectionChangedEvent``, ``IDialogService``,
  ``Dispatcher``) into Textual-native widget state.
* widget views (Phase 5.b — ``NotesShowcaseApp`` + ``MainScreen`` + per-pane
  Textual widget classes).
* modal screens (Phase 5.b — :mod:`notes_showcase.views.modals`).
"""

from notes_showcase.views.app import NotesShowcaseApp
from notes_showcase.views.main_screen import MainScreen

__all__ = ["MainScreen", "NotesShowcaseApp"]
