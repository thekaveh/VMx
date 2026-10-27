// Starter smoke test: construct, edit, command, error and dispose.
//
// Run it with `swift run NotesSmoke` from the package root. It is an
// executable, not an XCTest target, so it runs with the Command Line Tools
// alone. It also checks that the resolved VMx version equals the exact pin in
// Package.swift, so a partial upgrade fails here first.

import Combine
import Foundation
import Notes
import VMx

var failures = 0

func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    if condition() {
        print("ok - \(message)")
    } else {
        failures += 1
        print("not ok - \(message)")
    }
}

/// Wait up to two seconds for a condition that an async task completes.
func eventually(_ condition: () -> Bool) async -> Bool {
    for _ in 0..<200 {
        if condition() { return true }
        try? await Task.sleep(nanoseconds: 10_000_000)
    }
    return condition()
}

// Version: the resolved package equals the `exact:` pin in Package.swift.
let manifest = try String(contentsOfFile: "Package.swift", encoding: .utf8)
let pin = manifest.range(of: #"exact: "[0-9]+\.[0-9]+\.[0-9]+""#, options: .regularExpression)
    .map { String(manifest[$0].dropFirst(8).dropLast()) }
check(pin == VMxVersion.current, "VMx \(VMxVersion.current) equals the Package.swift pin \(pin ?? "-")")

let store = InMemoryNoteStore()
let app = try NotebookApp(store: store, seed: [
    NoteModel(id: "1", title: "Groceries", body: "Milk, eggs"),
    NoteModel(id: "2", title: "Ideas", body: "Write a starter"),
])
var changes: [String] = []
let subscription = app.hub.messages
    .compactMap { $0 as? PropertyChangedMessage }
    .sink { changes.append($0.propertyName) }
var notes: [NoteVM] = []

do {
    defer {
        subscription.cancel()
        app.dispose()
    }

    // Construct: the first construct() builds and constructs the children.
    check(!app.saveCurrent.canExecute(), "save is disabled before construct")
    try app.start()
    notes = app.notebook.snapshot()
    check(app.notebook.isConstructed, "notebook is constructed")
    check(notes.count == 2 && notes.allSatisfy(\.isConstructed), "both notes are constructed")
    check(app.notebook.current?.model.id == "1", "the first note is current")

    // Edit: assigning a new model publishes a change on the hub.
    try app.renameCurrent("Groceries for Monday")
    check(app.notebook.current?.modeledHint == "Groceries for Monday", "the hint tracks the model")
    check(changes.contains("model"), "the hub carried a model change")

    // Command: the predicate tracks the title, and the task saves the note.
    try app.renameCurrent("   ")
    check(!app.saveCurrent.canExecute(), "save is disabled for a blank title")
    try app.renameCurrent("Groceries for Monday")
    check(app.saveCurrent.canExecute(), "save is enabled for a valid title")
    try await app.saveCurrent.executeAsync()
    check(store.get("1")?.title == "Groceries for Monday", "the store saved the first note")

    // Error, inline: executeAsync throws the store's error.
    try app.select("2")
    try app.renameCurrent("Groceries for Monday")
    do {
        try await app.saveCurrent.executeAsync()
        check(false, "a duplicate title throws")
    } catch is NoteConflictError {
        check(store.get("2") == nil, "a duplicate title throws and saves nothing")
    }

    // Error, fire-and-forget: execute() routes the fault to `errors`.
    app.saveCurrent.execute()
    let routed = await eventually { app.errors.count == 1 }
    check(routed && app.errors.first is NoteConflictError, "execute() routes the error to errors")

    // Recover: fix the title and save again.
    try app.renameCurrent("Ideas for Monday")
    try await app.saveCurrent.executeAsync()
    check(store.count == 2, "the store saved both notes after the fix")
}

// Dispose: terminal for every VM and the command; idempotent for the app.
check(app.notebook.status == .disposed, "the notebook is disposed")
check(notes.allSatisfy { $0.status == .disposed }, "every note is disposed")
check(!app.saveCurrent.canExecute(), "save is disabled after dispose")
do {
    try app.notebook.construct()
    check(false, "construct() after dispose throws StatusTransitionError")
} catch is StatusTransitionError {
    check(true, "construct() after dispose throws StatusTransitionError")
}
app.dispose()

if failures > 0 {
    print("FAILED: \(failures) check(s)")
    exit(1)
}
print("PASSED: construct, edit, command, error and dispose")
