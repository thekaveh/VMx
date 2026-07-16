"""CapabilityActionsVM — projects a focused VM's capabilities to ActionVMs.

Inspects the currently-focused VM (supplied by a host-side getter) and
projects every capability interface it implements into a flat list of
:class:`~notes_showcase.viewmodels.action_vm.ActionVM` for the action-bar.
See spec §14.4 (capability dispatch).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable

from reactivex.subject import BehaviorSubject

from vmx import (
    AsyncRelayCommand,
    ComponentVM,
    DerivedProperty,
    IApprovable,
    ICancelable,
    IClosable,
    ICollapsible,
    IDeletable,
    IDeselectable,
    IExpandable,
    IExpansionTogglable,
    INewCreatable,
    IReconstructable,
    ISavable,
    ISelectable,
    ISelectionTogglable,
    MessageHub,
    MessageHubProto,
    RelayCommand,
    RxDispatcher,
    from_sources,
)
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher

from notes_showcase.viewmodels.action_vm import ActionVM
from notes_showcase.viewmodels.note_vm import NoteVM


class CapabilityActionsVM(ComponentVM):
    """Action-bar VM whose ``actions`` derives from a focused VM's capabilities."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        focused_getter: Callable[[], object | None],
        add_note_action: Callable[[], Awaitable[None] | None] | None = None,
        can_add_note: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._focused_getter = focused_getter
        self._focus_subject: BehaviorSubject[object | None] = BehaviorSubject(
            focused_getter()
        )
        self._actions: DerivedProperty[list[ActionVM]] = from_sources(
            self._focus_subject,
            transform=_project,
        )
        # Edge-case backfill (readonly notebook gating): a dedicated
        # "Add Note" command whose ``can_execute`` predicate consults the
        # host-supplied :meth:`can_add_note` callback. The host (e.g.
        # :class:`WorkspaceVM`) typically wires this to
        # ``not notes_view.current_notebook_is_readonly``. Defaults stay
        # backward-compatible: a no-op action and an always-true predicate.
        self._add_note_action_cb = add_note_action or (lambda: None)
        self._can_add_note_cb: Callable[[], bool] = can_add_note or (lambda: True)
        self._add_note_command: AsyncRelayCommand = (
            AsyncRelayCommand.builder()
            .predicate(self._can_add_note_cb)
            .task(self._invoke_add_note)
            .build()
        )

    # ── Public surface ─────────────────────────────────────────────────────
    @property
    def hub(self) -> MessageHubProto[Message]:
        return self._hub

    @property
    def focused_vm(self) -> object | None:
        return self._focused_getter()

    @property
    def actions(self) -> DerivedProperty[list[ActionVM]]:
        return self._actions

    @property
    def add_note_command(self) -> AsyncRelayCommand:
        """Host-driven "Add Note" command.

        Edge-case backfill (readonly notebook gating): ``can_execute``
        delegates to the ``can_add_note`` callback supplied at construction.
        :class:`WorkspaceVM` wires the predicate to
        ``not notes_view.current_notebook_is_readonly`` so the bar gates
        adding notes to readonly notebooks.
        """
        return self._add_note_command

    async def _invoke_add_note(self) -> None:
        pending = self._add_note_action_cb()
        if pending is not None:
            await pending

    def recompute_actions(self) -> None:
        """Refresh the projection from the focus-getter delegate."""
        self._focus_subject.on_next(self._focused_getter())

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def _on_dispose(self) -> None:
        self._actions.dispose()
        self._add_note_command.dispose()
        self._focus_subject.on_completed()
        self._focus_subject.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> CapabilityActionsVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase CapabilityActionsVMBuilder.
        return CapabilityActionsVMBuilder()


