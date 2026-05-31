using Avalonia;

namespace NotesShowcase;

/// <summary>
/// Process entrypoint. Standard Avalonia <c>AppBuilder</c> pattern (plan §5.a):
/// detect platform, register the Inter font, log to trace, then start the
/// classic desktop lifetime which drives <see cref="App"/>.
/// </summary>
public static class Program
{
    /// <summary>Process entry; STA-threaded for desktop UI compatibility.</summary>
    [STAThread]
    public static void Main(string[] args)
        => BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    /// <summary>Composed AppBuilder — also used by the headless smoke test harness.</summary>
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
