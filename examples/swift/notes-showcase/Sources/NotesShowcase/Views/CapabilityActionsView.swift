//
// CapabilityActionsView — dynamic capability-action bar.
//
// Observes `CapabilityActionsVM.actions: DerivedProperty<[ActionVM]>` via
// `BindableDerived<[ActionVM]>` so the bar repopulates whenever the focused
// VM changes. Each button calls `action.command.execute()` directly.
// Mirrors C# Avalonia CapabilityActionsView.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct CapabilityActionsView: View {
    @StateObject private var actionsBound: BindableDerived<[ActionVM]>
    @StateObject private var addNoteCmd: BindableCommand
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: CapabilityActionsVM) {
        _actionsBound = StateObject(wrappedValue: BindableDerived(vm.actions))
        _addNoteCmd = StateObject(wrappedValue: BindableCommand(vm.addNoteCommand))
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                Button("+ Note") {
                    addNoteCmd.execute()
                }
                .disabled(!addNoteCmd.canExecute)
                .buttonStyle(.bordered)
                .font(.caption)
                .accessibilityLabel("Add note")
                let actions = actionsBound.value ?? []
                if actions.isEmpty {
                    Text("No actions")
                        .font(.caption)
                        .foregroundColor(theme.textDim)
                } else {
                    ForEach(Array(actions.enumerated()), id: \.offset) { _, action in
                        Button(action.label) {
                            action.command.execute()
                        }
                        .disabled(!action.command.canExecute())
                        .buttonStyle(.bordered)
                        .font(.caption)
                    }
                }
            }
            .frame(minHeight: 28)
        }
    }
}
