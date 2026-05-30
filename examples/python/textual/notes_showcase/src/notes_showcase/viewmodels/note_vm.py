"""NoteVM — leaf VM for a single note.

Capabilities (plan §3.b.5, scenario §6.2):
    ``ISelectable``, ``IClosable``, ``IDeletable[NoteVM]``, ``ISavable[NoteVM]``,
    ``IReconstructable``.

The close / delete / save callbacks are host-supplied so the leaf stays
decoupled from the container. ``close_command`` invokes ``on_close`` (the host
wires it to ``NotesViewVM.current = None`` so the form clears).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable

from vmx import (
    ComponentVMOf,
    ConstructionStatus,
    IClosable,
    IDeletable,
    IReconstructable,
    ISavable,
    ISelectable,
    MessageHub,
    PropertyChangedMessage,
    RelayCommand,
    RxDispatcher,
)
from vmx.commands import ConfirmationDecoratorCommand
from vmx.commands.protocols import Command
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub, Notification, NotificationType
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.note_model import NoteModel


class NoteVM(
    ComponentVMOf[NoteModel],
    ISelectable,
    IClosable,
    IReconstructable,
):
    """Leaf VM for a single note."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        model: NoteModel,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        on_close: Callable[["NoteVM"], None] | None = None,
        on_delete: Callable[["NoteVM"], None] | None = None,
        on_save: Callable[["NoteVM"], None] | None = None,
        confirm_delete: Callable[["NoteVM"], Awaitable[bool]] | None = None,
        notification_hub: INotificationHub | None = None,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            initial_model=model,
            modeled_hinter=lambda m: m.title,
            on_model_changed=None,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._on_close = on_close
        self._on_delete = on_delete
        self._on_save = on_save
        self._confirm_delete = confirm_delete
        self._notification_hub = notification_hub

        self._close_command = (
            RelayCommand.builder().predicate(self.can_close).task(self.close).build()
        )
        self._save_command = (
            RelayCommand.builder()
            .predicate(lambda: self.can_save(self))
            .task(lambda: self.save(self))
            .build()
        )
        # Spec §5.2.8 / §6.2: when a confirm-delete delegate is wired, wrap
        # the delete in a ConfirmationDecoratorCommand. The inner command
        # invokes `_perform_delete`, which posts a "Note deleted" notification
        # (if a hub is wired) and calls the host delete callback.
        inner_delete: Command = (
            RelayCommand.builder()
            .predicate(lambda: self.can_delete(self))
            .task(lambda: self._perform_delete(self))
            .build()
        )
        self._delete_command: Command = (
            ConfirmationDecoratorCommand(
                inner_delete,
                lambda: confirm_delete(self),
            )
            if confirm_delete is not None
            else inner_delete
        )

    # ── Convenience accessors / proxies ────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    @property
    def note_id(self) -> str:
        return self.model.id

    @property
    def title(self) -> str:
        return self.model.title

    @property
    def body(self) -> str:
        return self.model.body

    @property
    def starred(self) -> bool:
        return self.model.starred

    @property
    def tags(self) -> tuple[str, ...]:
        return self.model.tags

    # ── IClosable / ISavable / IDeletable ──────────────────────────────────
    def can_close(self) -> bool:
        return self._status == ConstructionStatus.CONSTRUCTED

    def close(self) -> None:
        if self._on_close is not None:
            self._on_close(self)

    def can_delete(self, item: "NoteVM") -> bool:
        return item is self and self._status == ConstructionStatus.CONSTRUCTED

    def delete(self, item: "NoteVM") -> None:
        if not self.can_delete(item):
            return
        if self._on_delete is not None:
            self._on_delete(item)

    def _perform_delete(self, item: "NoteVM") -> None:
        """Inner delete: invokes the host callback and posts the notification.

        Called by the (decorated) DeleteCommand pipeline after the confirm
        gate has succeeded. Keeps the raw :meth:`delete` capability method
        notification-free so capability dispatch stays observable-pure.
        """
        if not self.can_delete(item):
            return
        if self._on_delete is not None:
            self._on_delete(item)
        if self._notification_hub is not None:
            self._notification_hub.post(
                Notification(
                    NotificationType.NOTIFICATION,
                    f'Note deleted: “{item.title}”',
                )
            )

    def can_save(self, item: "NoteVM") -> bool:
        return item is self and self._status == ConstructionStatus.CONSTRUCTED

    def save(self, item: "NoteVM") -> None:
        if not self.can_save(item):
            return
        if self._on_save is not None:
            self._on_save(item)

    # ── Command surface ────────────────────────────────────────────────────
    @property
    def close_command(self) -> RelayCommand:
        return self._close_command

    @property
    def save_command(self) -> RelayCommand:
        return self._save_command

    @property
    def delete_command(self) -> Command:
        """Delete command. ``ConfirmationDecoratorCommand`` when ``confirm_delete``
        was wired on the builder; raw :class:`RelayCommand` otherwise.
        """
        return self._delete_command

    # ── Model setter override — emit title / starred PCMs ──────────────────
    def _set_model(self, value: NoteModel) -> None:
        old_title = self._model.title
        old_starred = self._model.starred
        super()._set_model(value)
        if old_title != value.title:
            self._hub.send(PropertyChangedMessage.create(self, self._name, "title"))
            self._raise_property_changed("title")
        if old_starred != value.starred:
            self._hub.send(PropertyChangedMessage.create(self, self._name, "starred"))
            self._raise_property_changed("starred")

    # ── Lifecycle override — dispose owned commands ────────────────────────
    def _on_dispose(self) -> None:
        self._close_command.dispose()
        self._save_command.dispose()
        # ConfirmationDecoratorCommand is not Disposable in VMx-Py; only
        # dispose the inner RelayCommand when delete_command is undecorated.
        if isinstance(self._delete_command, RelayCommand):
            self._delete_command.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> NoteVMBuilder:  # type: ignore[override]
        # Narrows ComponentVMOf.builder() to the showcase NoteVMBuilder.
        return NoteVMBuilder()


