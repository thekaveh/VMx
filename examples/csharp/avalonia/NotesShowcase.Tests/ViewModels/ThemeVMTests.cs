using System;
using System.Collections.Generic;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Messages;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

/// <summary>
/// Conformance tests for the THEME-NNN family defined in
/// spec/proposals/2026-06-02-theme-vm-scenario.md §6.
///
/// Style note: matches the rest of this project (plain xunit
/// <see cref="Assert"/>). The proposal references "FluentAssertions style" as
/// shorthand for "BDD-leaning Arrange/Act/Assert" — FluentAssertions itself is
/// not a dependency of this test project (see <c>NotesShowcase.Tests.csproj</c>).
/// </summary>
public sealed class ThemeVMTests
{
    private static (ThemeVM vm, MessageHub hub) Build(
        ThemeModel? initial = null,
        Func<string>? systemThemeProvider = null)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var builder = ThemeVM.Builder()
            .Name("theme")
            .Services(hub, dispatcher)
            .InitialModel(initial ?? ThemeModel.LIGHT_PRESET);
        if (systemThemeProvider is not null)
            builder = builder.SystemThemeProvider(systemThemeProvider);
        var vm = builder.Build();
        vm.Construct();
        return (vm, hub);
    }

    private static List<ThemeChangedMessage> Capture(MessageHub hub)
    {
        var observed = new List<ThemeChangedMessage>();
        hub.Messages.OfType<ThemeChangedMessage>().Subscribe(observed.Add);
        return observed;
    }

    // ── THEME-001 ──────────────────────────────────────────────────────────

    [Fact]
    public void THEME_001_SetThemeCommand_dark_publishes_ThemeChangedMessage_with_prev_and_curr()
    {
        var (vm, hub) = Build(initial: ThemeModel.LIGHT_PRESET);
        var observed = Capture(hub);

        vm.SetThemeCommand.Execute("dark");

        Assert.Single(observed);
        var msg = observed[0];
        Assert.Equal(ThemeModel.LIGHT_PRESET, msg.Previous);
        Assert.Equal("dark", msg.Current.Name);
        Assert.Equal(ThemeModel.DARK_PRESET.AccentColor, msg.Current.AccentColor);
        Assert.Equal("dark", vm.CurrentTheme.Value.Name);
        Assert.False(vm.CurrentTheme.Value.FollowsSystem);
    }

    // ── THEME-002 ──────────────────────────────────────────────────────────

    [Fact]
    public void THEME_002_Unknown_preset_throws_ArgumentException_without_publishing_a_message()
    {
        var (vm, hub) = Build();
        var observed = Capture(hub);
        var before = vm.Model;

        Assert.Throws<ArgumentException>(() => vm.SetThemeCommand.Execute("unknown-preset"));

        Assert.Empty(observed);
        Assert.Equal(before, vm.Model);
    }

    // ── THEME-003 ──────────────────────────────────────────────────────────

    [Fact]
    public void THEME_003_ToggleHighContrast_preserves_accent_and_scale()
    {
        var custom = ThemeModel.LIGHT_PRESET with
        {
            AccentColor = "#ABCDEF",
            FontScaleFactor = 1.25,
        };
        var (vm, hub) = Build(initial: custom);
        var observed = Capture(hub);

        vm.ToggleHighContrast.Execute(null);

        Assert.Single(observed);
        Assert.True(vm.CurrentTheme.Value.HighContrast);
        Assert.Equal("#ABCDEF", vm.CurrentTheme.Value.AccentColor);
        Assert.Equal(1.25, vm.CurrentTheme.Value.FontScaleFactor);
        // Name unchanged — toggle is orthogonal to preset selection.
        Assert.Equal("light", vm.CurrentTheme.Value.Name);
    }

    // ── THEME-004 ──────────────────────────────────────────────────────────

    [Fact]
    public void THEME_004_SetFontScale_clamps_below_floor()
    {
        var (vm, hub) = Build();
        var observed = Capture(hub);

        vm.SetFontScale.Execute(0.1);

        Assert.Single(observed);
        Assert.Equal(ThemeModel.MinFontScale, vm.CurrentTheme.Value.FontScaleFactor);
    }

    [Fact]
    public void THEME_004_SetFontScale_clamps_above_ceiling()
    {
        var (vm, hub) = Build();
        var observed = Capture(hub);

        vm.SetFontScale.Execute(99.0);

        Assert.Single(observed);
        Assert.Equal(ThemeModel.MaxFontScale, vm.CurrentTheme.Value.FontScaleFactor);
    }

    [Fact]
    public void THEME_004_SetFontScale_in_range_keeps_value()
    {
        var (vm, _) = Build();

        vm.SetFontScale.Execute(1.5);

        Assert.Equal(1.5, vm.CurrentTheme.Value.FontScaleFactor);
    }

    // ── THEME-005 ──────────────────────────────────────────────────────────

    [Fact]
    public void THEME_005_FollowSystemCommand_sets_FollowsSystem_true_then_SetThemeCommand_resets_to_false()
    {
        var (vm, _) = Build(
            initial: ThemeModel.LIGHT_PRESET,
            systemThemeProvider: () => "dark");

        vm.FollowSystemCommand.Execute(null);

        Assert.True(vm.CurrentTheme.Value.FollowsSystem);
        Assert.Equal("dark", vm.CurrentTheme.Value.Name);

        vm.SetThemeCommand.Execute("light");

        Assert.False(vm.CurrentTheme.Value.FollowsSystem);
        Assert.Equal("light", vm.CurrentTheme.Value.Name);
    }

    // ── Sanity: Presets registry + DerivedProperty contracts ──────────────

    [Fact]
    public void Presets_exposes_three_named_models_in_registry_order()
    {
        var (vm, _) = Build();

        Assert.Equal(3, vm.Presets.Count);
        Assert.Equal("dark", vm.Presets[0].Name);
        Assert.Equal("light", vm.Presets[1].Name);
        Assert.Equal("high-contrast", vm.Presets[2].Name);
    }

    [Fact]
    public void CurrentTheme_ValueChanged_replays_on_every_effective_transition()
    {
        var (vm, _) = Build(initial: ThemeModel.LIGHT_PRESET);
        var seen = new List<string>();
        using var sub = vm.CurrentTheme.ValueChanged.Subscribe(t => seen.Add(t.Name));

        vm.SetThemeCommand.Execute("dark");
        vm.SetThemeCommand.Execute("high-contrast");

        Assert.Equal(new[] { "dark", "high-contrast" }, seen);
    }
}
