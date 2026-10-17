//
// NotesShowcaseApp — @main composition root for the Notes Showcase SwiftUI app.
//
// Mirrors the C# App.axaml.cs composition order:
//   1. Build InMemoryNoteRepository with SeedData
//   2. Build WorkspaceVM (MessageHub + NotificationHub + DefaultDispatcher +
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

private final class AppTransferBox<Value>: @unchecked Sendable {
    let value: Value

    init(_ value: Value) {
        self.value = value
    }
}

// MARK: - AppState

/// Holds the root `WorkspaceVM` and its derived `ThemeAdapter` for the
/// lifetime of the application window. Injected via `.environmentObject`.
final class AppState: ObservableObject {
    let workspace: WorkspaceVM
    let themeAdapter: ThemeAdapter
    private var hostSubscriptions = Set<AnyCancellable>()

    init() {
        let repo = InMemoryNoteRepository(seed: SeedData.build())
        // Use DefaultDispatcher so foreground-marshalled work arrives on the
        // main thread regardless of which async continuation fires scheduleForeground.
        let workspace = try! WorkspaceVM.builder()
            .repository(repo)
            .dispatcher(DefaultDispatcher())
            .dialogService(AppKitDialogService())
            .build()
        self.workspace = workspace
        self.themeAdapter = ThemeAdapter(themeVM: workspace.theme)

        // Fire-and-forget async construct: populates notebooks, selects first
        // root, binds notes view. The UI binds to live properties as each step
        // completes — startup latency mirrors the C# async construct path. A
        // failure surfaces as an error notification, as in the C# showcase.
        let transferableWorkspace = AppTransferBox(workspace)
        Task { [transferableWorkspace] in
            await transferableWorkspace.value.constructReportingFailure()
        }

        // Notification lifespans run on a virtual clock; advance it in real
        // time so toasts auto-dismiss in the running app.
        let clock = workspace.notificationClock
        Timer.publish(every: 1, on: .main, in: .common)
            .autoconnect()
            .sink { _ in clock.advance(by: .seconds(1)) }
            .store(in: &hostSubscriptions)
        // Closing the app disposes the workspace, as in the C# host.
        NotificationCenter.default
            .publisher(for: NSApplication.willTerminateNotification)
            .sink { _ in workspace.dispose() }
            .store(in: &hostSubscriptions)
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
