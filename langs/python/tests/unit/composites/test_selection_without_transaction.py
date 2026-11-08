"""Selection commits without a membership transaction (spec/06 §4.3, §5, ADR-0173).

Another thread's transaction neither fails nor delays a selection (#1145). A
child that an add or population attached but has not admitted is not a member
for selection (#1146, #1148). The owner thread cannot select before its
transaction commits. A non-null selection is refused while disposal is
pending, and a null clear is not. The destruct clear is never refused (#1144).
Mirrors the C# SelectionWithoutTransactionTests.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from tests.liveness import HANG_GUARD
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _QueueScheduler:
    """Queues work so a test decides when each item runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []
        self._lock = threading.Lock()

    def schedule(self, action: Any, state: Any = None) -> None:
        with self._lock:
            self.actions.append(action)

    def run_all(self) -> None:
        while True:
            with self._lock:
                if not self.actions:
                    return
                action = self.actions.pop(0)
            action(self, None)


def _immediate() -> RxDispatcher:
    return RxDispatcher(ImmediateScheduler(), ImmediateScheduler())


def _queued(*, foreground: bool = False) -> tuple[_QueueScheduler, _QueueScheduler, RxDispatcher]:
    fg = _QueueScheduler()
    bg = _QueueScheduler()
    dispatcher = RxDispatcher(
        fg if foreground else ImmediateScheduler(),  # type: ignore[arg-type]
        bg,  # type: ignore[arg-type]
    )
    return fg, bg, dispatcher


def _child(
    hub: Any,
    dispatcher: Any,
    name: str,
    *,
    background: bool = False,
    on_construct: Callable[[], None] | None = None,
) -> ComponentVM:
    builder = ComponentVMBuilder().name(name).services(hub, dispatcher).background(background)
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    return builder.build()


def _start(action: Any, errors: list[BaseException]) -> threading.Thread:
    def run() -> None:
        try:
            action()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class _Root:
    """A composite with recorders for its current changes."""

    def __init__(
        self,
        hub: Any,
        dispatcher: Any,
        children: Callable[[], Iterable[ComponentVM]],
        *,
        auto_construct_on_add: bool = True,
        async_selection: bool = False,
        select_first: bool = False,
        on_current: Callable[[ComponentVM | None], None] | None = None,
    ) -> None:
        self.changes: list[str | None] = []
        self.current_messages = 0
        self._on_current = on_current
        builder = (
            CompositeVMBuilder[ComponentVM]()
            .name("root")
            .services(hub, dispatcher)
            .children(children)
            .auto_construct_on_add(auto_construct_on_add)
            .async_selection(async_selection)
            .on_current_changed(self._on_current_changed)
        )
        if select_first:
            builder = builder.current(lambda kids: next(iter(kids), None))
        self.vm: CompositeVM[ComponentVM] = builder.build()
        self.vm.property_changed.subscribe(self._on_property)

    def _on_current_changed(self, value: ComponentVM | None) -> None:
        self.changes.append(None if value is None else value.name)
        if self._on_current is not None:
            self._on_current(value)

    def _on_property(self, name: str) -> None:
        if name == "current":
            self.current_messages += 1

    def reset_records(self) -> None:
        self.changes.clear()
        self.current_messages = 0


class _ParkedAdd:
    """``add(late)`` on a worker parked in the add's own collection-changed
    publication, while it still holds the transaction."""

    def __init__(
        self,
        root: CompositeVM[ComponentVM],
        late: ComponentVM,
        wait_in_handler: Callable[[], bool] | None = None,
    ) -> None:
        main = threading.get_ident()
        self._in_handler = threading.Event()
        self._release = threading.Event()
        self.errors: list[BaseException] = []
        self.handler_wait_succeeded = False

        def on_changed(_event: object) -> None:
            if threading.get_ident() == main:
                return
            self._in_handler.set()
            if wait_in_handler is not None:
                self.handler_wait_succeeded = wait_in_handler()
            else:
                self._release.wait(2 * HANG_GUARD)

        root.on_collection_changed.subscribe(on_changed)
        self._worker = _start(lambda: root.add(late), self.errors)
        assert self._in_handler.wait(HANG_GUARD)
        assert root._membership_transaction_active

    def finish(self) -> None:
        self._release.set()
        self._worker.join(3 * HANG_GUARD)
        assert not self._worker.is_alive()
        assert self.errors == []


