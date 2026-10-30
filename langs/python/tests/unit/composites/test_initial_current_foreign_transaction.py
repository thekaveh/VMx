"""The construct walk assigns the Current(selector) result while another thread
holds the composite's membership transaction (spec/06 §3.2, #1064).

The assignment is non-raising and never waits for the foreign transaction, so
the composite reaches Constructed with the selected child current. It selects
only committed members: a child that an in-flight add attached but has not
admitted is not contained yet. Mirrors the C# InitialCurrentForeignTransactionTests,
except the owner-thread case: in C# the walk resumes on a pool thread, never
inside the add's own completion callback.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from tests.liveness import HANG_GUARD
from vmx.components._late_child_starts import _LateChildStage
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _QueueScheduler:
    """Queues background work so a test decides when each item runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []
        self._lock = threading.Lock()

    def schedule(self, action: Any, state: Any = None) -> None:
        with self._lock:
            self.actions.append(action)

    def run_first(self) -> None:
        with self._lock:
            action = self.actions.pop(0)
        action(self, None)

    def run_all(self) -> None:
        while True:
            with self._lock:
                if not self.actions:
                    return
            self.run_first()


class _Root:
    """A composite whose Current(selector) picks its first child, with recorders."""

    def __init__(
        self,
        children: list[ComponentVM],
        hub: MessageHub[object],
        dispatcher: Any,
        on_current: Any = None,
    ):
        self.order: list[str] = []
        self.changes: list[str | None] = []
        self._on_current = on_current
        self.constructed = threading.Event()
        self._lock = threading.Lock()
        self.vm: CompositeVM[ComponentVM] = (
            CompositeVMBuilder[ComponentVM]()
            .name("root")
            .services(hub, dispatcher)
            .children(lambda: children)
            .auto_construct_on_add(True)
            .current(lambda kids: next(iter(kids), None))
            .on_current_changed(self._on_current_changed)
            .build()
        )
        self.vm.property_changed.subscribe(self._on_property)
        hub.messages.subscribe(self._on_message)

    def _on_current_changed(self, value: ComponentVM | None) -> None:
        self.changes.append(None if value is None else value.name)
        if self._on_current is not None:
            self._on_current(value)

    def _record(self, entry: str) -> None:
        with self._lock:
            self.order.append(entry)

    def _on_property(self, name: str) -> None:
        if name == "current":
            self._record("current")

    def _on_message(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage) and message.sender_name == "root":
            self._record(f"root:{message.status.name}")
            if message.status is S.CONSTRUCTED:
                self.constructed.set()

    def assert_selected_before_constructed(self) -> None:
        assert "root:DESTRUCTED" not in self.order
        assert self.order.index("current") < self.order.index("root:CONSTRUCTED")


def _services() -> tuple[_QueueScheduler, RxDispatcher, MessageHub[object]]:
    bg = _QueueScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    return bg, dispatcher, MessageHub()


def _child(hub: Any, dispatcher: Any, name: str, *, background: bool = False) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, dispatcher).background(background).build()


def _start(action: Any, errors: list[BaseException]) -> threading.Thread:
    def run() -> None:
        try:
            action()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("owner_waits_for_walk", [False, True])
def test_selector_assigns_while_another_thread_holds_the_add_transaction(
    owner_waits_for_walk: bool,
) -> None:
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    late = _child(hub, dispatcher, "late", background=True)
    root = _Root([first], hub, dispatcher)
    main = threading.get_ident()
    in_handler = threading.Event()
    release = threading.Event()
    owner_saw_constructed: list[bool] = []

    def on_changed(_event: object) -> None:
        if threading.get_ident() == main:
            return
        in_handler.set()
        # The transaction owner holds its committed add transaction here.
        if owner_waits_for_walk:
            owner_saw_constructed.append(root.constructed.wait(HANG_GUARD))
        else:
            release.wait(2 * HANG_GUARD)

    root.vm.on_collection_changed.subscribe(on_changed)
    root.vm.construct()
    errors: list[BaseException] = []
    worker = _start(lambda: root.vm.add(late), errors)
    assert in_handler.wait(HANG_GUARD)

    bg.run_all()  # the walk resumes on this thread and assigns the selector result
    assert root.vm.status is S.CONSTRUCTED
    release.set()
    worker.join(3 * HANG_GUARD)
    assert not worker.is_alive()

    assert errors == []
    if owner_waits_for_walk:
        assert owner_saw_constructed == [True]
    assert root.vm.current is first
    assert first.is_current
    assert root.changes == ["first"]
    assert any(child is late for child in root.vm.snapshot())
    root.assert_selected_before_constructed()


