"""Unit tests for :class:`notes_showcase.viewmodels.theme_vm.ThemeVM`.

Exercises every command, every public DerivedProperty, the
:class:`ThemeChangedMessage` publication, the builder pattern, and the
font-scale clamp. Conformance scenarios live in
``tests/conformance/test_theme_vm.py``.
"""

from __future__ import annotations

from typing import cast

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import MessageHub, PropertyChangedMessage, RxDispatcher
from vmx.messages.protocols import Message

from notes_showcase.messages.theme_changed import ThemeChangedMessage
from notes_showcase.models.theme_model import (
    DARK_PRESET,
    FONT_SCALE_MAX,
    FONT_SCALE_MIN,
    HIGH_CONTRAST_PRESET,
    LIGHT_PRESET,
    PRESETS,
    ThemeModel,
)
from notes_showcase.viewmodels.theme_vm import ThemeVM, ThemeVMBuilder


def _build(initial: ThemeModel = DARK_PRESET) -> ThemeVM:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    vm = (
        ThemeVM.builder()
        .name("theme")
        .hint("App theming")
        .initial(initial)
        .services(hub, dispatcher)
        .build()
    )
    vm.construct()
    return vm


def _capture_theme_messages(vm: ThemeVM) -> list[ThemeChangedMessage[ThemeVM]]:
    captured: list[ThemeChangedMessage[ThemeVM]] = []

    def _on_next(m: Message) -> None:
        if isinstance(m, ThemeChangedMessage):
            captured.append(cast(ThemeChangedMessage[ThemeVM], m))

    vm.hub.messages.subscribe(on_next=_on_next)
    return captured


# ── Construction / builder ─────────────────────────────────────────────────


def test_builder_requires_name() -> None:
    with pytest.raises(ValueError, match="name"):
        ThemeVM.builder().build()


def test_builder_returns_themevmbuilder_instance() -> None:
    assert isinstance(ThemeVM.builder(), ThemeVMBuilder)


def test_default_initial_is_dark_preset() -> None:
    vm = _build()
    assert vm.model == DARK_PRESET
    assert vm.current_theme.value == DARK_PRESET


def test_custom_initial_is_honoured() -> None:
    vm = _build(initial=LIGHT_PRESET)
    assert vm.current_theme.value == LIGHT_PRESET


# ── Public surface ─────────────────────────────────────────────────────────


def test_presets_exposes_three_known_models() -> None:
    vm = _build()
    assert vm.presets == (DARK_PRESET, LIGHT_PRESET, HIGH_CONTRAST_PRESET)
    assert all(isinstance(p, ThemeModel) for p in vm.presets)


def test_presets_dict_matches_module_registry() -> None:
    # Sanity: the module-level PRESETS table is the same one the VM resolves
    # against in set_theme_command.
    assert set(PRESETS) == {"dark", "light", "high-contrast"}
    for name, model in PRESETS.items():
        assert model.name == name


def test_follows_system_mirrors_model_flag() -> None:
    vm = _build()
    assert vm.follows_system.value is False
    vm.follow_system_command.execute()
    assert vm.follows_system.value is True


# ── set_theme_command ──────────────────────────────────────────────────────


def test_set_theme_dark_to_light_changes_model() -> None:
    vm = _build()
    vm.set_theme_command.execute("light")
    assert vm.current_theme.value.name == "light"
    assert vm.current_theme.value.accent_color == LIGHT_PRESET.accent_color


def test_set_theme_publishes_theme_changed_message_once() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_theme_command.execute("light")
    assert len(captured) == 1
    assert captured[0].prev_theme == DARK_PRESET
    assert captured[0].curr_theme.name == "light"


def test_set_theme_unknown_preset_raises_value_error() -> None:
    vm = _build()
    with pytest.raises(ValueError, match="Unknown theme preset"):
        vm.set_theme_command.execute("midnight-pastel")


def test_set_theme_unknown_does_not_publish_message() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    with pytest.raises(ValueError):
        vm.set_theme_command.execute("midnight-pastel")
    assert captured == []


def test_set_theme_none_is_noop() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_theme_command.execute(None)
    assert captured == []


def test_set_theme_empty_string_is_noop() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_theme_command.execute("")
    assert captured == []


def test_set_theme_to_current_preset_emits_no_message() -> None:
    # ``set_theme_command.execute("dark")`` on a dark VM with follows_system
    # already False is a no-op (equality guard in _apply_model).
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_theme_command.execute("dark")
    assert captured == []


# ── toggle_high_contrast ───────────────────────────────────────────────────


def test_toggle_high_contrast_flips_flag_without_changing_accent_or_scale() -> None:
    vm = _build()
    accent_before = vm.current_theme.value.accent_color
    scale_before = vm.current_theme.value.font_scale_factor
    vm.toggle_high_contrast.execute()
    assert vm.current_theme.value.high_contrast is True
    assert vm.current_theme.value.accent_color == accent_before
    assert vm.current_theme.value.font_scale_factor == scale_before


def test_toggle_high_contrast_is_idempotent_over_two_calls() -> None:
    vm = _build()
    vm.toggle_high_contrast.execute()
    vm.toggle_high_contrast.execute()
    assert vm.current_theme.value.high_contrast is False


def test_toggle_high_contrast_publishes_theme_changed_message() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.toggle_high_contrast.execute()
    assert len(captured) == 1
    assert captured[0].curr_theme.high_contrast is True


