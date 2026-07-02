//
// NotificationsView — toast overlay for the bounded notification list.
//
// Observes `NotificationsVM.visible` via `BindableVM<NotificationsVM>` —
// `propertyChanged("visible")` triggers re-renders, which re-read the
// current `bound.vm.visible` snapshot. Mirrors C# Avalonia NotificationsView.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct NotificationsView: View {
    @StateObject private var bound: BindableVM<NotificationsVM>
    @EnvironmentObject private var theme: ThemeAdapter

    init(vm: NotificationsVM) {
        _bound = StateObject(wrappedValue: BindableVM(vm))
    }

    var body: some View {
        VStack(spacing: 6) {
            ForEach(bound.vm.visible.indices, id: \.self) { i in
                // Guard against index-out-of-bounds between render and
                // collection mutation (rare but possible in async contexts).
                if i < bound.vm.visible.count {
                    NotificationToastView(
                        notif: bound.vm.visible[i],
                        theme: theme
                    )
                }
            }
        }
        .padding(.trailing, 16)
        .padding(.bottom, 40)
    }
}

// MARK: - NotificationToastView

private struct NotificationToastView: View {
    let notif: NotificationVM
    let theme: ThemeAdapter

    var body: some View {
        HStack(spacing: 8) {
            Text(notif.notification.message)
                .font(.callout)
                .foregroundColor(.primary)
            Spacer()
            Button("×") {
                notif.dismissCommand.execute()
            }
            .buttonStyle(.plain)
            .font(.callout)
            .accessibilityLabel("Dismiss notification")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(minWidth: 220, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(theme.pane)
                .shadow(color: .black.opacity(0.3), radius: 4, x: 0, y: 2)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(theme.accent, lineWidth: 1)
        )
    }
}
