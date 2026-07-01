//
// NotebookVMTests — scenario tests for NotebookVM.
//
// Ports NotesShowcase.Tests/ViewModels/NotebookVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - PropertyChangedRecorder

/// Reference-type recorder for `PropertyChangedMessage`s on a hub.
private final class PropertyChangedRecorder {
    var propertyNames: [String] = []
    var cancellables = Set<AnyCancellable>()
}

// MARK: - NotebookVMTests

final class NotebookVMTests: XCTestCase {

    // MARK: - Helpers

    private func build(
        id: String = "id-1",
        name: String = "Work",
        initiallyExpanded: Bool = false
    ) throws -> (NotebookVM, MessageHub) {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let vm = try NotebookVM.builder()
            .name("nb")
            .services(hub: hub, dispatcher: dispatcher)
            .model(NotebookModel(id: id, name: name, parentId: nil))
            .initiallyExpanded(initiallyExpanded)
            .build()
        return (vm, hub)
    }

    /// Subscribes a `PropertyChangedRecorder` to all `PropertyChangedMessage`s on `hub`.
    private func capture(_ hub: MessageHub) -> PropertyChangedRecorder {
        let recorder = PropertyChangedRecorder()
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .sink { [weak recorder] msg in recorder?.propertyNames.append(msg.propertyName) }
            .store(in: &recorder.cancellables)
        return recorder
    }

    // MARK: - Capability set

    func testCapabilitySetIsCorrect() throws {
        let (vm, _) = try build()
        XCTAssertTrue(vm is Selectable)
        XCTAssertTrue(vm is Deselectable)
        XCTAssertTrue(vm is Expandable)
        XCTAssertTrue(vm is Collapsible)
        XCTAssertTrue(vm is ExpansionTogglable)
        XCTAssertTrue(vm is Reconstructable)
        // Capabilities NOT applicable to a notebook:
        XCTAssertFalse(vm is Closable)
        XCTAssertFalse(vm is NewCreatable)
    }

    // MARK: - Expansion

    func testToggleExpansion_emitsIsExpanded_PropertyChangedMessage() throws {
        let (vm, hub) = try build()
        try vm.construct()
        let recorder = capture(hub)

        vm.toggleExpansion()

        XCTAssertTrue(recorder.propertyNames.contains("isExpanded"),
                      "Expected 'isExpanded' in \(recorder.propertyNames)")
        XCTAssertTrue(vm.isExpanded)
    }

    func testExpandAndCollapse_predicatesTrackState() throws {
        let (vm, _) = try build(initiallyExpanded: false)
        try vm.construct()

        XCTAssertTrue(vm.canExpand())
        XCTAssertFalse(vm.canCollapse())
        vm.expand()
        XCTAssertTrue(vm.isExpanded)
        XCTAssertFalse(vm.canExpand())
        XCTAssertTrue(vm.canCollapse())
        vm.collapse()
        XCTAssertFalse(vm.isExpanded)
        // Idempotent: re-collapse is a no-op.
        vm.collapse()
        XCTAssertFalse(vm.isExpanded)
    }

    // MARK: - Model setter

    func testSettingModel_emitsModelAndNotebookName_PropertyChangedMessages() throws {
        let (vm, hub) = try build(name: "Old Name")
        try vm.construct()
        let recorder = capture(hub)

        vm.model = NotebookModel(id: vm.model.id, name: "New Name", parentId: vm.model.parentId)

        XCTAssertTrue(recorder.propertyNames.contains("model"),
                      "Expected 'model' in \(recorder.propertyNames)")
        XCTAssertTrue(recorder.propertyNames.contains("notebookName"),
                      "Expected 'notebookName' in \(recorder.propertyNames)")
        XCTAssertEqual("New Name", vm.notebookName)
    }

    func testSettingModel_toEqualValue_isNoOp() throws {
        let (vm, hub) = try build(name: "Same")
        try vm.construct()
        let recorder = capture(hub)

        // Re-assign the exact same model — equality guard must suppress emission.
        vm.model = vm.model

        XCTAssertFalse(recorder.propertyNames.contains("model"),
                       "Expected no 'model' emission for equal value; got \(recorder.propertyNames)")
    }

    // MARK: - Children

    func testChildren_isEmpty_whenNoGetterWired() throws {
        let (vm, _) = try build()
        XCTAssertTrue(vm.children.isEmpty)
    }

    func testSetChildrenGetter_emitsChildren_PropertyChangedMessage() throws {
        let (vm, hub) = try build()
        try vm.construct()
        let recorder = capture(hub)

        vm.setChildrenGetter({ _ in [] })

        XCTAssertTrue(recorder.propertyNames.contains("children"),
                      "Expected 'children' in \(recorder.propertyNames)")
    }

    // MARK: - Lifecycle

    func testDispose_clearsStatus() throws {
        let (vm, _) = try build()
        try vm.construct()
        vm.dispose()
        XCTAssertEqual(.disposed, vm.status)
    }
}
