//
// NotebooksTreeView — left-pane notebook tree.
//
// Displays the flat `NotebooksRootVM.all` list with children indented one
// level. Tapping a row sets `notebooksRoot.current`. Mirrors the C# Avalonia
// NotebooksTreeView (TreeView + TreeDataTemplate). Reacts via
// `BindableVM<NotebooksRootVM>` — `propertyChanged("roots")` and
// `propertyChanged("current")` both drive re-renders.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct NotebooksTreeView: View {
    @StateObject private var bound: BindableVM<NotebooksRootVM>
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: NotebooksRootVM) {
        _bound = StateObject(wrappedValue: BindableVM(vm))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            Text("Notebooks")
                .font(.headline.weight(.semibold))
                .foregroundColor(theme.textDim)
                .padding(.horizontal, 12)
                .padding(.top, 12)
                .padding(.bottom, 6)

            Divider()

            // Tree (flat with indentation by parentId)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(bound.vm.all, id: \.name) { nb in
                        NotebookRowView(
                            nb: nb,
                            isSelected: nb === bound.vm.current,
                            theme: theme
                        ) {
                            bound.vm.current = nb
                        }
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
            }
        }
    }
}

// MARK: - NotebookRowView

private struct NotebookRowView: View {
    let nb: NotebookVM
    let isSelected: Bool
    let theme: ThemeAdapter
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 4) {
                // Indent children by their depth (single-level for now)
                if nb.model.parentId != nil {
                    Spacer().frame(width: 16)
                }
                Text(nb.notebookName)
                    .foregroundColor(isSelected ? theme.accent : .primary)
                    .font(.body)
                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 4)
                    .fill(isSelected ? theme.accent.opacity(0.15) : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }
}