# Generic capability ABCs (IDeletable[T], ISavable[T]) cannot be subclassed
# alongside ComponentVMOf[M] without an MRO conflict (multiple Generic bases).
# Register them on NoteVM instead — isinstance checks still pass, which is
# what spec §14.4 capability dispatch relies on (mirrors the C# capability
# discovery via interface checks).
IDeletable.register(NoteVM)
ISavable.register(NoteVM)


@dataclasses.dataclass(frozen=True, slots=True)
class NoteVMBuilder:
    """Immutable fluent builder for :class:`NoteVM` (spec ch. 10)."""

    _name: str | None = None
    _hint: str = ""
    _model: NoteModel | None = None
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _on_close: Callable[[NoteVM], None] | None = None
    _on_delete: Callable[[NoteVM], None] | None = None
    _on_save: Callable[[NoteVM], None] | None = None
    _confirm_delete: Callable[[NoteVM], Awaitable[bool]] | None = None
    _notification_hub: INotificationHub | None = None

    def name(self, value: str) -> NoteVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NoteVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def model(self, value: NoteModel) -> NoteVMBuilder:
        return dataclasses.replace(self, _model=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> NoteVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def on_close(self, callback: Callable[[NoteVM], None]) -> NoteVMBuilder:
        return dataclasses.replace(self, _on_close=callback)

    def on_delete(self, callback: Callable[[NoteVM], None]) -> NoteVMBuilder:
        return dataclasses.replace(self, _on_delete=callback)

    def on_save(self, callback: Callable[[NoteVM], None]) -> NoteVMBuilder:
        return dataclasses.replace(self, _on_save=callback)

    def confirm_delete(
        self, callback: Callable[[NoteVM], Awaitable[bool]]
    ) -> NoteVMBuilder:
        """When set, :attr:`NoteVM.delete_command` is wrapped in a
        :class:`ConfirmationDecoratorCommand` calling this delegate. Typically
        wires to ``IDialogService.confirm(f"Delete '{note.title}'?")``.
        """
        return dataclasses.replace(self, _confirm_delete=callback)

    def notification_hub(self, nh: INotificationHub) -> NoteVMBuilder:
        """When set, a successful delete (post-confirm if any) publishes a
        "Note deleted" notification.
        """
        return dataclasses.replace(self, _notification_hub=nh)

    def build(self) -> NoteVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._model is None:
            raise ValueError("model is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = self._dispatcher if self._dispatcher is not None else RxDispatcher.immediate()
        return NoteVM(
            name=self._name,
            hint=self._hint,
            model=self._model,
            hub=hub,
            dispatcher=dispatcher,
            on_close=self._on_close,
            on_delete=self._on_delete,
            on_save=self._on_save,
            confirm_delete=self._confirm_delete,
            notification_hub=self._notification_hub,
        )
