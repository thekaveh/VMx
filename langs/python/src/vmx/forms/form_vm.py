"""FormVM[TM] — snapshot/revert edit lifecycle ViewModel.

See spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

import reactivex as rx
from reactivex.subject import Subject

from vmx.commands.relay_command import RelayCommand
from vmx.messages.form_reverted import FormRevertedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHubProto
from vmx.services.null_message_hub import NULL_MESSAGE_HUB

TM = TypeVar("TM")


class FormVM(Generic[TM]):
    """ViewModel that wraps a mutable domain model with an edit lifecycle.

    Captures a snapshot at construction; allows mutation via :meth:`set_model`;
    provides :attr:`deny_command` (revert) and :attr:`approve_command` (persist).

    Parameters
    ----------
    initial:
        Initial domain model; also becomes the initial :attr:`snapshot`.
    persister:
        Async callable ``(model) -> Awaitable[None]``.  Raise on failure.
    hub:
        Message hub.  Defaults to ``NULL_MESSAGE_HUB`` (no hub messages).
    strict:
        When ``True``, ``approve_command.can_execute()`` returns ``False``
        when ``is_dirty`` is ``False``.  Default ``False``.
    snapshotter:
        Custom snapshot function ``(model) -> model``.  Defaults to
        ``copy.copy`` (shallow copy — idiomatic for ``@dataclass`` models).
    """

    def __init__(
        self,
        initial: TM,
        persister: Callable[[TM], Awaitable[None]],
        hub: MessageHubProto[Any] | None = None,
        strict: bool = False,
        snapshotter: Callable[[TM], TM] | None = None,
    ) -> None:
        if initial is None:
            raise ValueError("initial must not be None")
        if persister is None:
            raise ValueError("persister must not be None")

        self._persister = persister
        self._hub: MessageHubProto[Any] = hub if hub is not None else NULL_MESSAGE_HUB
        self._strict = strict
        self._snapshotter: Callable[[TM], TM] = (
            snapshotter if snapshotter is not None else copy.copy
        )

        self._model: TM = initial
        self._snapshot: TM = self._snapshotter(initial)

        # Observables
        self._on_approved: Subject[TM] = Subject()
        self._can_execute_trigger: Subject[None] = Subject()

        # Commands
        self._deny_command = RelayCommand.builder().task(self._deny).build()
        self._approve_command = (
            RelayCommand.builder()
            .task(self._approve_fire_and_forget)
            .predicate(lambda: not self._strict or self.is_dirty)
            .triggers(self._can_execute_trigger)
            .build()
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def model(self) -> TM:
        """Live, editable model."""
        return self._model

    @property
    def snapshot(self) -> TM:
        """Read-only snapshot captured at construction (until next approve)."""
        return self._snapshot

    @property
    def is_dirty(self) -> bool:
        """``True`` when ``model`` is structurally not equal to ``snapshot``."""
        return self._model != self._snapshot

    @property
    def deny_command(self) -> RelayCommand:
        """Reverts ``model`` to ``snapshot`` and publishes hub messages."""
        return self._deny_command

    @property
    def approve_command(self) -> RelayCommand:
        """Invokes the persister; on success advances ``snapshot`` and fires ``on_approved``."""
        return self._approve_command

    @property
    def on_approved(self) -> rx.Observable[TM]:
        """Observable that emits the current model after each successful persist."""
        return self._on_approved

    # ── Mutation ──────────────────────────────────────────────────────────────

    def set_model(self, model: TM) -> None:
        """Replace the current model.

        If in strict mode and ``is_dirty`` changes, fires ``can_execute_changed``.
        """
        if model is None:
            raise ValueError("model must not be None")
        was_dirty = self.is_dirty
        self._model = model
        if self._strict and self.is_dirty != was_dirty:
            self._can_execute_trigger.on_next(None)

    # ── Async core ────────────────────────────────────────────────────────────

    async def approve_async(self) -> None:
        """Awaitable entry-point to the approve flow.

        Invokes the persister, advances :attr:`snapshot` on success, and fires
        :attr:`on_approved`.  Raises when the persister raises (no state mutation).
        """
        current = self._model

        # May raise — intentional.  No state mutation if this raises.
        await self._persister(current)

        # Success: advance snapshot and notify.
        was_dirty = self.is_dirty
        self._snapshot = self._snapshotter(current)

        if self._strict and self.is_dirty != was_dirty:
            self._can_execute_trigger.on_next(None)

        self._on_approved.on_next(self._model)

    # ── Dispose ───────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete the ``on_approved`` observable and dispose resources."""
        self._on_approved.on_completed()
        self._on_approved.dispose()
        self._can_execute_trigger.on_completed()
        self._can_execute_trigger.dispose()
        self._deny_command.dispose()
        self._approve_command.dispose()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _deny(self) -> None:
        was_dirty = self.is_dirty
        self._model = self._snapshotter(self._snapshot)

        self._hub.send(FormRevertedMessage(sender=self, sender_name="FormVM"))
        self._hub.send(
            PropertyChangedMessage.create(
                sender=self,
                sender_name="FormVM",
                property_name="model",
            )
        )

        if self._strict and was_dirty != self.is_dirty:
            self._can_execute_trigger.on_next(None)

    def _approve_fire_and_forget(self) -> None:
        """Synchronous wrapper that schedules the async approve.

        Called by the RelayCommand (which expects a sync callable).
        Fire-and-forget; use :meth:`approve_async` in tests for awaitable behavior.
        """
        try:
            loop = asyncio.get_running_loop()
            _task = loop.create_task(self.approve_async())
            # Retrieve any exception so Python does not log "exception never retrieved".
            _task.add_done_callback(lambda _t: _t.exception())
        except RuntimeError:
            asyncio.run(self.approve_async())
