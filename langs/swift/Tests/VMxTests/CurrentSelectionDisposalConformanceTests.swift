//
// Composite selection and container walks with disposed children
// (spec/02-lifecycle.md §6, spec/06-composite-vm.md §3, §4.3 rules 8 and 9,
// §5; ADR-0188, ADR-0189).
//
// Claimed IDs: COMP-050, COMP-051, COMP-052, LIFE-022.
//
// The regression tests below cover the cases one conformance ID does not:
// a background child disposed while the walk waits for it, a selection from
// another thread or an asynchronous delivery while the composite is
// `.destructing`, a forwarding decorator as the current child, and a
// re-selection of the disposed child from `onCurrentChanged(nil)`.
//
import Combine
import Foundation
import XCTest
@testable import VMx

/// Records each hub message as `"sender:status"` or `"sender.property"`, in
/// order.
private final class HubLog {
    private let lock = NSLock()
    private var entries: [String] = []
    private var subscription: AnyCancellable?

    init(_ hub: MessageHubProtocol) {
        subscription = hub.messages.sink { [weak self] message in
            guard let self else { return }
            let entry: String?
            if let status = message as? ConstructionStatusChangedMessage {
                entry = "\(status.senderName):\(status.status)"
            } else if let property = message as? PropertyChangedMessage {
                entry = "\(property.senderName).\(property.propertyName)"
            } else {
                entry = nil
            }
            if let entry { self.lock.withLock { self.entries.append(entry) } }
        }
    }

    var all: [String] { lock.withLock { entries } }
    func count(_ entry: String) -> Int { all.filter { $0 == entry }.count }
    func clear() { lock.withLock { entries.removeAll() } }
}

/// A leaf whose hooks walk its members with the child-transition helper.
private final class MemberWalkingLeaf: ComponentVMBase {
    var members: [ComponentVMBase] = []

    override func _onConstruct() throws {
        try super._onConstruct()
        try _transitionChildren(members, construct: true)
    }

    override func _onDestruct() throws {
        try super._onDestruct()
        try _transitionChildren(members, construct: false)
    }
}

/// A leaf whose `_onDispose()` runs a test action.
private final class DisposeHookLeaf: ComponentVM {
    var onCleanup: (() -> Void)?

    override func _onDispose() {
        onCleanup?()
        super._onDispose()
    }
}

private func isNonMember(_ error: Error) -> Bool {
    guard let membership = error as? CompositeMembershipError else { return false }
    return membership.reason == .nonMember
}

final class CurrentSelectionDisposalConformanceTests: XCTestCase {
    private func vm(
        _ name: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher = ImmediateDispatcher.INSTANCE,
        background: Bool = false,
        onConstruct: (() throws -> Void)? = nil,
        onDestruct: (() throws -> Void)? = nil
    ) -> ComponentVMBase {
        ComponentVMBase(
            name: name, hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct, background: background
        )
    }

    // ── COMP-050 ─────────────────────────────────────────────────────────

    /// COMP-050 — Disposing the current child clears `current` once. The
    /// child's `isCurrent` becomes false with no child message, the disposed
    /// child is not selectable, and the composite's own dispose cascade does
    /// not clear `current`.
    func testComp050DisposingCurrentChildClearsCurrent() throws {
        let hub = MessageHub()
        var changes: [String?] = []
        let p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: { changes.append($0?.name) }
        )
        let a = vm("a", hub: hub)
        let b = vm("b", hub: hub)
        p.add(a)
        p.add(b)
        try p.construct()
        try p.setCurrent(a)
        changes.removeAll()
        let log = HubLog(hub)

        a.dispose()

        XCTAssertNil(p.current)
        XCTAssertFalse(a.isCurrent)
        XCTAssertEqual(log.count("p.current"), 1)
        XCTAssertEqual(changes, [nil])
        let disposedAt = try XCTUnwrap(log.all.firstIndex(of: "a:disposed"))
        XCTAssertFalse(log.all[disposedAt...].contains("a.isCurrent"))

