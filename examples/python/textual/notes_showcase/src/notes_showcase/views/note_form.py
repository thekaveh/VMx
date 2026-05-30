"""NoteFormView — right pane (Title / Body / Starred / Tags / Save·Revert).

Phase 5.b binding-gap #1: ``NoteFormVM`` exposes new scalar setters
(``title`` / ``body`` / ``starred``) that wrap ``draft = replace(draft, ...)``.
The widgets here two-way bind to those scalars, so typing into the Title
``Input`` actually writes back into the form and flips ``is_dirty`` →
``approve_command.can_execute``.

Status-line ``editing_text`` is a :class:`DerivedProperty`, so we route it
through ``bind_derived_property`` (Phase 5.b binding-gap #3) — the
``PropertyChangedMessage`` channel is not used.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Static, TextArea

from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.views.adapter import (
    bind_command,
    bind_derived_property,
    bind_property,
    bind_property_two_way,
)


class NoteFormView(Vertical):
    """Editor pane bound to a :class:`NoteFormVM`."""

    def __init__(self, vm: NoteFormVM) -> None:
        super().__init__(id="form_pane")
        self._vm = vm

    def compose(self) -> ComposeResult:
        yield Static("Note", classes="pane_title")
        yield Input(placeholder="Title", id="form_title")
        yield Checkbox("Starred", id="form_starred")
        yield Horizontal(
            Input(placeholder="add tag", id="form_tag_draft"),
            Button("+", id="form_add_tag"),
            id="tag_chip_row",
        )
        yield Static("", id="form_tag_chips")
        yield TextArea("", id="form_body")
        yield Static("", id="form_status")
        yield Horizontal(
            Button("Save", id="form_save", variant="primary"),
            Button("Revert", id="form_revert"),
            id="form_buttons",
        )

    def on_mount(self) -> None:
        # Two-way scalar bindings (binding-gap #1 fix).
        bind_property_two_way(
            self.query_one("#form_title", Input), "value", self._vm, "title"
        )
        bind_property_two_way(
            self.query_one("#form_starred", Checkbox),
            "value",
            self._vm,
            "starred",
        )
        bind_property_two_way(
            self.query_one("#form_body", TextArea), "text", self._vm, "body"
        )
        # Tag draft (text input) + add/save/revert commands.
        bind_property_two_way(
            self.query_one("#form_tag_draft", Input),
            "value",
            self._vm,
            "tag_draft",
        )
        bind_command(
            self.query_one("#form_add_tag", Button), self._vm.add_tag_command
        )
        bind_command(self.query_one("#form_save", Button), self._vm.approve_command)
        bind_command(self.query_one("#form_revert", Button), self._vm.deny_command)
        # Tag chip strip — one-way bound to ``tags`` (re-rendered as a flat
        # string for simplicity; the C# flavor renders chips, the Textual flavor
        # uses a comma-joined static, which keeps the widget class minimal).
        bind_property(
            self.query_one("#form_tag_chips", Static), "renderable", self._vm, "tags"
        )
        # Dirty marker ← DerivedProperty (binding-gap #3 fix). Uses the
        # bridge that subscribes to ``DerivedProperty.value_changed`` rather
        # than the hub (DerivedProperty does not publish PropertyChangedMessage).
        bind_derived_property(
            self.query_one("#form_status", Static),
            "renderable",
            self._vm.is_dirty,
        )