def _wait_until(condition: Callable[[], bool]) -> bool:
    deadline = threading.Event()
    timer = threading.Timer(HANG_GUARD, deadline.set)
    timer.start()
    try:
        while not condition():
            if deadline.wait(0.001):
                return condition()
        return True
    finally:
        timer.cancel()


# ── #1144: the destruct clear ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("operation", "owner_waits_for_destruct"),
    [("destruct", False), ("destruct", True), ("reconstruct", False)],
)
def test_destruct_clears_current_while_another_thread_holds_a_transaction(
    operation: str, owner_waits_for_destruct: bool
) -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    first = _child(hub, dispatcher, "first")
    late = _child(hub, dispatcher, "late")
    root = _Root(hub, dispatcher, lambda: [first], select_first=True)
    root.vm.construct()
    assert root.vm.current is first

    add = _ParkedAdd(
        root.vm,
        late,
        (lambda: _wait_until(lambda: root.vm.status is S.DESTRUCTED))
        if owner_waits_for_destruct
        else None,
    )
    try:
        if operation == "destruct":
            root.vm.destruct()
        else:
            root.vm.reconstruct()

        if operation == "destruct":
            assert root.vm.status is S.DESTRUCTED
            assert root.vm.current is None
            assert not first.is_current
            assert root.changes == ["first", None]
        else:
            assert root.vm.status is S.CONSTRUCTED
            assert root.vm.current is first  # the selector ran again
            assert root.changes == ["first", None, "first"]
    finally:
        add.finish()
    if owner_waits_for_destruct:
        assert add.handler_wait_succeeded


def test_destruct_clears_current_while_disposal_is_deferred() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    a = _child(hub, dispatcher, "a")
    seen: list[tuple[ConstructionStatus, ComponentVM | None]] = []

    def on_current(value: ComponentVM | None) -> None:
        if value is None:
            return
        root.vm.dispose()  # deferred: this thread publishes under the lease
        root.vm.destruct()
        seen.append((root.vm.status, root.vm.current))

    root = _Root(hub, dispatcher, lambda: [a], on_current=on_current)
    root.vm.construct()

    root.vm.current = a

    assert seen == [(S.DESTRUCTED, None)]
    assert not a.is_current
    assert root.changes == ["a", None]
    assert root.vm.status is S.DISPOSED  # the lease end admitted the disposal


def test_dispose_from_the_destruct_clear_callback_is_deferred() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    a = _child(hub, dispatcher, "a")
    seen: list[ConstructionStatus] = []

    def on_current(value: ComponentVM | None) -> None:
        if value is not None:
            return
        root.vm.dispose()
        seen.append(root.vm.status)

    root = _Root(hub, dispatcher, lambda: [a], select_first=True, on_current=on_current)
    root.vm.construct()

    root.vm.destruct()

    assert seen == [S.DESTRUCTING]  # the lease deferred the disposal
    assert root.vm.current is None
    assert _wait_until(lambda: root.vm.status is S.DISPOSED)


def test_destruct_from_the_own_add_publication_clears_current() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    first = _child(hub, dispatcher, "first")
    late = _child(hub, dispatcher, "late")
    root = _Root(hub, dispatcher, lambda: [first], select_first=True)
    root.vm.construct()
    root.vm.on_collection_changed.subscribe(lambda _event: root.vm.destruct())

    root.vm.add(late)

    assert root.vm.status is S.DESTRUCTED
    assert root.vm.current is None
    assert not first.is_current


# ── #1145: another thread's transaction ─────────────────────────────────────


@pytest.mark.parametrize("async_selection", [False, True])
def test_selection_calls_commit_while_another_thread_holds_a_transaction(
    async_selection: bool,
) -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    first = _child(hub, dispatcher, "first")
    second = _child(hub, dispatcher, "second")
    late = _child(hub, dispatcher, "late")
    root = _Root(hub, dispatcher, lambda: [first, second], async_selection=async_selection)
    root.vm.construct()

    add = _ParkedAdd(root.vm, late)
    try:
        root.vm.current = second
        assert root.vm.current is second
        assert root.vm.can_select_component(first)
        root.vm.select_component(first)
        assert root.vm.current is first
        root.vm.deselect_component(first)
        assert root.vm.current is None
        late.select()  # admitted before the add publishes
        assert root.vm.current is late
        late.deselect()
        assert root.vm.current is None
    finally:
        add.finish()

    assert root.changes == ["second", "first", None, "late", None]
    assert root.vm.snapshot() == (first, second, late)