        XCTAssertFalse(p.canSelectComponent(a))
        XCTAssertFalse(p.canSetCurrent(a))
        XCTAssertThrowsError(try p.setCurrent(a)) { XCTAssertTrue(isNonMember($0)) }
        XCTAssertNil(p.current)

        try p.setCurrent(b)
        log.clear()
        p.dispose()

        XCTAssertEqual(b.status, .disposed)
        XCTAssertEqual(log.count("p.current"), 0)
    }

    /// COMP-050 (regression, #1317) — a forwarding decorator as the current
    /// child: disposing the decorator clears `current`.
    func testComp050DisposingForwardingDecoratorClearsCurrent() throws {
        let hub = MessageHub()
        let p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        let inner = ComponentVMOf<Int>(
            name: "inner", initialModel: 0, hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        let decorator = ForwardingComponentVM(inner)
        p.add(decorator)
        try p.construct()
        try p.setCurrent(decorator)
        XCTAssertTrue(decorator.isCurrent)

        decorator.dispose()

        XCTAssertEqual(decorator.status, .disposed)
        XCTAssertNil(p.current)
        XCTAssertFalse(decorator.isCurrent)
    }

    /// COMP-050 (regression, #1317) — `onCurrentChanged(nil)` of the dispose
    /// clear selects the disposed child again: the selection is refused with
    /// the non-member error, and `current` stays `nil`.
    func testComp050ReselectingDisposedChildFromCallbackIsRefused() throws {
        let hub = MessageHub()
        var p: CompositeVM<ComponentVMBase>!
        var a: ComponentVMBase!
        var errors: [Error] = []
        var nils = 0
        p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: { value in
                guard value == nil else { return }
                nils += 1
                do { try p.setCurrent(a) } catch { errors.append(error) }
            }
        )
        a = vm("a", hub: hub)
        p.add(a)
        try p.construct()
        try p.setCurrent(a)

        a.dispose()

        XCTAssertEqual(nils, 1)
        XCTAssertEqual(errors.count, 1)
        XCTAssertTrue(errors.first.map(isNonMember) ?? false)
        XCTAssertNil(p.current)
    }

    /// COMP-050 (regression, #1383) — the construct walk's assignment of a
    /// disposed pick is a silent no-op.
    func testComp050InitialSelectorPickingDisposedChildIsSilent() throws {
        let hub = MessageHub()
        let a = vm("a", hub: hub)
        let b = vm("b", hub: hub)
        let p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            currentSelector: { children in children.last }
        )
        p.add(a)
        p.add(b)
        b.dispose()

        try p.construct()

        XCTAssertEqual(p.status, .constructed)
        XCTAssertNil(p.current)
    }

    // ── COMP-051 ─────────────────────────────────────────────────────────

    /// COMP-051 — A selection while the composite is `.destructing` changes
    /// nothing and raises nothing, from `onCurrentChanged(nil)` and from a
    /// child's destruct hook, through `setCurrent(_:)`, the `current`
    /// property setter, `selectComponent(_:)` and the child `select()`. A
    /// `nil` clear still commits. The destruct phase of `reconstruct()`
    /// behaves the same.
    func testComp051SelectionWhileDestructingChangesNothing() throws {
        let hub = MessageHub()
        var p: CompositeVM<ComponentVMBase>!
        var a: ComponentVMBase!
        var b: ComponentVMBase!
        var c: ComponentVMBase!
        var errors: [Error] = []
        var canSelectC: [Bool] = []
        var canSetC: [Bool] = []
        var changes: [String?] = []
        p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: { value in
                changes.append(value?.name)
                guard value == nil, p.status == .destructing else { return }
                do { try p.setCurrent(b) } catch { errors.append(error) }
                p.current = b
                do { try p.selectComponent(b) } catch { errors.append(error) }
                b.select()
            }
        )
        a = vm("a", hub: hub)
        b = vm("b", hub: hub, onDestruct: {
            do { try p.setCurrent(c) } catch { errors.append(error) }
            p.current = c
            c.select()
            canSelectC.append(p.canSelectComponent(c))
            canSetC.append(p.canSetCurrent(c))
            do { try p.setCurrent(a) } catch { errors.append(error) }
            p.current = a
            do { try p.setCurrent(nil) } catch { errors.append(error) }
            p.current = nil
        })
        c = vm("c", hub: hub)
        p.add(a)
        p.add(b)
        p.add(c)
        try p.construct()
        try p.setCurrent(a)
        changes.removeAll()
        let log = HubLog(hub)

        try p.destruct()

        XCTAssertTrue(errors.isEmpty, "\(errors)")
        XCTAssertEqual(p.status, .destructed)
        XCTAssertEqual([a, b, c].map(\.status), [.destructed, .destructed, .destructed])
        XCTAssertNil(p.current)
        XCTAssertEqual(canSelectC, [false])
        XCTAssertEqual(canSetC, [false])
        XCTAssertEqual(log.count("p.current"), 1)
        XCTAssertEqual(changes, [nil])

        try p.construct()
        try p.setCurrent(a)
        changes.removeAll()
        canSelectC.removeAll()
        canSetC.removeAll()
        log.clear()

        try p.reconstruct()

        XCTAssertTrue(errors.isEmpty, "\(errors)")
        XCTAssertEqual(p.status, .constructed)
        XCTAssertNil(p.current)
        XCTAssertEqual(canSelectC, [false])
        XCTAssertEqual(log.count("p.current"), 1)
        XCTAssertEqual(changes, [nil])
    }

    /// COMP-051 (regression, #1425) — another thread sets `current` while
    /// the destruct walk runs: `destruct()` returns with `current` `nil`.
    func testComp051SelectionFromAnotherThreadWhileDestructingIsIgnored() throws {
        let hub = MessageHub()
        var p: CompositeVM<ComponentVMBase>!
        var b: ComponentVMBase!
        var threadError: Error?
        let done = DispatchSemaphore(value: 0)
        let a = vm("a", hub: hub, onDestruct: {
            DispatchQueue.global().async {
                do { try p.setCurrent(b) } catch { threadError = error }
                done.signal()
            }
            XCTAssertEqual(done.wait(timeout: .now() + hangGuard), .success)
        })
        b = vm("b", hub: hub)
        p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        p.add(b)
        p.add(a)
        try p.construct()

        try p.destruct()

        XCTAssertNil(threadError)
        XCTAssertEqual(p.status, .destructed)
        XCTAssertNil(p.current)
        XCTAssertFalse(b.isCurrent)
    }

    /// COMP-051 (regression, #1425) — with `asyncSelection`, a selection
    /// scheduled before `destruct()` and delivered while the composite is
    /// `.destructing` is dropped.
    func testComp051AsyncDeliveryWhileDestructingIsDropped() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = vm("a", hub: hub, dispatcher: dispatcher)
        let p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: dispatcher,
            onDestruct: { dispatcher.flushForeground() },
            asyncSelection: true
        )
        p.add(a)
        try p.construct()
        dispatcher.flushForeground()

        try p.setCurrent(a)
        XCTAssertNil(p.current)
        try p.destruct()
        dispatcher.flushForeground()

        XCTAssertEqual(p.status, .destructed)
        XCTAssertNil(p.current)
        XCTAssertFalse(a.isCurrent)
    }

    // ── COMP-052 ─────────────────────────────────────────────────────────

    /// COMP-052 — A refused child `select()` or `deselect()` changes nothing
    /// and raises nothing: a member that is not Constructed, a deselect of a
    /// child that is not current, a select inside the caller's own
    /// uncommitted membership transaction, and a select while disposal of
    /// the composite is deferred.
    func testComp052RefusedChildSelectAndDeselectChangeNothing() throws {
        let hub = MessageHub()
        var p: CompositeVM<ComponentVMBase>!
        var a: ComponentVMBase!
        var c: ComponentVMBase!
        p = CompositeVM<ComponentVMBase>(
            name: "p", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: { value in
                guard let value, value === c else { return }
                p.dispose()
                a.select()
            },
            autoConstructOnAdd: true
        )
        a = vm("a", hub: hub)
        let b = vm("b", hub: hub)
        c = vm("c", hub: hub)
        try p.construct()
        p.add(a)
        p.add(b)
        p.add(c)
        try b.destruct()
        XCTAssertEqual([a, b, c].map(\.status), [.constructed, .destructed, .constructed])
        let log = HubLog(hub)

        b.select()
        XCTAssertNil(p.current)
        a.deselect()
        XCTAssertNil(p.current)
        let d = vm("d", hub: hub, onConstruct: { a.select() })
        p.add(d)
        XCTAssertEqual(d.status, .constructed)
        XCTAssertNil(p.current)

        try p.setCurrent(c)

        XCTAssertTrue(p.current === c)
        XCTAssertFalse(a.isCurrent)
        XCTAssertEqual(log.count("p.current"), 1)
        XCTAssertEqual(p.status, .disposed)
    }

    // ── LIFE-022 ─────────────────────────────────────────────────────────

    /// LIFE-022 — A composite and a group that hold a directly disposed
    /// child destruct, construct and reconstruct. The walks skip the
    /// disposed child, and the container keeps it as a member.
    func testLife022ContainerWalksSkipDisposedChild() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let a = vm("a", hub: hub)
            let b = vm("b", hub: hub)
            let box: ComponentVMBase
            let members: () -> [ComponentVMBase]
            if kind == "composite" {
                let composite = CompositeVM<ComponentVMBase>(
                    name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
                )
                composite.add(a)
                composite.add(b)
                box = composite
                members = { composite.snapshot() }
            } else {
                let group = GroupVM<ComponentVMBase>(
                    name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
                )
                group.add(a)
                group.add(b)
                box = group
                members = { group.snapshot() }
            }
            try box.construct()
            let log = HubLog(hub)

            b.dispose()
            XCTAssertNoThrow(try box.destruct(), kind)

            XCTAssertEqual(box.status, .destructed, kind)
            XCTAssertEqual(a.status, .destructed, kind)
            XCTAssertEqual(b.status, .disposed, kind)
            XCTAssertTrue(members().contains { $0 === b }, kind)

            XCTAssertNoThrow(try box.construct(), kind)
            XCTAssertEqual(box.status, .constructed, kind)
            XCTAssertEqual(a.status, .constructed, kind)
            XCTAssertEqual(b.status, .disposed, kind)

            XCTAssertNoThrow(try box.reconstruct(), kind)
            XCTAssertEqual(box.status, .constructed, kind)
            XCTAssertEqual(a.status, .constructed, kind)

            // No lifecycle operation reached the disposed child.
            let disposedAt = try XCTUnwrap(log.all.firstIndex(of: "b:disposed"), kind)
            XCTAssertFalse(log.all[(disposedAt + 1)...].contains { $0.hasPrefix("b:") }, kind)
        }
    }

    /// LIFE-022 — A child disposed while the composite or group is
    /// `.destructed` is skipped by the next construct.
    func testLife022ChildDisposedWhileDestructedIsSkipped() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let a = vm("a", hub: hub)
            let b = vm("b", hub: hub)
            let box: ComponentVMBase
            if kind == "composite" {
                let composite = CompositeVM<ComponentVMBase>(
                    name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
                )
                composite.add(a)
                composite.add(b)
                box = composite
            } else {
                let group = GroupVM<ComponentVMBase>(
                    name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
                )
                group.add(a)
                group.add(b)
                box = group
            }
            try box.construct()
            try box.destruct()

            b.dispose()
            XCTAssertNoThrow(try box.construct(), kind)

            XCTAssertEqual(box.status, .constructed, kind)
            XCTAssertEqual(a.status, .constructed, kind)
            XCTAssertEqual(b.status, .disposed, kind)
        }
    }

    /// LIFE-022 — An `AggregateVM2` with a directly disposed slot destructs,
    /// and its next construct replaces the slots from the factories. A
    /// reconstruct with a disposed slot ends in `.constructed`.
    func testLife022AggregateWithDisposedSlot() throws {
        let hub = MessageHub()
        var made = 0
        let box = AggregateVM2<ComponentVMBase, ComponentVMBase>(
            name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            factory1: { () -> ComponentVMBase in
                made += 1
                return ComponentVMBase(
                    name: "a\(made)", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            },
            factory2: { () -> ComponentVMBase in
                made += 1
                return ComponentVMBase(
                    name: "b\(made)", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            }
        )
        try box.construct()
        let a = try XCTUnwrap(box.component1)
        let b = try XCTUnwrap(box.component2)

        b.dispose()
        XCTAssertNoThrow(try box.destruct())
        XCTAssertEqual(box.status, .destructed)
        XCTAssertEqual(a.status, .destructed)
        XCTAssertEqual(b.status, .disposed)

        XCTAssertNoThrow(try box.construct())
        XCTAssertEqual(box.status, .constructed)
        let a2 = try XCTUnwrap(box.component1)
        let b2 = try XCTUnwrap(box.component2)
        XCTAssertFalse(a2 === a)
        XCTAssertFalse(b2 === b)
        XCTAssertEqual(a2.status, .constructed)
        XCTAssertEqual(b2.status, .constructed)

        b2.dispose()
        XCTAssertNoThrow(try box.reconstruct())
        XCTAssertEqual(box.status, .constructed)
        XCTAssertEqual(box.component2?.status, .constructed)
    }

    /// LIFE-022 — The child-transition helper skips a disposed member in
    /// both walks, and the leaf reaches the target status.
    func testLife022HelperSkipsDisposedMember() throws {
        let hub = MessageHub()
        let leaf = MemberWalkingLeaf(
            name: "leaf", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        let m1 = vm("m1", hub: hub)
        let m2 = vm("m2", hub: hub)
        leaf.members = [m1, m2]
        m2.dispose()

        XCTAssertNoThrow(try leaf.construct())
        XCTAssertEqual(leaf.status, .constructed)
        XCTAssertEqual(m1.status, .constructed)

        XCTAssertNoThrow(try leaf.destruct())
        XCTAssertEqual(leaf.status, .destructed)
        XCTAssertEqual(m1.status, .destructed)
        XCTAssertEqual(m2.status, .disposed)
    }

    /// LIFE-022 (regression, #1383) — a background child that another
    /// `dispose()` reaches while the walk waits for it ends the wait as a
    /// success: the walk goes on, and the container reaches its target.
    func testLife022WalkStopsWaitingForChildDisposedDuringWait() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = vm("a", hub: hub, dispatcher: dispatcher, background: true)
        let b = vm("b", hub: hub, dispatcher: dispatcher)
        let p = CompositeVM<ComponentVMBase>(name: "p", hub: hub, dispatcher: dispatcher)
        p.add(a)
        p.add(b)

        try p.construct()
        XCTAssertEqual(p.status, .constructing)
        XCTAssertEqual(a.status, .constructing)

        a.dispose()
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }

        XCTAssertEqual(a.status, .disposed)
        XCTAssertEqual(b.status, .constructed)
        XCTAssertEqual(p.status, .constructed)
    }

    /// LIFE-022 (regression) — a child in its inline dispose cascade is not
    /// `.disposed` yet, so a walk does not skip it. The walk's `destruct()`
    /// on that child fails under LIFE-021, and the parent rolls back, as in
    /// the other flavors (spec/02 §6, ADR-0189).
    func testLife022WalkDoesNotSkipChildInItsDisposeCascade() throws {
        let hub = MessageHub()
        let leaf = DisposeHookLeaf(
            name: "leaf", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        let box = GroupVM<ComponentVMBase>(
            name: "box", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        box.add(leaf)
        let outer = GroupVM<ComponentVMBase>(
            name: "outer", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        outer.add(box)
        try outer.construct()
        var caught: Error?
        var boxStatus: ConstructionStatus?
        leaf.onCleanup = {
            boxStatus = box.status
            do { try outer.destruct() } catch { caught = error }
        }

        box.dispose()

        XCTAssertEqual(boxStatus, .constructed)
        let error = try XCTUnwrap(caught as? StatusTransitionError)
        XCTAssertEqual(error.currentStatus, .disposed)
        XCTAssertEqual(outer.status, .constructed)
        XCTAssertEqual(box.status, .disposed)
    }
}
