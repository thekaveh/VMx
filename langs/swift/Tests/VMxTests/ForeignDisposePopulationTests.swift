//
// ForeignDisposePopulationTests.swift — LIFE-015 and #1369.
//
// Factory population is a post-hook container action. A container whose
// construct hook a foreign `dispose()` superseded does not call its children
// factory, and its `construct()` returns without an error (spec/02 §2.4,
// ADR-0218 rule 5). An `add()` during disposal still fails. Every wait is
// bounded, so a regression fails instead of hanging.
//
import Combine
import Foundation
import XCTest
@testable import VMx

final class ForeignDisposePopulationTests: XCTestCase {
    /// A thread-safe log and counter.
    private final class Log: @unchecked Sendable {
        private let lock = NSLock()
        private var entries: [String] = []
        private var count = 0
        func append(_ entry: String) { lock.withLock { entries.append(entry) } }
        var all: [String] { lock.withLock { entries } }
        func increment() { lock.withLock { count += 1 } }
        var calls: Int { lock.withLock { count } }
    }

    /// The container under test and its child count.
    private struct Container {
        let vm: ComponentVMBase
        let count: () -> Int
    }

    private func makeContainer(
        _ kind: String,
        hub: MessageHub,
        factoryCalls: Log,
        withChild: Bool,
        hook: @escaping () -> Void
    ) throws -> Container {
        let child = try ComponentVM.builder()
            .name("child").services(hub: hub, dispatcher: NullDispatcher.INSTANCE).build()
        let children: () -> [ComponentVM] = {
            factoryCalls.increment()
            return withChild ? [child] : []
        }
        switch kind {
        case "composite":
            let vm = CompositeVM<ComponentVM>(
                name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE,
                childrenFactory: children, onConstruct: hook
            )
            return Container(vm: vm, count: { vm.count })
        case "compositeOf":
            let vm = CompositeVMOf<Int, ComponentVM>(
                name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE,
                childrenModels: {
                    factoryCalls.increment()
                    return withChild ? [1] : []
                },
                childModelToChildViewModel: { _ in child },
                onConstruct: hook
            )
            return Container(vm: vm, count: { vm.count })
        default:
            let vm = GroupVM<ComponentVM>(
                name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE,
                childrenFactory: children, onConstruct: hook
            )
            return Container(vm: vm, count: { vm.count })
        }
    }

    /// LIFE-015 — a foreign `dispose()` while the construct hook blocks: the
    /// factory is never called, `construct()` returns without an error, and
    /// the container ends `Disposed` with no children.
    func testForeignDisposeSkipsPopulationAndConstructReturns() throws {
        for kind in ["composite", "compositeOf", "group"] {
            for withChild in [false, true] {
                let label = "\(kind) withChild=\(withChild)"
                let hub = MessageHub()
                let factoryCalls = Log()
                let statuses = Log()
                let entered = DispatchSemaphore(value: 0)
                let release = DispatchSemaphore(value: 0)
                let container = try makeContainer(
                    kind, hub: hub, factoryCalls: factoryCalls, withChild: withChild
                ) {
                    entered.signal()
                    _ = release.wait(timeout: .now() + hangGuard * 2)
                }
                let subscription = hub.messages
                    .compactMap { $0 as? ConstructionStatusChangedMessage }
                    .filter { $0.senderName == kind }
                    .sink { statuses.append("\($0.status)") }
                defer { subscription.cancel() }

                let constructed = DispatchSemaphore(value: 0)
                var constructError: Error?
                DispatchQueue.global().async {
                    do { try container.vm.construct() } catch { constructError = error }
                    constructed.signal()
                }
                XCTAssertEqual(entered.wait(timeout: .now() + hangGuard), .success, label)
                let disposed = DispatchSemaphore(value: 0)
                DispatchQueue.global().async {
                    container.vm.dispose()
                    disposed.signal()
                }
                let deadline = Date().addingTimeInterval(hangGuard)
                while !container.vm._isDisposalRequested() && Date() < deadline { usleep(1_000) }
                XCTAssertTrue(container.vm._isDisposalRequested(), label)
                release.signal()
                XCTAssertEqual(constructed.wait(timeout: .now() + hangGuard), .success, label)
                XCTAssertEqual(disposed.wait(timeout: .now() + hangGuard), .success, label)

                XCTAssertNil(constructError, "\(label): construct() returns without an error")
                XCTAssertEqual(factoryCalls.calls, 0, "\(label): the factory is not called")
                XCTAssertEqual(statuses.all, ["constructing", "disposed"], label)
                XCTAssertEqual(container.count(), 0, label)
                XCTAssertEqual(container.vm.status, .disposed, label)
            }
        }
    }

    /// LIFE-015 — an `add()` during disposal still fails.
    func testAddDuringDisposalStillFails() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let child = try ComponentVM.builder()
                .name("child").services(hub: hub, dispatcher: NullDispatcher.INSTANCE).build()
            let result: Result<Void, ContainerOwnershipError>
            if kind == "composite" {
                let composite = CompositeVM<ComponentVM>(
                    name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE
                )
                composite.dispose()
                result = composite.addResult(child)
            } else {
                let group = GroupVM<ComponentVM>(
                    name: kind, hub: hub, dispatcher: NullDispatcher.INSTANCE
                )
                group.dispose()
                result = group.addResult(child)
            }
            guard case .failure(.attachmentFailed) = result else {
                XCTFail("\(kind): expected attachmentFailed, got \(result)")
                continue
            }
            XCTAssertNil(child._ownershipParent, kind)
        }
    }
}
