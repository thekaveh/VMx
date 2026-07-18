//
// ThemeAdapter — Combine → SwiftUI bridge for ThemeVM theme tokens.
//
// Maps `ThemeModel` state (name, accentColor, fontScaleFactor) to SwiftUI
// `Color` tokens and a `fontScale` multiplier. Inject via
// `.environmentObject(themeAdapter)` and receive with
// `@EnvironmentObject var theme: ThemeAdapter` in any view.
//
// Mirrors the C# Avalonia ThemeAdapter (spec/proposals/2026-06-02-theme-vm-scenario.md §5).
//
import Combine
import SwiftUI
import VMx
import NotesShowcaseCore

/// Combine → SwiftUI bridge that exposes `ThemeVM` state as SwiftUI `Color`
/// tokens and a `fontScale` factor via `@Published` properties.
final class ThemeAdapter: ObservableObject {
    // MARK: - Published tokens (updated on main run loop)

    /// Application background color.
    @Published var background: Color = .black
    /// Accent / highlight color (from `ThemeModel.accentColor` hex).
    @Published var accent: Color = .blue
    /// Secondary pane / panel surface color.
    @Published var pane: Color = .black
    /// Muted / dimmed text color.
    @Published var textDim: Color = .gray
    /// Font scale multiplier (clamped `[0.75, 1.75]` by `ThemeVM`).
    @Published var fontScale: Double = 1.0

    // MARK: - Subscription

    private var cancellable: AnyCancellable?

    // MARK: - Init

    init(themeVM: ThemeVM) {
        // Apply synchronously so the very first SwiftUI frame is correct.
        // With `CurrentValueSubject`-backed `DerivedProperty`, `try? dp.value`
        // returns a non-nil value immediately after construction (DPROP-001).
        if let model = try? themeVM.currentTheme.value {
            applyModel(model)
        }
        cancellable = themeVM.currentTheme.valueChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] model in
                self?.applyModel(model)
            }
    }

    // MARK: - Private helpers

    private func applyModel(_ model: ThemeModel) {
        fontScale = model.fontScaleFactor
        accent = Color(hex: model.accentColor) ?? .blue
        if model.highContrast {
            background = .black
            pane = .black
            textDim = .white
            return
        }
        switch model.name {
        case "light":
            background = Color(hex: "#F7F9FC") ?? .white
            pane       = Color(hex: "#FFFFFF") ?? .white
            textDim    = Color(hex: "#5C6378") ?? .secondary
        default: // dark + high-contrast-with-adjustment-off + system fallback
            background = Color(hex: "#0E1320") ?? .black
            pane       = Color(hex: "#141B2D") ?? .black
            textDim    = Color(hex: "#9AA3B8") ?? .gray
        }
    }
}

// MARK: - Color hex initializer

extension Color {
    /// Creates a `Color` from a 6-digit hex string (with or without `#` prefix).
    /// Returns `nil` when the string cannot be parsed.
    init?(hex: String) {
        let h = hex
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        guard h.count == 6 else { return nil }
        var rgb: UInt64 = 0
        guard Scanner(string: h).scanHexInt64(&rgb) else { return nil }
        self.init(
            .sRGB,
            red:   Double((rgb >> 16) & 0xFF) / 255.0,
            green: Double((rgb >>  8) & 0xFF) / 255.0,
            blue:  Double( rgb        & 0xFF) / 255.0,
            opacity: 1.0
        )
    }
}
