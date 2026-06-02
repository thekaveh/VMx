using System.Collections.Generic;

namespace NotesShowcase.Models;

/// <summary>
/// Domain model for the application theme.
///
/// See spec/proposals/2026-06-02-theme-vm-scenario.md §3 (the "theme as a VM
/// concern" scenario contract). Pure data — no behavior, no VMx dependencies.
///
/// <para>
/// <see cref="Name"/> is one of <c>"dark"</c>, <c>"light"</c>,
/// <c>"high-contrast"</c>, or <c>"system"</c>. <see cref="AccentColor"/> is a
/// hex string (lingua franca across flavors). <see cref="FontScaleFactor"/>
/// is normalized to <c>[0.75 .. 1.75]</c>; values outside that range are
/// clamped at construction. <see cref="HighContrast"/> is independent of
/// <see cref="Name"/> (you can stack high-contrast over the light preset).
/// <see cref="FollowsSystem"/> is true iff the host should follow the
/// OS-level theme; <see cref="ThemeVM"/> resets this to false on explicit
/// preset selection.
/// </para>
/// </summary>
public sealed record ThemeModel(
    string Name,
    string AccentColor,
    double FontScaleFactor,
    bool HighContrast,
    bool FollowsSystem)
{
    /// <summary>Minimum font scale (clamp floor, per scenario §3).</summary>
    public const double MinFontScale = 0.75;

    /// <summary>Maximum font scale (clamp ceiling, per scenario §3).</summary>
    public const double MaxFontScale = 1.75;

    /// <summary>
    /// Clamps <paramref name="scale"/> into <c>[MinFontScale, MaxFontScale]</c>.
    /// </summary>
    public static double ClampFontScale(double scale)
    {
        if (scale < MinFontScale) return MinFontScale;
        if (scale > MaxFontScale) return MaxFontScale;
        return scale;
    }

    /// <summary>
    /// Dark preset (mirrors the palette declared in
    /// <c>Views/Theme/DarkTheme.axaml</c>; <c>#FF4F8CD9</c> is the
    /// <c>AccentColor</c> resource there). This is the initial theme of the
    /// app, matching <c>App.axaml</c>'s <c>RequestedThemeVariant="Dark"</c>.
    /// </summary>
    public static readonly ThemeModel DARK_PRESET = new(
        Name: "dark",
        AccentColor: "#4F8CD9",
        FontScaleFactor: 1.0,
        HighContrast: false,
        FollowsSystem: false);

    /// <summary>
    /// Light preset (flips background from dark to light; keeps the dark
    /// preset's accent — the Avalonia FluentTheme adjusts contrast for the
    /// requested variant on its own).
    /// </summary>
    public static readonly ThemeModel LIGHT_PRESET = new(
        Name: "light",
        AccentColor: "#1F6FEB",
        FontScaleFactor: 1.0,
        HighContrast: false,
        FollowsSystem: false);

    /// <summary>
    /// High-contrast preset (pure white on pure black, accent in saturated
    /// yellow). Accessibility-mandated; the contract sets
    /// <see cref="HighContrast"/> to true so the adapter can apply
    /// outline / focus-ring overrides.
    /// </summary>
    public static readonly ThemeModel HIGH_CONTRAST_PRESET = new(
        Name: "high-contrast",
        AccentColor: "#FFD400",
        FontScaleFactor: 1.0,
        HighContrast: true,
        FollowsSystem: false);

    /// <summary>
    /// Read-only preset registry, keyed by <see cref="Name"/>. Looking up an
    /// unknown key throws <see cref="System.Collections.Generic.KeyNotFoundException"/>;
    /// <see cref="ThemeVM.SetThemeCommand"/> wraps that into an
    /// <see cref="System.ArgumentException"/> for the caller.
    /// </summary>
    public static readonly IReadOnlyDictionary<string, ThemeModel> Presets =
        new Dictionary<string, ThemeModel>(System.StringComparer.Ordinal)
        {
            [DARK_PRESET.Name] = DARK_PRESET,
            [LIGHT_PRESET.Name] = LIGHT_PRESET,
            [HIGH_CONTRAST_PRESET.Name] = HIGH_CONTRAST_PRESET,
        };
}
