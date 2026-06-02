using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Markup.Xaml.Styling;
using Avalonia.Media;
using Avalonia.Styling;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// View-side adapter that translates <see cref="ThemeVM"/> state into
/// Avalonia framework calls. No business logic — just framework mapping.
///
/// See spec/proposals/2026-06-02-theme-vm-scenario.md §5 (Avalonia bullet).
///
/// <para>
/// On every emission of <see cref="ThemeVM.CurrentTheme"/>'s
/// <see cref="VMx.Properties.DerivedProperty{T}.ValueChanged"/>, the adapter:
/// <list type="bullet">
///   <item><description>Sets <see cref="Application.RequestedThemeVariant"/>
///     to <see cref="ThemeVariant.Dark"/> or <see cref="ThemeVariant.Light"/>
///     per <see cref="ThemeModel.Name"/>.</description></item>
///   <item><description>Hot-swaps a small in-memory
///     <see cref="ResourceDictionary"/> on
///     <see cref="IResourceDictionary.MergedDictionaries"/> so the new accent
///     and palette resources (<c>AccentBrush</c>, <c>BgBrush</c>, etc.) bind
///     immediately.</description></item>
///   <item><description>Publishes the font scale to a top-level
///     <c>FontScale</c> resource that any view can multiply into its
///     declared font size.</description></item>
/// </list>
/// </para>
/// </summary>
public static class ThemeAdapter
{
    /// <summary>Resource key for the floating-point font scale exposed app-wide.</summary>
    public const string FontScaleResourceKey = "FontScale";

    /// <summary>
    /// Subscribes the adapter to <paramref name="themeVM"/> and applies the
    /// current model to <paramref name="app"/> immediately, then on every
    /// subsequent change. Fire-and-forget: prefer <see cref="Bind"/> when
    /// the caller needs to detach later.
    /// </summary>
    public static void Apply(ThemeVM themeVM, Application app)
    {
        _ = Bind(themeVM, app);
    }

    /// <summary>
    /// Subscribes the adapter to <paramref name="themeVM"/> and returns the
    /// subscription so the caller can dispose it (e.g. on app shutdown).
    /// Applies the current model synchronously before returning.
    /// </summary>
    public static IDisposable Bind(ThemeVM themeVM, Application app)
    {
        if (themeVM is null) throw new ArgumentNullException(nameof(themeVM));
        if (app is null) throw new ArgumentNullException(nameof(app));

        // Apply the current model up front so the very first frame is correct.
        ApplyModel(themeVM.Model, app);

        return themeVM.CurrentTheme.ValueChanged.Subscribe(m => ApplyModel(m, app));
    }

    private static void ApplyModel(ThemeModel model, Application app)
    {
        app.RequestedThemeVariant = model.Name switch
        {
            "light" => ThemeVariant.Light,
            "dark" => ThemeVariant.Dark,
            "high-contrast" => ThemeVariant.Dark,
            _ => ThemeVariant.Default,
        };

        // Replace any previously-installed adapter dictionary so we never
        // leak ever-growing merged-dictionary state across theme changes.
        var resources = app.Resources;
        for (var i = resources.MergedDictionaries.Count - 1; i >= 0; i--)
        {
            if (resources.MergedDictionaries[i] is ResourceDictionary rd
                && rd.ContainsKey(AdapterMarkerKey))
            {
                resources.MergedDictionaries.RemoveAt(i);
            }
        }
        resources.MergedDictionaries.Add(BuildPaletteDictionary(model));

        // Single binding seam for font scale (see FontScaleResourceKey).
        resources[FontScaleResourceKey] = model.FontScaleFactor;
    }

    private const string AdapterMarkerKey = "__ThemeAdapter_Marker";

    private static ResourceDictionary BuildPaletteDictionary(ThemeModel model)
    {
        // Light/dark/high-contrast palettes share the same key set as
        // Views/Theme/DarkTheme.axaml so existing bindings keep resolving.
        var (bg, pane, border, text, subtle) = model.Name switch
        {
            "light" => ("#FFF7F9FC", "#FFFFFFFF", "#FFD7DCE5", "#FF1A2235", "#FF5C6378"),
            "high-contrast" => ("#FF000000", "#FF000000", "#FFFFFFFF", "#FFFFFFFF", "#FFFFFF66"),
            _ /* dark + system fallback */ => ("#FF0E1320", "#FF141B2D", "#FF2A3045", "#FFE6EAF2", "#FF9AA3B8"),
        };

        var accent = NormalizeAccentHex(model.AccentColor);
        var rd = new ResourceDictionary
        {
            [AdapterMarkerKey] = true,
            ["BgColor"] = Color.Parse(bg),
            ["PaneColor"] = Color.Parse(pane),
            ["BorderColor"] = Color.Parse(border),
            ["AccentColor"] = Color.Parse(accent),
            ["TextColor"] = Color.Parse(text),
            ["SubtleTextColor"] = Color.Parse(subtle),
            ["BgBrush"] = new SolidColorBrush(Color.Parse(bg)),
            ["PaneBrush"] = new SolidColorBrush(Color.Parse(pane)),
            ["BorderBrush"] = new SolidColorBrush(Color.Parse(border)),
            ["AccentBrush"] = new SolidColorBrush(Color.Parse(accent)),
            ["TextBrush"] = new SolidColorBrush(Color.Parse(text)),
            ["SubtleTextBrush"] = new SolidColorBrush(Color.Parse(subtle)),
        };
        return rd;
    }

    private static string NormalizeAccentHex(string hex)
    {
        // Color.Parse accepts both "#RGB" and "#RRGGBB"/"#AARRGGBB"; the
        // ThemeModel presets use "#RRGGBB" (no alpha) so we prefix the
        // opaque alpha channel to match the rest of the palette.
        if (string.IsNullOrEmpty(hex)) return "#FF000000";
        var trimmed = hex.StartsWith('#') ? hex.Substring(1) : hex;
        return trimmed.Length == 6 ? "#FF" + trimmed : hex;
    }
}
