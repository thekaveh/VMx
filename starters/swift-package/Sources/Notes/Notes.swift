// A small notebook built from VMx primitives.
//
// - Each note is a `ComponentVMOf<NoteModel>` leaf.
// - The notebook is a `CompositeVM` that owns the notes and tracks `current`.
// - `saveCurrent` is an `AsyncRelayCommand` that writes the current note to a
//   store. `executeAsync()` throws store errors to the caller; the
//   fire-and-forget `execute()` routes them to `errors`.
//
// Replace `InMemoryNoteStore` with your own persistence adapter.

import Combine
import Foundation
import VMx

public struct NoteModel: Equatable {
    public let id: String
    public let title: String
    public let body: String

    public init(id: String, title: String, body: String) {
        self.id = id
        self.title = title
        self.body = body
    }
}

public typealias NoteVM = ComponentVMOf<NoteModel>

/// The store rejects a save when another note already uses the title.
public struct NoteConflictError: Error, CustomStringConvertible {
    public let title: String

    public var description: String { "another note already uses the title \"\(title)\"" }
}

public final class InMemoryNoteStore {
    private let lock = NSLock()
    private var notes: [String: NoteModel] = [:]

    public init() {}

    public func save(_ note: NoteModel) throws {
        lock.lock()
        defer { lock.unlock() }
        if notes.values.contains(where: { $0.id != note.id && $0.title == note.title }) {
            throw NoteConflictError(title: note.title)
        }
        notes[note.id] = note
    }

    public func get(_ id: String) -> NoteModel? {
        lock.lock()
        defer { lock.unlock() }
        return notes[id]
    }

    public var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return notes.count
    }
}

public enum NotebookError: Error {
    case noSelection
    case unknownNote(String)
}

public final class NotebookApp {
    public let hub = MessageHub()
    public let notebook: CompositeVM<NoteVM>
    public let saveCurrent: AsyncRelayCommand
    public private(set) var errors: [Error] = []
    private var cancellables: [AnyCancellable] = []
    private var disposed = false

    public init(store: InMemoryNoteStore, seed: [NoteModel]) throws {
        // `ImmediateDispatcher` runs foreground and background work on the
        // calling thread. A SwiftUI or AppKit host uses `DefaultDispatcher()`.
        let dispatcher = ImmediateDispatcher.INSTANCE
        let hub = self.hub
        let notes = try seed.map { model in
            try NoteVM.builder()
                .name("note-\(model.id)")
                .model(model)
                .modeledHinter { $0.title }
                .services(hub: hub, dispatcher: dispatcher)
                .build()
        }
        let notebook = try CompositeVM<NoteVM>.builder()
            .name("notebook")
            .services(hub: hub, dispatcher: dispatcher)
            .children { notes }
            .build()
        self.notebook = notebook

        // Re-evaluate `canExecute` whenever any VM on this hub reports a change.
        let changes = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .map { _ in () }
            .eraseToAnyPublisher()
        saveCurrent = AsyncRelayCommand.builder()
            .predicate {
                guard notebook.isConstructed, let current = notebook.current else { return false }
                return !current.model.title.trimmingCharacters(in: .whitespaces).isEmpty
            }
            .task {
                if let current = notebook.current { try store.save(current.model) }
            }
            .triggers(changes)
            .build()
        cancellables.append(saveCurrent.errors.sink { [weak self] error in
            self?.errors.append(error)
        })
    }

    /// Construct the notebook (and its notes) and select the first note.
    public func start() throws {
        try notebook.construct()
        notebook.current = notebook.snapshot().first
    }

    /// Replace the current note's title. Models are immutable values.
    public func renameCurrent(_ title: String) throws {
        guard let current = notebook.current else { throw NotebookError.noSelection }
        let model = current.model
        current.model = NoteModel(id: model.id, title: title, body: model.body)
    }

    public func select(_ id: String) throws {
        guard let note = notebook.snapshot().first(where: { $0.model.id == id }) else {
            throw NotebookError.unknownNote(id)
        }
        notebook.current = note
    }

    /// Dispose subscriptions and the command first, then the VMs, then the hub.
    public func dispose() {
        if disposed { return }
        disposed = true
        cancellables.forEach { $0.cancel() }
        cancellables.removeAll()
        saveCurrent.dispose()
        notebook.dispose()
        hub.dispose()
    }
}
