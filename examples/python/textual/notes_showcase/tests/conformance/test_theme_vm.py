"""Conformance scenarios THEME-001..005 for the Textual flavor.

Mirrors ``spec/proposals/2026-06-02-theme-vm-scenario.md`` §6. Each scenario
maps one-to-one to the canonical wording in the contract — they exist as the
cross-language fixture row that the C# / TypeScript flavors must satisfy in
identical form. ``BuilderValidationError`` is the C# / TS idiom for unknown-
preset rejection; the Python flavor raises a plain ``ValueError`` (flavor-
idiomatic, see scenario §6 THEME-002 wording: "``BuilderValidationError`` (or
flavor-idiomatic exception)").
"""

from __future__ import annotations

from typing import cast

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message

from notes_showcase.messages.theme_changed import ThemeChangedMessage
from notes_showcase.models.theme_model import (
    DARK_PRESET,
    HIGH_CONTRAST_PRESET,
    LIGHT_PRESET,
    PRESETS,
    ThemeModel,
)
from notes_showcase.viewmodels.theme_vm import ThemeVM


def _build(
    initial: ThemeModel = DARK_PRESET,
    *,
    host_theme_provider: object = None,
) -> ThemeVM:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    builder = ThemeVM.builder().name("theme").initial(initial).services(hub, dispatcher)
    if host_theme_provider is not None:
        from collections.abc import Callable

        builder = builder.host_theme_provider(
            cast(Callable[[], ThemeModel], host_theme_provider)
        )
    vm = builder.build()
    vm.construct()
    return vm


def _capture(vm: ThemeVM) -> list[ThemeChangedMessage[ThemeVM]]:
    captured: list[ThemeChangedMessage[ThemeVM]] = []

    def _on_next(m: Message) -> None:
        if isinstance(m, ThemeChangedMessage):
            captured.append(cast(ThemeChangedMessage[ThemeVM], m))

    vm.hub.messages.subscribe(on_next=_on_next)
    return captured


# ---------------------------------------------------------------------------
# THEME-001 — setThemeCommand("dark") publishes one ThemeChangedMessage and
# the current_theme reflects the dark-preset accent.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THEME-001")
def test_THEME_001_set_theme_dark_publishes_one_message() -> None:
    # Start on LIGHT so switching to DARK is an actual transition.
    vm = _build(initial=LIGHT_PRESET)
    captured = _capture(vm)

    vm.set_theme_command.execute("dark")

    assert len(captured) == 1, f"Expected exactly one message, got {len(captured)}"
    assert vm.current_theme.value.name == "dark"
    assert vm.current_theme.value.accent_color == PRESETS["dark"].accent_color


# ---------------------------------------------------------------------------
# THEME-002 — setThemeCommand("unknown-preset") raises (BuilderValidationError
# in C# / TS; flavor-idiomatic ValueError in Python) without publishing.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THEME-002")
def test_THEME_002_set_theme_unknown_raises_without_publishing() -> None:
    vm = _build()
    captured = _capture(vm)

    with pytest.raises(ValueError):
        vm.set_theme_command.execute("unknown-preset")

    assert captured == []


# ---------------------------------------------------------------------------
# THEME-003 — toggle_high_contrast flips the flag without changing accent
# or scale.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THEME-003")
def test_THEME_003_toggle_high_contrast_preserves_accent_and_scale() -> None:
    vm = _build()
    accent_before = vm.current_theme.value.accent_color
    scale_before = vm.current_theme.value.font_scale_factor
    hc_before = vm.current_theme.value.high_contrast

    vm.toggle_high_contrast.execute()

    assert vm.current_theme.value.high_contrast is not hc_before
    assert vm.current_theme.value.accent_color == accent_before
    assert vm.current_theme.value.font_scale_factor == scale_before


# ---------------------------------------------------------------------------
# THEME-004 — set_font_scale clamps to [0.75..1.75] and publishes a single
# message; values outside the range result in clamped emission, not rejection.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THEME-004")
def test_THEME_004_set_font_scale_clamps_and_publishes_once() -> None:
    vm = _build()
    captured = _capture(vm)

    vm.set_font_scale.execute(3.5)  # well above max

    assert len(captured) == 1
    assert vm.current_theme.value.font_scale_factor == 1.75

    # And the clamp on the other side, on a fresh VM to isolate the message
    # count.
    vm2 = _build()
    captured2 = _capture(vm2)
    vm2.set_font_scale.execute(0.25)  # well below min
    assert len(captured2) == 1
    assert vm2.current_theme.value.font_scale_factor == 0.75


# ---------------------------------------------------------------------------
# THEME-005 — follow_system_command sets follows_system=True; calling
# set_theme_command afterward sets follows_system=False automatically.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THEME-005")
def test_THEME_005_follow_system_then_set_theme_clears_flag() -> None:
    # Use a provider returning HIGH_CONTRAST so the host snapshot is distinct
    # from the initial LIGHT preset (otherwise no message + the flag would
    # still flip but the visible state would be ambiguous).
    vm = _build(initial=LIGHT_PRESET, host_theme_provider=lambda: HIGH_CONTRAST_PRESET)

    vm.follow_system_command.execute()
    assert vm.current_theme.value.follows_system is True
    assert vm.current_theme.value.name == "high-contrast"

    vm.set_theme_command.execute("dark")
    assert vm.current_theme.value.follows_system is False
    assert vm.current_theme.value.name == "dark"
