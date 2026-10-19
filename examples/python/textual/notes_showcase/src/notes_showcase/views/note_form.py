"""NoteFormView — right pane (Title / Body / Starred / Tags / Save·Revert).

Phase 5.b binding-gap #1: ``NoteFormVM`` exposes new scalar setters
(``title`` / ``body`` / ``starred``) that wrap ``draft = replace(draft, ...)``.
The widgets here two-way bind to those scalars, so typing into the Title
``Input`` actually writes back into the form and flips ``is_dirty`` →
``approve_command.can_execute``.

The dirty marker reads the ``is_dirty`` :class:`DerivedProperty` through
``on_derived_change`` (Phase 5.b binding-gap #3) — the
``PropertyChangedMessage`` channel is not used. Tags render as removable
chips bound to ``remove_tag_command``; Enter in the tag field adds the tag.

Subscription hygiene (subscription ownership): every ``bind_*`` returns a
``Disposable`` that we collect into a ``CompositeDisposable`` and dispose
in ``on_unmount`` so subscriptions don't outlive the widget.
"""

from __future__ import annotations

from reactivex.disposable import CompositeDisposable
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Static, TextArea

from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.views.adapter import (
    bind_command,
    bind_property,
    bind_property_two_way,
    on_derived_change,
    on_vm_property_change,
)


def _dirty_text(is_dirty: object) -> str:
    return "Unsaved changes" if is_dirty else "Saved"


def _render_tag_chips(view: NoteFormView) -> None:
    """Rebuild the removable tag chips when the draft's tags change.

    Each chip is a button bound to ``remove_tag_command`` with its tag as the
    parameter. ``remove_children`` is asynchronous, so the rebuild runs on the
    widget's message pump and awaits it before mounting (see
    ``capability_actions._rebuild_buttons``).
    """
    tags = view._vm.tags
    if tags == view._rendered_tags:
        return
    view._rendered_tags = tags
    view.call_later(_render_tag_chips_async, view, tags)


async def _render_tag_chips_async(view: NoteFormView, tags: tuple[str, ...]) -> None:
    if tags != view._rendered_tags:
        return  # superseded by a later rebuild
    chips = view.query_one("#tag_chips", Horizontal)
    view._chip_bindings.dispose()
    view._chip_bindings = CompositeDisposable()
    await chips.remove_children()
    for index, tag in enumerate(tags):
        button = Button(f"✕ {tag}", id=f"tag_remove_{index}", classes="tag_chip")
        await chips.mount(button)
        view._chip_bindings.add(bind_command(button, view._vm.remove_tag_command, tag))


def _submit(vm: NoteFormVM, input_id: str | None) -> None:
    """Enter in the tag field adds the tag (when the command allows it)."""
    if input_id == "form_tag_draft" and vm.add_tag_command.can_execute():
        vm.add_tag_command.execute()


def _wire_bindings(view: NoteFormView) -> CompositeDisposable:
    vm = view._vm
    return CompositeDisposable(
        # Two-way scalar bindings (binding-gap #1 fix).
        bind_property_two_way(view.query_one("#form_title", Input), "value", vm, "title"),
        bind_property(
            view.query_one("#form_title_error", Static),
            "renderable",
            vm,
            "title_error",
            transform=lambda value: str(value) if value else "",
        ),
        bind_property_two_way(view.query_one("#form_starred", Checkbox), "value", vm, "starred"),
        bind_property_two_way(view.query_one("#form_body", TextArea), "text", vm, "body"),
        # Tag draft (text input) + add/save/revert commands.
        bind_property_two_way(view.query_one("#form_tag_draft", Input), "value", vm, "tag_draft"),
        bind_command(view.query_one("#form_add_tag", Button), vm.add_tag_command),
        bind_command(view.query_one("#form_mode_edit", Button), vm.show_edit_mode_command),
        bind_command(view.query_one("#form_mode_preview", Button), vm.show_preview_mode_command),
        bind_command(view.query_one("#form_save", Button), vm.approve_command),
        bind_command(view.query_one("#form_revert", Button), vm.deny_command),
        bind_property(view.query_one("#form_body", TextArea), "display", vm, "is_edit_mode"),
        bind_property(
            view.query_one("#form_body_preview", Static),
            "display",
            vm,
            "is_preview_mode",
        ),
        bind_property(
            view.query_one("#form_body_preview", Static),
            "renderable",
            vm,
            "body",
            transform=lambda value: str(value) if str(value) else "No body.",
        ),
        bind_property(
            view.query_one("#form_tag_suggestions", Static),
            "renderable",
            vm,
            "tag_suggestions_text",
            transform=lambda value: f"Suggestions: {value}" if str(value) else "",
        ),
        # Tag chip strip — one removable button per tag, bound to
        # ``remove_tag_command`` (see _render_tag_chips).
        on_vm_property_change(vm, {"tags"}, lambda _name: _render_tag_chips(view)),
        # Dirty marker ← DerivedProperty (binding-gap #3 fix). Uses the
        # bridge that subscribes to ``DerivedProperty.value_changed`` rather
        # than the hub (DerivedProperty does not publish PropertyChangedMessage).
        on_derived_change(
            vm.is_dirty,
            lambda value: view.query_one("#form_status", Static).update(_dirty_text(value)),
        ),
    )


class NoteFormView(Vertical):
    """Editor pane bound to a :class:`NoteFormVM`."""

    def __init__(self, vm: NoteFormVM) -> None:
        super().__init__(id="form_pane")
        self._vm = vm
        self._disposables: CompositeDisposable = CompositeDisposable()
        self._chip_bindings: CompositeDisposable = CompositeDisposable()
        self._rendered_tags: tuple[str, ...] = ()

    def compose(self) -> ComposeResult:
        yield Static("Note", classes="pane_title")
        yield Input(placeholder="Title", id="form_title")
        yield Static("", id="form_title_error")
        yield Checkbox("Starred", id="form_starred")
        yield Horizontal(
            Input(placeholder="add tag", id="form_tag_draft"),
            Button("Add tag", id="form_add_tag"),
            id="tag_chip_row",
        )
        yield Static("", id="form_tag_suggestions")
        yield Horizontal(id="tag_chips")
        yield Horizontal(
            Button("Edit", id="form_mode_edit"),
            Button("Preview", id="form_mode_preview"),
            id="form_mode_row",
        )
        yield TextArea("", id="form_body")
        yield Static("", id="form_body_preview")
        yield Static("", id="form_status")
        yield Horizontal(
            Button("Save", id="form_save", variant="primary"),
            Button("Revert", id="form_revert"),
            id="form_buttons",
        )

    def on_mount(self) -> None:
        self._disposables = _wire_bindings(self)
        _render_tag_chips(self)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        _submit(self._vm, event.input.id)

    def on_unmount(self) -> None:
        self._disposables.dispose()
        self._chip_bindings.dispose()
