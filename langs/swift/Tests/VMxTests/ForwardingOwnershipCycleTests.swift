//
// ForwardingOwnershipCycleTests.swift — #724 regression tests.
//
// A decorator and its wrapped composite are one ownership identity (spec/09
// §1-2). When only the decorator has a parent, the ancestor walk must climb
// through that parent, so adding the decorator's parent beneath the wrapped
// composite, directly or through a nested group, is rejected as a cycle
// without mutation, as COMP-039 requires.
//

import Foundation
import XCTest
@testable import VMx

final class ForwardingOwnershipCycleTests: XCTestCase {
    private func composite(_ name: String) -> CompositeVM<ComponentVMBase> {
        CompositeVM<ComponentVMBase>(
            name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
    }

    private func children(of container: CompositeVM<ComponentVMBase>) -> [ComponentVMBase] {
        (0..<container.count).map { container.at($0) }
    }

    private func assertCycle(
        _ result: Result<Void, ContainerOwnershipError>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard case .failure(.cycle) = result else {
            return XCTFail("expected .failure(.cycle), got \(result)", file: file, line: line)
        }
    }

    func testAddingTheDecoratorsParentBeneathTheDecoratorIsACycle() throws {
        let outer = composite("outer")
        let inner = composite("inner")
        let forwarding = ForwardingCompositeVM<ComponentVMBase>(inner)
        try outer.addResult(forwarding).get()

        assertCycle(forwarding.addResult(outer))
        assertCycle(inner.addResult(outer))

        XCTAssertEqual(children(of: outer).count, 1)
        XCTAssertTrue(children(of: outer).first === forwarding)
        XCTAssertTrue(children(of: inner).isEmpty)
        XCTAssertTrue(forwarding._transferOwnershipParent === outer)
        XCTAssertNil(outer._transferOwnershipParent)
    }

    func testAddingTheDecoratorsParentToANestedGroupIsACycle() throws {
        let outer = composite("outer")
        let inner = composite("inner")
        let forwarding = ForwardingCompositeVM<ComponentVMBase>(inner)
        let group = GroupVM<ComponentVMBase>(
            name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        try outer.addResult(forwarding).get()
        try forwarding.addResult(group).get()

        assertCycle(group.addResult(outer))

        XCTAssertEqual(group.count, 0)
        XCTAssertTrue(children(of: outer).first === forwarding)
        XCTAssertEqual(children(of: inner).count, 1)
        XCTAssertTrue(children(of: inner).first === group)
        XCTAssertNil(outer._transferOwnershipParent)
    }

    /// #1382 — with `d2` wrapping `d1` wrapping `inner` and `d2` added to
    /// `outer`, the ownership identity resolves through both decorators, so
    /// adding `outer` beneath any layer is a cycle without mutation.
    func testAddingTheOuterDecoratorsParentBeneathNestedDecoratorsIsACycle() throws {
        let outer = composite("outer")
        let inner = composite("inner")
        let d1 = ForwardingCompositeVM<ComponentVMBase>(inner)
        let d2 = ForwardingCompositeVM<ComponentVMBase>(d1)
        try outer.addResult(d2).get()

        for (label, attempt) in [
            ("d2", { d2.addResult(outer) }),
            ("d1", { d1.addResult(outer) }),
            ("inner", { inner.addResult(outer) }),
        ] as [(String, () -> Result<Void, ContainerOwnershipError>)] {
            assertCycle(attempt())
            XCTAssertEqual(inner.count, 0, label)
            XCTAssertNil(outer._transferOwnershipParent, label)
            XCTAssertEqual(children(of: outer).count, 1, label)
            XCTAssertTrue(children(of: outer).first === d2, label)
        }
    }

    /// #1382 — with only the middle decorator `d1` added to `outer`, the
    /// outer decorator `d2` still resolves to the same identity, so adding
    /// `outer` beneath `d2` is a cycle without mutation.
    func testAddingTheMiddleDecoratorsParentBeneathTheOuterDecoratorIsACycle() throws {
        let outer = composite("outer")
        let inner = composite("inner")
        let d1 = ForwardingCompositeVM<ComponentVMBase>(inner)
        let d2 = ForwardingCompositeVM<ComponentVMBase>(d1)
        try outer.addResult(d1).get()

        assertCycle(d2.addResult(outer))

        XCTAssertEqual(inner.count, 0)
        XCTAssertNil(outer._transferOwnershipParent)
        XCTAssertEqual(children(of: outer).count, 1)
        XCTAssertTrue(children(of: outer).first === d1)
    }

    func testAnAggregateSlotHoldingTheDecoratorsParentIsACycle() throws {
        let outer = composite("outer")
        let inner = composite("inner")
        let forwarding = ForwardingCompositeVM<ComponentVMBase>(inner)
        try outer.addResult(forwarding).get()
        let aggregate = AggregateVM1<ComponentVMBase>(
            name: "aggregate", hub: NullMessageHub.INSTANCE,
            dispatcher: ImmediateDispatcher.INSTANCE, factory1: { outer })
        try inner.addResult(aggregate).get()

        XCTAssertThrowsError(try aggregate.construct()) { error in
            guard case ContainerOwnershipError.cycle = error else {
                return XCTFail("expected .cycle, got \(error)")
            }
        }
        XCTAssertNil(aggregate.component1)
        XCTAssertNil(outer._transferOwnershipParent)
    }
}
