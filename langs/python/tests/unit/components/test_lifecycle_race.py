"""VMX-004 regression: background construct/destruct vs dispose lifecycle race.

Python parity of the C# fix in commit 4afc9b6 (VMX-001/054). With a *real-thread*
background dispatcher, a background ``construct()`` completion can interleave with
a concurrent foreground ``dispose()``: the non-atomic check-then-act on ``_status``
inside ``_set_status`` lets the background thread write ``_status = CONSTRUCTED``
*after* the VM was disposed (resurrection) and publish a post-dispose status
message. The GIL prevents torn reads, so the window is narrower than C#, but the
resurrection-write / post-dispose-publish TOCTOU is real and reproducible.

Test approach: **real-thread stress loop** (the primary option — the race
reproduces within the iteration budget; confirmed against the unfixed source). A small
``_RealThreadDispatcher`` runs scheduled background work on a shared
``ThreadPoolExecutor``; a per-iteration ``threading.Barrier`` aligns the worker's
start with the concurrent foreground ``dispose()`` so the interleaving window is
hit reliably. The assertions encode the *correct* (locked) behaviour — final
status ``DISPOSED`` (no resurrection), no post-dispose ``CONSTRUCTED`` message, and
no exception on the worker thread — which the fixed code satisfies deterministically
(0 violations regardless of timing), while the unfixed code fails it.
"""

from __future__ import annotations

import datetime
import sys
import threading
import traceback
import types
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest
import reactivex.disposable as rx_disposable
from reactivex.scheduler import ImmediateScheduler

from tests.liveness import HANG_GUARD, future_result
from vmx.components import base as component_base
from vmx.components.builders import ComponentVMOfBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

if TYPE_CHECKING:
    from collections.abc import Callable

    from reactivex.abc import DisposableBase, SchedulerBase


# ---------------------------------------------------------------------------
# Real-thread background dispatcher (test double)
# ---------------------------------------------------------------------------


class _RealThreadBackgroundScheduler:
    """Rx-scheduler-shaped double that runs scheduled work on a real worker thread.

    Unlike ``ImmediateScheduler`` / ``TestScheduler`` (which run scheduled work
    inline on the calling thread, where the lifecycle in-flight guard is trivially
    consistent), this submits the action to a shared ``ThreadPoolExecutor`` so a
    background ``construct()`` completion genuinely races a foreground ``dispose()``.

    An optional ``gate`` :class:`threading.Barrier` lets a test rendezvous the
    worker's start with a concurrent foreground action, widening the (otherwise
    GIL-narrow) interleaving window so the race is hit within the iteration budget.
    Worker exceptions are captured in :attr:`errors` instead of being swallowed by
    the pool.
    """

    def __init__(self, pool: ThreadPoolExecutor) -> None:
        self._pool = pool
        self.futures: list[Future[None]] = []
        self.errors: list[BaseException] = []
        self.gate: threading.Barrier | None = None

    @property
    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def schedule(
        self,
        action: Callable[[Any, Any], Any],
        state: Any = None,
    ) -> DisposableBase:
        gate = self.gate

        def run() -> None:
            try:
                if gate is not None:
                    gate.wait(HANG_GUARD)
                action(self, state)
            except Exception as exc:  # record worker error instead of crashing the pool
                self.errors.append(exc)

        self.futures.append(self._pool.submit(run))
        return rx_disposable.Disposable()


class _RealThreadDispatcher:
    """``Dispatcher``-shaped double: inline foreground, real-thread background."""

    def __init__(self, background: _RealThreadBackgroundScheduler) -> None:
        self._foreground = ImmediateScheduler()
        self._background = background

    @property
    def foreground(self) -> SchedulerBase:
        return self._foreground

    @property
    def background(self) -> SchedulerBase:
        return self._background  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# VMX-004 — background construct racing dispose must be atomic + dispose-safe
# ---------------------------------------------------------------------------


def test_background_construct_racing_dispose_is_atomic() -> None:
    """A background ``construct()`` completion racing a foreground ``dispose()``
    must never (a) resurrect the VM (final status flipping back to Constructed
    after Disposed), (b) publish a post-dispose ``Constructed`` status message, or
    (c) raise on the worker thread (e.g. ``on_next`` on a disposed Subject).

    Disposed is terminal (spec/02 invariant 3). The fixed code serializes the
    ``_status`` read-modify-write + emission against ``dispose()`` under a lock, so
    these hold deterministically (0 violations); the unfixed check-then-act loses
    the race within this iteration budget.
    """
    # A small switch interval forces frequent GIL hand-offs, widening the
    # interleaving window so the (unfixed) race is hit early; restored below.
    original_switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)

    iterations = 8000
    resurrections = 0
    post_dispose_messages = 0
    worker_exceptions = 0
    first_violation = -1

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        for i in range(iterations):
            background = _RealThreadBackgroundScheduler(pool)
            dispatcher = _RealThreadDispatcher(background)
            hub: MessageHub[object] = MessageHub()
            vm = (
                ComponentVMOfBuilder()
                .name("vm")
                .services(hub, dispatcher)
                .model("m")
                .background(True)
                .build()
            )

            seen_disposed: list[bool] = []
            constructed_after_dispose: list[bool] = []

            def on_message(
                message: object,
                _vm: object = vm,
                _seen_disposed: list[bool] = seen_disposed,
                _after: list[bool] = constructed_after_dispose,
            ) -> None:
                if isinstance(message, ConstructionStatusChangedMessage) and message.sender is _vm:
                    if message.status is ConstructionStatus.DISPOSED:
                        _seen_disposed.append(True)
                    elif message.status is ConstructionStatus.CONSTRUCTED and _seen_disposed:
                        # A Constructed message after Disposed is a post-dispose
                        # publish (spec/02 invariant 3 violation).
                        _after.append(True)

            sub = hub.messages.subscribe(on_message)

            barrier = threading.Barrier(2)
            background.gate = barrier

            vm.construct()  # schedules _bg_construct, parked on the barrier
            barrier.wait(HANG_GUARD)  # release the worker; race its completion vs dispose()
            vm.dispose()

            for future in background.futures:
                future_result(future)  # surface any unexpected worker crash
            sub.dispose()

            if vm.status is ConstructionStatus.CONSTRUCTED:
                resurrections += 1
            if constructed_after_dispose:
                post_dispose_messages += 1
            if background.errors:
                worker_exceptions += 1
            if first_violation < 0 and (
                vm.status is ConstructionStatus.CONSTRUCTED
                or constructed_after_dispose
                or background.errors
            ):
                first_violation = i
    finally:
        pool.shutdown(wait=True)
        sys.setswitchinterval(original_switch_interval)

    assert resurrections == 0, (
        f"a disposed VM resurrected to Constructed in {resurrections}/{iterations} "
        "iterations (Disposed is terminal — spec/02 invariant 3)"
    )
    assert post_dispose_messages == 0, (
        f"a post-dispose Constructed status message was published in "
        f"{post_dispose_messages}/{iterations} iterations"
    )
    assert worker_exceptions == 0, (
        f"the background worker raised in {worker_exceptions}/{iterations} iterations "
        "(e.g. on_next on a disposed Subject)"
    )
    assert first_violation == -1, (
        "the background transition and foreground dispose() must be atomic; "
        f"first violation at iteration {first_violation}"
    )


def test_construct_does_not_run_hook_after_dispose_wins_before_constructing() -> None:
    """If dispose wins before construct enters Constructing, construct must abort.

    This pins the entry-side lifecycle lock: the status read, in-flight claim, and
    first transient status write are one critical section. Without that, a racing
    dispose can complete after ``construct()`` sets ``_in_flight`` but before it
    publishes ``Constructing``; the old implementation then still ran
    ``_on_construct`` after the VM was already Disposed.
    """
    hook_called = threading.Event()
    dispose_done = threading.Event()
    release_constructing = threading.Event()
    dispose_won_before_constructing = False

    vm = (
        ComponentVMOfBuilder()
        .name("vm")
        .with_null_services()
        .model("m")
        .on_construct(hook_called.set)
        .build()
    )
    original_set_status = vm._set_status

    def instrumented_set_status(self: object, status: ConstructionStatus) -> bool:
        nonlocal dispose_won_before_constructing
        if status is ConstructionStatus.CONSTRUCTING:
            disposer = threading.Thread(target=lambda: (vm.dispose(), dispose_done.set()))
            disposer.start()
            dispose_won_before_constructing = dispose_done.wait(timeout=0.2)
            release_constructing.set()
            disposer.join(timeout=HANG_GUARD)
        return original_set_status(status)

    vm._set_status = types.MethodType(instrumented_set_status, vm)  # type: ignore[method-assign]

    vm.construct()
    release_constructing.wait(timeout=HANG_GUARD)

    assert dispose_won_before_constructing is False or not hook_called.is_set()
    assert dispose_done.wait(timeout=HANG_GUARD)
    assert vm.status is ConstructionStatus.DISPOSED