def test_late_child_hook_selects_during_another_threads_add_without_rolling_back() -> None:
    hub: MessageHub[object] = MessageHub()
    _fg, bg, dispatcher = _queued()
    first = _child(hub, dispatcher, "first", background=True)
    hook_errors: list[BaseException] = []

    def late_hook() -> None:
        try:
            root.vm.current = first
        except BaseException as error:
            hook_errors.append(error)
            raise

    late = _child(hub, dispatcher, "late", background=True, on_construct=late_hook)
    root = _Root(hub, dispatcher, lambda: [first], select_first=True)
    root.vm.construct()  # the walk waits on first

    add = _ParkedAdd(root.vm, late)
    try:

        def settled() -> bool:
            bg.run_all()  # late's hook runs here, on a non-owner thread
            return root.vm.status is not S.CONSTRUCTING

        assert _wait_until(settled)
        assert hook_errors == []
        assert root.vm.status is S.CONSTRUCTED
        assert root.vm.current is first
        assert first.is_current
        assert root.changes == ["first"]
        assert late.status is S.CONSTRUCTED
    finally:
        add.finish()


# ── #1146: the caller's own uncommitted transaction ────────────────────────


@pytest.mark.parametrize(
    ("operation", "target", "keep_current"),
    [
        ("add", "late", False),
        ("insert", "late", False),
        ("replace", "late", False),
        ("add", "late", True),
        ("add", "select-late", False),
        ("add", "keep", False),
        ("insert", "keep", False),
        ("replace", "keep", False),
        ("add", "null", True),
        ("add", "deselect-keep", True),
        ("replace", "null", True),
    ],
)
def test_owner_thread_selection_before_a_failed_admission_is_refused(
    operation: str, target: str, keep_current: bool
) -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    keep = _child(hub, dispatcher, "keep")
    spare = _child(hub, dispatcher, "spare")
    hook_errors: list[BaseException] = []

    def hook() -> None:
        try:
            if target == "late":
                root.vm.current = late
            elif target == "select-late":
                root.vm.select_component(late)
            elif target == "keep":
                root.vm.current = keep
            elif target == "null":
                root.vm.current = None
            else:
                root.vm.deselect_component(keep)
        except BaseException as error:
            hook_errors.append(error)
        raise RuntimeError("boom")

    late = _child(hub, dispatcher, "late", on_construct=hook)
    root = _Root(hub, dispatcher, lambda: [keep, spare])
    root.vm.construct()
    if keep_current:
        root.vm.current = keep
    root.reset_records()

    with pytest.raises(RuntimeError, match="boom"):
        if operation == "add":
            root.vm.add(late)
        elif operation == "insert":
            root.vm.insert(0, late)
        else:
            root.vm[1] = late  # replaces spare

    assert len(hook_errors) == 1
    if target == "select-late":
        assert isinstance(hook_errors[0], ValueError)
        assert "can_select_component returned False" in str(hook_errors[0])
    else:
        assert isinstance(hook_errors[0], RuntimeError)
        assert "already in progress" in str(hook_errors[0])
    assert root.vm.snapshot() == (keep, spare)
    assert root.vm.current is (keep if keep_current else None)
    assert keep.is_current is keep_current
    assert not late.is_current
    assert root.changes == []
    assert root.current_messages == 0


def test_owner_thread_selection_from_a_failed_factory_population_is_refused() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    hook_errors: list[BaseException] = []

    def a_hook() -> None:
        try:
            root.vm.current = a
        except BaseException as error:
            hook_errors.append(error)

    def b_hook() -> None:
        raise RuntimeError("population fails")

    a = _child(hub, dispatcher, "a", on_construct=a_hook)
    b = _child(hub, dispatcher, "b", on_construct=b_hook)
    root = _Root(hub, dispatcher, lambda: [a, b])

    with pytest.raises(RuntimeError, match="population fails"):
        root.vm.construct()

    assert len(hook_errors) == 1
    assert isinstance(hook_errors[0], RuntimeError)
    assert "already in progress" in str(hook_errors[0])
    assert root.vm.snapshot() == ()
    assert root.vm.current is None
    assert not a.is_current
    assert root.changes == []
    assert root.current_messages == 0


