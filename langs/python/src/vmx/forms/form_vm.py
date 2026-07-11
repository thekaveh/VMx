"""FormVM[TM] — snapshot/revert edit lifecycle ViewModel.

See spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.commands.relay_command import RelayCommand
from vmx.forms.builders import FormVMBuilder
from vmx.messages.form_reverted import FormRevertedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHubProto
from vmx.services.null_message_hub import NULL_MESSAGE_HUB

TM = TypeVar("TM")

FieldValidator = Callable[[TM], str | None]
ModelValidator = Callable[[TM], Mapping[str, str | None]]


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
        ``copy.deepcopy`` so that a mutation to a *nested* object inside the
        model is visible to :attr:`is_dirty` and restored by ``deny``/revert.
        Inject a custom snapshotter as the escape hatch for models that
        ``deepcopy`` cannot handle (e.g. live handles, unpicklable objects).
    reset_on_approved:
        Optional synchronous callback that derives the next pristine model
        from the captured value after persistence succeeds.
    """

    def __init__(
        self,
        initial: TM,
        persister: Callable[[TM], Awaitable[None]],
        hub: MessageHubProto[Any] | None = None,
        strict: bool = False,
        snapshotter: Callable[[TM], TM] | None = None,
        validators: Mapping[str, FieldValidator[TM]] | None = None,
        model_validator: ModelValidator[TM] | None = None,
        reset_on_approved: Callable[[TM], TM] | None = None,
    ) -> None:
        if initial is None:
            raise ValueError("initial must not be None")
        if persister is None:
            raise ValueError("persister must not be None")

        self._persister = persister
        self._hub: MessageHubProto[Any] = hub if hub is not None else NULL_MESSAGE_HUB
        self._strict = strict
        self._snapshotter: Callable[[TM], TM] = (
            snapshotter if snapshotter is not None else copy.deepcopy
        )
        self._validators: dict[str, FieldValidator[TM]] = dict(validators or {})
        self._model_validator = model_validator
        self._reset_on_approved = reset_on_approved

        self._model: TM = initial
        self._snapshot: TM = self._snapshotter(initial)
        self._errors: dict[str, str] = self._validate(initial)

        self._disposed = False

        # Observables
        self._on_approved: Subject[TM] = Subject()
        self._approve_errors: Subject[BaseException] = Subject()
        self._errors_changed: Subject[dict[str, str]] = Subject()
        self._can_execute_trigger: Subject[None] = Subject()

        # Commands
        self._deny_command = RelayCommand.builder().task(self._deny).build()
        self._approve_command = (
            RelayCommand.builder()
            .task(self._approve_fire_and_forget)
            .predicate(lambda: self.is_valid and (not self._strict or self.is_dirty))
            .triggers(self._can_execute_trigger)
            .build()
        )

    # ── Builder entrypoint ───────────────────────────────────────────────────

    @staticmethod
    def builder() -> FormVMBuilder[TM]:
        """Return a fresh :class:`FormVMBuilder` for this generic type.

        Provided for parity with the other VMx VM family entry points.
        See ADR-0035 §2 FV1. (Instantiated bare, like every sibling
        ``builder()``: subscripted instantiation of a frozen+slots dataclass
        raises ``TypeError`` when typing assigns ``__orig_class__``.)
        """
        return FormVMBuilder()

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
    def errors(self) -> dict[str, str]:
        """Current validation errors keyed by field name."""
        return dict(self._errors)

    @property
    def is_valid(self) -> bool:
        """``True`` when the current model has no validation errors."""
        return not self._errors

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
        return self._on_approved.pipe(ops.as_observable())

    @property
    def approve_errors(self) -> rx.Observable[BaseException]:
        """Observable that surfaces the persister error when the approve *command* fails.

        ``approve_command.execute()`` is fire-and-forget, so a persister failure
        cannot propagate to the caller; it is emitted here instead of being
        swallowed (VMX-008). The awaitable :meth:`approve_async` keeps its
        raising behavior — ``await`` it directly to handle the error inline.
        Completes on :meth:`dispose`.
        """
        return self._approve_errors.pipe(ops.as_observable())

    @property
    def errors_changed(self) -> rx.Observable[dict[str, str]]:
        """Observable that emits when the effective validation error map changes."""
        return self._errors_changed.pipe(ops.as_observable())

    def field_error(self, field: str) -> str | None:
        """Return the current validation error for ``field``, if any."""
        return self._errors.get(field)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def set_model(self, model: TM) -> None:
        """Replace the current model.

        If in strict mode and ``is_dirty`` changes, fires ``can_execute_changed``.
        Inert after :meth:`dispose` (like :meth:`approve_async`/:meth:`deny`): a
        post-dispose call would otherwise ``on_next`` a disposed reactivex Subject
        via ``_revalidate`` and raise (parity with the TS/Swift no-op).
        """
        if self._disposed:
            return
        if model is None:
            raise ValueError("model must not be None")
        was_dirty = self.is_dirty
        was_valid = self.is_valid
        self._model = model
        self._revalidate()
        if (self._strict and self.is_dirty != was_dirty) or self.is_valid != was_valid:
            self._can_execute_trigger.on_next(None)

    # ── Async core ────────────────────────────────────────────────────────────

    async def approve_async(self) -> None:
        """Awaitable entry-point to the approve flow.

        Invokes the persister, advances :attr:`snapshot` on success, and fires
        :attr:`on_approved`.  Raises when the persister raises (no state mutation).
        A disposed form is a full no-op — the persister is not invoked
        (symmetric with the deny guard).
        """
        if self._disposed:
            return
        if not self.is_valid:
            return
        current = self._model

        # May raise — intentional.  No state mutation if this raises.
        await self._persister(current)

        # dispose() may have run during the await; the subjects below are
        # completed and disposed, so emitting would raise DisposedException
        # (mirrors the C# guard).
        if self._disposed:
            return

        # Success: atomically install the configured reset state, or preserve
        # the legacy snapshot-advance behavior when no reset is configured.
        was_dirty = self.is_dirty
        was_valid = self.is_valid
        if self._reset_on_approved is not None:
            # Prepare callback output, independent live/snapshot values, and
            # validation before committing any local state.
            reset = self._reset_on_approved(current)
            next_model = self._snapshotter(reset)
            next_snapshot = self._snapshotter(reset)
            next_errors = self._validate(next_model)

            self._model = next_model
            self._snapshot = next_snapshot
            if next_errors != self._errors:
                self._errors = next_errors
                self._errors_changed.on_next(dict(next_errors))
        else:
            self._snapshot = self._snapshotter(current)

        if (self._strict and self.is_dirty != was_dirty) or self.is_valid != was_valid:
            self._can_execute_trigger.on_next(None)

        # Emit the value that was actually persisted (parity with C#'s
        # captured `current`): a set_model racing the persister await must
        # not swap the approved payload for a newer un-persisted model.
        self._on_approved.on_next(current)

    # ── Dispose ───────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete the ``on_approved`` observable and dispose resources. Idempotent."""
        # reactivex Subjects raise DisposedException on a second on_completed,
        # unlike rxjs (no-op) and the guarded C# FormVM — guard for parity.
        if self._disposed:
            return
        self._disposed = True
        self._on_approved.on_completed()
        self._on_approved.dispose()
        self._approve_errors.on_completed()
        self._approve_errors.dispose()
        self._errors_changed.on_completed()
        self._errors_changed.dispose()
        self._can_execute_trigger.on_completed()
        self._can_execute_trigger.dispose()
        self._deny_command.dispose()
        self._approve_command.dispose()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _deny(self) -> None:
        if self._disposed:
            return
        was_dirty = self.is_dirty
        was_valid = self.is_valid
        self._model = self._snapshotter(self._snapshot)
        self._revalidate()

        self._hub.send(FormRevertedMessage(sender=self, sender_name="FormVM"))
        self._hub.send(
            PropertyChangedMessage.create(
                sender=self,
                sender_name="FormVM",
                property_name="model",
            )
        )

        if (self._strict and was_dirty != self.is_dirty) or self.is_valid != was_valid:
            self._can_execute_trigger.on_next(None)

    def _validate(self, model: TM) -> dict[str, str]:
        errors: dict[str, str] = {}
        for field, validator in self._validators.items():
            error = validator(model)
            if error is not None:
                errors[field] = error
        if self._model_validator is not None:
            for field, error in self._model_validator(model).items():
                if error is None:
                    errors.pop(field, None)
                else:
                    errors[field] = error
        return errors

    def _revalidate(self) -> None:
        errors = self._validate(self._model)
        if errors == self._errors:
            return
        self._errors = errors
        self._errors_changed.on_next(dict(errors))

    def _approve_fire_and_forget(self) -> None:
        """Synchronous wrapper that schedules the async approve.

        Called by the RelayCommand (which expects a sync callable). Fire-and-forget:
        a persister failure is routed to :attr:`approve_errors` instead of being
        swallowed (VMX-008). Use :meth:`approve_async` for awaitable raising behavior.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop: run to completion synchronously, routing a
            # persister failure to the error channel (parity with the
            # running-loop path rather than propagating to the sync caller).
            try:
                asyncio.run(self.approve_async())
            except Exception as exc:
                self._emit_approve_error(exc)
            return
        task = loop.create_task(self.approve_async())
        # Mirror the C# continuation: surface the persister failure on the error
        # channel. Skip cancelled tasks — Task.exception() raises CancelledError
        # for those, which would error the loop's callback.
        task.add_done_callback(self._on_approve_done)

    def _on_approve_done(self, task: asyncio.Future[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._emit_approve_error(exc)

    def _emit_approve_error(self, exc: BaseException) -> None:
        # The subject is completed+disposed on dispose(); a persister failure
        # arriving after dispose must not raise reactivex DisposedException.
        if self._disposed:
            return
        self._approve_errors.on_next(exc)
