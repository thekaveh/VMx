"""FormVM[TM] — snapshot/revert edit lifecycle ViewModel.

See spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future
from functools import partial
from threading import Condition, RLock, get_ident
from typing import Any, Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx._asyncio_runner import ScheduledRun, submit_background
from vmx._disposal import _run_disposal_steps
from vmx._wait_for_graph import WAITS
from vmx.commands.relay_command import RelayCommand
from vmx.forms.builders import FormVMBuilder
from vmx.messages.form_reverted import FormRevertedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHubProto
from vmx.services.null_message_hub import NULL_MESSAGE_HUB

TM = TypeVar("TM")

FieldValidator = Callable[[TM], str | None]
ModelValidator = Callable[[TM], Mapping[str, str | None]]


class _PublicationScope:
    """The wait-for graph resource of one form's publication scopes."""

    __slots__ = ()


class _ThreadPublication:
    """One thread's publication state on one form (spec/20 §5.3, §5.5).

    ``depth`` counts the publication scopes the thread holds; scopes nest on
    their thread. ``pre_publishing`` marks settlement steps 2 and 3 of the
    innermost scope. ``commit_window`` marks the thread's post-persist commit,
    which is part of the pre-publication window but holds no other thread.
    ``queue`` holds the thread's own pre-publication updates and other
    threads' refused updates, in the order they joined it. Each item is a set
    or a deny that replays as a new call when the outermost scope ends.
    """

    __slots__ = ("commit_window", "depth", "pre_publishing", "queue")

    def __init__(self) -> None:
        self.depth = 0
        self.pre_publishing = False
        self.commit_window = False
        self.queue: list[Callable[[], None]] = []

    def in_pre_publication_window(self) -> bool:
        return (self.depth > 0 and self.pre_publishing) or self.commit_window


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
        # Per-thread publication state (spec/20 §5.5, ADR-0176): the threads
        # that hold publication scopes, are in a post-persist commit, or keep
        # a queue. Two threads can hold scopes when a cyclic settlement wait
        # was refused, so nothing here is form-wide.
        self._publications: dict[int, _ThreadPublication] = {}
        # The resource that publication-scope waits name in the wait-for
        # graph: one per form, owned by a publisher (ADR-0176 rule 4).
        self._publication_scope = _PublicationScope()
        self._active_mutations = 0
        self._mutation_teardown_pending = False
        # Update generation (spec/20 §5.4): advanced by every commit of model,
        # snapshot, or errors, and by every queued update (§5.3), so an update
        # whose callbacks re-entered the form can tell that its preparation
        # went stale.
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

        Inside an approval's pre-publication window on the approving thread
        (spec/20 §5.3, ADR-0174), the call prepares at call time, so a failing
        callback still raises here, and is then queued: it changes and
        publishes nothing until it replays after ``on_approved``.

        While another thread holds a publication scope (spec/20 §5.5), the
        call waits for it. When that wait would close a wait-for cycle, the
        call prepares, joins that publisher's queue, and returns before it
        takes effect.
        """
        caller = get_ident()
        admitted = False
        in_flight: BaseException | None = None
        replays: list[Callable[[], None]] | None = None
        try:
            with self._state_changed:
                refused = self._wait_for_other_publication(caller)
                if self._disposed:
                    return
                if model is None:
                    # Reject before any deferral, so the caller sees the error.
                    raise ValueError("model must not be None")
                queue = self._queue_for(caller, refused)
                self._active_mutations += 1
                admitted = True
                # Prepare (spec/20 §5.4) without touching form state. Callbacks
                # run under the re-entrant state lock: one may re-enter
                # set_model, deny, or dispose on this thread, while another
                # thread's update or dispose waits for this one. A call in the
                # approval's pre-publication window runs the same preparation
                # and is then queued (§5.3 rule 2): equality never skips the
                # enqueue, because earlier queued updates can change the live
                # model before this one replays. The replay prepares again.
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                if current == model and queue is None:
                    return
                was_dirty = current != snapshot
                was_valid = not self._errors
                next_errors = self._validate(model)
                is_dirty = model != snapshot
                # A re-entrant dispose, commit, or queued update made this
                # preparation stale.
                if self._disposed or self._generation != generation:
                    return
                queue = self._live_queue(caller, queue)
                if queue is not None:
                    self._queue_update(queue, partial(self.set_model, model))
                    return
                if current == model:
                    return
                # Commit in one step, then notify.
                errors_changed = next_errors != self._errors
                self._model = model
                self._errors = next_errors
                self._generation += 1
                is_valid = not next_errors
                notify_can_execute = (
                    self._strict and is_dirty != was_dirty
                ) or is_valid != was_valid
                # The update scope covers the error map, so error maps reach
                # observers in commit order (spec/20 §5.5).
                scope_outer = (
                    self._enter_publication(caller, pre_publishing=False)
                    if errors_changed
                    else None
                )
            if scope_outer is not None:
                try:
                    self._errors_changed.on_next(dict(next_errors))
                finally:
                    replays, _ = self._exit_scope(caller, scope_outer)
            if notify_can_execute:
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
            self._finish_update(admitted, in_flight, replays)

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
            # A wait for another thread's scope that would close a wait-for
            # cycle is refused, and the call is admitted without waiting
            # (spec/20 §5.5). Its settlement waits like any other.
            self._wait_for_other_publication(caller)
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
        except BaseException:
            # Persister failure or cancellation.
            self._settle_failed_approval()
            raise
        self._settle_approval(current)

    def _settle_approval(self, current: TM) -> None:
        """Run the post-persist commit of a successful approval and settle it.

        Order (spec/20 §5.1, §5.3): prepare the configured reset state, or the
        legacy snapshot advance, before committing any local state; clear the
        in-flight mark with the commit; ``errors_changed`` when the effective
        map changed; ``can_execute_changed`` exactly once; then ``on_approved``.

        The pre-publication window opens with the commit (ADR-0174): an update
        this thread makes from the reset, the snapshotter, a validator, or a
        settlement step 2 or 3 observer is queued. The commit marks only this
        thread, so another thread is not held until the settlement scope
        opens at settlement step 1 (rule 7). The queue replays when the
        outermost scope on this thread ends. The first replay failure then
        propagates to this approval's failure route unless the approval
        already carries a failure, which wins.
        """
        caller = get_ident()
        with self._state_changed:
            # dispose() may have run during the persister await; disposal
            # suppresses the whole settlement (spec/20 §5.3/§10): the subjects
            # are completed and disposed, so emitting would raise.
            if self._disposed:
                self._approval_in_flight = False
                return
            publication = self._publication_of(caller)
            outer_window = publication.commit_window
            publication.commit_window = True
        try:
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
            # A failed post-persist commit: the window ends with the failure.
            # The calls it queued replay after the failure settlement's
            # can_execute_changed, and the commit failure wins (FORM-033).
            with self._state_changed:
                publication.commit_window = outer_window
            self._settle_failed_approval()
            raise

        with self._state_changed:
            # Unlike the other waits, disposal does not end this one. A wait
            # that would close a wait-for cycle is refused, and the settlement
            # commits at once in its own scope (spec/20 §5.5).
            self._wait_for_other_publication(caller, stop_on_disposal=False)
            publication.commit_window = outer_window
            self._approval_in_flight = False
            if self._disposed:
                self._drop_queue_after_disposal(caller)
                return
            # Settlement step 1 opens the settlement scope.
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

        replay_failure: BaseException | None = None
        try:
            self._publish_approval(caller, current, published_errors)
        finally:
            # The queue replays here, after on_approved delivery returns. A
            # settlement observer failure propagates past this block and wins
            # over a replay failure.
            replay_failure = self._exit_publication(caller, outer)
        if replay_failure is not None:
            raise replay_failure

    def _publish_approval(
        self, caller: int, current: TM, published_errors: dict[str, str] | None
    ) -> None:
        """Publish settlement steps 2 to 4 of a committed approval.

        A disposing observer stops the remaining notifications. So does a
        disposal from another thread whose wait for this scope was refused.
        """
        if published_errors is not None:
            self._errors_changed.on_next(published_errors)
            if self._disposed:
                return
        self._can_execute_trigger.on_next(None)
        if self._disposed:
            return

        with self._state_changed:
            # A nested approval suspends the outer window while it delivers
            # on_approved; the exit of its scope restores it (spec/20 §5.5).
            self._publications[caller].pre_publishing = False

        # Emit the value that was actually persisted (parity with C#'s
        # captured `current`): a set_model racing the persister await must
        # not swap the approved payload for a newer un-persisted model.
        self._on_approved.on_next(current)

    def _settle_failed_approval(self) -> None:
        """Clear the in-flight mark and raise ``can_execute_changed`` once.

        The caller then routes the failure to the awaiter (or, on the command
        path, ``approve_errors``). That failure is the first error and wins: an
        observer raising from this notification must not replace it (the
        ``_end_mutation`` first-error policy). The notification runs in a
        settlement scope (spec/20 §5.5).
        """
        caller = get_ident()
        with self._state_changed:
            self._wait_for_other_publication(caller)
            self._approval_in_flight = False
            if self._disposed:
                self._drop_queue_after_disposal(caller)
                return
            # A failed settlement keeps an enclosing approval's window: only a
            # nested on_approved delivery suspends it (spec/20 §5.5).
            outer = self._enter_publication(
                caller, pre_publishing=self._publication_of(caller).pre_publishing
            )
        try:
            with contextlib.suppress(BaseException):
                self._can_execute_trigger.on_next(None)
        finally:
            # Calls a failed post-persist commit queued replay here, before
            # the caller routes the failure. That failure wins, so a replay
            # failure is discarded (spec/20 §5.3, ADR-0174).
            self._exit_publication(caller, outer)

    def _other_publisher(self, caller: int) -> int | None:
        """Return a thread other than *caller* that holds a publication scope.

        Must be called holding the state lock.
        """
        for thread, publication in self._publications.items():
            if thread != caller and publication.depth > 0:
                return thread
        return None

    def _publishers(self) -> list[int]:
        """The threads that hold publication scopes. Call holding the state lock."""
        return [thread for thread, publication in self._publications.items() if publication.depth]

    def _wait_for_other_publication(
        self, caller: int, *, stop_on_disposal: bool = True
    ) -> int | None:
        """Wait until no thread other than *caller* holds a publication scope.

        Must be called holding the state lock. When *stop_on_disposal* is set,
        disposal also ends the wait. Returns ``None`` once the caller may
        proceed. Each wait records an edge to one publisher in the
        process-wide wait-for graph (spec/20 §5.5, ADR-0176). When that wait
        would close a cycle, it is refused, and this returns the publisher it
        named; the caller then takes its refused-wait result.
        """
        while not (stop_on_disposal and self._disposed):
            publisher = self._other_publisher(caller)
            if publisher is None:
                return None
            if not WAITS.try_begin_owner_wait(
                self._publication_scope, owner=publisher, caller=caller
            ):
                return publisher
            try:
                self._state_changed.wait()
            finally:
                WAITS.end_wait(caller)
        return None

    def _publication_of(self, caller: int) -> _ThreadPublication:
        """Return *caller*'s publication state, creating it. Call holding the state lock."""
        publication = self._publications.get(caller)
        if publication is None:
            publication = self._publications[caller] = _ThreadPublication()
        return publication

    def _forget_if_idle(self, caller: int) -> None:
        """Drop *caller*'s publication state once nothing uses it. Call holding the state lock."""
        publication = self._publications.get(caller)
        if (
            publication is not None
            and publication.depth == 0
            and not publication.commit_window
            and not publication.queue
        ):
            del self._publications[caller]

    def _enter_publication(self, caller: int, *, pre_publishing: bool) -> bool:
        """Open a publication scope on *caller*; return the state to restore.

        Must be called holding the state lock, after waiting out any other
        thread's scope (or having that wait refused). Other threads' updates,
        approvals and disposal wait until :meth:`_exit_scope`; same-thread
        updates made while ``pre_publishing`` is set are queued and replay
        when the outermost scope on this thread ends.
        """
        publication = self._publication_of(caller)
        outer = publication.pre_publishing
        publication.pre_publishing = pre_publishing
        publication.depth += 1
        return outer

    def _exit_scope(self, caller: int, outer: bool) -> tuple[list[Callable[[], None]], bool]:
        """Close one publication scope on *caller*.

        Returns the queue to replay and whether this thread must run a
        deferred teardown. Both are empty unless the outermost scope on this
        thread ended. Before it wakes the waiters, the thread removes the
        wait-for edges that name it (ADR-0172 rule 3).
        """
        with self._state_changed:
            publication = self._publications[caller]
            publication.depth -= 1
            publication.pre_publishing = outer
            if publication.depth:
                return [], False
            queue = publication.queue
            publication.queue = []
            self._forget_if_idle(caller)
            WAITS.release_waiters(self._publication_scope, self._publishers())
            self._state_changed.notify_all()
            return queue, self._claim_deferred_teardown()

    def _exit_publication(self, caller: int, outer: bool) -> BaseException | None:
        """Close a settlement scope; replay the queue once the outermost one ends.

        The replay runs after other threads are released (spec/20 §5.3 rule 7).
        A teardown that a refused disposal deferred runs first, so the replays
        are no-ops (§5.5). Returns the first failure, which the caller routes
        to its approval's failure route unless the approval already carries a
        failure.
        """
        queue, tear_down = self._exit_scope(caller, outer)
        first_failure: BaseException | None = None
        if tear_down:
            try:
                self._tear_down()
            except BaseException as error:
                first_failure = error
        replay_failure = self._replay(queue)
        return first_failure if first_failure is not None else replay_failure

    @staticmethod
    def _replay(queue: list[Callable[[], None]] | None) -> BaseException | None:
        """Replay queued updates as new calls, in order and in isolation.

        A failing replay does not stop the later ones. Returns the first
        failure.
        """
        first_failure: BaseException | None = None
        for replay in queue or ():
            try:
                replay()
            except BaseException as error:
                if first_failure is None:
                    first_failure = error
        return first_failure

    def _finish_update(
        self,
        admitted: bool,
        in_flight: BaseException | None,
        replays: list[Callable[[], None]] | None,
    ) -> None:
        """End an update: replay its scope's queue, then release the mutation.

        An update replays after its last notification and before it returns
        (spec/20 §5.5). The first replay failure propagates from the update,
        unless the update already carries a failure, which wins.
        """
        replay_failure = self._replay(replays)
        if admitted:
            self._end_mutation(in_flight if in_flight is not None else replay_failure)
        if replay_failure is not None and in_flight is None:
            raise replay_failure

    def _queue_for(self, caller: int, refused: int | None) -> _ThreadPublication | None:
        """Return the queue an update by *caller* joins, or ``None`` to commit.

        Must be called holding the state lock, after the caller's wait for
        other threads' scopes. A call in the caller's own pre-publication
        window joins its own queue (spec/20 §5.3 rule 1). A call whose wait
        was refused joins the queue of the publisher that its edge named
        (§5.5).
        """
        own = self._publications.get(caller)
        if own is not None and own.in_pre_publication_window():
            return own
        if refused is not None:
            return self._publications.get(refused)
        return None

    def _live_queue(
        self, caller: int, queue: _ThreadPublication | None
    ) -> _ThreadPublication | None:
        """Recheck the chosen queue after preparation. Call holding the state lock.

        A preparation callback can release the lock while it waits, so the
        publisher whose queue a refused call chose may have closed its scope.
        The call then joins another thread's open scope, or commits when none
        remains.
        """
        if queue is None or queue.in_pre_publication_window() or queue.depth:
            return queue
        publisher = self._other_publisher(caller)
        return None if publisher is None else self._publications[publisher]

    def _queue_update(self, queue: _ThreadPublication, replay: Callable[[], None]) -> None:
        """Queue a prepared update that is not stale (spec/20 §5.3 rule 2).

        Must be called holding the state lock. Advancing the generation makes
        any update still preparing on this thread stale, so the newest call
        wins, as it does for a committed update.
        """
        self._generation += 1
        queue.queue.append(replay)

    def _drop_queue_after_disposal(self, caller: int) -> None:
        """Drop *caller*'s queued updates once disposal suppressed the settlement.

        Must be called holding the state lock. A queued update would replay as
        a no-op on the disposed form. An open scope on this thread keeps the
        queue: its exit replays it, and each replay does nothing.
        """
        publication = self._publications.get(caller)
        if publication is not None and publication.depth == 0:
            publication.queue.clear()
            self._forget_if_idle(caller)

    def _claim_deferred_teardown(self) -> bool:
        """Claim a deferred teardown once no update or scope holds it off.

        Must be called holding the state lock.
        """
        if (
            self._mutation_teardown_pending
            and self._active_mutations == 0
            and not self._publishers()
        ):
            self._mutation_teardown_pending = False
            return True
        return False

    # ── Dispose ───────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete the ``on_approved`` observable and dispose resources. Idempotent.

        Waits while another thread holds a publication scope (spec/20 §5.5).
        When that wait would close a wait-for cycle, the form is marked
        disposed at once and the publisher runs the teardown after its
        outermost scope ends.
        """
        # reactivex Subjects raise DisposedException on a second on_completed,
        # unlike rxjs (no-op) and the guarded C# FormVM — guard for parity.
        caller = get_ident()
        tear_down = False
        with self._state_changed:
            refused = self._wait_for_other_publication(caller)
            if self._disposed:
                return
            self._disposed = True
            if refused is None and self._active_mutations == 0:
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
        Every teardown step still runs either way. While a thread holds a
        publication scope, that thread's scope exit runs the teardown instead.
        """
        with self._state_changed:
            self._active_mutations -= 1
            tear_down = self._claim_deferred_teardown()
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
        replays: list[Callable[[], None]] | None = None
        try:
            with self._state_changed:
                refused = self._wait_for_other_publication(caller)
                if self._disposed:
                    return
                queue = self._queue_for(caller, refused)
                self._active_mutations += 1
                admitted = True
                # Prepare the revert (spec/20 §5.4): the snapshotter, equality,
                # and validators run before anything is committed or published.
                # Inside the approving thread's pre-publication window the
                # prepared revert is discarded and the deny is queued (§5.3,
                # ADR-0174); it replays as a new call.
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                was_dirty = current != snapshot
                was_valid = not self._errors
                next_model = self._snapshotter(snapshot)
                next_errors = self._validate(next_model)
                is_dirty = next_model != snapshot
                # A re-entrant dispose, commit, or queued update made this
                # preparation stale.
                if self._disposed or self._generation != generation:
                    return
                queue = self._live_queue(caller, queue)
                if queue is not None:
                    self._queue_update(queue, self._deny)
                    return
                errors_changed = next_errors != self._errors
                self._model = next_model
                self._errors = next_errors
                self._generation += 1
                is_valid = not next_errors
                can_execute_changed = (
                    self._strict and was_dirty != is_dirty
                ) or is_valid != was_valid
                # The update scope covers the error map (spec/20 §5.5).
                scope_outer = (
                    self._enter_publication(caller, pre_publishing=False)
                    if errors_changed
                    else None
                )
            if scope_outer is not None:
                try:
                    self._errors_changed.on_next(dict(next_errors))
                finally:
                    replays, _ = self._exit_scope(caller, scope_outer)

            self._hub.send(FormRevertedMessage(sender=self, sender_name="FormVM"))
            self._hub.send(
                PropertyChangedMessage.create(
                    sender=self,
                    sender_name="FormVM",
                    property_name="model",
                )
            )
            if can_execute_changed:
                self._can_execute_trigger.on_next(None)
        except BaseException as error:
            in_flight = error
            raise
        finally:
            self._finish_update(admitted, in_flight, replays)

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
        # The delivery opens no publication scope (spec/20 §5.5) and runs with
        # no lock held. It counts as a mutation instead, so a concurrent
        # dispose defers its teardown until the delivery returns.
        with self._state_changed:
            if self._disposed:
                return
            self._active_mutations += 1
        failure: BaseException | None = None
        try:
            self._approve_errors.on_next(exc)
        except BaseException as error:
            failure = error
            raise
        finally:
            self._end_mutation(failure)

    def _can_approve(self) -> bool:
        """``approve_command`` predicate: validity, strict mode, and admission."""
        with self._state_changed:
            if self._errors or self._approval_in_flight:
                return False
            return not self._strict or self._model != self._snapshot
