//
// CompositeSelectionTests.swift
//
// Conformance IDs: COMP-008, COMP-011 — throwing component selection.
// Phase 3 Increment 6 (swift-parity-inc6).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

final class CompositeSelectionTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder()
            .name(name)
            .withNullServices()
            .build()
    }

    /// COMP-008 — canSelectComponent returns false for non-children, and
    /// selectComponent throws CompositeMembershipError on a non-member.
    func testComp008CanSelectComponentReturnsFalseForNonChild() throws {
        let vmA = leaf("vmA")
        let vmB = leaf("vmB")
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("c")
            .withNullServices()
            .children { [vmA] }
            .build()
        try composite.construct()

        XCTAssertFalse(composite.canSelectComponent(vmB))
        XCTAssertThrowsError(try composite.selectComponent(vmB)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }
    }

    /// COMP-011 — deselectComponent throws CompositeMembershipError when the
    /// argument is not the current selection; current remains unchanged.
    func testComp011DeselectComponentThrowsWhenNotCurrent() throws {
        let vmA = leaf("vmA")
        let vmB = leaf("vmB")
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("c")
            .withNullServices()
            .children { [vmA, vmB] }
            .build()
        try composite.construct()
        try composite.selectComponent(vmA)

        XCTAssertThrowsError(try composite.deselectComponent(vmB)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }
        XCTAssertTrue(composite.current === vmA, "current must remain vmA")
    }
}
