"""NotificationsVM — bounded mirror of an INotificationHub's pending list.

Subscribes to ``INotificationHub.pending`` and surfaces the most recent
notifications as a bounded :class:`vmx.ObservableList` of
:class:`vmx.notifications.NotificationVM`. Cap defaults to 5 (drops the
oldest entry when full); auto-dismiss is handled by each inner
``NotificationVM``'s lifespan timer.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from reactivex.abc import DisposableBase, SchedulerBase
from reactivex.scheduler import TimeoutScheduler

from vmx import (
    ComponentVM,
    MessageHub,
    MessageHubProto,
    ObservableList,
    PropertyChangedMessage,
    RxDispatcher,
)
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub, Notification, NotificationVM
from vmx.services.dispatcher import Dispatcher

_DEFAULT_CAP = 5


class NotificationsVM(ComponentVM):
    """Bounded mirror of an INotificationHub's pending notifications."""

    DEFAULT_CAP = _DEFAULT_CAP

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        notification_hub: INotificationHub,
        scheduler: SchedulerBase | None = None,
        lifespan: timedelta | None = None,
        cap: int = _DEFAULT_CAP,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._notification_hub = notification_hub
        self._scheduler = scheduler or TimeoutScheduler()
        self._lifespan = lifespan
        self._cap = cap
        self._visible: ObservableList[NotificationVM] = ObservableList()
        self._map: dict[Notification, NotificationVM] = {}
        self._pending_sub: DisposableBase | None = None

    # ── Public surface ─────────────────────────────────────────────────────
    @property
    def hub(self) -> MessageHubProto[Message]:
        return self._hub

    @property
    def visible(self) -> ObservableList[NotificationVM]:
        return self._visible

    @property
    def cap(self) -> int:
        return self._cap

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def _on_construct(self) -> None:
        super()._on_construct()
        self._pending_sub = self._notification_hub.pending.subscribe(
            on_next=self._sync_from_pending
        )

    def _on_destruct(self) -> None:
        if self._pending_sub is not None:
            self._pending_sub.dispose()
            self._pending_sub = None
        self._clear_visible()
        super()._on_destruct()

    def _on_dispose(self) -> None:
        if self._pending_sub is not None:
            self._pending_sub.dispose()
            self._pending_sub = None
        self._clear_visible()
        super()._on_dispose()

    def _clear_visible(self) -> None:
        for vm in list(self._visible):
            vm.dispose()
        with self._visible.batch_update():
            while self._visible.count > 0:
                self._visible.remove_at(0)
        self._map.clear()

    def _sync_from_pending(self, pending: list[Notification]) -> None:
        # Add VMs for notifications not yet rendered.
        for n in pending:
            if n in self._map:
                continue
            vm = NotificationVM(
                notification=n,
                hub=self._notification_hub,
                scheduler=self._scheduler,
                lifespan=self._lifespan,
            )
            self._map[n] = vm
            self._visible.append(vm)
            # Drop oldest while over cap.
            while self._visible.count > self._cap:
                oldest = self._visible[0]
                self._visible.remove_at(0)
                key = next((k for k, v in self._map.items() if v is oldest), None)
                if key is not None:
                    self._map.pop(key, None)
                oldest.dispose()
        # Remove VMs whose notifications are no longer pending.
        still = set(map(id, pending))
        to_remove = [n for n in self._map if id(n) not in still]
        for n in to_remove:
            vm = self._map.pop(n)
            self._visible.remove(vm)
            vm.dispose()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "visible"))
        self._raise_property_changed("visible")

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> NotificationsVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase NotificationsVMBuilder.
        return NotificationsVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class NotificationsVMBuilder:
    """Immutable fluent builder for :class:`NotificationsVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHubProto[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _notification_hub: INotificationHub | None = None
    _scheduler: SchedulerBase | None = None
    _lifespan: timedelta | None = None
    _cap: int = _DEFAULT_CAP

    def name(self, value: str) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHubProto[Message], dispatcher: Dispatcher
    ) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def notification_hub(self, value: INotificationHub) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _notification_hub=value)

    def scheduler(self, value: SchedulerBase) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _scheduler=value)

    def lifespan(self, value: timedelta) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _lifespan=value)

    def cap(self, value: int) -> NotificationsVMBuilder:
        return dataclasses.replace(self, _cap=value)

    def build(self) -> NotificationsVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._notification_hub is None:
            raise ValueError("notification_hub is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return NotificationsVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            notification_hub=self._notification_hub,
            scheduler=self._scheduler,
            lifespan=self._lifespan,
            cap=self._cap,
        )