def test_selector_assigns_while_the_owner_of_a_remove_waits_for_the_walk() -> None:
    bg, dispatcher, hub = _services()
    extra = _child(hub, dispatcher, "extra")
    first = _child(hub, dispatcher, "first", background=True)
    root = _Root([extra, first], hub, dispatcher)
    main = threading.get_ident()
    in_handler = threading.Event()
    owner_saw_constructed: list[bool] = []

    def on_changed(_event: object) -> None:
        if threading.get_ident() == main:
            return
        in_handler.set()
        owner_saw_constructed.append(root.constructed.wait(HANG_GUARD))

    root.vm.on_collection_changed.subscribe(on_changed)
    root.vm.construct()  # extra constructs now; the walk then waits on first
    errors: list[BaseException] = []
    worker = _start(lambda: root.vm.remove(extra), errors)
    assert in_handler.wait(HANG_GUARD)

    bg.run_all()
    worker.join(3 * HANG_GUARD)
    assert not worker.is_alive()

    assert errors == []
    assert owner_saw_constructed == [True]
    assert root.vm.status is S.CONSTRUCTED
    assert root.vm.current is first
    assert root.changes == ["first"]
    assert not any(child is extra for child in root.vm.snapshot())
    root.assert_selected_before_constructed()


def test_selector_result_is_ignored_after_the_owner_disposes_the_composite() -> None:
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    late = _child(hub, dispatcher, "late", background=True)
    root = _Root([first], hub, dispatcher)
    main = threading.get_ident()
    in_handler = threading.Event()
    release = threading.Event()

    def on_changed(_event: object) -> None:
        if threading.get_ident() == main:
            return
        root.vm.dispose()  # deferred: this thread owns the transaction
        in_handler.set()
        release.wait(2 * HANG_GUARD)

    root.vm.on_collection_changed.subscribe(on_changed)
    root.vm.construct()
    errors: list[BaseException] = []
    worker = _start(lambda: root.vm.add(late), errors)
    assert in_handler.wait(HANG_GUARD)

    bg.run_all()
    assert root.vm.current is None
    release.set()
    worker.join(3 * HANG_GUARD)
    assert not worker.is_alive()

    assert root.changes == []
    assert root.vm.status is S.DISPOSED


@pytest.mark.parametrize("foreign_owner", [False, True])
def test_dispose_from_the_selector_publication_defers_to_the_lease(foreign_owner: bool) -> None:
    # A dispose from the selection's own callback defers until the publication
    # ends; it must not wait for another thread's transaction (spec/06 §3.2).
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    late = _child(hub, dispatcher, "late", background=True)
    seen: list[S] = []

    def dispose_root(_value: ComponentVM | None) -> None:
        root.vm.dispose()
        seen.append(root.vm.status)

    root = _Root([first], hub, dispatcher, on_current=dispose_root)
    main = threading.get_ident()
    in_handler = threading.Event()
    owner_saw_constructed: list[bool] = []

    def on_changed(_event: object) -> None:
        if threading.get_ident() == main:
            return
        in_handler.set()
        owner_saw_constructed.append(root.constructed.wait(HANG_GUARD))

    root.vm.on_collection_changed.subscribe(on_changed)
    root.vm.construct()
    errors: list[BaseException] = []
    worker = _start(lambda: root.vm.add(late), errors) if foreign_owner else None
    if worker is not None:
        assert in_handler.wait(HANG_GUARD)

    bg.run_all()
    if worker is not None:
        worker.join(3 * HANG_GUARD)
        assert not worker.is_alive()
        assert owner_saw_constructed == [True]

    assert errors == []
    assert root.changes == ["first"]
    assert seen == [S.CONSTRUCTING]  # the dispose waited for the publication
    assert root.vm.status is S.DISPOSED


def test_deferred_dispose_admits_no_transaction_after_the_owner_transaction_ends() -> None:
    # The owner's own transaction defers a dispose from its handler; when the
    # transaction ends, a foreign add before the dispose admits must be refused.
    _bg, dispatcher, hub = _services()
    b, x = _child(hub, dispatcher, "b"), _child(hub, dispatcher, "x")
    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [])
        .build()
    )
    root.construct()
    calls: list[int] = []
    errors: list[BaseException] = []
    original_dispose = root.dispose

    def dispose_with_foreign_add() -> None:
        calls.append(1)
        if len(calls) == 2:  # the handoff from the transaction end
            worker = _start(lambda: root.add(x), errors)
            worker.join(HANG_GUARD)
            assert not worker.is_alive()
        original_dispose()

    root.dispose = dispose_with_foreign_add  # type: ignore[method-assign]
    root.on_collection_changed.subscribe(lambda _event: root.dispose())
    root.add(b)

    assert len(calls) == 2
    assert [type(error) for error in errors] == [RuntimeError]
    assert "disposing" in str(errors[0])
    assert not any(child is x for child in root.snapshot())
    assert root.status is S.DISPOSED