def test_owner_thread_selection_from_the_add_publication_commits() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    keep = _child(hub, dispatcher, "keep")
    late = _child(hub, dispatcher, "late")
    root = _Root(hub, dispatcher, lambda: [keep])
    root.vm.construct()
    selectable: list[bool] = []

    def on_changed(_event: object) -> None:
        selectable.append(root.vm.can_select_component(late))
        root.vm.select_component(late)

    root.vm.on_collection_changed.subscribe(on_changed)

    root.vm.add(late)

    assert selectable == [True]
    assert root.vm.current is late
    assert late.is_current
    assert root.changes == ["late"]


def test_async_delivery_inside_the_owner_uncommitted_transaction_is_dropped() -> None:
    hub: MessageHub[object] = MessageHub()
    fg, _bg, dispatcher = _queued(foreground=True)
    immediate = _immediate()
    keep = _child(hub, immediate, "keep")
    late = _child(hub, immediate, "late", on_construct=fg.run_all)
    root = _Root(hub, dispatcher, lambda: [keep], async_selection=True)
    root.vm.construct()

    root.vm.current = keep  # validated now, delivered by late's hook inside the add
    root.vm.add(late)
    fg.run_all()

    assert root.vm.current is None
    assert not keep.is_current
    assert root.changes == []


# ── #1146: rule 2 on another thread ─────────────────────────────────────────


def test_another_thread_cannot_select_an_unadmitted_child_but_can_select_a_member() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    keep = _child(hub, dispatcher, "keep")
    in_hook = threading.Event()
    release = threading.Event()

    def hook() -> None:
        in_hook.set()
        release.wait(2 * HANG_GUARD)
        raise RuntimeError("boom")

    late = _child(hub, dispatcher, "late", on_construct=hook)
    root = _Root(hub, dispatcher, lambda: [keep])
    root.vm.construct()
    errors: list[BaseException] = []
    worker = _start(lambda: root.vm.add(late), errors)
    try:
        assert in_hook.wait(HANG_GUARD)
        with pytest.raises(ValueError, match="not a member"):
            root.vm.current = late
        assert not root.vm.can_select_component(late)
        root.vm.current = keep  # the foreign transaction neither fails nor delays it
    finally:
        release.set()
        worker.join(3 * HANG_GUARD)
    assert not worker.is_alive()

    assert [str(error) for error in errors] == ["boom"]
    assert root.vm.snapshot() == (keep,)
    assert root.vm.current is keep  # the rollback leaves a foreign selection
    assert keep.is_current
    assert not late.is_current
    assert root.changes == ["keep"]


# ── #1148: a staged population ──────────────────────────────────────────────


class _Repopulating(CompositeVM[ComponentVM]):
    """A subclass that attaches a population at any time."""

    def repopulate(self, children: Iterable[ComponentVM]) -> None:
        self._attach_population(children)


def test_walk_ignores_a_staged_population_candidate() -> None:
    hub: MessageHub[object] = MessageHub()
    _fg, bg, dispatcher = _queued()
    immediate = _immediate()
    first = _child(hub, dispatcher, "first", background=True)
    good = _child(hub, immediate, "good")
    in_hook = threading.Event()
    release = threading.Event()

    def bad_hook() -> None:
        in_hook.set()
        release.wait(2 * HANG_GUARD)
        raise RuntimeError("population fails")

    bad = _child(hub, immediate, "bad", on_construct=bad_hook)
    errors: list[BaseException] = []
    workers: list[threading.Thread] = []
    changes: list[str | None] = []
    selectable: list[bool] = []

    def selector(_kids: Iterable[ComponentVM]) -> ComponentVM:
        workers.append(_start(lambda: root.repopulate([good, bad]), errors))
        assert in_hook.wait(HANG_GUARD)
        selectable.append(root.can_select_component(good))
        return good  # staged by the worker's population

    root = _Repopulating(
        name="repop",
        hub=hub,
        dispatcher=dispatcher,
        current_selector=selector,
        on_current_changed=lambda value: changes.append(None if value is None else value.name),
    )
    root.add(first)
    try:
        root.construct()

        def settled() -> bool:
            bg.run_all()
            return root.status is not S.CONSTRUCTING

        assert _wait_until(settled)
        assert root.current is None
    finally:
        release.set()
        assert _wait_until(lambda: bool(workers))
        workers[0].join(3 * HANG_GUARD)
    assert not workers[0].is_alive()

    assert [str(error) for error in errors] == ["population fails"]
    assert selectable == [False]
    assert root.status is S.CONSTRUCTED
    assert root.snapshot() == (first,)
    assert root.current is None
    assert not good.is_current
    assert changes == []


