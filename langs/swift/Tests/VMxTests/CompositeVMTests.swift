//
// CompositeVM conformance tests.
//
// Claimed IDs: COMP-003 (select via child delegation), COMP-004,
// destruct cascade (COMP-005), COMP-025 (`current(selector)` builder hook), COMP-026
// (`onCurrentChanged(callback)` builder hook). COMP-001/002
// (CollectionChanged), COMP-006/010 (foreground dispatch), COMP-007
// (modeled composite), COMP-008 are NOT claimed. COMP-009 (non-child
// `current` assignment raises) is now a *catchable throw* via
// `setCurrent(_:)`/`canSetCurrent(_:)` (VMX-026 / ADR-0053); the
// `current` property setter still traps because Swift setters cannot
// throw.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class CompositeVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder()
            .name(name)
            .withNullServices()
            .build()
    }

    /// Composite reports the Composite kind.
    func testCompositeType() throws {
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [self.leaf("a")] }
            .build()
        XCTAssertEqual(c.type, .composite)
    }

    /// `add` appends to the children list.
    func testAddAppends() {
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        let a = leaf("a")
        c.add(a)
        XCTAssertEqual(c.count, 1)
        XCTAssertTrue(c.at(0) === a)
    }

    /// COMP-004 — construct cascades to (waits on) children.
    func testComp004ConstructCascades() throws {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices()
            .children { [a, b] }
            .build()
        try c.construct()
        XCTAssertEqual(a.status, .constructed)
        XCTAssertEqual(b.status, .constructed)
        // Catalog COMP-004: the composite itself must also be Constructed.
        XCTAssertEqual(c.status, .constructed)
    }

    /// COMP-005 — destruct cascades to (waits on) children, clears `current`,
    /// and the composite itself reaches `.destructed`.
    func testComp005DestructCascades() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        try c.destruct()
        XCTAssertEqual(a.status, .destructed)
        XCTAssertNil(c.current)                 // current cleared on destruct
        XCTAssertEqual(c.status, .destructed)   // composite itself destructed
    }

    /// Setting `current` to a child member updates the slot.
    func testCurrentSet() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)
    }

    /// Removing the current child drops the current slot.
    func testRemoveCurrentDropsSlot() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.current = a
        XCTAssertTrue(c.remove(a))
        XCTAssertNil(c.current)
    }

    /// Clear-like behaviour via repeated remove drops all children.
    /// (Full `clear()` lands in a follow-up.)
    func testRemoveAllChildren() throws {
        let a = leaf("a"); let b = leaf("b")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a, b] }.build()
        try c.construct()
        _ = c.remove(a); _ = c.remove(b)
        XCTAssertEqual(c.count, 0)
    }

    /// Dispose cascades to children (canonical assertion is LIFE-013 in
    /// the lifecycle suite; this covers the composite path explicitly).
    func testDisposeCascade() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()
        c.dispose()
        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(c.status, .disposed)
    }

    /// Child's `_parent` is wired on add — observed via `canSelect()`.
    func testChildParentWiredOnAdd() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)
        try a.construct()
        XCTAssertTrue(a.canSelect())
    }

    /// COMP-003 — selecting through the child (`select()` delegates to the
    /// parent's select-child path) sets the parent's `current` slot, flips the
    /// child's `isCurrent`, and emits both PropertyChangedMessage("current") on
    /// the composite and PropertyChangedMessage("isCurrent") with sender === the
    /// child (all four catalog clauses; the prior test built with null services
    /// so the two hub clauses were unobservable).
    func testComp003SelectThroughChildSetsCurrent() throws {
        let hub = MessageHub()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a] }.build()
        try c.construct()

        // Subscribe after construct so only the select() messages are captured.
        var propNames: [String] = []
        var isCurrentSenders: [ObjectIdentifier] = []
        let cancel = hub.messages.sink { msg in
            guard let pcm = msg as? PropertyChangedMessage else { return }
            propNames.append(pcm.propertyName)
            if pcm.propertyName == "isCurrent" {
                isCurrentSenders.append(ObjectIdentifier(pcm.sender))
            }
        }

        a.select()

        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)
        XCTAssertTrue(propNames.contains("current"),
            "PropertyChangedMessage(current) emitted on the composite")
        XCTAssertEqual(isCurrentSenders, [ObjectIdentifier(a)],
            "exactly one isCurrent PropertyChangedMessage, sender === a")
        cancel.cancel()
    }

    // ── current(_:) builder hook (COMP-025) ─────────────────────────────

    func testCurrentSelectorDrivesInitialSelectionAfterConstruct() throws {
        let a = leaf("a"); let b = leaf("b"); let cChild = leaf("c")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a, b, cChild] }
            .current { children in Array(children)[1] }
            .build()
        try composite.construct()

        XCTAssertTrue(composite.current === b)
    }

    func testCurrentSelectorReturningNilLeavesCurrentNil() throws {
        let a = leaf("a")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a] }
            .current { _ in nil }
            .build()
        try composite.construct()

        XCTAssertNil(composite.current)
    }

    // ── onCurrentChanged(_:) builder hook (COMP-026) ────────────────────

    func testOnCurrentChangedFiresAfterEachCurrentChange() throws {
        let hub1 = MessageHub()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let b = try ComponentVM.builder()
            .name("b").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let c = try ComponentVM.builder()
            .name("c").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        var observed: [ComponentVM?] = []
        // Shared event log: each callback must be recorded after the matching
        // PropertyChangedMessage("current") from the composite on the hub.
        var events: [String] = []
        var compositeRef: CompositeVM<ComponentVM>?

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .onCurrentChanged { vm in
                observed.append(vm)
                events.append("callback:\(vm?.name ?? "nil")")
            }
            .build()
        compositeRef = composite
        let currentSub = hub1.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "current" && $0.senderObject === compositeRef }
            .sink { _ in events.append("message") }
        try composite.construct()
        XCTAssertNil(composite.current)
        composite.selectChild(b)
        composite.deselectChild(b)

        XCTAssertEqual(observed.count, 2)
        XCTAssertTrue(observed[0] === b)
        XCTAssertNil(observed[1])
        XCTAssertEqual(events, ["message", "callback:b", "message", "callback:nil"],
                       "each callback must run after its PropertyChangedMessage(\"current\")")
        currentSub.cancel()
    }

    func testOnCurrentChangedFiresOnceForInitialSelector() throws {
        let a = leaf("a")
        var observed: [ComponentVM?] = []

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [a] }
            .current { children in Array(children).first }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        try composite.construct()

        XCTAssertEqual(observed.count, 1)
        XCTAssertTrue(observed[0] === a)
    }

    func testOnCurrentChangedDoesNotFireWhenSelectorReturnsNilOrOutOfSet() throws {
        let a = leaf("a")
        var observed: [ComponentVM?] = []

        // Case 1: selector returns nil.
        let c1 = try CompositeVM<ComponentVM>.builder()
            .name("c-null")
            .withNullServices()
            .children { [a] }
            .current { _ in nil }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        try c1.construct()
        XCTAssertTrue(observed.isEmpty)

        // Case 2: selector returns out-of-set.
        let foreign = leaf("foreign")
        let c2 = try CompositeVM<ComponentVM>.builder()
            .name("c-foreign")
            .withNullServices()
            .children { [a] }
            .current { _ in foreign }
            .onCurrentChanged { vm in observed.append(vm) }
            .build()
        try c2.construct()
        XCTAssertTrue(observed.isEmpty)
    }

    // ── Conformance — COMP-025 / COMP-026 ───────────────────────────────

    /// COMP-025 — `current(selector)` builder hook drives initial selection
    /// during construct. Three clauses (spec/12 COMP-025, parity with the
    /// Python/C# conformance tests):
    ///   1. the selector's return value becomes `current`;
    ///   2. the selector runs EXACTLY ONCE — after every child reached
    ///      `.constructed` and before the composite itself reaches
    ///      `.constructed`;
    ///   3. a null-returning selector leaves `current` nil AND publishes no
    ///      `PropertyChangedMessage("current")`.
    func testCOMP025CurrentSelectorDrivesInitialSelection() throws {
        let hub = MessageHub()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let b = try ComponentVM.builder()
            .name("b").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let cChild = try ComponentVM.builder()
            .name("c").services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE).build()

        var selectorCalls = 0
        var allChildrenConstructedAtSelector = false
        var compositeStatusAtSelector: ConstructionStatus?
        weak var compositeRef: CompositeVM<ComponentVM>?

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, cChild] }
            .current { children in
                selectorCalls += 1
                allChildrenConstructedAtSelector = children.allSatisfy { $0.status == .constructed }
                compositeStatusAtSelector = compositeRef?.status
                return Array(children)[1]
            }
            .build()
        compositeRef = composite

        try composite.construct()

        // Clause 1 — the selector's pick (b) becomes current.
        XCTAssertTrue(composite.current === b)
        // Clause 2 — exactly one selector call, after every child reached
        // Constructed and while the composite is still Constructing.
        XCTAssertEqual(selectorCalls, 1, "the selector must run exactly once during construct")
        XCTAssertTrue(allChildrenConstructedAtSelector,
                      "the selector must run after every child reached Constructed")
        XCTAssertEqual(compositeStatusAtSelector, .constructing,
                       "the selector must run before the composite itself reaches Constructed")

        // Clause 3 — a null-returning selector leaves current nil and publishes
        // no PropertyChangedMessage("current") on the hub.
        let hub2 = MessageHub()
        let a2 = try ComponentVM.builder()
            .name("a").services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE).build()
        var propertyNames: [String] = []
        let cancel = hub2.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .sink { propertyNames.append($0.propertyName) }

        let composite2 = try CompositeVM<ComponentVM>.builder()
            .name("composite2")
            .services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a2] }
            .current { _ in nil }
            .build()
        try composite2.construct()

        XCTAssertNil(composite2.current)
        XCTAssertFalse(propertyNames.contains("current"),
                       "a null-returning current selector must publish no "
                       + "PropertyChangedMessage(\"current\")")
        cancel.cancel()
    }

    /// COMP-026 — `onCurrentChanged(callback)` fires synchronously after
    /// each `current` change.
    ///
    /// The idiomatic `selectComponent` / `deselectComponent` surface and the
    /// child-to-parent selection path converge at the same current-change
    /// transaction, so callback ordering is identical.
    func testCOMP026OnCurrentChangedFiresAfterEachChange() throws {
        let hub1 = MessageHub()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let b = try ComponentVM.builder()
            .name("b").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let c = try ComponentVM.builder()
            .name("c").services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE).build()
        var observed: [ComponentVM?] = []
        // Shared event log: each callback must be recorded after the matching
        // PropertyChangedMessage("current") from the composite on the hub.
        var events: [String] = []
        var compositeRef: CompositeVM<ComponentVM>?

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub1, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a, b, c] }
            .onCurrentChanged { vm in
                observed.append(vm)
                events.append("callback:\(vm?.name ?? "nil")")
            }
            .build()
        compositeRef = composite
        let currentSub = hub1.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "current" && $0.senderObject === compositeRef }
            .sink { _ in events.append("message") }
        try composite.construct()
        XCTAssertNil(composite.current)
        composite.selectChild(b)
        composite.deselectChild(b)

        XCTAssertEqual(observed.count, 2)
        XCTAssertTrue(observed[0] === b)
        XCTAssertNil(observed[1])
        XCTAssertEqual(events, ["message", "callback:b", "message", "callback:nil"],
                       "each callback must run after its PropertyChangedMessage(\"current\")")
        currentSub.cancel()

        // Combined current(first) + onCurrentChanged: the initial-selector
        // assignment fires the hook exactly once with the first child during
        // construct — parity with the C#/Python/TypeScript COMP-026 second
        // composite (CompositeVMConformanceTests.cs, test_composite_vm.py,
        // compositeVM.test.ts).
        let hub2 = MessageHub()
        let a2 = try ComponentVM.builder()
            .name("a").services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE).build()
        let b2 = try ComponentVM.builder()
            .name("b").services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE).build()
        var observed2: [ComponentVM?] = []

        let composite2 = try CompositeVM<ComponentVM>.builder()
            .name("composite2")
            .services(hub: hub2, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [a2, b2] }
            .current { children in Array(children).first }
            .onCurrentChanged { vm in observed2.append(vm) }
            .build()
        try composite2.construct()

        XCTAssertEqual(observed2.count, 1,
                       "the initial-selector assignment fires onCurrentChanged exactly once")
        XCTAssertTrue(observed2[0] === a2,
                      "the construct-time hook receives the selected first child")

        let reentrantChild = leaf("reentrant")
        var reentrant: CompositeVM<ComponentVM>!
        var callbackStatus: ConstructionStatus?
        reentrant = try CompositeVM<ComponentVM>.builder()
            .name("reentrant-composite")
            .withNullServices()
            .children { [reentrantChild] }
            .onCurrentChanged { selected in
                callbackStatus = selected?.status
                reentrant.dispose()
            }
            .build()
        try reentrant.construct()

        reentrant.selectChild(reentrantChild)

        XCTAssertEqual(callbackStatus, .constructed)
        XCTAssertEqual(reentrant.status, .disposed)
    }

    /// COMP-026 — opposing `onCurrentChanged` callbacks that synchronously
    /// select children in two composites complete without deadlock.
    func testCOMP026OpposingCurrentCallbacksAcrossCompositesDoNotDeadlock() throws {
        let leftChild = leaf("left-child")
        let rightChild = leaf("right-child")
        var left: CompositeVM<ComponentVM>!
        var right: CompositeVM<ComponentVM>!
        left = try CompositeVM<ComponentVM>.builder().name("left")
            .withNullServices().children { [leftChild] }
            .onCurrentChanged { _ in right.selectChild(rightChild) }.build()
        right = try CompositeVM<ComponentVM>.builder().name("right")
            .withNullServices().children { [rightChild] }
            .onCurrentChanged { _ in left.selectChild(leftChild) }.build()
        try left.construct()
        try right.construct()

        let start = DispatchSemaphore(value: 0)
        let done = DispatchGroup()
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            left.selectChild(leftChild)
            done.leave()
        }
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            right.selectChild(rightChild)
            done.leave()
        }
        start.signal()
        start.signal()

        XCTAssertEqual(done.wait(timeout: .now() + 10), .success,
                       "opposing current callbacks must not deadlock")
        XCTAssertTrue(left.current === leftChild)
        XCTAssertTrue(right.current === rightChild)
    }

    /// COMP-026 — a collection-change callback that initiates a current change
    /// while a current callback initiates collection work completes without
    /// deadlock (consumer callbacks do not retain the shared coordinator).
    ///
    /// Only the current callback for the thread-A selection (`l1`) adds to
    /// `right`. The `l2` callback runs on thread B inside `right`'s own
    /// `collectionChanged` delivery, where an add to `right` is a re-entrant
    /// mutation that every flavor rejects (ADR-0118; see
    /// `testCOMP026AddFromTheSameCompositesCollectionCallbackChainIsRejected`).
    func testCOMP026CollectionAndCurrentCallbacksCrossingDoNotDeadlock() throws {
        let l1 = leaf("l1")
        let l2 = leaf("l2")
        let lock = NSLock()
        var currentCallbackAdded = false
        var collectionCallbackSelected = false
        var bag = Set<AnyCancellable>()
        var left: CompositeVM<ComponentVM>!
        let right = try CompositeVM<ComponentVM>.builder().name("right")
            .withNullServices().children { [] }.build()
        left = try CompositeVM<ComponentVM>.builder().name("left")
            .withNullServices().children { [l1, l2] }
            .onCurrentChanged { selected in
                guard selected === l1 else { return }
                lock.lock()
                let go = !currentCallbackAdded
                currentCallbackAdded = true
                lock.unlock()
                if go { right.add(self.leaf("from-current-callback")) }
            }.build()
        try left.construct()
        try right.construct()
        right.collectionChanged.sink { _ in
            lock.lock()
            let go = !collectionCallbackSelected
            collectionCallbackSelected = true
            lock.unlock()
            if go { left.selectChild(l2) }
        }.store(in: &bag)

        let start = DispatchSemaphore(value: 0)
        let done = DispatchGroup()
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            left.selectChild(l1)
            done.leave()
        }
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            right.add(self.leaf("from-thread"))
            done.leave()
        }
        start.signal()
        start.signal()

        XCTAssertEqual(done.wait(timeout: .now() + 10), .success,
                       "crossing collection/current callbacks must not deadlock")
        XCTAssertNotNil(left.current)
        XCTAssertEqual(right.count, 2)
        bag.removeAll()
    }

    /// COMP-026 — the crossing above, forced into one interleaving. Thread A's
    /// current callback is parked until thread B's collection callback has
    /// selected on `left`, so that selection must complete while A is still
    /// inside `left`'s callback (callbacks retain neither the shared coordinator
    /// nor `left`'s membership transaction). A's add starts only after B's add
    /// is delivering its change, so it waits for B's transaction if that is
    /// still open and always lands second.
    func testCOMP026CollectionAndCurrentCallbacksCrossingDeterministically() throws {
        let l1 = leaf("l1")
        let l2 = leaf("l2")
        let inCurrentCallback = DispatchSemaphore(value: 0)
        let collectionCallbackSelected = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var collectionCallbackRan = false
        var currentCallbackAdd: Result<Void, ContainerOwnershipError>?
        var bag = Set<AnyCancellable>()
        var left: CompositeVM<ComponentVM>!
        let right = try CompositeVM<ComponentVM>.builder().name("right")
            .withNullServices().children { [] }.build()
        left = try CompositeVM<ComponentVM>.builder().name("left")
            .withNullServices().children { [l1, l2] }
            .onCurrentChanged { selected in
                guard selected === l1 else { return }
                inCurrentCallback.signal()
                guard collectionCallbackSelected.wait(timeout: .now() + 10) == .success else {
                    return
                }
                let result = right.addResult(self.leaf("from-current-callback"))
                lock.withLock { currentCallbackAdd = result }
            }.build()
        try left.construct()
        try right.construct()
        right.collectionChanged.sink { _ in
            let first = lock.withLock { () -> Bool in
                defer { collectionCallbackRan = true }
                return !collectionCallbackRan
            }
            guard first else { return }
            left.selectChild(l2)
            collectionCallbackSelected.signal()
        }.store(in: &bag)

        let done = DispatchGroup()
        done.enter()
        DispatchQueue.global().async {
            left.selectChild(l1)
            done.leave()
        }
        XCTAssertEqual(inCurrentCallback.wait(timeout: .now() + 10), .success,
                       "thread A reaches left's current callback")
        done.enter()
        DispatchQueue.global().async {
            right.add(self.leaf("from-thread"))
            done.leave()
        }

        XCTAssertEqual(done.wait(timeout: .now() + 10), .success,
                       "crossing collection/current callbacks must not deadlock")
        let added = lock.withLock { currentCallbackAdd }
        guard case .success? = added else {
            return XCTFail("the current callback's add must succeed, got \(String(describing: added))")
        }
        XCTAssertTrue(left.current === l2, "B's selection commits after A's")
        XCTAssertEqual(right.snapshot().map(\.name), ["from-thread", "from-current-callback"])
        bag.removeAll()
    }

    /// COMP-026 / ADR-0118 — a selection made while another thread holds the
    /// composite's membership transaction waits for it and then completes. It
    /// was dropped (`selectChild`), rejected as a non-member (`setCurrent`), or
    /// trapped (`current =`), which also made the crossing test above flaky.
    /// The add's construct hook parks with a timeout, so the add always ends.
    func testCOMP026SelectionFromAnotherThreadWaitsForAnOpenMembershipTransaction() throws {
        let a = leaf("a")
        let b = leaf("b")
        let c = leaf("c")
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [a, b, c] }
            .autoConstructOnAdd(true).build()
        try composite.construct()

        func whileAnotherThreadAdds(_ name: String, _ select: () throws -> Void) rethrows {
            let entered = DispatchSemaphore(value: 0)
            let release = DispatchSemaphore(value: 0)
            let parked = try! ComponentVM.builder().name(name).withNullServices()
                .onConstruct {
                    entered.signal()
                    _ = release.wait(timeout: .now() + 0.2)
                }.build()
            let added = DispatchGroup()
            added.enter()
            DispatchQueue.global().async {
                composite.add(parked)
                added.leave()
            }
            XCTAssertEqual(entered.wait(timeout: .now() + 10), .success)
            defer {
                release.signal()
                XCTAssertEqual(added.wait(timeout: .now() + 10), .success)
            }
            try select()
        }

        whileAnotherThreadAdds("parked-1") { composite.selectChild(a) }
        XCTAssertTrue(composite.current === a, "selectChild waits instead of being dropped")
        try whileAnotherThreadAdds("parked-2") { try composite.setCurrent(b) }
        XCTAssertTrue(composite.current === b, "setCurrent waits instead of throwing")
        whileAnotherThreadAdds("parked-3") { composite.current = c }
        XCTAssertTrue(composite.current === c, "the current setter waits instead of trapping")
        XCTAssertEqual(composite.count, 6)
    }

    /// COMP-026 — a selection waiting for another thread's membership
    /// transaction does not retain the shared cross-composite coordinator, so
    /// that thread's construct hook can still select in another composite.
    func testCOMP026SelectionWaitingForATransactionDoesNotRetainTheCoordinator() throws {
        let a = leaf("a")
        let o = leaf("o")
        let other = try CompositeVM<ComponentVM>.builder().name("other")
            .withNullServices().children { [o] }.build()
        try other.construct()
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices().children { [a] }
            .autoConstructOnAdd(true).build()
        try composite.construct()
        let entered = DispatchSemaphore(value: 0)
        let selectionStarted = DispatchSemaphore(value: 0)
        let parked = try ComponentVM.builder().name("parked").withNullServices()
            .onConstruct {
                entered.signal()
                // Give the other thread time to start waiting, then select.
                _ = selectionStarted.wait(timeout: .now() + 10)
                Thread.sleep(forTimeInterval: 0.05)
                other.selectChild(o)
            }.build()

        let done = DispatchGroup()
        done.enter()
        DispatchQueue.global().async {
            composite.add(parked)
            done.leave()
        }
        XCTAssertEqual(entered.wait(timeout: .now() + 10), .success)
        done.enter()
        DispatchQueue.global().async {
            selectionStarted.signal()
            composite.selectChild(a)
            done.leave()
        }

        XCTAssertEqual(done.wait(timeout: .now() + 10), .success,
                       "a waiting selection must not block selection in another composite")
        XCTAssertTrue(other.current === o)
        XCTAssertTrue(composite.current === a)
    }

    /// COMP-026 / ADR-0118 — the ordering that made the crossing test flaky:
    /// when the composite's own `collectionChanged` delivery selects on
    /// another composite whose current callback adds back to the first, that
    /// add re-enters the first composite's open membership transaction on the
    /// same thread. It is rejected (as in C#, Python and TypeScript) without
    /// changing membership, and the outer add still succeeds.
    func testCOMP026AddFromTheSameCompositesCollectionCallbackChainIsRejected() throws {
        let l1 = leaf("l1")
        let l2 = leaf("l2")
        var reentrant: Result<Void, ContainerOwnershipError>?
        var selected = false
        var bag = Set<AnyCancellable>()
        let right = try CompositeVM<ComponentVM>.builder().name("right")
            .withNullServices().children { [] }.build()
        let left = try CompositeVM<ComponentVM>.builder().name("left")
            .withNullServices().children { [l1, l2] }
            .onCurrentChanged { _ in
                if reentrant == nil {
                    reentrant = right.addResult(self.leaf("from-current-callback"))
                }
            }.build()
        try left.construct()
        try right.construct()
        right.collectionChanged.sink { _ in
            if !selected {
                selected = true
                left.selectChild(l2)
            }
        }.store(in: &bag)

        try right.addResult(leaf("from-thread")).get()

        XCTAssertTrue(left.current === l2)
        guard case let .failure(.attachmentFailed(error))? = reentrant else {
            return XCTFail("expected a rejection, got \(String(describing: reentrant))")
        }
        XCTAssertTrue("\(error)".contains("MembershipTransaction"), "got \(error)")
        XCTAssertEqual(right.snapshot().map(\.name), ["from-thread"])
        bag.removeAll()
    }

    /// VMX-098 — `selectChild` gates on Constructed, mirroring C#
    /// `CanSelectComponent` (`member && status == .constructed`). Selecting a
    /// member that is not yet constructed is a no-op (Swift keeps the no-op
    /// rather than the C# throw — trap-vs-throw is tracked separately,
    /// ADR-0037); once constructed, the same call selects it.
    func testSelectChildGatesOnConstructed() throws {
        let a = leaf("a")
        let c = try! CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [] }.build()
        c.add(a)                       // member, but still .destructed

        c.selectChild(a)
        XCTAssertNil(c.current, "a non-constructed child must not be selectable")

        try a.construct()
        c.selectChild(a)
        XCTAssertTrue(c.current === a, "a constructed member is selectable")
        XCTAssertTrue(a.isCurrent)
    }

    // ── VMX-026 / ADR-0053 — throwing `setCurrent(_:)` + `canSetCurrent(_:)` ──

    /// VMX-026 — `setCurrent(_:)` throws a catchable `CompositeMembershipError`
    /// on a non-child (was a `preconditionFailure` trap with no predicate). This
    /// is the Swift convergence to the C#/Python/TypeScript catchable throw on a
    /// non-child `Current` assignment (spec/06 §3.1, COMP-009).
    func testVMX026SetCurrentThrowsOnNonChild() throws {
        let a = leaf("a")
        let foreign = leaf("foreign")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        XCTAssertThrowsError(try c.setCurrent(foreign)) { error in
            guard let e = error as? CompositeMembershipError else {
                return XCTFail("expected CompositeMembershipError, got \(error)")
            }
            XCTAssertEqual(e.memberName, "foreign")
            XCTAssertEqual(e.compositeName, "c")
            XCTAssertTrue(e.description.contains("foreign"))
        }
        XCTAssertNil(c.current, "a failed setCurrent must not change the slot")
    }

    /// VMX-026 — `canSetCurrent(_:)` is the pre-flight predicate: true for a
    /// member or `nil`, false for a non-child.
    func testVMX026CanSetCurrentPredicate() throws {
        let a = leaf("a")
        let foreign = leaf("foreign")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        XCTAssertTrue(c.canSetCurrent(a))
        XCTAssertTrue(c.canSetCurrent(nil))
        XCTAssertFalse(c.canSetCurrent(foreign))
    }

    /// VMX-026 — `setCurrent(_:)` accepts a member (selecting it) and `nil`
    /// (clearing it), behaving exactly like the property setter for the valid
    /// cases.
    func testVMX026SetCurrentAcceptsMemberAndNil() throws {
        let a = leaf("a")
        let c = try CompositeVM<ComponentVM>.builder()
            .name("c").withNullServices().children { [a] }.build()
        try c.construct()

        try c.setCurrent(a)
        XCTAssertTrue(c.current === a)
        XCTAssertTrue(a.isCurrent)

        try c.setCurrent(nil)
        XCTAssertNil(c.current)
        XCTAssertFalse(a.isCurrent)
    }
}
