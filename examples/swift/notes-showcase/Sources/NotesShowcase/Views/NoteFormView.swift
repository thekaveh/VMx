//
// NoteFormView — right-pane note editor.
//
// Two-way bindings route through NoteFormVM's scalar accessors:
//   `title`   → TextField (rebuilds draft via NoteModel.with(title:))
//   `body`    → TextEditor (rebuilds draft via NoteModel.with(body:))
//   `starred` → Toggle   (rebuilds draft via NoteModel.with(starred:))
//   `tagDraft` → TextField for tag entry
//
// Approve (Save) and Deny (Revert) use BindableCommand so their enabled
// state is reactive. Mirrors C# Avalonia NoteFormView.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct NoteFormView: View {
    @StateObject private var bound: BindableVM<NoteFormVM>
    @StateObject private var approveCmd: BindableCommand
    @StateObject private var addTagCmd: BindableCommand
    @StateObject private var showEditCmd: BindableCommand
    @StateObject private var showPreviewCmd: BindableCommand
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: NoteFormVM) {
        _bound     = StateObject(wrappedValue: BindableVM(vm))
        _approveCmd = StateObject(wrappedValue: BindableCommand(vm.approveCommand))
        _addTagCmd  = StateObject(wrappedValue: BindableCommand(vm.addTagCommand))
        _showEditCmd = StateObject(wrappedValue: BindableCommand(vm.showEditModeCommand))
        _showPreviewCmd = StateObject(wrappedValue: BindableCommand(vm.showPreviewModeCommand))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Text("Note")
                    .font(.headline.weight(.semibold))
                    .foregroundColor(theme.textDim)
                if bound.vm.isDirty {
                    Text("●")
                        .foregroundColor(theme.accent)
                        .font(.caption)
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 12)
            .padding(.bottom, 8)

            Divider()

            if !bound.vm.hasBoundNote {
                Spacer()
                Text("Select a note to edit")
                    .foregroundColor(theme.textDim)
                    .frame(maxWidth: .infinity, alignment: .center)
                Spacer()
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        // Title
                        TextField("Title", text: Binding(
                            get: { bound.vm.title },
                            set: { bound.vm.title = $0 }
                        ))
                        .textFieldStyle(.roundedBorder)
                        if let titleError = bound.vm.titleError {
                            Text(titleError)
                                .font(.caption)
                                .foregroundColor(.red)
                        }

                        // Tags row
                        VStack(alignment: .leading, spacing: 4) {
                            // Tag chips
                            if !bound.vm.tags.isEmpty {
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 4) {
                                        ForEach(bound.vm.tags, id: \.self) { tag in
                                            TagChipView(
                                                tag: tag,
                                                theme: theme,
                                                onRemove: {
                                                    bound.vm.removeTagCommand.execute(tag)
                                                }
                                            )
                                        }
                                    }
                                }
                            }
                            // Tag input
                            HStack(spacing: 4) {
                                TextField("Add tag…", text: Binding(
                                    get: { bound.vm.tagDraft },
                                    set: { bound.vm.tagDraft = $0 }
                                ))
                                .textFieldStyle(.roundedBorder)
                                .frame(maxWidth: 160)
                                Button("+") { addTagCmd.execute() }
                                    .disabled(!addTagCmd.canExecute)
                                    .accessibilityLabel("Add tag")
                            }
                        }

                        // Starred toggle
                        Toggle("Starred", isOn: Binding(
                            get: { bound.vm.starred },
                            set: { bound.vm.starred = $0 }
                        ))

                        // Body editor / preview
                        HStack(spacing: 8) {
                            Text("Body")
                                .font(.caption)
                                .foregroundColor(theme.textDim)
                            Spacer()
                            Button("Edit") { showEditCmd.execute() }
                                .disabled(!showEditCmd.canExecute)
                            Button("Preview") { showPreviewCmd.execute() }
                                .disabled(!showPreviewCmd.canExecute)
                        }
                        if bound.vm.isPreviewMode {
                            Text(bound.vm.body.isEmpty ? "No body." : bound.vm.body)
                                .font(.body)
                                .frame(maxWidth: .infinity, minHeight: 160, alignment: .topLeading)
                                .padding(8)
                                .background(Color.secondary.opacity(0.08))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 4)
                                        .stroke(Color.secondary.opacity(0.3), lineWidth: 1)
                                )
                                .accessibilityLabel("Body preview")
                        } else {
                            TextEditor(text: Binding(
                                get: { bound.vm.body },
                                set: { bound.vm.body = $0 }
                            ))
                            .font(.body)
                            .frame(minHeight: 160)
                            .accessibilityLabel("Body")
                            .overlay(
                                RoundedRectangle(cornerRadius: 4)
                                    .stroke(Color.secondary.opacity(0.3), lineWidth: 1)
                            )
                        }

                        // Action buttons
                        HStack(spacing: 8) {
                            Button("Save") { approveCmd.execute() }
                                .disabled(!approveCmd.canExecute)
                                .buttonStyle(.borderedProminent)
                            Button("Revert") {
                                bound.vm.denyCommand.execute()
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    .padding(12)
                }
            }
        }
    }
}

// MARK: - TagChipView

private struct TagChipView: View {
    let tag: String
    let theme: ThemeAdapter
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 3) {
            Text(tag)
                .font(.caption)
            Button("×", action: onRemove)
                .buttonStyle(.plain)
                .font(.caption)
                .accessibilityLabel("Remove tag \(tag)")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(theme.textDim.opacity(0.2))
        )
    }
}