# ── Rule 3: disposal ────────────────────────────────────────────────────────


def test_pending_disposal_refuses_a_non_null_selection_but_not_a_null_clear() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    a = _child(hub, dispatcher, "a")
    b = _child(hub, dispatcher, "b")
    errors: dict[str, BaseException] = {}
    can_select: list[bool] = []

    def on_current(value: ComponentVM | None) -> None:
        if value is None:
            return
        root.vm.dispose()  # deferred by the lease
        try:
            root.vm.current = b
        except BaseException as error:
            errors["set"] = error
        can_select.append(root.vm.can_select_component(b))
        try:
            root.vm.select_component(b)
        except BaseException as error:
            errors["select"] = error
        root.vm.current = None

    root = _Root(hub, dispatcher, lambda: [a, b], on_current=on_current)
    root.vm.construct()

    root.vm.current = a

    assert isinstance(errors["set"], RuntimeError)
    assert "disposing" in str(errors["set"])
    assert can_select == [False]
    assert isinstance(errors["select"], ValueError)
    assert "can_select_component returned False" in str(errors["select"])
    assert root.changes == ["a", None]
    assert not a.is_current
    assert not b.is_current
    assert root.vm.status is S.DISPOSED


@pytest.mark.parametrize("async_selection", [False, True])
def test_reassigning_the_current_child_while_disposing_is_a_no_op(async_selection: bool) -> None:
    # Re-assigning the child that is already current changes nothing, so rule 3
    # does not refuse it: a two-way binding may write the selection back while
    # or after the VM is disposed (chapter 01 §4).
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    a = _child(hub, dispatcher, "a")
    b = _child(hub, dispatcher, "b")
    errors: list[BaseException] = []

    def on_current(value: ComponentVM | None) -> None:
        if value is None:
            return
        root.vm.dispose()  # deferred by the lease
        try:
            root.vm.current = a
        except BaseException as error:
            errors.append(error)

    root = _Root(
        hub, dispatcher, lambda: [a, b], async_selection=async_selection, on_current=on_current
    )
    root.vm.construct()

    root.vm.current = a

    assert errors == []
    assert root.vm.status is S.DISPOSED
    assert root.changes == ["a"]


@pytest.mark.parametrize("async_selection", [False, True])
def test_reassigning_the_current_child_after_disposed_is_a_no_op(async_selection: bool) -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    a = _child(hub, dispatcher, "a")
    root = _Root(hub, dispatcher, lambda: [a], async_selection=async_selection)
    root.vm.construct()
    root.vm.current = a
    root.vm.dispose()
    assert root.vm.status is S.DISPOSED
    current = root.vm.current

    root.vm.current = current

    assert root.vm.current is current
    assert root.changes == ["a"]


@pytest.mark.parametrize("path", ["deselect-not-current", "select-non-member"])
def test_child_paths_that_change_nothing_are_refused_inside_the_owner_transaction(
    path: str,
) -> None:
    # Every selection call fails on the thread that owns an uncommitted
    # transaction, also one that would change nothing (spec/06 §4.3 rule 4),
    # as the C# child paths do through DeselectComponent and SelectComponent.
    hub: MessageHub[object] = MessageHub()
    dispatcher = _immediate()
    keep = _child(hub, dispatcher, "keep")
    outsider = _child(hub, dispatcher, "outsider")
    hook_errors: list[BaseException] = []

    def hook() -> None:
        try:
            if path == "deselect-not-current":
                root.vm.deselect_child(keep)
            else:
                root.vm.select_child(outsider)
        except BaseException as error:
            hook_errors.append(error)

    late = _child(hub, dispatcher, "late", on_construct=hook)
    root = _Root(hub, dispatcher, lambda: [keep])
    root.vm.construct()
    root.reset_records()

    root.vm.add(late)

    assert len(hook_errors) == 1
    assert isinstance(hook_errors[0], RuntimeError)
    assert "already in progress" in str(hook_errors[0])
    assert root.vm.current is None
    assert root.changes == []
