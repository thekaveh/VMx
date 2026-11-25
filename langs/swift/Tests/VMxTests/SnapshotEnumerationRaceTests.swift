//
// SnapshotEnumerationRaceTests.swift — the Swift readers that list a
// CompositeVM or GroupVM read its membership once, through `snapshot()`, so a
// removal on another thread cannot trap them (ADR-0187, #1921).
//
// Claimed IDs: none. This file adds no conformance ID. It covers the five
// readers that enumerate a container: `walk`, `walkExpanded` and `find` (through
// `childComponents`), `FilteredCompositeVM.orderedVisible()`,
// `ScoredFilteredCompositeVM.orderedVisible()` and
// `PagedComposition(sourceComposite:)`.
//
// Each stress test runs a mutating thread that removes and re-adds the last
// child for a bounded number of cycles. The reading side runs on the test
// thread. Before the fix, a reader can take `count`, lose the last child to the
// mutating thread, and then call `at(_:)` past the end. That traps and ends the
// whole test process, so the run fails. The mutating thread is joined with a
// bounded wait, so a deadlock fails the test instead of hanging it.
//
// NOTE: `swift test` needs full Xcode (XCTest); CI runs it on macos-15.
//
import Foundation
import XCTest
@testable import VMx

final class SnapshotEnumerationRaceTests: XCTestCase {
    /// Children in each stress container. The last child is the one removed.
    private let childCount = 8
    /// Mutating-thread cycles. Each cycle is one remove and one add.
    private let cycles = 1_000
    /// Reads on the test thread in each stress test.
    private let reads = 1_000
    /// The bound on the wait for the mutating thread, in seconds.
    private let bound: TimeInterval = 30

    private var stressNames: [String] { (0..<childCount).map { "c\($0)" } }

    private func leaf(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder().name(name).withNullServices().build()
    }

    private func composite(_ names: [String]) throws -> CompositeVM<ComponentVM> {
        let vm = try CompositeVM<ComponentVM>.builder()
            .name("parent").withNullServices().children { [] }.build()
        for name in names { vm.add(try leaf(name)) }
        return vm
    }

    private func group(_ names: [String]) throws -> GroupVM<ComponentVM> {
        let vm = try GroupVM<ComponentVM>.builder()
            .name("parent").withNullServices().children { [] }.build()
        for name in names { vm.add(try leaf(name)) }
        return vm
    }

    /// Starts the mutating thread. It removes `victim` and adds it back for
    /// `cycles` cycles, then signals the returned semaphore. A refused change
    /// is possible (ADR-0187), so each result is ignored: the readers below
    /// accept any state that a whole change can leave.
    private func startMutator(
        victim: ComponentVM,
        remove: @escaping (ComponentVM) -> Bool,
        add: @escaping (ComponentVM) -> Result<Void, ContainerOwnershipError>
    ) -> DispatchSemaphore {
        let finished = DispatchSemaphore(value: 0)
        let cycles = self.cycles
        DispatchQueue.global(qos: .userInitiated).async {
            for _ in 0..<cycles {
                _ = remove(victim)
                _ = add(victim)
            }
            finished.signal()
        }
        return finished
    }

    /// Reads `walk`, `walkExpanded` and `find` on `root` while the mutating
    /// thread changes its membership. A change is atomic, so each walk sees
    /// the root with either every child or every child but the victim.
    private func stressTreeReads(
        root: ComponentVMBase,
        victim: ComponentVM,
        remove: @escaping (ComponentVM) -> Bool,
        add: @escaping (ComponentVM) -> Result<Void, ContainerOwnershipError>
    ) throws {
        let finished = startMutator(victim: victim, remove: remove, add: add)
        var outOfRange = 0
        for _ in 0..<reads {
            let walked = try walk(root).count
            let expanded = try walkExpanded(root).count
            let found = try find(root) { $0 === victim }
            // Root plus children: `childCount` or `childCount + 1` nodes.
            if !(childCount...(childCount + 1)).contains(walked) { outOfRange += 1 }
            if !(childCount...(childCount + 1)).contains(expanded) { outOfRange += 1 }
            if !(found == nil || found === victim) { outOfRange += 1 }
        }
        XCTAssertEqual(finished.wait(timeout: .now() + bound), .success, "mutating thread did not finish")
        XCTAssertEqual(outOfRange, 0, "a walk or find read a membership that no whole change leaves")
        XCTAssertEqual(try walk(root).count, childCount + 1, "the last cycle re-adds the victim")
    }

    // MARK: - walk, walkExpanded and find

    func testWalkAndFindSurviveConcurrentRemovalFromComposite() throws {
        let root = try composite(stressNames)
        let victim = root.at(childCount - 1)
        try stressTreeReads(
            root: root, victim: victim,
            remove: { root.remove($0) },
            add: { root.addResult($0) }
        )
    }

    func testWalkAndFindSurviveConcurrentRemovalFromGroup() throws {
        let root = try group(stressNames)
        let victim = root.at(childCount - 1)
        try stressTreeReads(
            root: root, victim: victim,
            remove: { root.remove($0) },
            add: { root.addResult($0) }
        )
    }

