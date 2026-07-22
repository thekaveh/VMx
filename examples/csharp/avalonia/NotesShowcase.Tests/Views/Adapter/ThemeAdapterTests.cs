using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless.XUnit;
using Avalonia.Media;
using Avalonia.Styling;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views.Adapter;
using System.Reactive.Concurrency;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.Views.Adapter;

public sealed class ThemeAdapterTests
{
    [AvaloniaFact]
    public void Independent_high_contrast_toggle_projects_black_white_palette()
    {
        var vm = ThemeVM.Builder()
            .Name("theme")
            .Services(
                new MessageHub(),
                new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance))
            .InitialModel(ThemeModel.LIGHT_PRESET)
            .Build();
        vm.Construct();
        var app = Application.Current!;
        using var binding = ThemeAdapter.Bind(vm, app);

        vm.ToggleHighContrast.Execute(null);

        var palette = Assert.IsType<ResourceDictionary>(app.Resources.MergedDictionaries[^1]);
        Assert.Equal(Color.Parse("#FF000000"), palette["BgColor"]);
        Assert.Equal(Color.Parse("#FFFFFFFF"), palette["TextColor"]);
        Assert.Equal(Color.Parse("#FFFFFFFF"), palette["BorderColor"]);
        Assert.Equal(ThemeVariant.Dark, app.RequestedThemeVariant);

        vm.Dispose();
    }
}
