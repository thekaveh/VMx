"""FormVM[TM] — snapshot/revert edit lifecycle ViewModel.

See spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future
from threading import Condition, RLock, get_ident
from typing import Any, Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx._asyncio_runner import ScheduledRun, submit_background
from vmx._disposal import _run_disposal_steps
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
        self._state_changed = Condition(RLock())
        # Single-flight approval admission (spec/20 §5.3, ADR-0143): set when an
        # approve call is admitted, cleared first thing at settlement.
        self._approval_in_flight = False
        self._approval_publishing = False
        self._approval_pre_publishing = False
        self._approval_publisher_thread: int | None = None
        self._deferred_approval_models: list[TM] = []
        self._active_mutations = 0
        self._mutation_teardown_pending = False
        # Commit generation (spec/20 §5.4): advanced by every commit of model,
        # snapshot, or errors, so an update whose callbacks re-entered the form
        # can tell that its preparation went stale.
        self._generation = 0

        # Construction runs the same preparation as an update (spec/20 §5.4):
        # a failing snapshotter or validator fails construction.
        snapshot = self._snapshotter(initial)
        errors = self._validate(initial)
        self._model: TM = initial
        self._snapshot: TM = snapshot
        self._errors: dict[str, str] = errors

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
            .predicate(self._can_approve)
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
        with self._state_changed:
            return self._model

    @property
    def snapshot(self) -> TM:
        """Read-only snapshot captured at construction (until next approve)."""
        with self._state_changed:
            return self._snapshot

    @property
    def is_dirty(self) -> bool:
        """``True`` when ``model`` is structurally not equal to ``snapshot``."""
        with self._state_changed:
            return self._model != self._snapshot

    @property
    def errors(self) -> dict[str, str]:
        """Current validation errors keyed by field name."""
        with self._state_changed:
            return dict(self._errors)

    @property
    def is_valid(self) -> bool:
        """``True`` when the current model has no validation errors."""
        with self._state_changed:
            return not self._errors

    @property
    def deny_command(self) -> RelayCommand:
        """Reverts ``model`` to ``snapshot`` and publishes hub messages."""
        return self._deny_command

    @property
    def approve_command(self) -> RelayCommand:
        """Invokes the persister; on success advances ``snapshot`` and fires ``on_approved``.

        Disabled while an approval is in flight (spec/20 §5.3).
        """
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
        with self._state_changed:
            return self._errors.get(field)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def set_model(self, model: TM) -> None:
        """Replace the current model.

        If in strict mode and ``is_dirty`` changes, fires ``can_execute_changed``.
        Inert after :meth:`dispose` (like :meth:`approve_async`/:meth:`deny`): a
        post-dispose call would otherwise ``on_next`` a disposed reactivex Subject
        during validation publication and raise (parity with the TS/Swift no-op).

        Failure-atomic (spec/20 §5.4): the model's ``__eq__`` and the validators
        run on the candidate before anything is committed. If one raises, the
        exception propagates unchanged and the form keeps its model, snapshot,
        errors, and command state, with nothing published. If a callback
        re-enters the form and another update commits, or the form is disposed,
        this call commits and publishes nothing.
        """
        caller = get_ident()
        admitted = False
        in_flight: BaseException | None = None
        try:
            with self._state_changed:
                while (
                    self._approval_publishing
                    and self._approval_publisher_thread != caller
                    and not self._disposed
                ):
                    self._state_changed.wait()
                if self._disposed:
                    return
                if model is None:
                    # Reject before any deferral, so the caller sees the error.
                    raise ValueError("model must not be None")
                if self._approval_publishing and self._approval_pre_publishing:
                    self._deferred_approval_models.append(model)
                    return
                self._active_mutations += 1
                admitted = True
                # Prepare (spec/20 §5.4) without touching form state. Callbacks
                # run under the re-entrant state lock: one may re-enter
                # set_model, deny, or dispose on this thread, while another
                # thread's update or dispose waits for this one.
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                if current == model:
                    return
                was_dirty = current != snapshot
                was_valid = not self._errors
                next_errors = self._validate(model)
                is_dirty = model != snapshot
                # A re-entrant dispose or commit made this preparation stale.
                if self._disposed or self._generation != generation:
                    return
                # Commit in one step, then notify.
                errors_changed = next_errors != self._errors
                self._model = model
                self._errors = next_errors
                self._generation += 1
                is_valid = not next_errors
                if errors_changed:
                    self._errors_changed.on_next(dict(next_errors))
                if (self._strict and is_dirty != was_dirty) or is_valid != was_valid:
                    self._can_execute_trigger.on_next(None)
            self._hub.send(
                PropertyChangedMessage.create(
                    sender=self,
                    sender_name="FormVM",
                    property_name="model",
                )
            )
        except BaseException as error:
            in_flight = error
            raise
        finally:
            if admitted:
                self._end_mutation(in_flight)

    # ── Async core ────────────────────────────────────────────────────────────

    async def approve_async(self) -> None:
        """Awaitable entry-point to the approve flow.

        Invokes the persister, advances :attr:`snapshot` on success, and fires
        :attr:`on_approved`.  Raises when the persister raises (no state mutation).
        A disposed form is a full no-op — the persister is not invoked
        (symmetric with the deny guard).

        One approval runs at a time (spec/20 §5.3): the call is admitted when the
        coroutine starts, and while another approval is in flight it returns
        normally without invoking the persister, mutating state, or emitting.
        """
        admission = self._admit_approval()
        if admission is None:
            return
        await self._run_admitted_approval(admission[0])

    def _admit_approval(self) -> tuple[TM] | None:
        """Admit one approval or refuse it (spec/20 §5.3).

        Admission marks the approval in flight and captures the model in one
        critical section, then raises ``can_execute_changed`` once with no lock
        held. Returns the captured model, or ``None`` when the call is refused
        (disposed, invalid, or another approval in flight) or an admission
        observer disposed the form, so the persister must not run.
        """
        caller = get_ident()
        with self._state_changed:
            while (
                self._approval_publishing
                and self._approval_publisher_thread != caller
                and not self._disposed
            ):
                self._state_changed.wait()
            if self._disposed or self._errors or self._approval_in_flight:
                return None
            self._approval_in_flight = True
            captured = self._model
            # Hold teardown off while the admission notification is delivered.
            self._active_mutations += 1
        failure: BaseException | None = None
        try:
            self._can_execute_trigger.on_next(None)
        except BaseException as error:
            # The persister never runs; do not leave the form wedged in flight,
            # and tell observers that saw the admission edge (#732). The
            # original failure wins over one from the release notification.
            failure = error
            with self._state_changed:
                self._approval_in_flight = False
            with contextlib.suppress(BaseException):
                self._can_execute_trigger.on_next(None)
            raise
        finally:
            self._end_mutation(failure)
        with self._state_changed:
            if self._disposed:
                return None
        return (captured,)

    async def _run_admitted_approval(
        self, current: TM, scheduled: ScheduledRun | None = None
    ) -> None:
        """Persist the captured model of an admitted approval and settle it.

        ``scheduled`` is the start claim of an approval scheduled as a task.
        """
        if scheduled is not None and not scheduled.claim_start():
            return
        try:
            # May raise — intentional.  No state mutation if this raises.
            await self._persister(current)

            # dispose() may have run during the await; disposal suppresses the
            # whole settlement (spec/20 §5.3/§10): the subjects are completed
            # and disposed, so emitting would raise DisposedException.
            with self._state_changed:
                if self._disposed:
                    self._approval_in_flight = False
                    return

            # Success: prepare the configured reset state, or the legacy
            # snapshot advance, before committing any local state.
            if self._reset_on_approved is not None:
                reset = self._reset_on_approved(current)
                next_model = self._snapshotter(reset)
                next_snapshot = self._snapshotter(reset)
                next_errors = self._validate(next_model)
                reset_state: tuple[TM, TM, dict[str, str]] | None = (
                    next_model,
                    next_snapshot,
                    next_errors,
                )
            else:
                reset_state = None
                next_snapshot = self._snapshotter(current)
        except BaseException:
            # Persister failure or cancellation, or a failed reset transaction.
            self._settle_failed_approval()
            raise
        self._settle_approval(current, reset_state, next_snapshot)

    def _settle_approval(
        self,
        current: TM,
        reset_state: tuple[TM, TM, dict[str, str]] | None,
        next_snapshot: TM,
    ) -> None:
        """Commit a successful approval, then publish its settlement in order.

        Order (spec/20 §5.3): clear the in-flight mark with the commit,
        ``errors_changed`` when the effective map changed, ``can_execute_changed``
        exactly once, then ``on_approved``.
        """
        caller = get_ident()
        with self._state_changed:
            while self._approval_publishing and self._approval_publisher_thread != caller:
                self._state_changed.wait()
            self._approval_in_flight = False
            if self._disposed:
                return
            outer = self._enter_publication(caller, pre_publishing=True)
            # The approval commit (snapshot advance or reset) supersedes any
            # update still preparing on this thread (spec/20 §5.4).
            self._generation += 1
            published_errors: dict[str, str] | None = None
            if reset_state is not None:
                next_model, next_snapshot, next_errors = reset_state
                self._model = next_model
                self._snapshot = next_snapshot
                if next_errors != self._errors:
                    self._errors = next_errors
                    published_errors = dict(next_errors)
            else:
                self._snapshot = next_snapshot

        try:
            if published_errors is not None:
                self._errors_changed.on_next(published_errors)
                if self._disposed:
                    return
            self._can_execute_trigger.on_next(None)
            if self._disposed:
                return

            with self._state_changed:
                self._approval_pre_publishing = False

            # Emit the value that was actually persisted (parity with C#'s
            # captured `current`): a set_model racing the persister await must
            # not swap the approved payload for a newer un-persisted model.
            self._on_approved.on_next(current)
        finally:
            self._exit_publication(outer)

    def _settle_failed_approval(self) -> None:
        """Clear the in-flight mark and raise ``can_execute_changed`` once.

        The caller then routes the failure to the awaiter (or, on the command
        path, ``approve_errors``). That failure is the first error and wins: an
        observer raising from this notification must not replace it (the
        ``_end_mutation`` first-error policy).
        """
        caller = get_ident()
        with self._state_changed:
            while (
                self._approval_publishing
                and self._approval_publisher_thread != caller
                and not self._disposed
            ):
                self._state_changed.wait()
            self._approval_in_flight = False
            if self._disposed:
                return
            outer = self._enter_publication(caller, pre_publishing=False)
        try:
            with contextlib.suppress(BaseException):
                self._can_execute_trigger.on_next(None)
        finally:
            self._exit_publication(outer)

    def _enter_publication(
        self, caller: int, *, pre_publishing: bool
    ) -> tuple[bool, bool, int | None]:
        """Mark *caller* as the approval publisher; return the state to restore.

        Must be called holding the state lock, after waiting out any other
        thread's publication. Other threads' mutations and disposal wait until
        :meth:`_exit_publication`; same-thread edits made while
        ``pre_publishing`` is set are deferred until it ends.
        """
        outer = (
            self._approval_publishing,
            self._approval_pre_publishing,
            self._approval_publisher_thread,
        )
        self._approval_publishing = True
        self._approval_pre_publishing = pre_publishing
        self._approval_publisher_thread = caller
        return outer

    def _exit_publication(self, outer: tuple[bool, bool, int | None]) -> None:
        """End a publication; replay deferred edits once the outermost one ends."""
        with self._state_changed:
            if outer[0]:
                # Nested inside this thread's own publication: restore it and
                # leave the deferred edits to the outer publication.
                (
                    self._approval_publishing,
                    self._approval_pre_publishing,
                    self._approval_publisher_thread,
                ) = outer
                return
            self._approval_pre_publishing = False
            self._approval_publishing = False
            self._approval_publisher_thread = None
            deferred_models = self._deferred_approval_models
            self._deferred_approval_models = []
            self._state_changed.notify_all()
        for deferred_model in deferred_models:
            self.set_model(deferred_model)

    # ── Dispose ───────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete the ``on_approved`` observable and dispose resources. Idempotent."""
        # reactivex Subjects raise DisposedException on a second on_completed,
        # unlike rxjs (no-op) and the guarded C# FormVM — guard for parity.
        caller = get_ident()
        tear_down = False
        with self._state_changed:
            while (
                self._approval_publishing
                and self._approval_publisher_thread != caller
                and not self._disposed
            ):
                self._state_changed.wait()
            if self._disposed:
                return
            self._disposed = True
            if self._active_mutations == 0:
                tear_down = True
            else:
                self._mutation_teardown_pending = True
        if tear_down:
            self._tear_down()

    def _end_mutation(self, in_flight: BaseException | None = None) -> None:
        """Release one mutation and run any teardown deferred during it.

        ``in_flight`` is the error the mutation is already unwinding with, if
        any. It is the first failure and wins: a deferred-teardown failure
        must not replace it (the ``_run_disposal_steps`` first-error policy).
        Every teardown step still runs either way.
        """
        tear_down = False
        with self._state_changed:
            self._active_mutations -= 1
            if self._active_mutations == 0 and self._mutation_teardown_pending:
                self._mutation_teardown_pending = False
                tear_down = True
        if not tear_down:
            return
        if in_flight is None:
            self._tear_down()
            return
        with contextlib.suppress(BaseException):
            self._tear_down()

    def _tear_down(self) -> None:
        """Attempt every owned teardown step exactly once, even if one raises.

        Uses the shared ``_run_disposal_steps`` convention (see
        ``relay_command.py``): every step runs, and the first ``BaseException``
        is re-raised after all steps have been attempted.  This prevents an
        observer raising in one ``on_completed`` from permanently leaking the
        remaining subjects and commands.
        """
        _run_disposal_steps(
            self._on_approved.on_completed,
            self._on_approved.dispose,
            self._approve_errors.on_completed,
            self._approve_errors.dispose,
            self._errors_changed.on_completed,
            self._errors_changed.dispose,
            self._can_execute_trigger.on_completed,
            self._can_execute_trigger.dispose,
            self._deny_command.dispose,
            self._approve_command.dispose,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _deny(self) -> None:
        caller = get_ident()
        admitted = False
        in_flight: BaseException | None = None
        try:
            with self._state_changed:
                while (
                    self._approval_publishing
                    and self._approval_publisher_thread != caller
                    and not self._disposed
                ):
                    self._state_changed.wait()
                if self._disposed:
                    return
                self._active_mutations += 1
                admitted = True
                # Prepare the revert (spec/20 §5.4): the snapshotter, equality,
                # and validators run before anything is committed or published.
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                was_dirty = current != snapshot
                was_valid = not self._errors
                next_model = self._snapshotter(snapshot)
                next_errors = self._validate(next_model)
                is_dirty = next_model != snapshot
                # A re-entrant dispose or commit made this preparation stale.
                if self._disposed or self._generation != generation:
                    return
                errors_changed = next_errors != self._errors
                self._model = next_model
                self._errors = next_errors
                self._generation += 1
                is_valid = not next_errors

                if errors_changed:
                    self._errors_changed.on_next(dict(next_errors))
                can_execute_changed = (
                    self._strict and was_dirty != is_dirty
                ) or is_valid != was_valid

            self._hub.send(FormRevertedMessage(sender=self, sender_name="FormVM"))
            self._hub.send(
                PropertyChangedMessage.create(
                    sender=self,
                    sender_name="FormVM",
                    property_name="model",
                )
            )
            if can_execute_changed:
                with self._state_changed:
                    self._can_execute_trigger.on_next(None)
        except BaseException as error:
            in_flight = error
            raise
        finally:
            if admitted:
                self._end_mutation(in_flight)

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

    def _approve_fire_and_forget(self) -> None:
        """Synchronous wrapper that schedules the async approve.

        Called by the RelayCommand (which expects a sync callable). Fire-and-forget:
        a persister failure is routed to :attr:`approve_errors` instead of being
        swallowed (VMX-008). Use :meth:`approve_async` for awaitable raising behavior.

        Admission (spec/20 §5.3) happens synchronously here, before the persist
        is scheduled, so a second ``execute()`` in the same turn is refused.
        """
        admission = self._admit_approval()
        if admission is None:
            return
        scheduled_run = ScheduledRun()
        approval = self._run_admitted_approval(admission[0], scheduled_run)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            scheduled: asyncio.Task[None] | Future[None] = (
                loop.create_task(approval) if loop is not None else submit_background(approval)
            )
        except BaseException:
            # Nothing was scheduled: release the admission instead of wedging.
            approval.close()
            if scheduled_run.claim_release():
                self._settle_failed_approval()
            raise
        # Mirror the C# continuation: surface the persister failure on the error
        # channel. A cancelled approval is also a non-success outcome (spec/20
        # §5.3); Task.exception() raises for it, so it is reported explicitly.
        scheduled.add_done_callback(lambda done: self._on_approve_done(done, scheduled_run))

    def _on_approve_done(
        self,
        task: asyncio.Future[None] | Future[None],
        scheduled_run: ScheduledRun,
    ) -> None:
        if task.cancelled():
            # A task cancelled before its first step never ran the body that
            # settles the approval: settle it here, before routing (spec/20 §5.3).
            if scheduled_run.claim_release():
                self._settle_failed_approval()
            self._emit_approve_error(asyncio.CancelledError())
            return
        exc = task.exception()
        if exc is not None:
            self._emit_approve_error(exc)

    def _emit_approve_error(self, exc: BaseException) -> None:
        # The subject is completed+disposed on dispose(); a persister failure
        # arriving after dispose must not raise reactivex DisposedException.
        # Publish as an approval publication rather than under the lock, so a
        # concurrent dispose still waits for delivery but observers run unlocked.
        caller = get_ident()
        with self._state_changed:
            while (
                self._approval_publishing
                and self._approval_publisher_thread != caller
                and not self._disposed
            ):
                self._state_changed.wait()
            if self._disposed:
                return
            outer = self._enter_publication(caller, pre_publishing=False)
        try:
            self._approve_errors.on_next(exc)
        finally:
            self._exit_publication(outer)

    def _can_approve(self) -> bool:
        """``approve_command`` predicate: validity, strict mode, and admission."""
        with self._state_changed:
            if self._errors or self._approval_in_flight:
                return False
            return not self._strict or self._model != self._snapshot
