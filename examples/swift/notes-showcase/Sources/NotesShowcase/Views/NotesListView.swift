//
// NotesListView — centre-pane paged, searchable, filterable note list.
//
// Two-way bindings:
//   `searchTerm`     → TextField via Binding on notesView.searchTerm setter
//   `showStarredOnly` → Toggle via Binding
//   `current`        → tapping a row sets notesView.current (tap gesture,
//                      not List(selection:) which requires Hashable)
//
// Pagination commands use BindableCommand so button enabled state is reactive.
// Mirrors the C# Avalonia NotesListView.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct NotesListView: View {
    @StateObject private var bound: BindableVM<NotesViewVM>
    @StateObject private var firstPageCmd: BindableCommand
    @StateObject private var prevPageCmd: BindableCommand
    @StateObject private var nextPageCmd: BindableCommand
    @StateObject private var lastPageCmd: BindableCommand
    @StateObject private var isEmpty: BindableDerived<Bool>
    @StateObject private var pageLabel: BindableDerived<String>
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: NotesViewVM) {
        _bound        = StateObject(wrappedValue: BindableVM(vm))
        _firstPageCmd = StateObject(wrappedValue: BindableCommand(vm.moveToFirstPageCommand))
        _prevPageCmd  = StateObject(wrappedValue: BindableCommand(vm.moveToPreviousPageCommand))
        _nextPageCmd  = StateObject(wrappedValue: BindableCommand(vm.moveToNextPageCommand))
        _lastPageCmd  = StateObject(wrappedValue: BindableCommand(vm.moveToLastPageCommand))
        _isEmpty      = StateObject(wrappedValue: BindableDerived(vm.isEmptyDerived))
        _pageLabel    = StateObject(wrappedValue: BindableDerived(vm.pageLabelDerived))
    }

    var body: some View {
        VStack(spacing: 0) {
            // ── Search bar ────────────────────────────────────────────────
            TextField("Search…", text: Binding(
                get: { bound.vm.searchTerm },
                set: { bound.vm.searchTerm = $0 }
            ))
            .textFieldStyle(.roundedBorder)
            .padding(EdgeInsets(top: 8, leading: 12, bottom: 4, trailing: 12))

            // ── Starred-only toggle ───────────────────────────────────────
            Toggle("Starred only", isOn: Binding(
                get: { bound.vm.showStarredOnly },
                set: { bound.vm.showStarredOnly = $0 }
            ))
            .padding(EdgeInsets(top: 4, leading: 12, bottom: 6, trailing: 12))

            Divider()

            // ── Notes list ────────────────────────────────────────────────
            if isEmpty.value ?? bound.vm.isEmpty {
                Spacer()
                Text("No notes")
                    .foregroundColor(theme.textDim)
                    .font(.body)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(bound.vm.visibleItems, id: \.noteId) { noteVM in
                            Button {
                                bound.vm.current = noteVM
                            } label: {
                                NoteRowView(
                                    noteVM: noteVM,
                                    isSelected: noteVM === bound.vm.current,
                                    theme: theme
                                )
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(noteVM.title)
                            .accessibilityAddTraits(noteVM === bound.vm.current ? [.isSelected] : [])
                        }
                    }
                }
            }

            Divider()

            // ── Pagination strip ──────────────────────────────────────────
            HStack(spacing: 6) {
                Button("⏮") { firstPageCmd.execute() }
                    .disabled(!firstPageCmd.canExecute)
                    .accessibilityLabel("First page")
                Button("◀") { prevPageCmd.execute() }
                    .disabled(!prevPageCmd.canExecute)
                    .accessibilityLabel("Previous page")
                Text(pageLabel.value ?? bound.vm.pageLabel)
                    .font(.caption)
                    .foregroundColor(theme.textDim)
                    .frame(minWidth: 80, alignment: .center)
                Button("▶") { nextPageCmd.execute() }
                    .disabled(!nextPageCmd.canExecute)
                    .accessibilityLabel("Next page")
                Button("⏭") { lastPageCmd.execute() }
                    .disabled(!lastPageCmd.canExecute)
                    .accessibilityLabel("Last page")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }
}

// MARK: - NoteRowView

private struct NoteRowView: View {
    let noteVM: NoteVM
    let isSelected: Bool
    let theme: ThemeAdapter

    var body: some View {
        HStack(spacing: 6) {
            if noteVM.starred {
                Text("★")
                    .foregroundColor(theme.accent)
                    .font(.body)
            }
            Text(noteVM.title)
                .foregroundColor(isSelected ? theme.accent : .primary)
                .font(.body)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(isSelected ? theme.accent.opacity(0.15) : Color.clear)
    }
}
