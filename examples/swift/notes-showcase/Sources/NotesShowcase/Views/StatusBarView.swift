//
// StatusBarView — three DerivedProperty<String> slots for the status bar.
//
// Wraps `noteCountText`, `starredText`, and `editingText` in
// `BindableDerived<String>` so each slot live-updates on every DerivedProperty
// recompute. Mirrors C# Avalonia StatusBarView.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct StatusBarView: View {
    @StateObject private var noteCount: BindableDerived<String>
    @StateObject private var starred:   BindableDerived<String>
    @StateObject private var editing:   BindableDerived<String>
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: StatusBarVM) {
        _noteCount = StateObject(wrappedValue: BindableDerived(vm.noteCountText))
        _starred   = StateObject(wrappedValue: BindableDerived(vm.starredText))
        _editing   = StateObject(wrappedValue: BindableDerived(vm.editingText))
    }

    var body: some View {
        HStack(spacing: 12) {
            Text(noteCount.value ?? "–")
                .foregroundColor(theme.textDim)
                .font(.caption)
            Text("·")
                .foregroundColor(theme.textDim)
                .font(.caption)
            Text(starred.value ?? "–")
                .foregroundColor(theme.textDim)
                .font(.caption)
            Text("·")
                .foregroundColor(theme.textDim)
                .font(.caption)
            Text(editing.value ?? "No selection")
                .foregroundColor(.primary)
                .font(.caption)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 4)
    }
}