    // MARK: - Filtered and scored views

    func testFilteredVisibleSurvivesConcurrentRemoval() throws {
        let source = try composite(stressNames)
        let victim = source.at(childCount - 1)
        // Subscribed before the concurrent phase, so the final recompute on the
        // mutating thread sees the final membership.
        let view = FilteredCompositeVM(source) { _ in true }
        let finished = startMutator(
            victim: victim,
            remove: { source.remove($0) },
            add: { source.addResult($0) }
        )
        var outOfRange = 0
        for _ in 0..<reads {
            let count = view.orderedVisible().count
            if !((childCount - 1)...childCount).contains(count) { outOfRange += 1 }
        }
        XCTAssertEqual(finished.wait(timeout: .now() + bound), .success, "mutating thread did not finish")
        XCTAssertEqual(outOfRange, 0, "orderedVisible read a membership that no whole change leaves")
        XCTAssertEqual(view.visible.count, childCount)
        view.dispose()
    }

    func testScoredVisibleSurvivesConcurrentRemoval() throws {
        let source = try composite(stressNames)
        let victim = source.at(childCount - 1)
        // A pure function of the child: the child "c3" scores 3.
        let view = ScoredFilteredCompositeVM(source) { child -> Double? in
            Double(child.name.dropFirst()) ?? 0
        }
        let finished = startMutator(
            victim: victim,
            remove: { source.remove($0) },
            add: { source.addResult($0) }
        )
        var outOfRange = 0
        var unsorted = 0
        for _ in 0..<reads {
            let ordered = view.orderedVisible()
            let scores = ordered.map { Double($0.name.dropFirst()) ?? 0 }
            if !((childCount - 1)...childCount).contains(ordered.count) { outOfRange += 1 }
            // Descending by score; every score is distinct, so the order is strict.
            if zip(scores, scores.dropFirst()).contains(where: { $0 < $1 }) { unsorted += 1 }
        }
        XCTAssertEqual(finished.wait(timeout: .now() + bound), .success, "mutating thread did not finish")
        XCTAssertEqual(outOfRange, 0, "orderedVisible read a membership that no whole change leaves")
        XCTAssertEqual(unsorted, 0, "orderedVisible returned items out of score order")
        XCTAssertEqual(view.visible.count, childCount)
        view.dispose()
    }

    // MARK: - PagedComposition

    func testPagedCompositionInitSurvivesConcurrentRemoval() throws {
        let source = try composite(stressNames)
        let victim = source.at(childCount - 1)
        let finished = startMutator(
            victim: victim,
            remove: { source.remove($0) },
            add: { source.addResult($0) }
        )
        // Each page is kept until the mutating thread is joined, so no page is
        // released while its subscriber can still run.
        var pages: [PagedComposition<ComponentVM>] = []
        for _ in 0..<(reads / 10) {
            pages.append(PagedComposition(sourceComposite: source))
        }
        XCTAssertEqual(finished.wait(timeout: .now() + bound), .success, "mutating thread did not finish")
        // A page created during the change may keep the membership it read
        // before the last change, so only the range is checked.
        let outOfRange = pages.filter { !((childCount - 1)...childCount).contains($0.items.count) }.count
        XCTAssertEqual(outOfRange, 0, "PagedComposition read a membership that no whole change leaves")
        pages.forEach { $0.dispose() }
    }

    // MARK: - Scorer replacement

    /// Scores a child by a table the test fills in. On the first call only, the
    /// probe runs `onFirstCall` once, after the flag `armed` is set.
    private final class ScoreProbe {
        var scores: [ObjectIdentifier: Double] = [:]
        var armed = false
        var onFirstCall: (() -> Void)?

        func score(_ child: ComponentVM) -> Double? {
            if armed, let hook = onFirstCall {
                onFirstCall = nil
                hook()
            }
            return scores[ObjectIdentifier(child)] ?? 0
        }
    }

    /// The scorer replaces a later child while the view is scoring the first
    /// child. The result must list the children from before the replacement,
    /// sorted by each child's own score. A later read of `at(_:)` would pick up
    /// the replacement, and `d` (score 10) would come first.
    func testScorerReplacementKeepsPreReplacementSnapshot() throws {
        let source = try composite(["a", "b", "c"])
        let a = source.at(0)
        let b = source.at(1)
        let c = source.at(2)
        let d = try leaf("d")
        let probe = ScoreProbe()
        probe.scores = [
            ObjectIdentifier(a): 1,
            ObjectIdentifier(b): 2,
            ObjectIdentifier(c): 3,
            ObjectIdentifier(d): 10,
        ]
        let view = ScoredFilteredCompositeVM(source) { probe.score($0) }
        probe.onFirstCall = { _ = source.replaceResult(at: 2, with: d) }
        probe.armed = true
        let result = view.orderedVisible()
        probe.armed = false
        XCTAssertTrue(source.at(2) === d, "the scorer replacement did not run")
        XCTAssertEqual(result.map(\.name), ["c", "b", "a"])
        view.dispose()
    }
}