# ── set_accent_color ───────────────────────────────────────────────────────


def test_set_accent_color_updates_model_and_publishes() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_accent_color.execute("#FF5733")
    assert vm.current_theme.value.accent_color == "#FF5733"
    assert len(captured) == 1


def test_set_accent_color_to_existing_value_is_noop() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_accent_color.execute(DARK_PRESET.accent_color)
    assert captured == []


def test_set_accent_color_empty_or_none_is_noop() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_accent_color.execute("")
    vm.set_accent_color.execute(None)
    assert captured == []


# ── set_font_scale ─────────────────────────────────────────────────────────


def test_set_font_scale_within_range_passes_through() -> None:
    vm = _build()
    vm.set_font_scale.execute(1.25)
    assert vm.current_theme.value.font_scale_factor == 1.25


def test_set_font_scale_below_min_is_clamped() -> None:
    vm = _build()
    vm.set_font_scale.execute(0.1)
    assert vm.current_theme.value.font_scale_factor == FONT_SCALE_MIN


def test_set_font_scale_above_max_is_clamped() -> None:
    vm = _build()
    vm.set_font_scale.execute(5.0)
    assert vm.current_theme.value.font_scale_factor == FONT_SCALE_MAX


def test_set_font_scale_emits_single_theme_changed_message() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_font_scale.execute(1.5)
    assert len(captured) == 1
    assert captured[0].curr_theme.font_scale_factor == 1.5


def test_set_font_scale_clamped_to_same_value_emits_no_message() -> None:
    # Min-clamp twice — second call doesn't change anything.
    vm = _build()
    vm.set_font_scale.execute(0.1)
    captured = _capture_theme_messages(vm)
    vm.set_font_scale.execute(0.05)
    assert captured == []


def test_set_font_scale_none_is_noop() -> None:
    vm = _build()
    captured = _capture_theme_messages(vm)
    vm.set_font_scale.execute(None)
    assert captured == []


# ── follow_system_command ──────────────────────────────────────────────────


def test_follow_system_command_default_adopts_dark_preset_under_flag() -> None:
    # Start on LIGHT so the host snapshot (DARK by default) is a real change.
    vm = _build(initial=LIGHT_PRESET)
    captured = _capture_theme_messages(vm)
    vm.follow_system_command.execute()
    assert vm.current_theme.value.follows_system is True
    assert vm.current_theme.value.name == "dark"  # default provider
    assert len(captured) == 1


def test_follow_system_command_uses_custom_provider() -> None:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    vm = (
        ThemeVM.builder()
        .name("theme")
        .initial(DARK_PRESET)
        .services(hub, dispatcher)
        .host_theme_provider(lambda: LIGHT_PRESET)
        .build()
    )
    vm.construct()
    vm.follow_system_command.execute()
    assert vm.current_theme.value.name == "light"
    assert vm.current_theme.value.follows_system is True


def test_set_theme_after_follow_system_clears_follows_system_flag() -> None:
    # Mirrors THEME-005 (conformance) at the unit-test level.
    vm = _build(initial=LIGHT_PRESET)
    vm.follow_system_command.execute()
    assert vm.current_theme.value.follows_system is True
    vm.set_theme_command.execute("light")
    assert vm.current_theme.value.follows_system is False


# ── DerivedProperty value_changed ──────────────────────────────────────────


def test_current_theme_value_changed_fires_on_set_theme() -> None:
    vm = _build()
    captured: list[ThemeModel] = []
    vm.current_theme.value_changed.subscribe(on_next=captured.append)
    vm.set_theme_command.execute("light")
    assert len(captured) == 1
    assert captured[0].name == "light"


def test_follows_system_value_changed_fires_on_follow_system_command() -> None:
    vm = _build()
    captured: list[bool] = []
    vm.follows_system.value_changed.subscribe(on_next=captured.append)
    vm.follow_system_command.execute()
    assert captured == [True]


# ── PropertyChangedMessage parity ──────────────────────────────────────────


def test_property_changed_message_fires_for_model_on_set_theme() -> None:
    vm = _build()
    observed: list[str] = []

    def _on_next(m: Message) -> None:
        if isinstance(m, PropertyChangedMessage):
            observed.append(cast(PropertyChangedMessage[ThemeVM], m).property_name)

    vm.hub.messages.subscribe(on_next=_on_next)
    vm.set_theme_command.execute("light")
    assert "model" in observed


# ── Builder pattern ────────────────────────────────────────────────────────


def test_builder_is_immutable_each_setter_returns_new_instance() -> None:
    b1 = ThemeVM.builder()
    b2 = b1.name("theme")
    b3 = b2.hint("App theme")
    assert b1 is not b2
    assert b2 is not b3


def test_builder_default_initial_is_dark_preset_constant() -> None:
    # Builder's _initial default before any .initial(...) call.
    b = ThemeVMBuilder()
    assert b._initial == DARK_PRESET


def test_builder_default_hub_and_dispatcher_are_supplied() -> None:
    # Build with only name set — hub + dispatcher get filled in.
    vm = ThemeVM.builder().name("theme").build()
    vm.construct()
    assert vm.hub is not None


# ── Lifecycle ──────────────────────────────────────────────────────────────


def test_dispose_is_idempotent() -> None:
    vm = _build()
    vm.dispose()
    # Second dispose must not raise.
    vm.dispose()


def test_dispose_releases_commands_and_subjects() -> None:
    vm = _build()
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED
