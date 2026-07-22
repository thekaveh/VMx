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
import time
import types
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import reactivex.disposable as rx_disposable
from reactivex.scheduler import ImmediateScheduler

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
                    gate.wait()
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
            barrier.wait()  # release the worker; race its completion vs dispose()
            vm.dispose()

            for future in background.futures:
                future.result()  # surface any unexpected worker crash
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
            disposer.join(timeout=1)
        return original_set_status(status)

    vm._set_status = types.MethodType(instrumented_set_status, vm)  # type: ignore[method-assign]

    vm.construct()
    release_constructing.wait(timeout=1)

    assert dispose_won_before_constructing is False or not hook_called.is_set()
    assert dispose_done.wait(timeout=1)
    assert vm.status is ConstructionStatus.DISPOSED


def test_foreign_dispose_waits_for_ordinary_lifecycle_publication() -> None:
    """A foreign caller stays synchronous unless its wait closes a real cycle."""
    hub: MessageHub[object] = MessageHub()
    entered = threading.Event()
    release = threading.Event()
    disposed_seen = threading.Event()
    dispose_done = threading.Event()
    vm = (
        ComponentVMOfBuilder().name("vm").services(hub, RxDispatcher.immediate()).model("m").build()
    )

    def observe(message: object) -> None:
        if not isinstance(message, ConstructionStatusChangedMessage) or message.sender is not vm:
            return
        if message.status is ConstructionStatus.CONSTRUCTING:
            entered.set()
            assert release.wait(timeout=2)
        elif message.status is ConstructionStatus.DISPOSED:
            disposed_seen.set()

    subscription = hub.messages.subscribe(observe)
    constructor = threading.Thread(target=vm.construct)
    constructor.start()
    assert entered.wait(timeout=2)

    disposer = threading.Thread(target=lambda: (vm.dispose(), dispose_done.set()))
    disposer.start()
    time.sleep(0.05)
    assert not dispose_done.is_set()

    release.set()
    constructor.join(timeout=2)
    disposer.join(timeout=2)
    subscription.dispose()

    assert not constructor.is_alive()
    assert not disposer.is_alive()
    assert disposed_seen.is_set()
    assert dispose_done.is_set()


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
                barrier.wait(timeout=2)
                vms[1 - index].dispose()

        hubs[index].messages.subscribe(observe)

    subscribe(0)
    subscribe(1)
    threads = [threading.Thread(target=vm.construct) for vm in vms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert [vm.status for vm in vms] == [
        ConstructionStatus.DISPOSED,
        ConstructionStatus.DISPOSED,
    ]
    assert all(history[-1] is ConstructionStatus.DISPOSED for history in histories)
