// Run the notebook flow once: construct, edit, save, recover from an error,
// and dispose. Replace this file with your own host (CLI, SwiftUI or AppKit).

import Notes
import VMx

let store = InMemoryNoteStore()
let app = try NotebookApp(store: store, seed: [
    NoteModel(id: "1", title: "Groceries", body: "Milk, eggs"),
    NoteModel(id: "2", title: "Ideas", body: "Write a starter"),
])

do {
    defer {
        app.dispose()
        print("disposed: \(app.notebook.status == .disposed)")
    }
    print("VMx \(VMxVersion.current)")
    try app.start()
    print("constructed: \(app.notebook.isConstructed), current: \(app.notebook.current?.model.title ?? "-")")

    try app.renameCurrent("Groceries for Monday")
    try await app.saveCurrent.executeAsync()
    print("saved: \(store.get("1")?.title ?? "-")")

    // Error path: the store rejects a duplicate title. `executeAsync()` throws,
    // so the caller handles the error inline and the app keeps running.
    try app.select("2")
    try app.renameCurrent("Groceries for Monday")
    do {
        try await app.saveCurrent.executeAsync()
    } catch let error as NoteConflictError {
        print("rejected: \(error)")
        try app.renameCurrent("Ideas for Monday")
        try await app.saveCurrent.executeAsync()
        print("saved after fix: \(store.get("2")?.title ?? "-")")
    }
}
