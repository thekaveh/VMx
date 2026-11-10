//
// CurrentSelectorLiveMembershipTests.swift — COMP-053 and #1312.
//
// `current(selector)` receives the composite's live membership when the
// selector runs, so it can pick a late child. The pick still goes through
// the walk's assignment: a pick that is not an admitted member is a silent
// no-op (spec/06 §3.2, ADR-0218 rule 2).
//
import Foundation
import XCTest
@testable import VMx

final class CurrentSelectorLiveMembershipTests: XCTestCase {
    /// Runs background hooks and their foreground completions until quiescent.
    private func pump(_ dispatcher: ManualDispatcher) {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// COMP-053 — the selector receives the live membership: a child added
    /// while the composite is `Constructing` is in its input, and the
    /// selector can pick it.
    func testCOMP053SelectorReceivesLiveMembership() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: dispatcher).background(true).build()
        let late = try ComponentVM.builder()
            .name("l").services(hub: hub, dispatcher: dispatcher).build()
        var inputs: [[String]] = []
        let composite = CompositeVM<ComponentVM>(
            name: "composite", hub: hub, dispatcher: dispatcher,
            childrenFactory: { [a] },
            currentSelector: { members in
                inputs.append(members.map(\.name))
                return members.first { $0 === late }
            },
            autoConstructOnAdd: true
        )

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        try composite.addResult(late).get()
        pump(dispatcher)

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertEqual(inputs, [["a", "l"]], "the selector ran once with the live membership")
        XCTAssertTrue(composite.current === late)
        XCTAssertTrue(late.isCurrent)
    }

    /// #1312 — the same holds when the late child is the only child the
    /// selector can pick: the snapshot of the walk did not contain it.
    func testCurrentSelectorSeesLateChild() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: dispatcher).background(true).build()
        let late = try ComponentVM.builder()
            .name("late").services(hub: hub, dispatcher: dispatcher).build()
        let composite = CompositeVM<ComponentVM>(
            name: "composite", hub: hub, dispatcher: dispatcher,
            childrenFactory: { [a] },
            currentSelector: { $0.last },
            autoConstructOnAdd: true
        )

        try composite.construct()
        try composite.addResult(late).get()
        pump(dispatcher)

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertTrue(composite.current === late)
        XCTAssertFalse(a.isCurrent)
    }

    /// #1312 — a pick that is not a member is a silent no-op: the composite
    /// still constructs, and `current` stays `nil`.
    func testCurrentSelectorPickOfUnadmittedChildIsNoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let a = try ComponentVM.builder()
            .name("a").services(hub: hub, dispatcher: dispatcher).build()
        let stranger = try ComponentVM.builder()
            .name("stranger").services(hub: hub, dispatcher: dispatcher).build()
        try stranger.construct()
        let composite = CompositeVM<ComponentVM>(
            name: "composite", hub: hub, dispatcher: dispatcher,
            childrenFactory: { [a] },
            currentSelector: { _ in stranger }
        )

        try composite.construct()
        pump(dispatcher)

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertNil(composite.current)
        XCTAssertFalse(stranger.isCurrent)
    }
}