def test_selector_result_is_ignored_while_the_composite_is_disposing() -> None:
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    changes: list[ComponentVM | None] = []

    def selector(_kids: Any) -> ComponentVM:
        root.dispose()  # no transaction or publication is open: disposal starts now
        return first

    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [first])
        .auto_construct_on_add(True)
        .current(selector)
        .on_current_changed(changes.append)
        .build()
    )
    root.construct()
    bg.run_all()

    assert root.current is None
    assert changes == []
    assert not first.is_current
    assert root.status is S.DISPOSED


def test_dispose_from_an_ordinary_selection_callback_defers_to_the_lease() -> None:
    # The lease covers every current change, not only the walk's selection: a
    # dispose from the callback must not wait for another thread's transaction.
    _bg, dispatcher, hub = _services()
    a = _child(hub, dispatcher, "a")
    c = _child(hub, dispatcher, "c")
    main = threading.get_ident()
    in_handler = threading.Event()
    dispose_returned = threading.Event()
    owner_saw_dispose_return: list[bool] = []
    seen: list[S] = []
    errors: list[BaseException] = []
    workers: list[threading.Thread] = []

    def on_current(_value: ComponentVM | None) -> None:
        workers.append(_start(lambda: root.add(c), errors))
        assert in_handler.wait(HANG_GUARD)
        root.dispose()
        seen.append(root.status)
        dispose_returned.set()

    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [a])
        .on_current_changed(on_current)
        .build()
    )
    root.construct()

    def on_changed(_event: object) -> None:
        if threading.get_ident() == main:
            return
        in_handler.set()
        owner_saw_dispose_return.append(dispose_returned.wait(HANG_GUARD))

    root.on_collection_changed.subscribe(on_changed)
    root.current = a
    workers[0].join(3 * HANG_GUARD)
    assert not workers[0].is_alive()

    assert errors == []
    assert owner_saw_dispose_return == [True]
    assert seen == [S.CONSTRUCTED]  # deferred: the dispose returned at once
    assert root.status is S.DISPOSED


def test_deferred_dispose_admits_no_transaction_during_the_handoff() -> None:
    # When the lease ends, the deferred dispose runs on this thread. A foreign
    # add in between must be refused, or that dispose would wait for it.
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    x = _child(hub, dispatcher, "x")
    calls: list[int] = []
    errors: list[BaseException] = []

    def dispose_root(_value: ComponentVM | None) -> None:
        root.vm.dispose()

    root = _Root([first], hub, dispatcher, on_current=dispose_root)
    original_dispose = root.vm.dispose

    def dispose_with_foreign_add() -> None:
        calls.append(1)
        if len(calls) == 2:  # the handoff from the lease end
            worker = _start(lambda: root.vm.add(x), errors)
            worker.join(HANG_GUARD)
            assert not worker.is_alive()
        original_dispose()

    root.vm.dispose = dispose_with_foreign_add  # type: ignore[method-assign]
    root.vm.construct()
    bg.run_all()

    assert len(calls) == 2
    assert [type(error) for error in errors] == [RuntimeError]
    assert "disposing" in str(errors[0])
    assert not any(child is x for child in root.vm.snapshot())
    assert root.vm.status is S.DISPOSED


@pytest.mark.parametrize("operation", ["add", "insert", "replace"])
def test_selector_result_whose_add_is_not_admitted_is_not_selected(operation: str) -> None:
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    spare = _child(hub, dispatcher, "spare")
    late = _child(hub, dispatcher, "late")
    attached = threading.Event()
    release = threading.Event()
    workers: list[threading.Thread] = []
    errors: list[BaseException] = []

    def attach_late() -> None:
        if operation == "add":
            root.add(late)
        elif operation == "insert":
            root.insert(0, late)
        else:
            root[1] = late  # replaces spare

    def selector(_children: Any) -> ComponentVM:
        workers.append(_start(attach_late, errors))
        assert attached.wait(HANG_GUARD)
        return late  # attached, not admitted

    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [first, spare])
        .auto_construct_on_add(True)
        .current(selector)
        .build()
    )

    def probe(child: object, stage: _LateChildStage) -> None:
        if stage is _LateChildStage.ATTACHED and child is late:
            attached.set()
            release.wait(2 * HANG_GUARD)
            raise RuntimeError("the add rolls back")

    root._late_starts.probe_for_testing = probe
    root.construct()
    bg.run_all()
    assert root.current is None
    release.set()
    workers[0].join(3 * HANG_GUARD)
    assert not workers[0].is_alive()
    bg.run_all()

    assert [str(error) for error in errors] == ["the add rolls back"]
    assert root.snapshot() == (first, spare)  # the rollback restored the membership
    assert root.current is None
    assert not late.is_current


