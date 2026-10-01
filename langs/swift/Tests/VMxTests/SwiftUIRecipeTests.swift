//
// SwiftUIRecipeTests — compiles and exercises the SwiftUI integration recipe.
//
// The swiftui-recipe region is the exact code shown in
// docs/content/integration/swiftui.md, imports included, and `make docs-check`
// keeps the two identical. The file imports VMx without @testable, so the recipe
// and these tests compile against the public API only. No conformance-ID
// markers (integration recipe).
//
import XCTest

#if canImport(SwiftUI)
// docs-snippet:start swiftui-recipe
import Combine
import SwiftUI
import VMx

struct Note: Equatable {
    var title: String
}

/// Who ends the view model's lifetime.
enum ViewModelOwnership {
    /// The view created the VM: construct it on first appearance and dispose
    /// it exactly once, when SwiftUI releases the adapter.
    case owned
    /// A parent owns the VM: the view observes it and never changes its
    /// lifecycle.
    case borrowed
}

/// Bridges a VMx view model into SwiftUI. Appearance never ends the VM's
/// lifetime, because a view that disappears may appear again.
final class ViewModelAdapter<Model>: ObservableObject {
    let vm: ComponentVMOf<Model>
    let ownership: ViewModelOwnership
    /// A lifecycle failure for the host to show; never swallowed.
    @Published private(set) var lifecycleError: (any Error)?
    private var cancellables: Set<AnyCancellable> = []

    init(_ vm: ComponentVMOf<Model>, ownership: ViewModelOwnership) {
        self.vm = vm
        self.ownership = ownership
        vm.propertyChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }

    /// Call from `.onAppear`. Constructing an already constructed VM is a
    /// no-op, so repeated appearances are safe.
    func appeared() {
        guard ownership == .owned, lifecycleError == nil else { return }
        do {
            try vm.construct()
        } catch {
            lifecycleError = error
        }
    }

    deinit {
        cancellables.removeAll()
        if ownership == .owned {
            vm.dispose()
        }
    }
}

struct NoteView: View {
    @StateObject private var adapter: ViewModelAdapter<Note>
    private let save: any Command

    /// `save` is the domain's save command, e.g. from a form or workspace VM.
    init(vm: ComponentVMOf<Note>, ownership: ViewModelOwnership, save: any Command) {
        _adapter = StateObject(wrappedValue: ViewModelAdapter(vm, ownership: ownership))
        self.save = save
    }

    var body: some View {
        VStack {
            if let error = adapter.lifecycleError {
                Text("Could not open this note: \(String(describing: error))")
            }
            Text(adapter.vm.model.title)
            Button("Save") { save.execute() }
                .disabled(!save.canExecute())
        }
        .onAppear { adapter.appeared() }
    }
}
// docs-snippet:end swiftui-recipe

final class SwiftUIRecipeTests: XCTestCase {
    private func makeNote(
        _ title: String = "draft",
        hub: MessageHub = MessageHub(),
        onConstruct: @escaping () -> Void = {}
    ) throws -> ComponentVMOf<Note> {
        try ComponentVMOf<Note>.builder()
            .name("note-\(title)")
            .model(Note(title: title))
            .modelEquals(==)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .onConstruct { onConstruct() }
            .build()
    }

    private func disposals(of vm: ComponentVMOf<Note>, on hub: MessageHub) -> (() -> Int, AnyCancellable) {
        var count = 0
        let subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .filter { $0.senderObject === vm && $0.status == .disposed }
            .sink { _ in count += 1 }
        return ({ count }, subscription)
    }

    func testOwnedAdapterSurvivesAppearDisappearReappearWithoutReconstructing() throws {
        var constructs = 0
        let vm = try makeNote(onConstruct: { constructs += 1 })
        let adapter = ViewModelAdapter(vm, ownership: .owned)

        adapter.appeared()   // .onAppear
        // .onDisappear: no lifecycle action, the view may come back.
        adapter.appeared()   // .onAppear again

        XCTAssertEqual(vm.status, .constructed)
        XCTAssertEqual(constructs, 1)
        XCTAssertNil(adapter.lifecycleError)
    }

    func testOwnedAdapterDisposesOnceAndBorrowedAdapterNever() throws {
        let hub = MessageHub()
        let owned = try makeNote("owned", hub: hub)
        let borrowed = try makeNote("borrowed", hub: hub)
        try borrowed.construct()   // the parent's responsibility
        let (ownedDisposals, ownedSubscription) = disposals(of: owned, on: hub)
        let (borrowedDisposals, borrowedSubscription) = disposals(of: borrowed, on: hub)

        do {
            let ownedAdapter = ViewModelAdapter(owned, ownership: .owned)
            let borrowedAdapter = ViewModelAdapter(borrowed, ownership: .borrowed)
            withExtendedLifetime((ownedAdapter, borrowedAdapter)) {
                for _ in 0..<2 {
                    ownedAdapter.appeared()
                    borrowedAdapter.appeared()
                }
                XCTAssertEqual(ownedDisposals(), 0)
            }
        }   // SwiftUI releases both adapters

        XCTAssertEqual(owned.status, .disposed)
        XCTAssertEqual(ownedDisposals(), 1)
        XCTAssertEqual(borrowed.status, .constructed)
        XCTAssertEqual(borrowedDisposals(), 0)
        withExtendedLifetime((ownedSubscription, borrowedSubscription)) {}
    }

    func testSaveRunsTheSuppliedCommandAndLeavesSelectionUnchanged() throws {
        let first = try makeNote("first")
        let second = try makeNote("second")
        let parent = try CompositeVM<ComponentVMOf<Note>>.builder()
            .name("notes").withNullServices().children { [first, second] }.build()
        try parent.construct()
        first.selectCommand.execute()
        XCTAssertTrue(parent.current === first)
        var saves = 0
        let save = RelayCommand.builder().task { saves += 1 }.build()
        _ = NoteView(vm: second, ownership: .borrowed, save: save)

        save.execute()   // what NoteView's Save button runs

        XCTAssertEqual(saves, 1)
        XCTAssertTrue(parent.current === first, "Save must not select a sibling")
    }

    func testAnIllegalConstructIsCaughtAndLeavesTheVmSettled() throws {
        let vm = try makeNote()
        vm.dispose()   // constructing a disposed VM is an illegal transition

        // docs-snippet:start swiftui-throwing-lifecycle
        do {
            try vm.construct()
        } catch let error as StatusTransitionError {
            // Recover — the VM is left in its prior settled state, not crashed.
            print("illegal lifecycle transition: \(error)")
        }
        // docs-snippet:end swiftui-throwing-lifecycle

        XCTAssertEqual(vm.status, .disposed)
    }

    func testConstructionFailureReachesTheHostAndDisposalDoesNotMaskIt() throws {
        let vm = try makeNote()
        vm.dispose()   // e.g. a parent already ended the VM's lifetime
        let adapter = ViewModelAdapter(vm, ownership: .owned)

        adapter.appeared()
        vm.dispose()   // later cleanup is a no-op

        XCTAssertTrue(adapter.lifecycleError is StatusTransitionError)
        XCTAssertEqual(vm.status, .disposed)
    }
}
#endif
