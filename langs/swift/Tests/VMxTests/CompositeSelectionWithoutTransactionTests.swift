//
// CompositeSelectionWithoutTransactionTests.swift — spec/06 §4.3 and §5,
// ADR-0165, ADR-0173.
//
// Every selection path commits without a membership transaction and never
// waits for another thread's transaction (rule 1). An unadmitted child is not
// a member (rule 2). A non-nil selection is refused while disposal is pending
// (rule 3). On the thread that owns an uncommitted transaction, a selection
// call is refused and the walk's assignment is a silent no-op (rule 4). A
// disposal from a publication is deferred through its lease (rule 5). A
// detach clears only a child that is still current (rule 6). The walk's
// assignment is synchronous under `asyncSelection` (rule 7). The destruct
// clear is never refused or skipped (§5, COMP-005).
//
// Issues: #1145, #1146, #1148, #1150, #1201. Every wait is bounded by
// `hangGuard`; a regression shows up as a timed-out wait, not a hang.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private final class Shared<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: T
    init(_ value: T) { stored = value }
    var value: T {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

final class CompositeSelectionWithoutTransactionTests: XCTestCase {
    /// The hang guard for every wait. Tests resume as soon as the awaited
    /// event happens; only a regression waits this long.
    private let hangGuard: TimeInterval = 5
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func deadline() -> DispatchTime { .now() + hangGuard }

    private func leaf(
        _ name: String,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        dispatcher: Dispatcher = ImmediateDispatcher.INSTANCE,
        background: Bool = false,
        onConstruct: (() throws -> Void)? = nil
    ) throws -> ComponentVM {
        var builder = ComponentVM.builder().name(name)
            .services(hub: hub, dispatcher: dispatcher).background(background)
        if let onConstruct { builder = builder.onConstruct(onConstruct) }
        return try builder.build()
    }

    /// Counts the composite's `"current"` property messages on `hub`.
    private func currentMessages(from composite: AnyObject, on hub: MessageHub) -> () -> Int {
        let count = Shared(0)
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === composite && $0.propertyName == "current" }
            .sink { _ in count.value += 1 }
            .store(in: &cancellables)
        return { count.value }
    }

    private func flush(_ dispatcher: ManualDispatcher) {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(hangGuard)
        while !condition() && Date() < end { Thread.sleep(forTimeInterval: 0.001) }
        return condition()
    }

    // ── #1150: the construct walk's assignment ──────────────────────────

    /// #1150 case 1 (ADR-0165 rule 3): the walk's assignment does not wait for
    /// another thread's open transaction, also when that thread waits for the
    /// construct.
    func testWalkAssignmentDoesNotWaitForAForeignTransaction() throws {
        let handlerStarted = DispatchSemaphore(value: 0)
        let constructReturned = DispatchSemaphore(value: 0)
        let addDone = DispatchSemaphore(value: 0)
        let handlerWait = Shared<DispatchTimeoutResult?>(nil)
        let hookWait = Shared<DispatchTimeoutResult?>(nil)
        let addResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let late = try leaf("late")
        let guardWait = hangGuard
        let first = try leaf("first", onConstruct: {
            Thread.detachNewThread {
                addResult.value = compositeRef.value?.addResult(late)
                addDone.signal()
            }
            hookWait.value = handlerStarted.wait(timeout: .now() + guardWait)
        })
        // `first` is added before construct(), so its hook runs outside any
        // membership transaction (a population would hold one).
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [] }.current { $0.first }.build()
        composite.add(first)
        compositeRef.value = composite
        composite.collectionChanged.sink { event in
            // The population of `children` publishes too; react to `late` only.
            guard event.newItems.contains(where: { $0 === late }) else { return }
            handlerStarted.signal()
            handlerWait.value = constructReturned.wait(timeout: .now() + guardWait)
        }.store(in: &cancellables)

        try composite.construct()
        constructReturned.signal()

        XCTAssertEqual(addDone.wait(timeout: deadline()), .success)
        XCTAssertEqual(hookWait.value, .success, "the worker's add did not reach its handler")
        XCTAssertEqual(handlerWait.value, .success, "construct() waited for the worker's transaction")
        XCTAssertEqual(composite.status, .constructed)
        XCTAssertTrue(composite.current === first)
        XCTAssertNoThrow(try addResult.value?.get())
        XCTAssertEqual(composite.count, 2)
    }

    /// #1150 case 2 (rule 5): a disposal from the walk's `onCurrentChanged`
    /// returns at once instead of waiting for another thread's transaction,
    /// and the composite is disposed once the callback and the transaction
    /// end.
    func testDisposeFromTheWalksCallbackDoesNotWaitForAForeignTransaction() throws {
        let handlerStarted = DispatchSemaphore(value: 0)
        let disposeReturned = DispatchSemaphore(value: 0)
        let addDone = DispatchSemaphore(value: 0)
        let handlerWait = Shared<DispatchTimeoutResult?>(nil)
        let statusAfterDispose = Shared<ConstructionStatus?>(nil)
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let started = Shared(false)
        let guardWait = hangGuard
        let late = try leaf("late")
        let first = try leaf("first")
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [first] }.current { $0.first }
            .onCurrentChanged { value in
                guard value != nil, !started.value, let composite = compositeRef.value else { return }
                started.value = true
                Thread.detachNewThread {
                    _ = composite.addResult(late)
                    addDone.signal()
                }
                _ = handlerStarted.wait(timeout: .now() + guardWait)
                composite.dispose()
                statusAfterDispose.value = composite.status
                disposeReturned.signal()
            }.build()
        compositeRef.value = composite
        composite.collectionChanged.sink { event in
            // The population of `children` publishes too; react to `late` only.
            guard event.newItems.contains(where: { $0 === late }) else { return }
            handlerStarted.signal()
            handlerWait.value = disposeReturned.wait(timeout: .now() + guardWait)
        }.store(in: &cancellables)

        _ = try? composite.construct()

        XCTAssertEqual(addDone.wait(timeout: deadline()), .success)
        XCTAssertEqual(handlerWait.value, .success, "dispose() waited for the worker's transaction")
        XCTAssertNotEqual(statusAfterDispose.value, .disposed, "the disposal is deferred")
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    /// #1150 case 3 (rules 3 and 4): the walk resumes on the thread whose add
    /// has not admitted its child and has deferred the composite's disposal.
    /// The assignment is a silent no-op.
    func testWalkResumingInsideAnUncommittedAddWithDeferredDisposalIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let releaseLate = DispatchSemaphore(value: 0)
        let addFinished = DispatchSemaphore(value: 0)
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let callbacks = Shared<[String]>([])
        let addResult = Shared<Result<Void, ContainerOwnershipError>?>(nil)
        let guardWait = hangGuard
        let late = try leaf("late", hub: hub, dispatcher: dispatcher, onConstruct: {
            _ = releaseLate.wait(timeout: .now() + guardWait)
            compositeRef.value?.dispose()
        })
        let picked = try leaf("picked", hub: hub, dispatcher: dispatcher)
        let background = try leaf("background", hub: hub, dispatcher: dispatcher, background: true)
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: dispatcher).autoConstructOnAdd()
            .children { [picked, background] }
            .current { children in children.first { $0 === picked } }
            .onCurrentChanged { callbacks.value.append($0?.name ?? "nil") }
            .build()
        compositeRef.value = composite
        let currentChanges = currentMessages(from: composite, on: hub)

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        Thread.detachNewThread {
            addResult.value = composite.addResult(late)
            addFinished.signal()
        }
        XCTAssertTrue(waitUntil { late.status == .constructing })
        flush(dispatcher)
        releaseLate.signal()
        XCTAssertEqual(addFinished.wait(timeout: deadline()), .success, "the add stalled")
        flush(dispatcher)

        XCTAssertNil(composite.current)
        XCTAssertEqual(callbacks.value, [])
        XCTAssertEqual(currentChanges(), 0)
        guard case .failure = addResult.value else {
            return XCTFail("the add must fail on the deferred disposal: \(String(describing: addResult.value))")
        }
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    /// #1150 (rule 3): a worker defers the composite's disposal from inside its
    /// own open add. The walk then resumes on another thread: its assignment
    /// is a silent no-op and does not wait for the worker's transaction.
    func testWalkAssignmentOnAnotherThreadWhileDisposalIsDeferredIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let inSink = DispatchSemaphore(value: 0)
        let walkDone = DispatchSemaphore(value: 0)
        let addFinished = DispatchSemaphore(value: 0)
        let sinkWait = Shared<DispatchTimeoutResult?>(nil)
        let guardWait = hangGuard
        let picked = try leaf("picked", hub: hub, dispatcher: dispatcher)
        let background = try leaf("background", hub: hub, dispatcher: dispatcher, background: true)
        let late = try leaf("late", hub: hub, dispatcher: dispatcher)
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [picked, background] }
            .current { children in children.first { $0 === picked } }
            .build()
        let currentChanges = currentMessages(from: composite, on: hub)
        composite.collectionChanged.sink { event in
            // The population of `children` publishes too; react to `late` only.
            guard event.newItems.contains(where: { $0 === late }) else { return }
            composite.dispose()
            inSink.signal()
            sinkWait.value = walkDone.wait(timeout: .now() + guardWait)
        }.store(in: &cancellables)

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        Thread.detachNewThread {
            _ = composite.addResult(late)
            addFinished.signal()
        }
        XCTAssertEqual(inSink.wait(timeout: deadline()), .success)
        flush(dispatcher)
        walkDone.signal()
        XCTAssertEqual(addFinished.wait(timeout: deadline()), .success)

        XCTAssertEqual(sinkWait.value, .success, "the walk waited for the worker's transaction")
        XCTAssertNil(composite.current)
        XCTAssertEqual(currentChanges(), 0)
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    /// #1150 case 4 (rules 2 and 4): the walk finishes inside the add that has
    /// attached but not admitted its pick. The assignment is a no-op.
    func testWalkFinishingInsideTheAddOfItsUnadmittedPickIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let picked = try leaf("picked", hub: hub, dispatcher: dispatcher)
        let background = try leaf("background", hub: hub, dispatcher: dispatcher, background: true)
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: dispatcher).autoConstructOnAdd()
            .children { [picked, background] }
            .current { children in children.first { $0 === picked } }
            .build()
        let currentChanges = currentMessages(from: composite, on: hub)
        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        XCTAssertTrue(composite.remove(picked))
        let probed = Shared(false)
        let statusInProbe = Shared<ConstructionStatus?>(nil)
        composite.lateChildProbeForTesting = { [unowned self] child, stage in
            guard child === picked, stage == .attached, !probed.value else { return }
            probed.value = true
            flush(dispatcher)
            statusInProbe.value = composite.status
        }
        defer { composite.lateChildProbeForTesting = nil }

        XCTAssertNoThrow(try composite.addResult(picked).get())
        flush(dispatcher)

        XCTAssertTrue(probed.value)
        XCTAssertEqual(statusInProbe.value, .constructed, "the walk finished inside the add")
        XCTAssertNil(composite.current)
        XCTAssertEqual(currentChanges(), 0)
        XCTAssertTrue(composite.canSelectComponent(picked), "the child is selectable once admitted")
    }

    /// #1150 case 5 (rule 6): the transfer's detach of the current child does
    /// not clear a selection that another thread made after the detach.
    func testTransferDetachKeepsASelectionMadeAfterTheDetach() throws {
        let dispatcher = ManualDispatcher()
        let callbacks = Shared<[String]>([])
        let x = try leaf("x")
        let y = try leaf("y")
        let a = try CompositeVM<ComponentVM>.builder().name("A").withNullServices()
            .children { [x, y] }
            .onCurrentChanged { callbacks.value.append($0?.name ?? "nil") }
            .build()
        try a.construct()
        try a.setCurrent(x)
        let background = try leaf("background", dispatcher: dispatcher, background: true)
        let b = try CompositeVM<ComponentVM>.builder().name("B")
            .services(hub: NullMessageHub.INSTANCE, dispatcher: dispatcher)
            .autoConstructOnAdd().children { [background] }.build()
        try b.construct()
        XCTAssertEqual(b.status, .constructing)
        let probed = Shared(false)
        let selection = Shared<DispatchTimeoutResult?>(nil)
        let selectionError = Shared<Error?>(nil)
        let guardWait = hangGuard
        b.lateChildProbeForTesting = { child, stage in
            guard child === x, stage == .attached, !probed.value else { return }
            probed.value = true
            let done = DispatchSemaphore(value: 0)
            Thread.detachNewThread {
                do { try a.setCurrent(y) } catch { selectionError.value = error }
                done.signal()
            }
            selection.value = done.wait(timeout: .now() + guardWait)
        }
        defer { b.lateChildProbeForTesting = nil }

        XCTAssertNoThrow(try b.addResult(x).get())
        flush(dispatcher)

        XCTAssertTrue(probed.value)
        XCTAssertEqual(selection.value, .success, "the selection waited for the transfer")
        XCTAssertNil(selectionError.value)
        XCTAssertTrue(a.current === y)
        XCTAssertTrue(y.isCurrent)
        XCTAssertEqual(callbacks.value, ["x", "y"], "the detach commit must not clear y")
        XCTAssertTrue(b.containsIdentity(x))
        XCTAssertFalse(a.containsIdentity(x))
    }

    /// #1150 case 6 (rule 7): with `asyncSelection(true)` the walk's
    /// assignment is synchronous, so `construct()` returns with the pick
    /// current before any foreground flush (COMP-010 covers the setter).
    func testWalkAssignmentIsSynchronousUnderAsyncSelection() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = try leaf("a", hub: hub, dispatcher: dispatcher)
        let b = try leaf("b", hub: hub, dispatcher: dispatcher)
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: dispatcher).asyncSelection(true)
            .children { [a, b] }.current { $0.first }.build()
        let currentChanges = currentMessages(from: composite, on: hub)

        try composite.construct()

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertTrue(composite.current === a)
        XCTAssertTrue(a.isCurrent)
        XCTAssertEqual(currentChanges(), 1)
        dispatcher.flushForeground()
        XCTAssertTrue(composite.current === a)
    }

    // ── #1145 / #1146 / #1148: the selection calls ──────────────────────

    /// Runs `body` on this thread while a worker's add of `parked` is inside
    /// the parked child's construct hook, that is, while the worker holds an
    /// uncommitted membership transaction. Returns whether the add was still
    /// parked when `body` returned.
    private func whileAWorkerAddIsParked(
        in composite: CompositeVM<ComponentVM>,
        _ name: String,
        _ body: (ComponentVM) throws -> Void
    ) throws -> Bool {
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let added = DispatchSemaphore(value: 0)
        let guardWait = hangGuard
        let parked = try leaf(name, onConstruct: {
            entered.signal()
            _ = release.wait(timeout: .now() + guardWait)
        })
        Thread.detachNewThread {
            composite.add(parked)
            added.signal()
        }
        XCTAssertEqual(entered.wait(timeout: deadline()), .success)
        try body(parked)
        let stillParked = added.wait(timeout: .now()) == .timedOut
        release.signal()
        XCTAssertEqual(added.wait(timeout: deadline()), .success)
        return stillParked
    }

    /// #1145 option 3 (rule 1) with `asyncSelection(true)`: the setter
    /// validates at call time and its delivery commits without waiting for
    /// another thread's open transaction.
    func testAsyncSetterDoesNotWaitForAForeignTransaction() throws {
        let a = try leaf("a")
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().asyncSelection(true).autoConstructOnAdd()
            .children { [a] }.build()
        try composite.construct()

        let parked = try whileAWorkerAddIsParked(in: composite, "parked") { _ in
            try composite.setCurrent(a)
            XCTAssertTrue(composite.current === a, "the immediate delivery committed")
        }
        XCTAssertTrue(parked, "the selection returned while the add was still open")
    }

    /// Rule 2 (#1146, #1148): another thread cannot select a child that an add
    /// attached but has not admitted; an admitted sibling is selectable.
    func testForeignThreadCannotSelectAnUnadmittedChild() throws {
        let a = try leaf("a")
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().autoConstructOnAdd().children { [a] }.build()
        try composite.construct()

        _ = try whileAWorkerAddIsParked(in: composite, "late") { late in
            XCTAssertFalse(composite.canSetCurrent(late))
            XCTAssertThrowsError(try composite.setCurrent(late)) { error in
                XCTAssertTrue("\(error)".contains("not an admitted child"), "\(error)")
            }
            XCTAssertNoThrow(try composite.setCurrent(a))
        }
        XCTAssertTrue(composite.current === a)
        XCTAssertEqual(composite.count, 2)
    }

    /// Rule 2 for a staged population (#1148): the walk cannot select a child
    /// that a population hook observes before the population is admitted, and
    /// another thread cannot select it either.
    func testStagedPopulationChildIsNotSelectableBeforeAdmission() throws {
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let foreignResult = Shared<Bool?>(nil)
        let staged = Shared<ComponentVM?>(nil)
        let guardWait = hangGuard
        let first = try leaf("first", onConstruct: {
            guard let composite = compositeRef.value, let second = staged.value else { return }
            let done = DispatchSemaphore(value: 0)
            Thread.detachNewThread {
                foreignResult.value = composite.canSetCurrent(second)
                    || (try? composite.setCurrent(second)) != nil
                done.signal()
            }
            _ = done.wait(timeout: .now() + guardWait)
        })
        let second = try leaf("second")
        staged.value = second
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [first, second] }.build()
        compositeRef.value = composite

        try composite.construct()

        XCTAssertEqual(foreignResult.value, false, "a staged child is not a member for selection")
        XCTAssertNil(composite.current)
        XCTAssertNoThrow(try composite.setCurrent(second))
    }

    /// Rule 4 (ledger §2.9, #1146 option a): on the thread that owns an
    /// uncommitted add, every selection call fails before it changes
    /// anything, also a `nil` clear. From the commit on, including the add's
    /// `CollectionChanged` publication, the owner thread selects.
    func testOwnerThreadSelectionIsRefusedUntilItsAddCommits() throws {
        let a = try leaf("a")
        let b = try leaf("b")
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let refusals = Shared<[String]>([])
        let late = try leaf("late", onConstruct: {
            guard let composite = compositeRef.value else { return }
            var refused: [String] = []
            if !composite.canSetCurrent(b) { refused.append("canSetCurrent(b)") }
            if !composite.canSetCurrent(nil) { refused.append("canSetCurrent(nil)") }
            if !composite.canSelectComponent(b) { refused.append("canSelectComponent(b)") }
            do { try composite.setCurrent(b) } catch {
                if "\(error)".contains("membership transaction") { refused.append("setCurrent(b)") }
            }
            do { try composite.setCurrent(nil) } catch { refused.append("setCurrent(nil)") }
            do { try composite.selectComponent(b) } catch { refused.append("selectComponent(b)") }
            do { try composite.deselectComponent(a) } catch { refused.append("deselectComponent(a)") }
            composite.selectChild(b)
            a.deselect()
            refusals.value = refused
        })
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().autoConstructOnAdd().children { [a, b] }.build()
        compositeRef.value = composite
        try composite.construct()
        try composite.setCurrent(a)
        let selectedInPublication = Shared(false)
        composite.collectionChanged.sink { event in
            guard case .add = event.action else { return }
            selectedInPublication.value = (try? composite.setCurrent(late)) != nil
        }.store(in: &cancellables)

        XCTAssertNoThrow(try composite.addResult(late).get())

        XCTAssertEqual(refusals.value, [
            "canSetCurrent(b)", "canSetCurrent(nil)", "canSelectComponent(b)", "setCurrent(b)",
            "setCurrent(nil)", "selectComponent(b)", "deselectComponent(a)",
        ])
        XCTAssertTrue(selectedInPublication.value, "the add's publication phase is committed")
        XCTAssertTrue(composite.current === late)
        XCTAssertFalse(a.isCurrent)
    }

    /// Rule 4 (#1146): a selection attempted inside an add that then fails
    /// changes nothing, so the rollback needs no `Current` restore.
    func testFailedAddLeavesCurrentAsBefore() throws {
        struct HookFailure: Error {}
        let hub = MessageHub()
        let a = try leaf("a", hub: hub)
        let b = try leaf("b", hub: hub)
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let late = try leaf("late", hub: hub, onConstruct: {
            try? compositeRef.value?.setCurrent(b)
            try? compositeRef.value?.setCurrent(nil)
            throw HookFailure()
        })
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .autoConstructOnAdd().children { [a, b] }.build()
        compositeRef.value = composite
        try composite.construct()
        try composite.setCurrent(a)
        let currentChanges = currentMessages(from: composite, on: hub)

        guard case .failure = composite.addResult(late) else { return XCTFail("the add must fail") }

        XCTAssertTrue(composite.current === a)
        XCTAssertTrue(a.isCurrent)
        XCTAssertFalse(b.isCurrent)
        XCTAssertEqual(currentChanges(), 0)
    }

    /// Rule 3: while disposal is deferred, a non-nil selection is refused on
    /// every thread and a `nil` clear commits.
    func testDeferredDisposalRefusesSelectionButNotTheClear() throws {
        let a = try leaf("a")
        let b = try leaf("b")
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().autoConstructOnAdd().children { [a, b] }.build()
        try composite.construct()
        try composite.setCurrent(a)
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let added = DispatchSemaphore(value: 0)
        let guardWait = hangGuard
        let late = try leaf("late", onConstruct: {
            composite.dispose()
            entered.signal()
            _ = release.wait(timeout: .now() + guardWait)
        })
        Thread.detachNewThread {
            _ = composite.addResult(late)
            added.signal()
        }
        XCTAssertEqual(entered.wait(timeout: deadline()), .success)

        XCTAssertFalse(composite.canSetCurrent(b))
        XCTAssertFalse(composite.canSelectComponent(b))
        XCTAssertThrowsError(try composite.setCurrent(b)) { error in
            XCTAssertTrue("\(error)".contains("disposal"), "\(error)")
        }
        XCTAssertThrowsError(try composite.selectComponent(b))
        b.select()
        XCTAssertTrue(composite.current === a)
        XCTAssertTrue(composite.canSetCurrent(nil))
        XCTAssertNoThrow(try composite.setCurrent(nil))
        XCTAssertNil(composite.current)

        release.signal()
        XCTAssertEqual(added.wait(timeout: deadline()), .success)
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    /// Rule 5: a disposal requested on another thread while a selection
    /// publishes is deferred, and runs once the publication ends.
    func testForeignDisposeDuringAPublicationIsDeferredToItsEnd() throws {
        let a = try leaf("a")
        let inCallback = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let guardWait = hangGuard
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [a] }
            .onCurrentChanged { value in
                guard value != nil else { return }
                inCallback.signal()
                _ = release.wait(timeout: .now() + guardWait)
            }.build()
        try composite.construct()
        let selected = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            try? composite.setCurrent(a)
            selected.signal()
        }
        XCTAssertEqual(inCallback.wait(timeout: deadline()), .success)

        composite.dispose()
        XCTAssertNotEqual(composite.status, .disposed, "the disposal waits for the publication")
        release.signal()

        XCTAssertEqual(selected.wait(timeout: deadline()), .success)
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    // ── #1201: the destruct clear (COMP-005) ─────────────────────────────

    /// #1201 reproduction: a destruct from the composite's own add
    /// `CollectionChanged` delivery clears `Current`.
    func testDestructInsideTheCompositesOwnAddClearsCurrent() throws {
        let first = try leaf("first")
        let late = try leaf("late")
        let composite = try CompositeVM<ComponentVM>.builder().name("root")
            .withNullServices().children { [first] }.current { $0.first }.build()
        try composite.construct()
        XCTAssertTrue(composite.current === first)
        let destructError = Shared<Error?>(nil)
        composite.collectionChanged.sink { _ in
            do { try composite.destruct() } catch { destructError.value = error }
        }.store(in: &cancellables)

        XCTAssertNoThrow(try composite.addResult(late).get())

        XCTAssertNil(destructError.value)
        XCTAssertEqual(composite.status, .destructed)
        XCTAssertNil(composite.current)
        XCTAssertFalse(first.isCurrent)
    }

    /// #1201: a destruct whose clear meets another thread's open membership
    /// transaction does not wait for it.
    func testDestructClearDoesNotWaitForAForeignTransaction() throws {
        let first = try leaf("first")
        let late = try leaf("late")
        let composite = try CompositeVM<ComponentVM>.builder().name("root")
            .withNullServices().autoConstructOnAdd().children { [first] }
            .current { $0.first }.build()
        try composite.construct()
        let inSink = DispatchSemaphore(value: 0)
        let destructReturned = DispatchSemaphore(value: 0)
        let added = DispatchSemaphore(value: 0)
        let sinkWait = Shared<DispatchTimeoutResult?>(nil)
        let guardWait = hangGuard
        composite.collectionChanged.sink { _ in
            inSink.signal()
            sinkWait.value = destructReturned.wait(timeout: .now() + guardWait)
        }.store(in: &cancellables)
        Thread.detachNewThread {
            _ = composite.addResult(late)
            added.signal()
        }
        XCTAssertEqual(inSink.wait(timeout: deadline()), .success)

        try composite.destruct()
        destructReturned.signal()

        XCTAssertEqual(added.wait(timeout: deadline()), .success)
        XCTAssertEqual(sinkWait.value, .success, "the destruct clear waited for the worker's transaction")
        XCTAssertEqual(composite.status, .destructed)
        XCTAssertNil(composite.current)
        XCTAssertFalse(first.isCurrent)
    }

    /// #1144 / #1201: a destruct while disposal is deferred still clears
    /// `Current`, and the deferred disposal then runs.
    func testDestructWhileDisposalIsDeferredClearsCurrent() throws {
        let first = try leaf("first")
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let destructError = Shared<Error?>(nil)
        let clearedByDestruct = Shared<Bool?>(nil)
        let composite = try CompositeVM<ComponentVM>.builder().name("root")
            .withNullServices().children { [first] }
            .onCurrentChanged { value in
                guard value != nil, let composite = compositeRef.value else { return }
                composite.dispose()
                do { try composite.destruct() } catch { destructError.value = error }
                clearedByDestruct.value = composite.current == nil
            }.build()
        compositeRef.value = composite
        try composite.construct()

        try composite.setCurrent(first)

        XCTAssertNil(destructError.value)
        XCTAssertEqual(clearedByDestruct.value, true, "COMP-005: Current is null after destruct")
        XCTAssertFalse(first.isCurrent)
        XCTAssertEqual(composite.status, .disposed)
    }

    /// Rule 5 for the destruct clear: a disposal from `onCurrentChanged(nil)`
    /// is deferred through the clear's lease.
    func testDisposeFromTheDestructClearsCallbackIsDeferred() throws {
        let first = try leaf("first")
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let statusInCallback = Shared<ConstructionStatus?>(nil)
        let composite = try CompositeVM<ComponentVM>.builder().name("root")
            .withNullServices().children { [first] }.current { $0.first }
            .onCurrentChanged { value in
                guard value == nil, let composite = compositeRef.value else { return }
                composite.dispose()
                statusInCallback.value = composite.status
            }.build()
        compositeRef.value = composite
        try composite.construct()

        _ = try? composite.destruct()

        XCTAssertEqual(statusInCallback.value, .destructing, "the disposal waits for the callback")
        XCTAssertNil(composite.current)
        XCTAssertTrue(waitUntil { composite.status == .disposed })
    }

    /// COMP-006 with a transfer: a selection of the moved child in the
    /// destination, made by another thread while the add runs, leaves the
    /// child's flag set. The destination admits the child only after the old
    /// parent's detach commit has cleared the flag there, so that commit can
    /// no longer reset the flag of a child that is already current in the
    /// destination. The race is narrow, so the test repeats it.
    func testForeignSelectionInTheDestinationOfATransferKeepsIsCurrent() throws {
        var selectedInDestination = 0
        var desynchronized = 0
        let guardWait = hangGuard
        for iteration in 0..<300 {
            let x = try leaf("x\(iteration)")
            let a = try CompositeVM<ComponentVM>.builder().name("A").withNullServices()
                .children { [x] }.build()
            try a.construct()
            try a.setCurrent(x)
            let b = try CompositeVM<ComponentVM>.builder().name("B").withNullServices()
                .children { [] }.build()
            try b.construct()
            let started = DispatchSemaphore(value: 0)
            let done = DispatchSemaphore(value: 0)
            let stop = Shared(false)
            Thread.detachNewThread {
                started.signal()
                let end = Date().addingTimeInterval(guardWait)
                while !stop.value && Date() < end {
                    if (try? b.setCurrent(x)) != nil, b.current === x { break }
                }
                done.signal()
            }
            XCTAssertEqual(started.wait(timeout: deadline()), .success)
            XCTAssertNoThrow(try b.addResult(x).get())
            let finished = done.wait(timeout: deadline())
            stop.value = true
            XCTAssertEqual(finished, .success, "the selecting thread did not finish")
            XCTAssertNil(a.current)
            if b.current === x {
                selectedInDestination += 1
                if !x.isCurrent { desynchronized += 1 }
            }
        }
        XCTAssertGreaterThan(selectedInDestination, 0)
        XCTAssertEqual(desynchronized, 0, "B.current is x while x.isCurrent is false")
    }

    /// Rule 4 on the old parent of a transfer: between the detach and its
    /// commit, the adding thread owns the old parent's uncommitted transaction,
    /// so a selection call there is refused, and the predicate says so.
    func testSelectionOnTheOldParentDuringATransferIsRefusedOnTheAddingThread() throws {
        let aRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let refusals = Shared<[String]>([])
        let y = try leaf("y")
        let x = try leaf("x", onConstruct: {
            guard let a = aRef.value else { return }
            var refused: [String] = []
            if !a.canSetCurrent(y) { refused.append("canSetCurrent(y)") }
            if !a.canSetCurrent(nil) { refused.append("canSetCurrent(nil)") }
            do { try a.setCurrent(y) } catch {
                if "\(error)".contains("membership transaction") { refused.append("setCurrent(y)") }
            }
            refusals.value = refused
        })
        let a = try CompositeVM<ComponentVM>.builder().name("A").withNullServices()
            .children { [] }.build()
        aRef.value = a
        a.add(x)
        a.add(y)
        try a.setCurrent(x)
        let b = try CompositeVM<ComponentVM>.builder().name("B").withNullServices()
            .autoConstructOnAdd().children { [] }.build()
        try b.construct()

        XCTAssertNoThrow(try b.addResult(x).get())

        XCTAssertEqual(refusals.value, ["canSetCurrent(y)", "canSetCurrent(nil)", "setCurrent(y)"])
        XCTAssertNil(a.current, "the detach commit clears the moved child")
        XCTAssertFalse(x.isCurrent)
        XCTAssertFalse(y.isCurrent)
        XCTAssertTrue(b.containsIdentity(x))
        XCTAssertNoThrow(try a.setCurrent(y), "the old parent is selectable after the commit")
    }

    /// Rule 3 ends at Disposed: a composite that disposes itself in its own
    /// construct hook publishes Disposed before its dispose hook runs, and
    /// from then on selection is inert (chapter 01 §4), not refused as
    /// "disposal in progress".
    func testSelectionAfterDisposedInsideTheCompositesOwnHookIsInert() throws {
        let member = try leaf("member")
        let compositeRef = Shared<CompositeVM<ComponentVM>?>(nil)
        let statusInHook = Shared<ConstructionStatus?>(nil)
        let errorInHook = Shared<Error?>(nil)
        let canSetInHook = Shared<Bool?>(nil)
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [] }
            .onConstruct {
                guard let composite = compositeRef.value else { return }
                composite.dispose()
                statusInHook.value = composite.status
                do { try composite.setCurrent(member) } catch { errorInHook.value = error }
                // The trapping setter must not trap either.
                composite.current = member
                canSetInHook.value = composite.canSetCurrent(member)
            }.build()
        compositeRef.value = composite
        composite.add(member)

        _ = try? composite.construct()

        XCTAssertEqual(statusInHook.value, .disposed)
        XCTAssertNil(errorInHook.value, "a selection after Disposed is inert, not refused")
        XCTAssertEqual(canSetInHook.value, false)
        XCTAssertNil(composite.current)
        XCTAssertFalse(member.isCurrent)
        XCTAssertEqual(composite.status, .disposed)
        XCTAssertNoThrow(try composite.setCurrent(member))
        XCTAssertNil(composite.current)
    }
}
