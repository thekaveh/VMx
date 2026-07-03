//
// FilteredCompositeVMTests.swift — COMP-028..037.
//
import XCTest
@testable import VMx

final class FilteredCompositeVMTests: XCTestCase {
    private func child(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder().name(name).withNullServices().build()
    }

    private func source(_ names: String...) throws -> CompositeVM<ComponentVM> {
        let vm = try CompositeVM<ComponentVM>.builder()
            .name("source")
            .withNullServices()
            .children { [] }
            .build()
        for name in names { vm.add(try child(name)) }
        return vm
    }

    /// COMP-028 — filtered visible projection.
    func testCOMP028FilteredVisibleProjection() throws {
        let sut = try FilteredCompositeVM(source("alpha", "beta")) { $0.name.contains("a") }
        XCTAssertEqual(sut.visible.map(\.name), ["alpha", "beta"])
    }

    /// COMP-029 — visible count.
    func testCOMP029VisibleCount() throws {
        let sut = try FilteredCompositeVM(source("alpha", "bee")) { $0.name.contains("a") }
        XCTAssertEqual(sut.visibleCount, 1)
    }

    /// COMP-030 — current maps to visible domain.
    func testCOMP030CurrentMapsToVisibleDomain() throws {
        let src = try source("alpha", "bee")
        let sut = FilteredCompositeVM(src) { $0.name.contains("a") }
        sut.current = sut.visible[0]
        XCTAssertTrue(sut.current === src.at(0))
    }

    /// COMP-031 — predicate change recomputes projection.
    func testCOMP031PredicateChangeRecomputesProjection() throws {
        let sut = try FilteredCompositeVM(source("alpha", "bee")) { $0.name.contains("a") }
        sut.setPredicate { $0.name.contains("e") }
        XCTAssertEqual(sut.visible.map(\.name), ["bee"])
    }

    /// COMP-032 — source mutation reconciles projection.
    func testCOMP032SourceMutationReconcilesProjection() throws {
        let src = try source("alpha")
        let sut = FilteredCompositeVM(src) { $0.name.contains("z") }
        src.add(try child("zulu"))
        XCTAssertEqual(sut.visible.map(\.name), ["zulu"])
    }

    /// COMP-033 — cursor policies.
    func testCOMP033CursorPolicies() throws {
        let src = try source("alpha", "bee")
        let snap = FilteredCompositeVM(src) { _ in true }
        snap.current = src.at(1)
        snap.setPredicate { $0.name == "alpha" }
        XCTAssertTrue(snap.current === src.at(0))

        let clear = FilteredCompositeVM(src, cursorPolicy: .clear) { _ in true }
        clear.current = src.at(1)
        clear.setPredicate { $0.name == "alpha" }
        XCTAssertNil(clear.current)
    }

    /// COMP-034 — visible navigation.
    func testCOMP034VisibleNavigation() throws {
        let sut = try FilteredCompositeVM(source("alpha", "bee", "gamma")) { $0.name.contains("a") }
        sut.current = sut.visible[0]
        sut.moveToNextVisible()
        XCTAssertTrue(sut.current === sut.visible[1])
        sut.moveToPreviousVisible()
        XCTAssertTrue(sut.current === sut.visible[0])
    }

    /// COMP-035 — dispose stops source subscription.
    func testCOMP035DisposeStopsSourceSubscription() throws {
        let src = try source("alpha")
        let sut = FilteredCompositeVM(src) { _ in true }
        sut.dispose()
        src.add(try child("bee"))
        XCTAssertEqual(sut.visible.map(\.name), ["alpha"])
    }

    /// COMP-036 — scored filter sorts by score with stable ties.
    func testCOMP036ScoredFilterSortsByScoreWithStableTies() throws {
        let sut = try ScoredFilteredCompositeVM(source("alpha", "bee", "ax")) {
            $0.name.hasPrefix("a") ? 1 : nil
        }
        XCTAssertEqual(sut.visible.map(\.name), ["alpha", "ax"])
    }

    /// COMP-037 — scored filter recomputes order when scores change.
    func testCOMP037ScoredFilterRecomputesOrderWhenScoresChange() throws {
        var weights: [String: Double] = ["alpha": 1, "bee": 2]
        let sut = try ScoredFilteredCompositeVM(source("alpha", "bee")) { weights[$0.name] }
        XCTAssertEqual(sut.visible.map(\.name), ["bee", "alpha"])
        weights["alpha"] = 3
        sut.refreshScores()
        XCTAssertEqual(sut.visible.map(\.name), ["alpha", "bee"])
    }
}
