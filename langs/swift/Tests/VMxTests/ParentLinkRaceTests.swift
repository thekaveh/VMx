//
// ParentLinkRaceTests.swift — #1546 regression tests.
//
// A container writes a child's parent link (`_parent`, `_ownershipParent`)
// under its own locks, while the child reads the link from `dispose()` and
// from its selection API under its own lifecycle lock or under no lock. The
// link has its own lock, so these accesses never race. The cases run under
// the Swift `thread sanitizer` job, which fails on any data-race report;
// without Thread Sanitizer they check only that the operations finish.
//

import Foundation
import XCTest
@testable import VMx

final class ParentLinkRaceTests: XCTestCase {
    private let rounds = 1_000

    private func leaf(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    /// Runs `first` and `second` on two new threads that start together, and
    /// waits for both.
    private func race(_ first: @escaping () -> Void, _ second: @escaping () -> Void) {
        let start = DispatchGroup()
        start.enter()
        let done = DispatchGroup()
        for body in [first, second] {
            done.enter()
            Thread.detachNewThread {
                start.wait()
                body()
                done.leave()
            }
        }
        start.leave()
        XCTAssertEqual(done.wait(timeout: .now() + hangGuard), .success, "a racing thread hung")
    }

    func testGroupAddAndRemoveDoNotRaceChildDispose() throws {
        for round in 0..<rounds {
            let group = GroupVM<ComponentVM>(
                name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE
            )
            let child = try leaf("child-\(round)")
            race({
                _ = group.addResult(child)
                _ = group.remove(child)
            }, {
                child.dispose()
            })
            group.dispose()
        }
    }

    func testCompositeAddAndRemoveDoNotRaceChildSelection() throws {
        for round in 0..<rounds {
            let composite = CompositeVM<ComponentVM>(
                name: "composite", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE
            )
            let child = try leaf("child-\(round)")
            race({
                _ = composite.addResult(child)
                _ = composite.remove(child)
            }, {
                _ = child.canSelect()
                _ = child.canDeselect()
                child.dispose()
            })
            composite.dispose()
        }
    }

    func testForwardingOwnerLinkDoesNotRaceWrappedDispose() throws {
        for round in 0..<rounds {
            let group = GroupVM<ForwardingComponentVM<String>>(
                name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE
            )
            let wrapped = try ComponentVMOf<String>.builder()
                .name("wrapped-\(round)").model("").withNullServices().build()
            let decorator = ForwardingComponentVM(wrapped)
            race({
                _ = group.addResult(decorator)
                _ = group.remove(decorator)
            }, {
                _ = wrapped.canSelect()
                wrapped.dispose()
            })
            group.dispose()
        }
    }
}