def test_foreign_dispose_waits_for_ordinary_lifecycle_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispose cannot return before the held ordinary publication drains."""
    hub: MessageHub[object] = MessageHub()
    entered = threading.Event()
    release = threading.Event()
    wait_entered = threading.Event()
    disposed_seen = threading.Event()
    vm = (
        ComponentVMOfBuilder().name("vm").services(hub, RxDispatcher.immediate()).model("m").build()
    )

    class ObservedCompletion:
        def __init__(self, event: threading.Event) -> None:
            self.event = event

        def wait(self, timeout: float | None = None) -> bool:
            # This is the actual VMx publication wait, not a pre-Dispose gate.
            # The native event alone blocks the caller; removing VMx's wait
            # bypasses this acknowledgment entirely.
            wait_entered.set()
            return self.event.wait(timeout)

        def set(self) -> None:
            self.event.set()

        def is_set(self) -> bool:
            return self.event.is_set()

    class ObservedPublication(component_base._LifecyclePublication):
        def __init__(
            self,
            status: ConstructionStatus | None = None,
            action: Callable[[], None] | None = None,
        ) -> None:
            super().__init__(status, action)
            if status is ConstructionStatus.DISPOSED:
                self.completed = ObservedCompletion(self.completed)  # type: ignore[assignment]

    monkeypatch.setattr(component_base, "_LifecyclePublication", ObservedPublication)
    observer_failures: list[BaseException] = []

    def observe(message: object) -> None:
        if not isinstance(message, ConstructionStatusChangedMessage) or message.sender is not vm:
            return
        if message.status is ConstructionStatus.CONSTRUCTING:
            entered.set()
            if not release.wait(timeout=HANG_GUARD):
                # MessageHub isolates subscriber exceptions, so retain this
                # failure explicitly and report it after joining the workers.
                observer_failures.append(
                    AssertionError("coordinator never released ordinary publication")
                )
        elif message.status is ConstructionStatus.DISPOSED:
            disposed_seen.set()

    def dispose() -> None:
        vm.dispose()
        assert disposed_seen.is_set(), "Dispose returned before terminal publication"

    subscription = hub.messages.subscribe(observe)
    failures: list[BaseException] = []
    workers: list[Future[None]] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            workers.append(executor.submit(vm.construct))
            assert entered.wait(timeout=HANG_GUARD), "ordinary publication was not entered"
            disposer = executor.submit(dispose)
            workers.append(disposer)
            assert wait_entered.wait(timeout=HANG_GUARD), (
                "Dispose never entered publication.completed.wait"
            )
            assert not disposed_seen.is_set()
            assert not disposer.done()
        except BaseException as error:
            failures.append(error)
        finally:
            release.set()
            # Join every submitted worker and retrieve every failure, including
            # when the coordinator assertion fails. External process watchdogs
            # contain implementation mutants that deadlock despite release.
            for worker in workers:
                try:
                    future_result(worker)
                except BaseException as error:
                    failures.append(error)
            subscription.dispose()
            hub.dispose()

    failures.extend(observer_failures)
    if failures:
        # ExceptionGroup requires Python 3.11; retain every traceback on 3.10.
        details = "\n".join(
            "".join(traceback.format_exception(type(error), error, error.__traceback__))
            for error in failures
        )
        raise AssertionError(f"Lifecycle race failures:\n{details}") from failures[0]
    assert disposed_seen.is_set()


def test_opposing_lifecycle_observers_do_not_deadlock() -> None:
    """Two status callbacks may cross-dispose their peer without lock inversion."""
    hubs = [MessageHub(), MessageHub()]
    vms = [
        ComponentVMOfBuilder()
        .name(f"vm-{index}")
        .services(hubs[index], RxDispatcher.immediate())
        .model(index)
        .build()
        for index in range(2)
    ]
    barrier = threading.Barrier(2)
    histories: list[list[ConstructionStatus]] = [[], []]

    def subscribe(index: int) -> None:
        def observe(message: object) -> None:
            if not isinstance(message, ConstructionStatusChangedMessage):
                return
            histories[index].append(message.status)
            if message.status is ConstructionStatus.CONSTRUCTING:
                barrier.wait(timeout=HANG_GUARD)
                vms[1 - index].dispose()

        hubs[index].messages.subscribe(observe)

    subscribe(0)
    subscribe(1)
    threads = [threading.Thread(target=vm.construct) for vm in vms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2 * HANG_GUARD)

    assert all(not thread.is_alive() for thread in threads)
    assert [vm.status for vm in vms] == [
        ConstructionStatus.DISPOSED,
        ConstructionStatus.DISPOSED,
    ]
    assert all(history[-1] is ConstructionStatus.DISPOSED for history in histories)


def test_opposing_active_lifecycle_hooks_cross_dispose_without_deadlock() -> None:
    """Hook-to-hook disposal cycles defer cleanup instead of mutually waiting."""
    barrier = threading.Barrier(2)
    vms: list[Any] = []

    def hook(index: int) -> None:
        barrier.wait(timeout=HANG_GUARD)
        vms[1 - index].dispose()

    vms.extend(
        ComponentVMOfBuilder()
        .name(f"vm-{index}")
        .with_null_services()
        .model(index)
        .on_construct(lambda index=index: hook(index))
        .build()
        for index in range(2)
    )
    threads = [threading.Thread(target=vm.construct) for vm in vms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2 * HANG_GUARD)

    assert all(not thread.is_alive() for thread in threads)
    assert all(vm.status is ConstructionStatus.DISPOSED for vm in vms)


def test_cycle_broken_deferred_cleanup_does_not_replace_first_failure() -> None:
    barrier = threading.Barrier(2)
    vms: list[Any] = []
    cleanup_order: list[str] = []
    failures: list[BaseException] = []

    def hook(index: int) -> None:
        barrier.wait(timeout=HANG_GUARD)
        vms[1 - index].dispose()

    def failing_dispose(self: object, name: str) -> None:
        cleanup_order.append(name)
        raise RuntimeError(f"dispose failure {name}")

    for index, name in enumerate(("first", "second")):
        vm = (
            ComponentVMOfBuilder()
            .name(name)
            .with_null_services()
            .model(index)
            .on_construct(lambda index=index: hook(index))
            .build()
        )
        vm._on_dispose = types.MethodType(  # type: ignore[method-assign]
            lambda self, name=name: failing_dispose(self, name), vm
        )
        vms.append(vm)

    def construct(vm: Any) -> None:
        try:
            vm.construct()
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=construct, args=(vm,)) for vm in vms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2 * HANG_GUARD)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(cleanup_order) == ["first", "second"]
    assert len(failures) == 1
    assert str(failures[0]) == f"dispose failure {cleanup_order[0]}"
    assert all(vm.status is ConstructionStatus.DISPOSED for vm in vms)


# ---------------------------------------------------------------------------
# #1182: a finished hook or a delivered publication never counts in a cycle
# ---------------------------------------------------------------------------
#
# Q's ``a.dispose()`` waits for P (P runs a's hook, or drains a's
# publications). P ends that wait and then disposes ``b``, whose hook or drain
# runs on Q. Q's wait has ended, so P's wait for Q closes no live cycle: P
# must wait. The harness holds Q after P ends Q's wait, and before Q's
# ``a.dispose()`` returns, until P's ``b.dispose()`` decides whether to wait.
# A stale Q-to-P edge would make P take the cycle escape (spec/02 §2.4,
# spec/03 §4.1, ADR-0172).


class _CrossDisposeHarness:
    """Observe the lease and publication waits of threads P and Q."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.p_ident = 0
        self.q_ident = 0
        self.q_waits = threading.Event()
        self.p_decided = threading.Event()
        self.failures: list[BaseException] = []
        harness = self

        class ObservedCompletion:
            def __init__(self, event: threading.Event) -> None:
                self.event = event

            def wait(self, timeout: float | None = None) -> bool:
                caller = threading.get_ident()
                if caller == harness.p_ident:
                    harness.p_decided.set()
                elif caller == harness.q_ident:
                    harness.q_waits.set()
                result = self.event.wait(timeout)
                if caller == harness.q_ident and not harness.p_decided.wait(HANG_GUARD):
                    harness.failures.append(AssertionError("P never decided its wait"))
                return result

            def set(self) -> None:
                self.event.set()

            def is_set(self) -> bool:
                return self.event.is_set()

        class ObservedLease(component_base._LifecycleHookLease):
            def __init__(self) -> None:
                super().__init__()
                self.completed = ObservedCompletion(self.completed)  # type: ignore[assignment]

        class ObservedPublication(component_base._LifecyclePublication):
            def __init__(
                self,
                status: ConstructionStatus | None = None,
                action: Callable[[], None] | None = None,
            ) -> None:
                super().__init__(status, action)
                self.completed = ObservedCompletion(self.completed)  # type: ignore[assignment]

        monkeypatch.setattr(component_base, "_LifecycleHookLease", ObservedLease)
        monkeypatch.setattr(component_base, "_LifecyclePublication", ObservedPublication)

    def run(self, p_action: Callable[[], None], q_action: Callable[[], None]) -> None:
        """Run P and Q, then raise every failure that either recorded."""
        idents_known = threading.Barrier(3)

        def thread(name: str, action: Callable[[], None]) -> threading.Thread:
            def body() -> None:
                if name == "P":
                    self.p_ident = threading.get_ident()
                else:
                    self.q_ident = threading.get_ident()
                idents_known.wait(HANG_GUARD)
                try:
                    action()
                except BaseException as error:
                    self.failures.append(error)

            return threading.Thread(target=body, name=name, daemon=True)

        threads = [thread("P", p_action), thread("Q", q_action)]
        for worker in threads:
            worker.start()
        idents_known.wait(HANG_GUARD)
        for worker in threads:
            worker.join(3 * HANG_GUARD)
        assert all(not worker.is_alive() for worker in threads), "a thread hung"
        if self.failures:
            details = "\n".join(
                "".join(traceback.format_exception(type(error), error, error.__traceback__))
                for error in self.failures
            )
            raise AssertionError(f"Cross-dispose failures:\n{details}") from self.failures[0]


