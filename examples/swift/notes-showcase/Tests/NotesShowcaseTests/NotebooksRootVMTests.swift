//
// NotebooksRootVMTests — scenario tests for NotebooksRootVM.
//
// Ports NotesShowcase.Tests/ViewModels/NotebooksRootVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - NotebooksRootVMTests

final class NotebooksRootVMTests: XCTestCase {

    // MARK: - Helpers

    private func makeRepo(
        loadAllDelay: TimeInterval = 0,
        addNotebookDelay: TimeInterval = 0
    ) -> InMemoryNoteRepository {
        InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: loadAllDelay,
            addNotebookDelay: addNotebookDelay
        )
    }

    private func buildVM(repo: InMemoryNoteRepository) throws -> NotebooksRootVM {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        return try NotebooksRootVM.builder()
            .name("root")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .build()
    }

    /// Waits (via cooperative yields) until `condition()` returns `true` or
    /// the attempt limit is exhausted. Used for fire-and-forget async paths.
    private func waitUntil(
        _ condition: @escaping () -> Bool,
        attempts: Int = 50
    ) async {
        for _ in 0..<attempts {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    // MARK: - Capability conformances

    func testImplementsNewCreatableAndReconstructable() throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        XCTAssertTrue(vm is NewCreatable)
        XCTAssertTrue(vm is Reconstructable)
    }

    // MARK: - populate

    func testPopulateLoadsAllNotebooksAndAssignsRoots() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()

        try await vm.populate()

        // SeedData has 5 notebooks total.
        XCTAssertEqual(5, vm.all.count)
        // 4 root notebooks (nb-specs is a child of nb-work).
        XCTAssertEqual(4, vm.roots.count)
        // nb-specs is a child of nb-work via parentId.
        guard let work = vm.all.first(where: { $0.model.id == "nb-work" }) else {
            return XCTFail("nb-work not found after populate")
        }
        let specsChildren = vm.childrenOf(work)
        XCTAssertEqual(1, specsChildren.count)
        XCTAssertEqual("nb-specs", specsChildren[0].model.id)
    }

    // MARK: - addNotebook

    func testAddNotebookEmitsTreeStructureChangedMessageAndAppends() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()

        var observed: [TreeStructureChangedMessage] = []
        var cancellables = Set<AnyCancellable>()
        vm.hub.messages
            .compactMap { $0 as? TreeStructureChangedMessage }
            .sink { observed.append($0) }
            .store(in: &cancellables)

        try await vm.addNotebook(parentId: nil, name: "Inbox")

        XCTAssertFalse(observed.isEmpty, "Expected at least one TreeStructureChangedMessage")
        XCTAssertTrue(vm.walk().contains(where: { $0.model.name == "Inbox" }),
                      "Expected 'Inbox' in walk() after addNotebook")
    }

    // MARK: - current

    func testCurrentSetterRoundTripAndIdempotent() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()

        let first = vm.roots[0]
        vm.current = first
        XCTAssertTrue(vm.current === first)

        // Idempotent: setting the same reference is a no-op.
        vm.current = first
        XCTAssertTrue(vm.current === first)

        // Clear.
        vm.current = nil
        XCTAssertNil(vm.current)
    }

    // MARK: - addNotebookCommand

    func testAddNotebookCommandExecutesWhenConstructed() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()
        let before = vm.all.count

        try await vm.addNotebookCommand.executeAsync()

        XCTAssertTrue(vm.all.count > before,
                      "Expected at least one new notebook after addNotebookCommand")
    }

    // MARK: - Children accessor

    func testAfterPopulateEachNotebookResolvesChildrenViaParentId() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()

        guard let work  = vm.all.first(where: { $0.model.id == "nb-work" }),
              let specs = vm.all.first(where: { $0.model.id == "nb-specs" }) else {
            return XCTFail("nb-work / nb-specs not found")
        }

        // Specs must appear in Work's children.
        XCTAssertTrue(work.children.contains { $0 === specs },
                      "Expected nb-specs in nb-work.children")
        XCTAssertEqual(1, work.children.count)
        // Leaf notebooks (no children) return an empty list.
        XCTAssertTrue(specs.children.isEmpty)
    }

    // MARK: - Notification posting

    func testAddNotebookPublishesNotebookAddedNotificationWhenHubWired() async throws {
        let repo = makeRepo()
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let notifHub = NotificationHub()
        defer { notifHub.dispose() }

        var observed: [VMx.Notification] = []
        var cancellables = Set<AnyCancellable>()
        notifHub.pending
            .sink { snapshot in
                for n in snapshot where !observed.contains(where: { $0 === n }) {
                    observed.append(n)
                }
            }
            .store(in: &cancellables)

        let vm = try NotebooksRootVM.builder()
            .name("root")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .notificationHub(notifHub)
            .build()
        try vm.construct()
        try await vm.populate()

        try await vm.addNotebook(parentId: nil, name: "Inbox")

        // The notification posts via a detached Task (awaiting
        // NotificationHub.post would suspend until the toast resolves), so
        // wait briefly for its arrival.
        await waitUntil {
            observed.contains(where: { $0.message.contains("Notebook added") && $0.message.contains("Inbox") })
        }
        XCTAssertTrue(
            observed.contains(where: { $0.message.contains("Notebook added") && $0.message.contains("Inbox") }),
            "Expected 'Notebook added: \"Inbox\"' notification; got: \(observed.map(\.message))"
        )
    }

    func testAddNotebookWithParentIdAppearsUnderParentChildren() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()

        guard let work = vm.all.first(where: { $0.model.id == "nb-work" }) else {
            return XCTFail("nb-work not found")
        }
        let beforeCount = work.children.count

        try await vm.addNotebook(parentId: "nb-work", name: "Subspecs")

        guard let added = vm.all.first(where: { $0.model.name == "Subspecs" }) else {
            return XCTFail("Subspecs not found after addNotebook")
        }
        XCTAssertEqual("nb-work", added.model.parentId)
        XCTAssertTrue(work.children.contains { $0 === added },
                      "Expected Subspecs in nb-work.children")
        XCTAssertEqual(beforeCount + 1, work.children.count)
    }

    // MARK: - PropertyChanged raises

    func testPopulateRaisesPropertyChangedForRoots() async throws {
        // Regression: without this raise, an already-bound view that's wired
        // before populate() completes never refreshes.
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()

        var raisedProps: [String] = []
        var cancellables = Set<AnyCancellable>()
        vm.hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak vm] m in m.sender === vm }
            .sink { raisedProps.append($0.propertyName) }
            .store(in: &cancellables)

        try await vm.populate()

        XCTAssertTrue(raisedProps.contains("roots"),
                      "Expected 'roots' in raised property names; got \(raisedProps)")
    }

    func testAddNotebookRootLevelRaisesPropertyChangedForRoots() async throws {
        let repo = makeRepo()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        try await vm.populate()

        var raisedProps: [String] = []
        var cancellables = Set<AnyCancellable>()
        vm.hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak vm] m in m.sender === vm }
            .sink { raisedProps.append($0.propertyName) }
            .store(in: &cancellables)

        try await vm.addNotebook(parentId: nil, name: "Fresh Root")

        XCTAssertTrue(raisedProps.contains("roots"),
                      "Expected 'roots' in raised property names; got \(raisedProps)")
    }
}
