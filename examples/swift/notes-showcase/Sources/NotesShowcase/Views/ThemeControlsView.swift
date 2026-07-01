//
// ThemeControlsView — preset picker + high-contrast + font-scale controls.
//
// Calls ThemeVM commands directly (setThemeCommand, toggleHighContrast,
// setFontScale). No BindableCommand needed here — visual feedback comes from
// the ThemeAdapter environment object which re-renders the whole app on change.
//
import SwiftUI
import Combine
import VMx
import NotesShowcaseCore

struct ThemeControlsView: View {
    private let themeVM: ThemeVM
    @EnvironmentObject private var theme: ThemeAdapter

    init(themeVM: ThemeVM) {
        self.themeVM = themeVM
    }

    var body: some View {
        HStack(spacing: 6) {
            // Preset picker buttons
            ForEach(themeVM.presets, id: \.name) { preset in
                Button(preset.name.capitalized) {
                    themeVM.setThemeCommand.execute(preset.name)
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(
                    RoundedRectangle(cornerRadius: 4)
                        .fill(theme.textDim.opacity(0.15))
                )
                .font(.caption)
            }

            Divider().frame(height: 16)

            // High-contrast toggle
            Button("HC") {
                themeVM.toggleHighContrast.execute()
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(
                RoundedRectangle(cornerRadius: 4)
                    .fill(theme.textDim.opacity(0.15))
            )
            .font(.caption)

            Divider().frame(height: 16)

            // Font scale stepper
            Button("A-") {
                if let current = try? themeVM.currentTheme.value {
                    themeVM.setFontScale.execute(current.fontScaleFactor - 0.1)
                }
            }
            .buttonStyle(.plain)
            .font(.caption.bold())

            Button("A+") {
                if let current = try? themeVM.currentTheme.value {
                    themeVM.setFontScale.execute(current.fontScaleFactor + 0.1)
                }
            }
            .buttonStyle(.plain)
            .font(.caption.bold())
        }
    }
}