def _cross_vm(name: str, hub: MessageHub[object], on_construct: Callable[[], None] | None) -> Any:
    builder = ComponentVMOfBuilder().name(name).services(hub, RxDispatcher.immediate()).model(name)
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    return builder.build()


@pytest.mark.parametrize("cleanup_raises", [False, True], ids=["returns", "raises"])
def test_dispose_waits_for_a_hook_whose_waiter_was_released(
    monkeypatch: pytest.MonkeyPatch, cleanup_raises: bool
) -> None:
    # #1182 form 1: Q waits for P's lease on a. P finishes a's hook, then
    # disposes b while b's hook still runs on Q.
    harness = _CrossDisposeHarness(monkeypatch)
    p_in_a_hook = threading.Event()
    b_hook_returned = threading.Event()
    on_dispose_calls: list[tuple[str, bool]] = []
    dispose_outcome: list[object] = []
    vms: dict[str, Any] = {}

    def a_hook() -> None:
        p_in_a_hook.set()
        assert harness.q_waits.wait(HANG_GUARD), "Q never waited for a's hook"

    def b_hook() -> None:
        assert p_in_a_hook.wait(HANG_GUARD)
        vms["a"].dispose()
        b_hook_returned.set()

    vms["a"] = _cross_vm("a", MessageHub(), a_hook)
    vms["b"] = _cross_vm("b", MessageHub(), b_hook)

    def b_on_dispose(_self: object) -> None:
        on_dispose_calls.append((threading.current_thread().name, b_hook_returned.is_set()))
        if cleanup_raises:
            raise RuntimeError("b cleanup failed")

    vms["b"]._on_dispose = types.MethodType(b_on_dispose, vms["b"])

    def p_action() -> None:
        vms["a"].construct()
        try:
            vms["b"].dispose()
            dispose_outcome.append(list(on_dispose_calls))
        except RuntimeError as error:
            dispose_outcome.append(error)
        finally:
            harness.p_decided.set()

    harness.run(p_action, vms["b"].construct)

    assert on_dispose_calls == [("P", True)]
    if cleanup_raises:
        assert len(dispose_outcome) == 1
        assert isinstance(dispose_outcome[0], RuntimeError)
        assert str(dispose_outcome[0]) == "b cleanup failed"
    else:
        assert dispose_outcome == [[("P", True)]]
    assert vms["a"].status is ConstructionStatus.DISPOSED
    assert vms["b"].status is ConstructionStatus.DISPOSED


