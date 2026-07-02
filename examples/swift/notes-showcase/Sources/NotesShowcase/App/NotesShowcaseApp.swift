//
// NotesShowcaseApp — @main composition root for the Notes Showcase SwiftUI app.
//
// Mirrors the C# App.axaml.cs composition order:
//   1. Build InMemoryNoteRepository with SeedData
//   2. Build WorkspaceVM (MessageHub + NotificationHub + MainQueueDispatcher +
//      AppKitDialogService for native file/confirm/notify dialogs)
//   3. Fire async construct (fire-and-forget)
//   4. Build ThemeAdapter from workspace.theme and apply synchronously
//   5. Inject workspace (via AppState) + ThemeAdapter as .environmentObject
//
// SwiftUI constraint: a `@main struct` and a top-level `main.swift` cannot
// coexist — the placeholder `main.swift` was deleted when this file was added.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

// MARK: - MainQueueDispatcher

/// A foreground dispatcher that marshals UI work to `DispatchQueue.main`,
/// running synchronously when already on the main thread.
///
/// Replaces `ImmediateDispatcher.INSTANCE` (which runs work synchronously on
/// whichever thread called it — correct for tests but not for a real app whose
/// async task continuations may resume off the main thread).
final class MainQueueDispatcher: Dispatcher {
    static let INSTANCE = MainQueueDispatcher()
    private init() {}

    func scheduleForeground(_ work: @escaping () -> Void) {
        if Thread.isMainThread {
            work()
        } else {
            DispatchQueue.main.async { work() }
        }
    }

    func scheduleBackground(_ work: @escaping () -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { work() }
    }
}

// MARK: - AppState

/// Holds the root `WorkspaceVM` and its derived `ThemeAdapter` for the
/// lifetime of the application window. Injected via `.environmentObject`.
final class AppState: ObservableObject {
    let workspace: WorkspaceVM
    let themeAdapter: ThemeAdapter

    init() {
        let repo = InMemoryNoteRepository(seed: SeedData.build())
        // Use MainQueueDispatcher so foreground-marshalled work arrives on the
        // main thread regardless of which async continuation fires scheduleForeground.
        let workspace = try! WorkspaceVM.builder()
            .repository(repo)
            .dispatcher(MainQueueDispatcher.INSTANCE)
            .dialogService(AppKitDialogService())
            .build()
        self.workspace = workspace
        self.themeAdapter = ThemeAdapter(themeVM: workspace.theme)

        // Fire-and-forget async construct: populates notebooks, selects first
        // root, binds notes view. The UI binds to live properties as each step
        // completes — startup latency mirrors the C# async construct path.
        Task {
            try? await workspace.constructAsync()
        }
    }
}

// MARK: - App

@main
struct NotesShowcaseApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appState)
                .environmentObject(appState.themeAdapter)
        }
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