@pytest.mark.parametrize("pick_late", [True, False])
def test_walk_resumed_on_the_add_owner_thread_selects_only_admitted_children(
    pick_late: bool,
) -> None:
    # The walk waits for the add's start attempt, then resumes in the add's
    # completion callback on the owner thread, before the add admits the child.
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    late = _child(hub, dispatcher, "late")
    main = threading.get_ident()
    selector_threads: list[str] = []

    def selector(kids: Any) -> ComponentVM:
        selector_threads.append("main" if threading.get_ident() == main else "owner")
        children = list(kids)
        return children[-1] if pick_late else children[0]

    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [first])
        .auto_construct_on_add(True)
        .current(selector)
        .build()
    )
    attached = threading.Event()
    walk_waiting = threading.Event()
    release = threading.Event()

    def probe(child: object, stage: _LateChildStage) -> None:
        if stage is _LateChildStage.ATTACHED and child is late:
            attached.set()
            release.wait(2 * HANG_GUARD)
        if stage is _LateChildStage.WALK_WAITING_ON_ADD:
            walk_waiting.set()

    root._late_starts.probe_for_testing = probe
    root.construct()
    errors: list[BaseException] = []
    worker = _start(lambda: root.add(late), errors)
    assert attached.wait(HANG_GUARD)
    bg.run_all()
    assert walk_waiting.wait(HANG_GUARD)
    release.set()
    worker.join(3 * HANG_GUARD)
    assert not worker.is_alive()
    bg.run_all()

    assert errors == []
    assert selector_threads == ["owner"]
    assert root.status is S.CONSTRUCTED
    assert any(child is late for child in root.snapshot())
    assert root.current is (None if pick_late else first)


@pytest.mark.parametrize(
    "mode", ["transfer-commit", "transfer-rollback", "replace", "replace-from-container"]
)
def test_transaction_that_detached_the_current_child_keeps_the_selector_result(mode: str) -> None:
    bg, dispatcher, hub = _services()
    first = _child(hub, dispatcher, "first", background=True)
    x, y = _child(hub, dispatcher, "X"), _child(hub, dispatcher, "Y")
    dfirst = _child(hub, dispatcher, "dfirst", background=True)
    dest: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("dest")
        .services(hub, dispatcher)
        .children(lambda: [dfirst])
        .auto_construct_on_add(True)
        .build()
    )
    # Y's old parent: its removal callback runs after root admits Y and before
    # root clears the replaced child, so the walk can select inside that window.
    # The case guards against reading Current before that callback; the clear's
    # own check-and-clear is atomic under the gates and has no user code inside.
    source: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("source")
        .services(hub, dispatcher)
        .children(lambda: [y] if mode == "replace-from-container" else [])
        .build()
    )
    source.construct()
    paused = threading.Event()
    release = threading.Event()
    selected = threading.Event()
    saw_selection: list[bool] = []
    changes: list[str | None] = []
    workers: list[threading.Thread] = []
    errors: list[BaseException] = []

    def on_source_changed(event: Any) -> None:
        if event.action == "remove":
            paused.set()
            saw_selection.append(selected.wait(HANG_GUARD))

    source.on_collection_changed.subscribe(on_source_changed)

    def on_current(value: ComponentVM | None) -> None:
        changes.append(None if value is None else value.name)
        if value is first:
            selected.set()

    def foreign() -> None:
        if mode.startswith("replace"):
            root[1] = y
        else:
            dest.add(x)

    def selector(_children: Any) -> ComponentVM:
        workers.append(_start(foreign, errors))
        assert paused.wait(HANG_GUARD)
        return first

    root: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [])
        .auto_construct_on_add(True)
        .current(selector)
        .on_current_changed(on_current)
        .build()
    )
    root.add(first)
    root.add(x)
    root.current = x
    changes.clear()
    selected.clear()

    def probe(_child: object, stage: _LateChildStage) -> None:
        if stage is _LateChildStage.ATTACHED:
            paused.set()
            release.wait(2 * HANG_GUARD)
            if mode == "transfer-rollback":
                raise RuntimeError("dest attach fails")

    if mode != "replace-from-container":
        (root if mode == "replace" else dest)._late_starts.probe_for_testing = probe
    root.construct()
    dest.construct()
    bg.run_first()  # first settles; root's walk runs the selector
    release.set()
    workers[0].join(3 * HANG_GUARD)
    assert not workers[0].is_alive()
    bg.run_all()

    assert [str(error) for error in errors] == (
        ["dest attach fails"] if mode == "transfer-rollback" else []
    )
    assert root.status is S.CONSTRUCTED
    assert root.current is first
    assert first.is_current
    assert not x.is_current
    assert changes == ["first"]
    if mode == "replace-from-container":
        assert saw_selection == [True]  # selected after root admitted Y
        assert root.snapshot() == (first, y)
