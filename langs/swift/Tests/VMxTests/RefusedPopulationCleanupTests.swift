// A fixed-slot population that its preflight refuses disposes the candidates
// that nobody owns (spec/08 §2 and §4, ADR-0224, #1324). Swift factories
// cannot throw, so a refused preflight is the only failed population.

import XCTest
@testable import VMx

final class RefusedPopulationCleanupTests: XCTestCase {
    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// A component that a constructed composite owns.
    private func owned(_ name: String) throws -> (ComponentVM, CompositeVM<ComponentVM>) {
        let component = leaf(name)
        let owner = try CompositeVM<ComponentVM>.builder()
            .name("owner").withNullServices().children { [component] }.build()
        try owner.construct()
        XCTAssertEqual(component.status, .constructed)
        return (component, owner)
    }

    private func assertOwned(
        _ component: ComponentVM, by owner: CompositeVM<ComponentVM>,
        file: StaticString = #filePath, line: UInt = #line
    ) {
        XCTAssertEqual(component.status, .constructed, file: file, line: line)
        XCTAssertTrue(component._ownershipParent?.ownershipOwner === owner, file: file, line: line)
        XCTAssertEqual(owner.count, 1, file: file, line: line)
        XCTAssertTrue(owner.snapshot().first === component, file: file, line: line)
    }

    private func assertInconsistentParent(
        _ body: () throws -> Void, file: StaticString = #filePath, line: UInt = #line
    ) {
        XCTAssertThrowsError(try body(), file: file, line: line) { error in
            guard let ownershipError = error as? ContainerOwnershipError,
                  case .inconsistentParent = ownershipError else {
                return XCTFail("expected inconsistentParent, got \(error)", file: file, line: line)
            }
        }
    }

    /// AGG-008 — a refused `construct()` disposes the fresh candidate, keeps
    /// the owned candidate's status and parent, and leaves both slots empty.
    func testRefusedConstructDisposesTheUnownedCandidates() throws {
        let fresh = leaf("fresh")
        let (borrowed, owner) = try owned("borrowed")
        let aggregate = try AggregateVM2<ComponentVM, ComponentVM>.builder()
            .name("aggregate").withNullServices()
            .component1 { fresh }.component2 { borrowed }.build()

        assertInconsistentParent { try aggregate.construct() }

        XCTAssertEqual(fresh.status, .disposed)
        assertOwned(borrowed, by: owner)
        XCTAssertNil(aggregate.component1)
        XCTAssertNil(aggregate.component2)
    }

    /// AGG-008 — a refused `reconstruct()` keeps the old slots and parent
    /// links and disposes the fresh replacement candidate.
    func testRefusedReconstructDisposesTheFreshCandidatesAndKeepsTheOldSlots() throws {
        let first = leaf("first")
        let second = leaf("second")
        let replacement = leaf("replacement")
        let (borrowed, owner) = try owned("borrowed")
        var calls1 = 0
        var calls2 = 0
        let aggregate = try AggregateVM2<ComponentVM, ComponentVM>.builder()
            .name("aggregate").withNullServices()
            .component1 {
                calls1 += 1
                return calls1 == 1 ? first : replacement
            }
            .component2 {
                calls2 += 1
                return calls2 == 1 ? second : borrowed
            }
            .build()
        try aggregate.construct()

        assertInconsistentParent { try aggregate.reconstruct() }

        XCTAssertTrue(aggregate.component1 === first)
        XCTAssertTrue(aggregate.component2 === second)
        for old in [first, second] {
            XCTAssertTrue(old._ownershipParent?.ownershipOwner === aggregate)
            XCTAssertEqual(old.status, .destructed)
        }
        XCTAssertEqual(replacement.status, .disposed)
        XCTAssertNil(replacement._ownershipParent)
        assertOwned(borrowed, by: owner)
    }
}
