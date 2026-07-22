"""Unit tests for :mod:`notes_showcase.views.adapter.theme_adapter`.

Verifies the model→Theme projection and that :func:`bind_theme` registers and
flips the active :class:`textual.app.App` theme on every VM emission.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from notes_showcase.models.theme_model import (
    DARK_PRESET,
    HIGH_CONTRAST_PRESET,
    LIGHT_PRESET,
)
from notes_showcase.viewmodels.theme_vm import ThemeVM
from notes_showcase.views.adapter.theme_adapter import (
    _THEME_NAME,
    _to_textual_theme,
    bind_theme,
)


# ── Pure projection ────────────────────────────────────────────────────────


def test_to_textual_theme_uses_dark_preset_colours() -> None:
    theme = _to_textual_theme(DARK_PRESET)
    assert theme.name == _THEME_NAME
    assert theme.accent == DARK_PRESET.accent_color
    assert theme.primary == DARK_PRESET.accent_color
    assert theme.background == DARK_PRESET.bg_color
    assert theme.foreground == DARK_PRESET.text_color
    assert theme.panel == DARK_PRESET.panel_color
    assert theme.dark is True
    assert theme.variables["text-muted"] == DARK_PRESET.muted_text_color


def test_to_textual_theme_light_preset_is_not_dark() -> None:
    theme = _to_textual_theme(LIGHT_PRESET)
    assert theme.dark is False
    assert theme.background == LIGHT_PRESET.bg_color


def test_to_textual_theme_high_contrast_preset_is_dark() -> None:
    theme = _to_textual_theme(HIGH_CONTRAST_PRESET)
    assert theme.dark is True
    assert theme.accent == HIGH_CONTRAST_PRESET.accent_color


def test_to_textual_theme_renders_independent_high_contrast_toggle() -> None:
    theme = _to_textual_theme(replace(LIGHT_PRESET, high_contrast=True))
    assert theme.dark is True
    assert theme.background == "#000000"
    assert theme.foreground == "#FFFFFF"
    assert theme.panel == "#000000"
    assert theme.variables["text-muted"] == "#FFFFFF"
    assert theme.accent == LIGHT_PRESET.accent_color


# ── bind_theme ─────────────────────────────────────────────────────────────


class _SmokeApp(App[None]):
    """Minimal Textual app used to drive ``bind_theme``."""

    def compose(self) -> ComposeResult:
        yield Static("smoke")


@pytest.mark.asyncio
async def test_bind_theme_registers_and_flips_app_theme() -> None:
    app = _SmokeApp()
    async with app.run_test() as pilot:
        vm = ThemeVM.builder().name("theme").initial(LIGHT_PRESET).build()
        vm.construct()
        sub = bind_theme(app, vm)
        try:
            await pilot.pause()
            # Initial seed: the rolling theme name is registered + activated.
            assert app.theme == _THEME_NAME
            assert _THEME_NAME in app.available_themes
            registered = app.get_theme(_THEME_NAME)
            assert registered is not None
            assert registered.background == LIGHT_PRESET.bg_color

            # Drive a VM transition; the adapter re-registers and reflows.
            vm.set_theme_command.execute("dark")
            await pilot.pause()
            registered2 = app.get_theme(_THEME_NAME)
            assert registered2 is not None
            assert registered2.background == DARK_PRESET.bg_color
        finally:
            sub.dispose()
            vm.dispose()


@pytest.mark.asyncio
async def test_bind_theme_handles_unseeded_derived_property_gracefully() -> None:
    # The Textual ``app.theme`` is only seeded if the VM's DerivedProperty has
    # a value. In practice ``ComponentVMOf`` seeds its model on construction,
    # so this exercises the defensive ``RuntimeError`` swallow.
    app = _SmokeApp()
    async with app.run_test() as pilot:
        vm = ThemeVM.builder().name("theme").initial(DARK_PRESET).build()
        vm.construct()
        sub = bind_theme(app, vm)
        try:
            await pilot.pause()
            assert app.theme == _THEME_NAME
        finally:
            sub.dispose()
            vm.dispose()
