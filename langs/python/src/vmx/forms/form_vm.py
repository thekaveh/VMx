"""FormVM[TM] — snapshot/revert edit lifecycle ViewModel.

See spec/20-form-vm.md and ADR-0030.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import enum
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


class _NestedApproval:
    """An approval admitted by a nested call (spec/20 §5.4, ADR-0180).

    ``start(run)`` starts its persister when ``run`` is set, after the
    outermost update sends its queue; ``start(False)`` abandons it.
    ``announced`` records that its admission notification was sent;
    ``released`` that a failed admission notification released it.
    """

    __slots__ = ("announced", "released", "start")

    def __init__(self, start: Callable[[bool], None]) -> None:
        self.start = start
        self.announced = False
        self.released = False


class _Frame:
    """One thread's update preparations on one form (spec/20 §5.4, ADR-0215).

    ``depth`` counts the thread's ``set_model`` and deny frames that are
    preparing. ``changes`` counts the commits and queued calls the thread
    made while a frame was open, so a frame can tell that a callback on its
    own thread made its preparation stale. ``pending`` holds the
    notifications that nested calls queued for the outermost update.
    """

    __slots__ = ("changes", "depth", "pending")

    def __init__(self) -> None:
        self.depth = 0
        self.changes = 0
        self.pending = _Notices()


class _Notice:
    """One queued notification. ``approval`` marks an admission notification."""

    __slots__ = ("approval", "nested", "send")

    def __init__(self, send: Callable[[], None], approval: _NestedApproval | None = None) -> None:
        self.send = send
        self.approval = approval
        self.nested = False


class _Notices:
    """Notifications an update or admission sends with no form lock held.

    Each ``errors`` map is sent inside the update scope its commit opened;
    ``scopes`` holds the state each of those scopes restores when it closes.
    ``after_scope`` follows once the scopes close, and ``starts`` start the
    persisters of nested approvals last (spec/20 §5.4, ADR-0180).
    """

    __slots__ = ("after_scope", "errors", "scopes", "starts")

    def __init__(self) -> None:
        self.errors: list[_Notice] = []
        self.scopes: list[bool] = []
        self.after_scope: list[_Notice] = []
        self.starts: list[_NestedApproval] = []

    def extend(self, other: _Notices) -> None:
        self.errors += other.errors
        self.scopes += other.scopes
        self.after_scope += other.after_scope
        self.starts += other.starts

    def mark_nested(self) -> None:
        for notice in (*self.errors, *self.after_scope):
            notice.nested = True


class _Placement(enum.Enum):
    """What a completed preparation does (spec/20 §5.4, ADR-0215)."""

    STOP = enum.auto()
    """The form was disposed, or a callback on the preparing thread made it stale."""
    QUEUE = enum.auto()
    """The call joins a publisher's queue."""
    RETRY = enum.auto()
    """Another thread overtook the preparation; the call runs again."""
    COMMIT = enum.auto()
    """The prepared result is committed."""


