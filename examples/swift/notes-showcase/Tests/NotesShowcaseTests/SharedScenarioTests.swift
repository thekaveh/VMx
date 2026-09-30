//
// SharedScenarioTests — shared Notes scenario `notes-lifecycle-v1` (#346).
//
// Runs examples/notes-showcase-scenario.json through this showcase's view
// models and compares every step's semantic snapshot with the shared
// expectation. The C#, Python, and TypeScript showcases run the same file
// through their own adapters.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

private let flavor = "swift"

private final class ScenarioAdapter {
    let workspace: WorkspaceVM
    private var events: [String] = []
    private var savedCompleted = false
    private var subscriptions = Set<AnyCancellable>()

    init() throws {
        let repo = InMemoryNoteRepository(
            seed: SeedData.build(),
            loadAllDelay: 0,
            loadNotesDelay: 0,
            saveNoteDelay: 0,
            deleteNoteDelay: 0,
            addNotebookDelay: 0,
            exportDelay: 0
        )
        let hub = MessageHub()
        workspace = try WorkspaceVM.builder().repository(repo).messageHub(hub).build()
        hub.messages
            .compactMap { $0 as? ThemeChangedMessage }
            .sink { [unowned self] message in
                self.events.append("theme:\(message.previous.name)->\(message.current.name)")
            }
            .store(in: &subscriptions)
    }

    /// Runs one step; returns "invalid" when the step's operation was rejected.
    func run(_ step: [String: Any]) async throws -> String? {
        let action = step["action"] as? String ?? ""
        switch action {
        case "construct":
            try await workspace.constructAsync()
            workspace.noteForm.onSaved
                .sink(
                    receiveCompletion: { [unowned self] _ in self.savedCompleted = true },
                    receiveValue: { [unowned self] model in self.events.append("saved:\(model.title)") }
                )
                .store(in: &subscriptions)
        case "create_note":
            try await workspace.newNoteCommand.executeAsync()
        case "select_note":
            workspace.notesView.current = workspace.notesView.inner.at(step["index"] as? Int ?? -1)
        case "edit_title":
            workspace.noteForm.title = step["title"] as? String ?? ""
        case "save":
            try await workspace.noteForm.approveAsync()
        case "delete_selected_declined":
            // The default dialog service declines every confirmation.
            let current = try XCTUnwrap(workspace.notesView.current)
            let command = try XCTUnwrap(current.deleteCommand as? ConfirmationDecoratorCommand)
            try await command.executeAsync()
        case "set_theme":
            // Swift commands cannot throw, and `setThemeCommand` discards a
            // rejected preset; `applyPreset` is Swift's throwing surface, as in
            // the THEME-002 test (declared in the scenario's normalization).
            do {
                try workspace.theme.applyPreset(step["theme"] as? String ?? "")
            } catch {
                return "invalid"
            }
        case "dispose":
            workspace.dispose()
        default:
            XCTFail("unknown scenario action \(action)")
        }
        return nil
    }

    func snapshot(error: String?) throws -> [String: Any] {
        if savedCompleted {
            return ["events": drain(), "error": error ?? NSNull(), "disposed": true]
        }
        let view = workspace.notesView
        let form = workspace.noteForm
        let formSnapshot: Any = form.hasBoundNote
            ? ["title": form.title, "dirty": form.isDirty, "valid": form.isValid] as [String: Any]
            : NSNull()
        return [
            "notebook": view.boundNotebookId ?? NSNull(),
            "notes": view.inner.snapshot().map { $0.model.title },
            "selected": view.current?.model.title ?? NSNull(),
            "form": formSnapshot,
            "theme": try workspace.theme.currentTheme.value.name,
            "events": drain(),
            "error": error ?? NSNull(),
            "disposed": false,
        ]
    }

    private func drain() -> [String] {
        defer { events.removeAll() }
        return events
    }
}

private func canonical(_ value: Any) -> String {
    guard let data = try? JSONSerialization.data(
        withJSONObject: value, options: [.sortedKeys, .fragmentsAllowed]
    ) else { return "\(value)" }
    return String(decoding: data, as: UTF8.self)
}

private func differences(_ expected: [String: Any], _ actual: [String: Any]) -> [String] {
    expected.keys.sorted().compactMap { key in
        let want = canonical(expected[key] ?? NSNull())
        guard let value = actual[key] else { return "\(key): expected \(want), got <absent>" }
        let got = canonical(value)
        return want == got ? nil : "\(key): expected \(want), got \(got)"
    }
}

final class SharedScenarioTests: XCTestCase {
    func testSharedNotesScenarioMatchesTheSemanticExpectation() async throws {
        let examples = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // NotesShowcaseTests
            .deletingLastPathComponent()  // Tests
            .deletingLastPathComponent()  // notes-showcase
            .deletingLastPathComponent()  // swift
            .deletingLastPathComponent()  // examples
        let data = try Data(contentsOf: examples.appendingPathComponent("notes-showcase-scenario.json"))
        let scenario = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let id = scenario["id"] as? String ?? "?"
        let steps = try XCTUnwrap(scenario["steps"] as? [[String: Any]])

        let adapter = try ScenarioAdapter()
        var failures: [String] = []
        for (offset, step) in steps.enumerated() {
            let error = try await adapter.run(step)
            let expected = try XCTUnwrap(step["expect"] as? [String: Any])
            let action = step["action"] as? String ?? "?"
            for difference in differences(expected, try adapter.snapshot(error: error)) {
                failures.append("\(id) [\(flavor)] step \(offset + 1) \(action): \(difference)")
            }
        }
        XCTAssertTrue(failures.isEmpty, failures.joined(separator: "\n"))
    }
}
