//
// RootView — three-pane shell with toolbar, status bar, capability bar, and
//            toast overlay. Mirrors C# Avalonia MainWindow.axaml layout.
//
// Layout (top to bottom):
//   Row 0: Toolbar (commands + theme controls)
//   Row 1: 3-pane body (Notebooks | Notes | Form)
//   Row 2: Status bar
//   Row 3: Capability action bar
//   Overlay: Notification toasts (bottom-trailing)
//
// Child views each own their `@StateObject` bridge adapters (BindableVM etc.);
// RootView just passes the stable VM references from appState.workspace.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @EnvironmentObject private var theme: ThemeAdapter

    var body: some View {
        let workspace = appState.workspace
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                // ── Toolbar ──────────────────────────────────────────────
                ToolbarView(workspace: workspace)
                    .background(theme.pane)

                Divider()

                // ── 3-pane body ──────────────────────────────────────────
                HStack(spacing: 0) {
                    // Left: notebooks tree
                    NotebooksTreeView(vm: workspace.notebooksRoot)
                        .frame(width: 240)
                        .background(theme.pane)

                    Divider()

                    // Centre: notes list
                    NotesListView(vm: workspace.notesView)
                        .background(theme.background)

                    Divider()

                    // Right: note form
                    NoteFormView(vm: workspace.noteForm)
                        .frame(width: 360)
                        .background(theme.pane)
                }

                Divider()

                // ── Global search ────────────────────────────────────────
                GlobalSearchView(vm: workspace.globalSearch)
                    .background(theme.pane)

                Divider()

                // ── Status bar ───────────────────────────────────────────
                StatusBarView(vm: workspace.statusBar)
                    .background(theme.pane)

                Divider()

                // ── Capability action bar ─────────────────────────────────
                CapabilityActionsView(vm: workspace.capabilityActions)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(theme.pane)
            }
            .background(theme.background)

            // ── Toast overlay ─────────────────────────────────────────────
            NotificationsView(vm: workspace.notifications)
        }
        .frame(minWidth: 900, minHeight: 560)
        .background(theme.background)
    }
}

// MARK: - ToolbarView

private struct ToolbarView: View {
    let workspace: WorkspaceVM
    @StateObject private var newNotebookCmd: BindableCommand
    @StateObject private var newNoteCmd: BindableCommand
    @StateObject private var exportCmd: BindableCommand
    @EnvironmentObject private var theme: ThemeAdapter

    init(workspace: WorkspaceVM) {
        self.workspace = workspace
        _newNotebookCmd = StateObject(wrappedValue: BindableCommand(workspace.newNotebookCommand))
        _newNoteCmd     = StateObject(wrappedValue: BindableCommand(workspace.newNoteCommand))
        _exportCmd      = StateObject(wrappedValue: BindableCommand(workspace.exportCommand))
    }

    var body: some View {
        HStack(spacing: 8) {
            Button("+ Notebook") { newNotebookCmd.execute() }
                .disabled(!newNotebookCmd.canExecute)
                .keyboardShortcut("N", modifiers: [.command, .shift])

            Button("+ Note") { newNoteCmd.execute() }
                .disabled(!newNoteCmd.canExecute)
                .keyboardShortcut("n", modifiers: .command)

            Button("Export…") { exportCmd.execute() }
                .disabled(!exportCmd.canExecute)
                .keyboardShortcut("e", modifiers: .command)

            Divider().frame(height: 20)

            ThemeControlsView(themeVM: workspace.theme)

            Spacer()

            Text("VMx Notes Workspace")
                .foregroundColor(theme.textDim)
                .font(.callout)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}
