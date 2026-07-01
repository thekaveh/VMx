import SwiftUI
import NotesShowcaseCore

struct GlobalSearchView: View {
    @StateObject private var bindable: BindableVM<GlobalSearchVM>
    @StateObject private var refreshCmd: BindableCommand
    @StateObject private var loadMoreCmd: BindableCommand
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: GlobalSearchVM) {
        _bindable = StateObject(wrappedValue: BindableVM(vm))
        _refreshCmd = StateObject(wrappedValue: BindableCommand(vm.refreshCommand))
        _loadMoreCmd = StateObject(wrappedValue: BindableCommand(vm.loadMoreCommand))
    }

    var body: some View {
        let vm = bindable.vm
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                TextField(
                    "Search all notes...",
                    text: Binding(
                        get: { vm.searchTerm },
                        set: {
                            vm.searchTerm = $0
                            vm.searchNow()
                        }
                    )
                )
                .textFieldStyle(.roundedBorder)

                Button("Search") { refreshCmd.execute() }
                    .disabled(!refreshCmd.canExecute)

                Button("Load more") { loadMoreCmd.execute() }
                    .disabled(!loadMoreCmd.canExecute)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(vm.results, id: \.noteId) { note in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(note.title)
                                .lineLimit(1)
                            Text(note.model.notebookId)
                                .font(.caption)
                                .foregroundColor(theme.textDim)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .overlay(
                            RoundedRectangle(cornerRadius: 4)
                                .stroke(theme.textDim.opacity(0.35), lineWidth: 1)
                        )
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(theme.pane)
    }
}
