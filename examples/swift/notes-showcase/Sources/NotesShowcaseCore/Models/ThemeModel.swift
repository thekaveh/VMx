import Foundation

/// Domain model for the application theme.
///
/// See spec/proposals/2026-06-02-theme-vm-scenario.md §3.
/// Pure data — no behavior, no VMx dependencies.
///
/// `name` is one of `"dark"`, `"light"`, `"high-contrast"`, or `"system"`.
/// `accentColor` is a hex string (lingua franca across flavors).
/// `fontScaleFactor` is normalised to `[0.75 .. 1.75]`; values outside that
/// range are clamped at construction. `highContrast` is independent of `name`.
/// `followsSystem` is true iff the host should follow the OS-level theme;
/// `ThemeVM` resets this to false on explicit preset selection.
public struct ThemeModel: Sendable, Equatable {
    public let name: String
    public let accentColor: String
    public let fontScaleFactor: Double
    public let highContrast: Bool
    public let followsSystem: Bool

    public init(
        name: String,
        accentColor: String,
        fontScaleFactor: Double,
        highContrast: Bool,
        followsSystem: Bool
    ) {
        self.name = name
        self.accentColor = accentColor
        self.fontScaleFactor = fontScaleFactor
        self.highContrast = highContrast
        self.followsSystem = followsSystem
    }

    // MARK: - Font scale clamping

    /// Minimum font scale (clamp floor, per scenario §3).
    public static let minFontScale: Double = 0.75

    /// Maximum font scale (clamp ceiling, per scenario §3).
    public static let maxFontScale: Double = 1.75

    /// Clamps `scale` into `[minFontScale, maxFontScale]`.
    public static func clampFontScale(_ scale: Double) -> Double {
        if scale < minFontScale { return minFontScale }
        if scale > maxFontScale { return maxFontScale }
        return scale
    }

    // MARK: - Presets

    /// Dark preset — initial app theme (#4F8CD9 accent).
    /// Mirrors `ThemeModel.DARK_PRESET` in the C#/Python/TS flavors.
    public static let DARK_PRESET = ThemeModel(
        name: "dark",
        accentColor: "#4F8CD9",
        fontScaleFactor: 1.0,
        highContrast: false,
        followsSystem: false
    )

    /// Light preset (#1F6FEB accent).
    public static let LIGHT_PRESET = ThemeModel(
        name: "light",
        accentColor: "#1F6FEB",
        fontScaleFactor: 1.0,
        highContrast: false,
        followsSystem: false
    )

    /// High-contrast preset (saturated yellow accent, `highContrast = true`).
    public static let HIGH_CONTRAST_PRESET = ThemeModel(
        name: "high-contrast",
        accentColor: "#FFD400",
        fontScaleFactor: 1.0,
        highContrast: true,
        followsSystem: false
    )

    /// Read-only preset registry, keyed by `name`.
    public static let presets: [String: ThemeModel] = [
        DARK_PRESET.name: DARK_PRESET,
        LIGHT_PRESET.name: LIGHT_PRESET,
        HIGH_CONTRAST_PRESET.name: HIGH_CONTRAST_PRESET,
    ]

    /// Ordered preset list — dark, light, high-contrast.
    /// Registry order matters for THEME scenario contracts.
    public static let presetOrder: [ThemeModel] = [
        DARK_PRESET,
        LIGHT_PRESET,
        HIGH_CONTRAST_PRESET,
    ]
}
