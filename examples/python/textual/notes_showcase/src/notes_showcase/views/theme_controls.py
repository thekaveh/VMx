"""ThemeControlsView — the theme control strip of ADR-0201 §2.4.

The strip has one button for each preset (``set_theme_command`` with the
preset name), a high-contrast toggle (``toggle_high_contrast``), and a
decrease and an increase font-size button (``set_font_scale`` with the current
factor minus or plus 0.1; :class:`ThemeVM` clamps the result). There is no
accent or follow-system control.

The preset and high-contrast buttons bind through the CommandBridge. The
font-size step depends on the current factor, so those two buttons forward
their press to a module-level helper. The bindings are disposed on unmount.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button

from notes_showcase.viewmodels.theme_vm import ThemeVM
from notes_showcase.views.adapter import bind_command

# ADR-0201 §2.4: the font-size buttons step the factor by 0.1.
_FONT_SCALE_STEPS: dict[str, float] = {
    "theme_font_smaller": -0.1,
    "theme_font_larger": 0.1,
}


def _preset_button_id(name: str) -> str:
    return f"theme_preset_{name.replace('-', '_')}"


def _step_font_scale(theme: ThemeVM, button_id: str | None) -> None:
    """Run ``set_font_scale`` with the current factor plus the button's step.

    ``ThemeVM`` clamps the sum, as in every flagship (ADR-0201 §2.4).
    """
    step = _FONT_SCALE_STEPS.get(button_id or "")
    if step is not None:
        theme.set_font_scale.execute(theme.model.font_scale_factor + step)


def _wire_bindings(view: ThemeControlsView) -> CompositeDisposable:
    theme = view._vm
    bindings = CompositeDisposable(
        bind_command(
            view.query_one("#theme_high_contrast", Button),
            theme.toggle_high_contrast,
        ),
    )
    for preset in theme.presets:
        button = view.query_one(f"#{_preset_button_id(preset.name)}", Button)
        bindings.add(bind_command(button, theme.set_theme_command, preset.name))
    return bindings


class ThemeControlsView(Horizontal):
    """One-row strip: preset buttons, high contrast, and font size."""

    def __init__(self, vm: ThemeVM) -> None:
        super().__init__(id="theme_controls")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()

    def compose(self) -> ComposeResult:
        for preset in self._vm.presets:
            yield Button(preset.name, id=_preset_button_id(preset.name), compact=True)
        yield Button("HC", id="theme_high_contrast", tooltip="Toggle high contrast", compact=True)
        yield Button("A-", id="theme_font_smaller", tooltip="Decrease font size", compact=True)
        yield Button("A+", id="theme_font_larger", tooltip="Increase font size", compact=True)

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)

    def on_unmount(self) -> None:
        self._disposables.dispose()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        _step_font_scale(self._vm, event.button.id)
