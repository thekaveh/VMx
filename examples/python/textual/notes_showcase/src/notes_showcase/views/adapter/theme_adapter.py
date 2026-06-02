"""ThemeAdapter — projects :class:`ThemeVM` state onto a Textual :class:`App`.

Pure adapter — no business logic. Subscribes to
``theme_vm.current_theme.value_changed`` and rewrites the four CSS variables
that ``views/theme.tcss`` consumes (``$bg`` / ``$accent`` / ``$panel`` /
``$text-muted``) by registering a Textual :class:`textual.theme.Theme` and
flipping :attr:`App.theme` to its name.

The Textual ``Theme`` API is the cleanest seam: it ships ``background`` /
``foreground`` / ``panel`` / ``accent`` first-class fields, and any extra
custom variables (we surface ``text-muted`` for the muted-text colour) ride
through the ``variables`` dict and become ``$<name>`` tokens in stylesheets.

See ``spec/proposals/2026-06-02-theme-vm-scenario.md`` §5 (Textual flavor).
"""

from __future__ import annotations

from reactivex.abc import DisposableBase
from textual.app import App
from textual.theme import Theme

from notes_showcase.models.theme_model import ThemeModel
from notes_showcase.viewmodels.theme_vm import ThemeVM

# Theme name registered with Textual — every model is projected onto a single
# rolling theme name so flipping ``app.theme`` re-applies the fresh palette
# without leaking a registry entry per change.
_THEME_NAME = "vmx-notes-showcase"


def _to_textual_theme(model: ThemeModel) -> Theme:
    """Project a :class:`ThemeModel` onto a Textual :class:`Theme`.

    The ``variables`` dict carries any palette tokens that don't have a
    first-class :class:`Theme` field — currently just ``text-muted``.
    ``dark=True`` for the dark + high-contrast presets so Textual selects the
    dark ANSI fallback when the terminal doesn't support truecolor.
    """
    return Theme(
        name=_THEME_NAME,
        primary=model.accent_color,
        accent=model.accent_color,
        background=model.bg_color,
        foreground=model.text_color,
        panel=model.panel_color,
        dark=model.name != "light",
        variables={"text-muted": model.muted_text_color},
    )


def bind_theme(app: App[object], theme_vm: ThemeVM) -> DisposableBase:
    """Bind ``theme_vm.current_theme`` → ``app.theme``.

    Seeds the app with the current model (so the very first render uses the
    VM-driven palette), then subscribes to
    ``theme_vm.current_theme.value_changed`` and re-projects on every effective
    change.

    Returns the underlying :class:`reactivex.abc.DisposableBase` so the caller
    can ``dispose()`` to unbind.
    """

    def _apply(model: ThemeModel) -> None:
        # ``register_theme`` overwrites the existing registration when the
        # name matches — that's the rolling-theme strategy described above.
        app.register_theme(_to_textual_theme(model))
        # Setting ``app.theme`` to the same name still triggers the
        # ``_watch_theme`` callback, which re-applies the stylesheet variables
        # downstream. Required for the second-and-onward updates.
        app.theme = _THEME_NAME

    # Seed from the VM's current value. If the DerivedProperty has no value
    # yet (no source emission), skip the seed — the subscription below will
    # cover the next tick.
    try:
        _apply(theme_vm.current_theme.value)
    except RuntimeError:
        pass

    return theme_vm.current_theme.value_changed.subscribe(on_next=_apply)
