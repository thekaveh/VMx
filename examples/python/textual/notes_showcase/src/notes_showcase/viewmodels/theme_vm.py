"""ThemeVM — Textual-flavor implementation of the theme-as-VM contract.

Implements the surface defined in
``spec/proposals/2026-06-02-theme-vm-scenario.md`` §4:

* ``current_theme``      — :class:`vmx.DerivedProperty` mirroring ``self.model``.
* ``presets``            — tuple of named presets (``DARK_PRESET``,
  ``LIGHT_PRESET``, ``HIGH_CONTRAST_PRESET``).
* ``follows_system``     — :class:`vmx.DerivedProperty` mirroring
  ``model.follows_system``.
* ``set_theme_command``  — :class:`vmx.RelayCommandOf[str]` accepting a preset
  name; raises ``ValueError`` on unknown preset.
* ``toggle_high_contrast`` — non-parameterised toggle of
  ``model.high_contrast`` (preserves accent + scale).
* ``set_accent_color``   — :class:`vmx.RelayCommandOf[str]` accepting a hex
  colour string.
* ``set_font_scale``     — :class:`vmx.RelayCommandOf[float]` clamping to
  ``[0.75..1.75]``.
* ``follow_system_command`` — sets ``follows_system=True`` and re-reads the
  host theme via the injected :data:`host_theme_provider` callback.

Every effective mutation publishes a :class:`ThemeChangedMessage` carrying the
prior and the freshly-adopted :class:`ThemeModel`. The base
``ComponentVMOf._set_model`` continues to publish its standard
``PropertyChangedMessage("model")`` so generic adapters (the property bridge,
the status bar) keep working without ThemeVM-specific code.

TODO(spec v2.5.0):
    Wire-up into :class:`WorkspaceVM` is intentionally out of scope here.
    Composing a seventh child into ``WorkspaceVM`` requires ``AggregateVM7``
    (currently only ``AggregateVM6`` exists in core) plus a matching
    cross-flavor builder. Track that under task #97 follow-up / ADR-0036 §3.D.
    Until then, hosts construct ``ThemeVM`` standalone and bind the
    :class:`~notes_showcase.views.adapter.theme_adapter.ThemeAdapter`
    explicitly at app boot.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import cast

from reactivex.subject import BehaviorSubject

from vmx import (
    ComponentVMOf,
    DerivedProperty,
    MessageHub,
    RelayCommand,
    RelayCommandOf,
    RxDispatcher,
    from_sources,
)
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher

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


def _default_host_theme_provider() -> ThemeModel:
    """Fallback :data:`host_theme_provider` — used when no host hook is wired.

    Returns the :data:`DARK_PRESET` so ``follow_system_command`` is always
    safe to execute, even in unit tests or non-Textual hosts.
    """
    return DARK_PRESET


class ThemeVM(ComponentVMOf[ThemeModel]):
    """Theming viewmodel — owns the active :class:`ThemeModel`.

    Every effective mutation publishes a :class:`ThemeChangedMessage` on the
    hub. The DerivedProperties (``current_theme``, ``follows_system``) re-emit
    via an internal ``BehaviorSubject[ThemeModel]`` that the VM nudges from
    :meth:`_set_model`.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        initial: ThemeModel,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        host_theme_provider: Callable[[], ThemeModel] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            initial_model=initial,
            modeled_hinter=lambda m: m.name,
            on_model_changed=None,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._host_theme_provider = (
            host_theme_provider
            if host_theme_provider is not None
            else _default_host_theme_provider
        )

        # Drives both DerivedProperties. Seeded with the initial model; updated
        # whenever ``_set_model`` accepts a new value.
        self._model_subject: BehaviorSubject[ThemeModel] = BehaviorSubject(initial)

        self._current_theme: DerivedProperty[ThemeModel] = from_sources(
            self._model_subject,
            transform=lambda m: cast(ThemeModel, m),
        )
        self._follows_system: DerivedProperty[bool] = from_sources(
            self._model_subject,
            transform=lambda m: cast(ThemeModel, m).follows_system,
        )

        # Presets — exposed as a tuple so callers can iterate / index but not
        # mutate the registry (the model layer's ``PRESETS`` dict is the
        # authoritative source).
        self._presets: tuple[ThemeModel, ...] = (
            DARK_PRESET,
            LIGHT_PRESET,
            HIGH_CONTRAST_PRESET,
        )

        # ── Commands ────────────────────────────────────────────────────────
        # set_theme_command — parameterised by preset name. Predicate refuses
        # ``None`` / empty strings so views can bind unconditionally. The
        # unknown-preset case is handled inside the task (raises ``ValueError``)
        # because the predicate cannot raise per the RelayCommand contract.
        self._set_theme_command: RelayCommandOf[str] = (
            RelayCommandOf[str]
            .builder()
            .predicate(lambda arg: arg is not None and bool(arg))
            .task(self._set_theme)
            .build()
        )

        # toggle_high_contrast — non-parameterised; predicate is always-true
        # while the VM is alive.
        self._toggle_high_contrast: RelayCommand = (
            RelayCommand.builder()
            .predicate(lambda: True)
            .task(self._toggle_high_contrast_impl)
            .build()
        )

        # set_accent_color — parameterised by hex string. Predicate rejects
        # empty strings; the task accepts any non-empty hex (parsing is the
        # adapter's job — keeps the VM framework-agnostic).
        self._set_accent_color: RelayCommandOf[str] = (
            RelayCommandOf[str]
            .builder()
            .predicate(lambda arg: arg is not None and bool(arg))
            .task(self._set_accent_color_impl)
            .build()
        )

        # set_font_scale — parameterised by float. Predicate accepts any
        # non-None value; the task clamps to the model's allowed range.
        self._set_font_scale: RelayCommandOf[float] = (
            RelayCommandOf[float]
            .builder()
            .predicate(lambda arg: arg is not None)
            .task(self._set_font_scale_impl)
            .build()
        )

        # follow_system_command — non-parameterised. Sets ``follows_system``
        # and adopts the host theme snapshot.
        self._follow_system_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(lambda: True)
            .task(self._follow_system_impl)
            .build()
        )

    # ── Public surface ──────────────────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        """Hub accessor — exposed so views/tests can subscribe."""
        return self._hub

    @property
    def current_theme(self) -> DerivedProperty[ThemeModel]:
        """Live view of the active model (mirrors :attr:`model`)."""
        return self._current_theme

    @property
    def presets(self) -> tuple[ThemeModel, ...]:
        """Immutable tuple of the known named presets."""
        return self._presets

    @property
    def follows_system(self) -> DerivedProperty[bool]:
        """Live view of ``model.follows_system``."""
        return self._follows_system

    @property
    def set_theme_command(self) -> RelayCommandOf[str]:
        return self._set_theme_command

    @property
    def toggle_high_contrast(self) -> RelayCommand:
        return self._toggle_high_contrast

    @property
    def set_accent_color(self) -> RelayCommandOf[str]:
        return self._set_accent_color

    @property
    def set_font_scale(self) -> RelayCommandOf[float]:
        return self._set_font_scale

    @property
    def follow_system_command(self) -> RelayCommand:
        return self._follow_system_command

    # ── Command implementations ─────────────────────────────────────────────
    def _set_theme(self, name: str | None) -> None:
        # Defensive: the predicate already rejects ``None`` / empty, but the
        # type narrows here too for mypy. Idempotency note: when the requested
        # preset is already active *and* ``follows_system`` is already False,
        # no message is emitted (handled by ``_apply_model`` equality guard).
        if name is None or not name:
            return
        if name not in PRESETS:
            raise ValueError(
                f"Unknown theme preset: {name!r}. Known presets: {sorted(PRESETS)!r}."
            )
        preset = PRESETS[name]
        # Preserve user-tuned accent + scale when switching presets? Per the
        # scenario the answer is "no — presets are atomic" — switching to a
        # preset adopts its accent. The high-contrast flag is part of the
        # preset too. ``follows_system`` is forced False per scenario §6
        # THEME-005 (``setThemeCommand`` after ``followSystem`` clears it).
        self._apply_model(dataclasses.replace(preset, follows_system=False))

    def _toggle_high_contrast_impl(self) -> None:
        # Non-destructive flip — keeps accent / scale / colours; only the flag
        # changes. Adapter is responsible for interpreting the flag (e.g.
        # bumping contrast on top of the active preset).
        self._apply_model(
            dataclasses.replace(
                self._model,
                high_contrast=not self._model.high_contrast,
            )
        )

    def _set_accent_color_impl(self, hex_color: str | None) -> None:
        if hex_color is None or not hex_color:
            return
        if self._model.accent_color == hex_color:
            return
        self._apply_model(dataclasses.replace(self._model, accent_color=hex_color))

    def _set_font_scale_impl(self, scale: float | None) -> None:
        if scale is None:
            return
        clamped = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
        if self._model.font_scale_factor == clamped:
            return
        self._apply_model(dataclasses.replace(self._model, font_scale_factor=clamped))

    def _follow_system_impl(self) -> None:
        host = self._host_theme_provider()
        # Always adopt the host snapshot under ``follows_system=True`` — even
        # if the host happens to match the current preset, we still need to
        # flip the follows_system flag to True. Equality guard in
        # ``_apply_model`` then decides whether a message fires.
        self._apply_model(dataclasses.replace(host, follows_system=True))

    # ── Internal apply pipeline ─────────────────────────────────────────────
    def _apply_model(self, new_model: ThemeModel) -> None:
        """Adopt ``new_model`` if it differs from the current; emit on success.

        Routes through :meth:`_set_model` (which preserves the standard
        ``PropertyChangedMessage("model")`` semantics) and additionally
        publishes a :class:`ThemeChangedMessage` carrying both halves. The
        ``BehaviorSubject`` is re-nudged so DerivedProperty subscribers fire.
        """
        prev = self._model
        if prev == new_model:
            return
        self._set_model(new_model)
        # Drive DerivedProperty subscribers — the BehaviorSubject does the
        # equality guard via DerivedProperty's internal de-dupe.
        self._model_subject.on_next(new_model)
        self._hub.send(ThemeChangedMessage.create(self, self._name, prev, new_model))

    # ── Lifecycle override ──────────────────────────────────────────────────
    def _on_dispose(self) -> None:
        # Dispose commands first so any pending trigger subscriptions release
        # before we tear down the DerivedProperty subjects.
        self._set_theme_command.dispose()
        self._toggle_high_contrast.dispose()
        self._set_accent_color.dispose()
        self._set_font_scale.dispose()
        self._follow_system_command.dispose()
        self._current_theme.dispose()
        self._follows_system.dispose()
        self._model_subject.on_completed()
        self._model_subject.dispose()
        super()._on_dispose()

    # ── Builder entry-point ─────────────────────────────────────────────────
    # Mirrors the existing showcase pattern (NotebookVM / StatusBarVM) of
    # narrowing the base ``ComponentVMOf.builder()`` to the per-VM fluent
    # builder so callers reach the showcase-specific configuration surface.
    @staticmethod
    def builder() -> ThemeVMBuilder:  # type: ignore[override]
        return ThemeVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class ThemeVMBuilder:
    """Immutable fluent builder for :class:`ThemeVM` (spec ch. 10)."""

    _name: str | None = None
    _hint: str = ""
    _initial: ThemeModel = DARK_PRESET
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _host_theme_provider: Callable[[], ThemeModel] | None = None

    def name(self, value: str) -> ThemeVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> ThemeVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def initial(self, value: ThemeModel) -> ThemeVMBuilder:
        """Set the initial :class:`ThemeModel`. Defaults to :data:`DARK_PRESET`."""
        return dataclasses.replace(self, _initial=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> ThemeVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def host_theme_provider(self, provider: Callable[[], ThemeModel]) -> ThemeVMBuilder:
        """Inject the host-theme snapshot resolver used by
        :meth:`ThemeVM.follow_system_command`. Defaults to a function that
        returns :data:`DARK_PRESET` so the command is always safe to invoke.
        """
        return dataclasses.replace(self, _host_theme_provider=provider)

    def build(self) -> ThemeVM:
        if self._name is None:
            raise ValueError("name is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return ThemeVM(
            name=self._name,
            hint=self._hint,
            initial=self._initial,
            hub=hub,
            dispatcher=dispatcher,
            host_theme_provider=self._host_theme_provider,
        )