def test_dispose_waits_for_a_publication_whose_waiter_was_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #1182 form 2: Q waits for P to deliver a's Disposed. P delivers it, then
    # disposes b while Q still delivers b's Constructing.
    harness = _CrossDisposeHarness(monkeypatch)
    hubs: dict[str, MessageHub[object]] = {"a": MessageHub(), "b": MessageHub()}
    vms = {name: _cross_vm(name, hub, None) for name, hub in hubs.items()}
    p_in_a_subscriber = threading.Event()
    on_dispose_runs: list[str] = []
    b_deliveries: list[tuple[ConstructionStatus, str, bool]] = []
    disposed_before_return: list[bool] = []
    subscriber_failures: list[BaseException] = []

    def observe_a(message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.CONSTRUCTING
        ):
            p_in_a_subscriber.set()
            if not harness.q_waits.wait(HANG_GUARD):
                subscriber_failures.append(AssertionError("Q never waited for a's drain"))

    def observe_b(message: object) -> None:
        if not isinstance(message, ConstructionStatusChangedMessage):
            return
        b_deliveries.append(
            (message.status, threading.current_thread().name, bool(on_dispose_runs))
        )
        if message.status is ConstructionStatus.CONSTRUCTING:
            if not p_in_a_subscriber.wait(HANG_GUARD):
                subscriber_failures.append(AssertionError("P never drained a"))
            vms["a"].dispose()

    hubs["a"].messages.subscribe(observe_a)
    hubs["b"].messages.subscribe(observe_b)

    def b_on_dispose(_self: object) -> None:
        on_dispose_runs.append(threading.current_thread().name)

    vms["b"]._on_dispose = types.MethodType(b_on_dispose, vms["b"])

    def p_action() -> None:
        vms["a"].construct()
        try:
            vms["b"].dispose()
            disposed_before_return.append(
                any(status is ConstructionStatus.DISPOSED for status, _, _ in b_deliveries)
            )
        finally:
            harness.p_decided.set()

    harness.run(p_action, vms["b"].construct)

    assert subscriber_failures == []
    disposed = [entry for entry in b_deliveries if entry[0] is ConstructionStatus.DISPOSED]
    assert disposed == [(ConstructionStatus.DISPOSED, "Q", False)]
    assert on_dispose_runs == ["P"]
    assert disposed_before_return == [True]
    assert vms["a"].status is ConstructionStatus.DISPOSED
    assert vms["b"].status is ConstructionStatus.DISPOSED