def _project(focused: object | None) -> list[ActionVM]:
    if focused is None:
        return []
    actions: list[ActionVM] = []

    # Selection
    if isinstance(focused, ISelectable):
        actions.append(
            ActionVM(
                "Select",
                RelayCommand.builder()
                .predicate(focused.can_select)
                .task(focused.select)
                .build(),
            )
        )
    if isinstance(focused, IDeselectable):
        actions.append(
            ActionVM(
                "Deselect",
                RelayCommand.builder()
                .predicate(focused.can_deselect)
                .task(focused.deselect)
                .build(),
            )
        )
    if isinstance(focused, ISelectionTogglable):
        actions.append(
            ActionVM(
                "Toggle Selection",
                RelayCommand.builder()
                .predicate(focused.can_toggle_selection)
                .task(focused.toggle_selection)
                .build(),
            )
        )

    # Expansion
    if isinstance(focused, IExpandable):
        actions.append(
            ActionVM(
                "Expand",
                RelayCommand.builder()
                .predicate(focused.can_expand)
                .task(focused.expand)
                .build(),
            )
        )
    if isinstance(focused, ICollapsible):
        actions.append(
            ActionVM(
                "Collapse",
                RelayCommand.builder()
                .predicate(focused.can_collapse)
                .task(focused.collapse)
                .build(),
            )
        )
    if isinstance(focused, IExpansionTogglable):
        actions.append(
            ActionVM(
                "Toggle Expansion",
                RelayCommand.builder()
                .predicate(focused.can_toggle_expansion)
                .task(focused.toggle_expansion)
                .build(),
            )
        )

    # Dialog
    if isinstance(focused, IClosable):
        actions.append(
            ActionVM(
                "Close",
                RelayCommand.builder()
                .predicate(focused.can_close)
                .task(focused.close)
                .build(),
            )
        )
    if isinstance(focused, IApprovable):
        actions.append(
            ActionVM(
                "Approve",
                RelayCommand.builder()
                .predicate(focused.can_approve)
                .task(focused.approve)
                .build(),
            )
        )
    if isinstance(focused, ICancelable):
        actions.append(
            ActionVM(
                "Cancel",
                RelayCommand.builder()
                .predicate(focused.can_cancel)
                .task(focused.cancel)
                .build(),
            )
        )

    # CRUD
    if isinstance(focused, INewCreatable):
        actions.append(
            ActionVM(
                "New",
                RelayCommand.builder()
                .predicate(focused.can_create_new)
                .task(focused.create_new)
                .build(),
            )
        )
    # ISavable / IDeletable are parameterised — only NoteVM implements them
    # in this scenario, and the parameter is always the focused note itself.
    # Reuse ``note.save_command`` / ``note.delete_command`` directly so the
    # action-bar Delete fires the same ConfirmationDecoratorCommand (and
    # "Note deleted" notification) the in-list delete button uses — keeping
    # the action-bar and the in-list delete button behaviorally identical
    # (parity with C# CapabilityActionsVM.cs:121-131).
    if isinstance(focused, NoteVM):
        note: NoteVM = focused
        if isinstance(focused, ISavable):
            actions.append(ActionVM("Save", note.save_command))
        if isinstance(focused, IDeletable):
            actions.append(ActionVM("Delete", note.delete_command))

    # Lifecycle
    if isinstance(focused, IReconstructable):
        actions.append(
            ActionVM(
                "Reconstruct",
                RelayCommand.builder()
                .predicate(focused.can_reconstruct)
                .task(focused.reconstruct)
                .build(),
            )
        )

    return actions


@dataclasses.dataclass(frozen=True, slots=True)
class CapabilityActionsVMBuilder:
    """Immutable fluent builder for :class:`CapabilityActionsVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHubProto[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _focused_getter: Callable[[], object | None] | None = None
    _add_note_action: Callable[[], Awaitable[None] | None] | None = None
    _can_add_note: Callable[[], bool] | None = None

    def name(self, value: str) -> CapabilityActionsVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> CapabilityActionsVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHubProto[Message], dispatcher: Dispatcher
    ) -> CapabilityActionsVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def focused_getter(
        self, getter: Callable[[], object | None]
    ) -> CapabilityActionsVMBuilder:
        return dataclasses.replace(self, _focused_getter=getter)

    def add_note_action(
        self, action: Callable[[], Awaitable[None] | None]
    ) -> CapabilityActionsVMBuilder:
        """Wire the *Add Note* command body (edge-case backfill)."""
        return dataclasses.replace(self, _add_note_action=action)

    def can_add_note(self, predicate: Callable[[], bool]) -> CapabilityActionsVMBuilder:
        """Wire the *Add Note* command can-execute predicate.

        Used by :class:`WorkspaceVM` to consult
        ``notes_view.current_notebook_is_readonly`` so the bar disables
        *Add Note* against readonly notebooks.
        """
        return dataclasses.replace(self, _can_add_note=predicate)

    def build(self) -> CapabilityActionsVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._focused_getter is None:
            raise ValueError("focused_getter is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return CapabilityActionsVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            focused_getter=self._focused_getter,
            add_note_action=self._add_note_action,
            can_add_note=self._can_add_note,
        )