def _resolve(future: asyncio.Future[bool], value: bool) -> None:
    if not future.done():
        future.set_result(value)


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
        # Commit generation (spec/20 §5.4, ADR-0215): advanced by every commit
        # of model, snapshot, or errors. An update whose preparation another
        # thread's commit overtook runs again as a new call.
        self._generation = 0
        # Preparation frames per thread (spec/20 §5.4, ADR-0180, ADR-0215).
        # set_model and deny run their callbacks with no lock held, so each
        # thread keeps its own nesting depth, own-change count, and the
        # notifications its nested calls queued for its outermost update.
        self._frames: dict[int, _Frame] = {}
        # The threads that send error maps inside their update scopes. An
        # update or admission made from such an errors_changed observer
        # queues its notifications in that thread's _scoped_notices entry.
        self._error_delivery_threads: set[int] = set()
        self._scoped_notices: dict[int, _Notices] = {}

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
            .build()
        )
        # The form's own notification is call-fed (spec/03 §3.6): an observer
        # failure reaches the form's caller (spec/20 §5.3). A command trigger
        # would log it instead, so the form raises the command directly.
        self._can_execute_trigger.subscribe(
            lambda _: self._approve_command.raise_can_execute_changed()
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
        """``True`` when ``model`` is structurally not equal to ``snapshot``.

        The comparison runs after the state lock is released (spec/20 §5.4).
        """
        with self._state_changed:
            model, snapshot = self._model, self._snapshot
        return model != snapshot

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
        re-enters the form and another update commits or is queued, or the
        form is disposed, this call commits and publishes nothing.

        The callbacks run with no form lock held (spec/20 §5.4, ADR-0215).
        Other threads' reads and calls do not wait for them. When another
        thread commits while they run, this call runs again as a new call.
        In non-strict mode only the candidate is compared with the live model
        (spec/20 §5.2, ADR-0216).

        Inside an approval's pre-publication window on the approving thread
        (spec/20 §5.3, ADR-0174), the call prepares at call time, so a failing
        callback still raises here, and is then queued: it changes and
        publishes nothing until it replays after ``on_approved``. Such a call
        never waits for another thread's publication scope (§5.5).

        While another thread holds a publication scope (spec/20 §5.5), the
        call waits for it. When that wait would close a wait-for cycle, the
        call prepares, joins that publisher's queue, and returns before it
        takes effect.

        A call nested in a preparation callback, or in an ``errors_changed``
        observer, of another ``set_model`` or deny on this thread (spec/20
        §5.4, ADR-0180) commits at once but returns before its notifications.
        The outermost update sends them before it returns, with no lock held,
        and drops them once the form is disposed. A nested call never waits
        for another thread's publication scope; it takes the refused-wait
        result.
        """
        while self._set_model_once(model):
            pass

    def _set_model_once(self, model: TM) -> bool:
        """Run one ``set_model`` call. Return ``True`` when it must run again.

        Admission and commit take the state lock; the preparation callbacks
        run between them with no lock held (spec/20 §5.4, ADR-0215).
        """
        caller = get_ident()
        admitted = False
        in_flight: BaseException | None = None
        delivery: _Notices | None = None
        try:
            with self._state_changed:
                refused = self._wait_for_admission(caller)
                if self._disposed:
                    return False
                if model is None:
                    # Reject before any deferral, so the caller sees the error.
                    raise ValueError("model must not be None")
                queue = self._queue_for(caller, refused)
                self._active_mutations += 1
                admitted = True
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                was_valid = not self._errors
                frame = self._enter_frame(caller)
                changes = frame.changes
            own = _Notices()
            try:
                # Prepare (spec/20 §5.4) with no lock held. A call in the
                # approval's pre-publication window runs the same preparation
                # and is then queued (§5.3 rule 2): equality never skips the
                # enqueue, because earlier queued updates can change the live
                # model before this one replays. The replay prepares again.
                # Only strict mode compares with the snapshot (§5.2).
                unchanged = current == model
                if unchanged and queue is None:
                    return False
                was_dirty = self._strict and current != snapshot
                next_errors = self._validate(model)
                is_dirty = self._strict and model != snapshot
                with self._state_changed:
                    placement, queue = self._place_locked(caller, frame, changes, generation, queue)
                    if placement is _Placement.QUEUE:
                        assert queue is not None
                        self._queue_update(caller, queue, partial(self.set_model, model))
                    if placement is not _Placement.COMMIT or unchanged:
                        return placement is _Placement.RETRY
                    # Commit in one step, then queue the notifications.
                    errors_changed = next_errors != self._errors
                    self._model = model
                    self._errors = next_errors
                    self._note_commit(caller)
                    is_valid = not next_errors
                    if errors_changed:
                        self._queue_error_map(caller, own, next_errors)
                    if (self._strict and is_dirty != was_dirty) or is_valid != was_valid:
                        own.after_scope.append(_Notice(self._raise_can_execute))
                    own.after_scope.append(_Notice(partial(self._hub.send, self._model_message())))
                    return False
            finally:
                with self._state_changed:
                    frame.depth -= 1
                    delivery = self._take_notices_locked(caller, own)
        except BaseException as error:
            in_flight = error
            raise
        finally:
            self._finish_update(caller, admitted, in_flight, delivery)

    def _model_message(self) -> PropertyChangedMessage[FormVM[TM]]:
        return PropertyChangedMessage.create(
            sender=self,
            sender_name="FormVM",
            property_name="model",
        )

    def _raise_can_execute(self) -> None:
        self._can_execute_trigger.on_next(None)

    def _queue_error_map(self, caller: int, own: _Notices, errors: dict[str, str]) -> None:
        """Queue a committed error map inside a new update scope. Call holding the state lock.

        The update scope covers the error map, so error maps reach observers
        in commit order (spec/20 §5.5).
        """
        own.errors.append(_Notice(partial(self._errors_changed.on_next, dict(errors))))
        own.scopes.append(self._enter_publication(caller, pre_publishing=False))

    def _in_nested_window(self, caller: int) -> bool:
        """``True`` when a call by *caller* is nested (spec/20 §5.4).

        Must be called holding the state lock.
        """
        frame = self._frames.get(caller)
        return (frame is not None and frame.depth > 0) or caller in self._error_delivery_threads

    def _enter_frame(self, caller: int) -> _Frame:
        """Open a preparation frame on *caller*. Call holding the state lock."""
        frame = self._frames.get(caller)
        if frame is None:
            frame = self._frames[caller] = _Frame()
        frame.depth += 1
        return frame

    def _note_change(self, caller: int) -> None:
        """Record that *caller* committed or queued an update. Call holding the state lock.

        A preparation open on *caller* is then stale (spec/20 §5.4).
        """
        frame = self._frames.get(caller)
        if frame is not None:
            frame.changes += 1

    def _note_commit(self, caller: int) -> None:
        """Advance the commit generation for a commit by *caller*. Call holding the state lock."""
        self._generation += 1
        self._note_change(caller)

    def _wait_for_admission(self, caller: int) -> int | None:
        """Wait before a ``set_model`` or deny is admitted. Call holding the state lock.

        A call in its own thread's pre-publication window joins that thread's
        queue, so it never waits for another thread's scope (spec/20 §5.5,
        ADR-0215). Any other call waits as :meth:`_wait_for_other_publication`
        states.
        """
        own = self._publications.get(caller)
        if own is not None and own.in_pre_publication_window():
            return None
        return self._wait_for_other_publication(caller)

    def _place_locked(
        self,
        caller: int,
        frame: _Frame,
        changes: int,
        generation: int,
        queue: _ThreadPublication | None,
    ) -> tuple[_Placement, _ThreadPublication | None]:
        """Decide what a completed preparation does. Call holding the state lock.

        The cases apply in order (spec/20 §5.4, ADR-0215): a disposed form
        stops the call; a commit or queued call by a callback on this thread
        makes it stale; a call bound for a queue joins it; and a commit by
        another thread since the preparation started, or another thread's
        open scope, makes the call run again as a new call.
        """
        if self._disposed or frame.changes != changes:
            return _Placement.STOP, None
        queue = self._live_queue(caller, queue)
        if queue is not None:
            return _Placement.QUEUE, queue
        if self._generation != generation or self._other_publisher(caller) is not None:
            return _Placement.RETRY, None
        return _Placement.COMMIT, None

    def _take_notices_locked(self, caller: int, own: _Notices) -> _Notices:
        """Return the notifications *caller* sends once it leaves its frame.

        Must be called holding the state lock. A nested call queues *own* for
        the outermost update on its thread and returns nothing (spec/20 §5.4,
        ADR-0180). The outermost update takes the whole queue.
        """
        if self._in_nested_window(caller):
            own.mark_nested()
        frame = self._frames.get(caller)
        if frame is not None and frame.depth > 0:
            frame.pending.extend(own)
            return _Notices()
        delivery = own
        if frame is not None:
            del self._frames[caller]
            frame.pending.extend(own)
            delivery = frame.pending
        if caller in self._error_delivery_threads:
            self._scoped_notices.setdefault(caller, _Notices()).extend(delivery)
            return _Notices()
        return delivery

    def _deliver(
        self, caller: int, notices: _Notices
    ) -> tuple[list[Callable[[], None]], BaseException | None]:
        """Send the notifications of an outermost update, with no form lock held.

        Order (spec/20 §5.4, ADR-0180): each error map inside its update
        scope, in commit order, including the maps of updates that its
        errors_changed observers made; then the scopes close; then the other
        notifications in queue order; then the persisters of nested
        approvals start. A notification that a nested call queued is dropped
        once the form is disposed.

        The first observer failure stops the remaining notifications, and a
        nested approval not yet started is then released. Returns the queue
        to replay and the first failure.
        """
        failure: BaseException | None = None
        if notices.errors:
            with self._state_changed:
                self._error_delivery_threads.add(caller)
            try:
                sent = 0
                while sent < len(notices.errors):
                    notice = notices.errors[sent]
                    sent += 1
                    if failure is None:
                        failure = self._send(notice)
                    if sent == len(notices.errors):
                        with self._state_changed:
                            scoped = self._scoped_notices.pop(caller, None)
                        if scoped is not None:
                            notices.extend(scoped)
            finally:
                with self._state_changed:
                    self._error_delivery_threads.discard(caller)
        replays: list[Callable[[], None]] = []
        for outer in reversed(notices.scopes):
            # The teardown claim cannot succeed here: this update still counts
            # in _active_mutations, so its _end_mutation runs a deferred
            # teardown. Keep the update inside that count.
            queue, _ = self._exit_scope(caller, outer)
            replays += queue
        for notice in notices.after_scope:
            if failure is None:
                failure = self._send(notice)
        for approval in notices.starts:
            if failure is None:
                failure = self._start_nested_approval(approval)
                continue
            if not approval.released:
                self._release_nested_approval(approval, notify=approval.announced)
            approval.start(False)
        return replays, failure

    def _send(self, notice: _Notice) -> BaseException | None:
        """Send one queued notification; return its observer's failure."""
        if notice.nested:
            with self._state_changed:
                if self._disposed:
                    return None
        try:
            notice.send()
        except BaseException as error:
            if notice.approval is not None:
                # The persister never runs; tell the observers that saw the
                # admission edge (#732), as a top-level admission does.
                self._release_nested_approval(notice.approval, notify=True)
            return error
        if notice.approval is not None:
            notice.approval.announced = True
        return None

    def _start_nested_approval(self, approval: _NestedApproval) -> BaseException | None:
        """Start a nested approval's persister, unless the form is disposed (§10)."""
        if not approval.released:
            with self._state_changed:
                disposed = self._disposed
            if disposed:
                self._release_nested_approval(approval, notify=False)
        if approval.released:
            approval.start(False)
            return None
        try:
            approval.start(True)
        except BaseException as error:
            return error
        return None

    def _release_nested_approval(self, approval: _NestedApproval, *, notify: bool) -> None:
        """Clear a nested approval's in-flight mark; its persister never starts.

        With *notify*, the observers that saw the admission edge get the
        release edge, unless the form is disposed.
        """
        approval.released = True
        with self._state_changed:
            self._approval_in_flight = False
            notify = notify and not self._disposed
        if notify:
            with contextlib.suppress(BaseException):
                self._can_execute_trigger.on_next(None)

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

        A call nested in a ``set_model`` or deny on this thread (spec/20 §5.4)
        is admitted at once, but its persister starts only after the
        outermost update sends its notifications. Blocking on it inside the
        callback, as ``asyncio.run(form.approve_async())`` does, never returns.
        """
        loop = asyncio.get_running_loop()
        started: asyncio.Future[bool] = loop.create_future()
        claim = ScheduledRun()

        def start(_: TM, run: bool) -> None:
            # Runs in the outermost update's delivery (ADR-0180). An awaiter
            # cancelled first, or a closed loop, releases the admission.
            if run and not claim.claim_start():
                self._settle_failed_approval()
                return
            try:
                loop.call_soon_threadsafe(_resolve, started, run)
            except RuntimeError:
                if run:
                    self._settle_failed_approval()

        admission = self._admit_approval(start)
        if admission is None:
            return
        current, nested = admission
        if nested:
            try:
                run = await started
            except BaseException:
                if not claim.claim_release():
                    self._settle_failed_approval()
                raise
            if not run:
                return
        await self._run_admitted_approval(current)

    def _admit_approval(self, start: Callable[[TM, bool], None]) -> tuple[TM, bool] | None:
        """Admit one approval or refuse it (spec/20 §5.3).

        Admission marks the approval in flight and captures the model in one
        critical section, then raises ``can_execute_changed`` once with no lock
        held. Returns the captured model and whether the call is nested, or
        ``None`` when the call is refused (disposed, invalid, or another
        approval in flight) or an admission observer disposed the form, so the
        persister must not run.

        A nested call (spec/20 §5.4, ADR-0180) queues the admission
        notification and ``start`` for the outermost update on this thread.
        That update calls ``start(captured, run)`` after its other
        notifications; ``run`` is ``False`` when the persister must not start.
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
            if self._in_nested_window(caller):
                approval = _NestedApproval(partial(start, captured))
                own = _Notices()
                own.after_scope.append(_Notice(self._raise_can_execute, approval))
                own.starts.append(approval)
                self._take_notices_locked(caller, own)
                return captured, True
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
        return captured, False

    async def _run_admitted_approval(
        self, current: TM, scheduled: ScheduledRun | None = None
    ) -> None:
        """Persist the captured model of an admitted approval and settle it.

        ``scheduled`` is the start claim of an approval scheduled as a task.
        A form disposed since admission never calls the persister and
        settles silently (spec/20 §10, ADR-0180).
        """
        if scheduled is not None and not scheduled.claim_start():
            return
        with self._state_changed:
            if self._disposed:
                self._approval_in_flight = False
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
            # The approval commit (snapshot advance or reset) makes an update
            # preparing on this thread stale, and one preparing on another
            # thread runs again (spec/20 §5.4).
            self._note_commit(caller)
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

        A nested call (spec/20 §5.4, ADR-0180) never waits. It takes the
        refused-wait result for any other thread's scope.
        """
        if self._in_nested_window(caller):
            if stop_on_disposal and self._disposed:
                return None
            return self._other_publisher(caller)
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
        caller: int,
        admitted: bool,
        in_flight: BaseException | None,
        delivery: _Notices | None,
    ) -> None:
        """End an update: send its notifications, replay its scope's queue, then release it.

        The outermost update sends the queue with no form lock held, then
        replays its scopes' queue, before it returns (spec/20 §5.4, §5.5). The
        first observer or replay failure propagates from the update, unless
        the update already carries a failure, which wins.
        """
        replays: list[Callable[[], None]] = []
        failure: BaseException | None = None
        if delivery is not None:
            replays, failure = self._deliver(caller, delivery)
        replay_failure = self._replay(replays)
        if failure is None:
            failure = replay_failure
        if admitted:
            self._end_mutation(in_flight if in_flight is not None else failure)
        if failure is not None and in_flight is None:
            raise failure

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

        The preparation runs with no lock held, so the publisher whose queue
        a refused call chose may have closed its scope.
        The call then joins another thread's open scope, or commits when none
        remains.
        """
        if queue is None or queue.in_pre_publication_window() or queue.depth:
            return queue
        publisher = self._other_publisher(caller)
        return None if publisher is None else self._publications[publisher]

    def _queue_update(
        self, caller: int, queue: _ThreadPublication, replay: Callable[[], None]
    ) -> None:
        """Queue a prepared update that is not stale (spec/20 §5.3 rule 2).

        Must be called holding the state lock. Any update still preparing on
        this thread is then stale, so the newest call wins, as it does for a
        committed update. A queued call commits nothing, so it does not make
        another thread's preparation run again.
        """
        self._note_change(caller)
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
        outermost scope ends. The calls that wait for a scope then wake at
        once and find the form disposed (ADR-0215). A ``dispose()`` while
        another thread's update prepares returns at once; the teardown runs
        when that update returns (spec/20 §10).
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
            # Remove the edges that name this form's scope and wake every
            # scope waiter (spec/20 §5.5, ADR-0215). A settlement, which
            # disposal does not stop, records its wait again.
            WAITS.release_waiters(self._publication_scope, ())
            self._state_changed.notify_all()
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
        while self._deny_once():
            pass

    def _deny_once(self) -> bool:
        """Run one deny call. Return ``True`` when it must run again.

        Admission and commit take the state lock; the preparation callbacks
        run between them with no lock held (spec/20 §5.4, ADR-0215).
        """
        caller = get_ident()
        admitted = False
        in_flight: BaseException | None = None
        delivery: _Notices | None = None
        try:
            with self._state_changed:
                refused = self._wait_for_admission(caller)
                if self._disposed:
                    return False
                queue = self._queue_for(caller, refused)
                self._active_mutations += 1
                admitted = True
                generation = self._generation
                current, snapshot = self._model, self._snapshot
                was_valid = not self._errors
                frame = self._enter_frame(caller)
                changes = frame.changes
            own = _Notices()
            try:
                # Prepare the revert (spec/20 §5.4) with no lock held: the
                # snapshotter, the strict-mode equality (§5.2), and the
                # validators run before anything is committed or published.
                # Inside the approving thread's pre-publication window the
                # prepared revert is discarded and the deny is queued (§5.3,
                # ADR-0174); it replays as a new call.
                was_dirty = self._strict and current != snapshot
                next_model = self._snapshotter(snapshot)
                next_errors = self._validate(next_model)
                is_dirty = self._strict and next_model != snapshot
                with self._state_changed:
                    placement, queue = self._place_locked(caller, frame, changes, generation, queue)
                    if placement is _Placement.QUEUE:
                        assert queue is not None
                        self._queue_update(caller, queue, self._deny)
                    if placement is not _Placement.COMMIT:
                        return placement is _Placement.RETRY
                    errors_changed = next_errors != self._errors
                    self._model = next_model
                    self._errors = next_errors
                    self._note_commit(caller)
                    is_valid = not next_errors
                    if errors_changed:
                        self._queue_error_map(caller, own, next_errors)
                    reverted = FormRevertedMessage(sender=self, sender_name="FormVM")
                    own.after_scope.append(_Notice(partial(self._hub.send, reverted)))
                    own.after_scope.append(_Notice(partial(self._hub.send, self._model_message())))
                    if (self._strict and was_dirty != is_dirty) or is_valid != was_valid:
                        own.after_scope.append(_Notice(self._raise_can_execute))
                    return False
            finally:
                with self._state_changed:
                    frame.depth -= 1
                    delivery = self._take_notices_locked(caller, own)
        except BaseException as error:
            in_flight = error
            raise
        finally:
            self._finish_update(caller, admitted, in_flight, delivery)

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
        is scheduled, so a second ``execute()`` in the same turn is refused. A
        nested call (§5.4, ADR-0180) schedules the persist after the outermost
        update sends its notifications.
        """
        admission = self._admit_approval(self._start_queued_command_approval)
        if admission is None:
            return
        current, nested = admission
        if not nested:
            self._schedule_approval(current)

    def _start_queued_command_approval(self, current: TM, run: bool) -> None:
        if run:
            self._schedule_approval(current)

    def _schedule_approval(self, current: TM) -> None:
        """Schedule the persist of an admitted command-path approval."""
        scheduled_run = ScheduledRun()
        approval = self._run_admitted_approval(current, scheduled_run)
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
        """``approve_command`` predicate: validity, strict mode, and admission.

        The strict comparison runs after the state lock is released (spec/20
        §5.4).
        """
        with self._state_changed:
            if self._errors or self._approval_in_flight:
                return False
            if not self._strict:
                return True
            model, snapshot = self._model, self._snapshot
        return model != snapshot
