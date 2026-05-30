"""View layer for the notes-showcase (Textual TUI).

Per scenario §6.1 / §8.1, the view layer owns:

* the **adapter** sub-package — the *only* code permitted to subscribe to a
  VM's hub. It translates VMx primitives (``PropertyChangedMessage``,
  ``RelayCommand``, ``CollectionChangedEvent``, ``IDialogService``,
  ``Dispatcher``) into Textual-native widget state.
* widget views (composed in Phase 5.b — not present yet).
* modal screens (Phase 5.b).

Phase 4.b ships only the adapter. Importing :mod:`notes_showcase.views.adapter`
does not pull in any Textual widget code beyond what the bridges require, so
the existing VM tests remain runtime-isolated from the UI.
"""