def test_dispose_inside_the_hook_that_its_waiter_waits_for_takes_the_cycle_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real-cycle control for form 1: P disposes b inside a's hook, while Q
    # waits for a's lease. P still holds that lease, so P defers b's cleanup
    # to b's hook on Q.
    harness = _CrossDisposeHarness(monkeypatch)
    p_in_a_hook = threading.Event()
    on_dispose_runs: list[str] = []
    vms: dict[str, Any] = {}

    def a_hook() -> None:
        p_in_a_hook.set()
        assert harness.q_waits.wait(HANG_GUARD), "Q never waited for a's hook"
        try:
            vms["b"].dispose()
        finally:
            harness.p_decided.set()

    def b_hook() -> None:
        assert p_in_a_hook.wait(HANG_GUARD)
        vms["a"].dispose()

    vms["a"] = _cross_vm("a", MessageHub(), a_hook)
    vms["b"] = _cross_vm("b", MessageHub(), b_hook)
    vms["b"]._on_dispose = types.MethodType(
        lambda _self: on_dispose_runs.append(threading.current_thread().name), vms["b"]
    )

    harness.run(vms["a"].construct, vms["b"].construct)

    assert on_dispose_runs == ["Q"]
    assert vms["a"].status is ConstructionStatus.DISPOSED
    assert vms["b"].status is ConstructionStatus.DISPOSED


def test_dispose_inside_the_drain_that_its_waiter_waits_for_takes_the_cycle_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real-cycle control for form 2: P disposes b inside a's subscriber, while
    # Q waits for P to deliver a's Disposed. P still drains a, so P leaves b's
    # Disposed queued for Q's drain and returns.
    harness = _CrossDisposeHarness(monkeypatch)
    hubs: dict[str, MessageHub[object]] = {"a": MessageHub(), "b": MessageHub()}
    vms = {name: _cross_vm(name, hub, None) for name, hub in hubs.items()}
    p_in_a_subscriber = threading.Event()
    on_dispose_runs: list[str] = []
    b_disposed_threads: list[str] = []
    subscriber_failures: list[BaseException] = []

    def observe_a(message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.CONSTRUCTING
        ):
            p_in_a_subscriber.set()
            try:
                if not harness.q_waits.wait(HANG_GUARD):
                    raise AssertionError("Q never waited for a's drain")
                vms["b"].dispose()
            except BaseException as error:
                subscriber_failures.append(error)
            finally:
                harness.p_decided.set()

    def observe_b(message: object) -> None:
        if not isinstance(message, ConstructionStatusChangedMessage):
            return
        if message.status is ConstructionStatus.DISPOSED:
            b_disposed_threads.append(threading.current_thread().name)
        elif message.status is ConstructionStatus.CONSTRUCTING:
            if not p_in_a_subscriber.wait(HANG_GUARD):
                subscriber_failures.append(AssertionError("P never drained a"))
            vms["a"].dispose()

    hubs["a"].messages.subscribe(observe_a)
    hubs["b"].messages.subscribe(observe_b)
    vms["b"]._on_dispose = types.MethodType(
        lambda _self: on_dispose_runs.append(threading.current_thread().name), vms["b"]
    )

    harness.run(vms["a"].construct, vms["b"].construct)

    assert subscriber_failures == []
    assert on_dispose_runs == ["P"]
    assert b_disposed_threads == ["Q"]
    assert vms["a"].status is ConstructionStatus.DISPOSED
    assert vms["b"].status is ConstructionStatus.DISPOSED
