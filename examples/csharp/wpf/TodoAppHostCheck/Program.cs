using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Controls;
using System.Windows.Threading;
using WpfTodoApp;

// Opens the real TodoApp window on an STA Dispatcher, types a title through the
// bound TextBox, clicks Add through UI Automation, checks the bound ListBox, then
// closes the window and checks that nothing keeps the view-model alive. Every
// wait is a Dispatcher priority or a timeout guard, never a fixed delay.
var failures = new List<string>();
var trace = new List<string>();
void Check(bool condition, string description)
{
    trace.Add((condition ? "ok   " : "FAIL ") + description);
    if (!condition)
        failures.Add(description);
}

WeakReference? viewModel = null;
var ui = new Thread(() =>
{
    var dispatcher = Dispatcher.CurrentDispatcher;
    SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
    var hangGuard = new DispatcherTimer(TimeSpan.FromSeconds(30), DispatcherPriority.Normal, (_, _) =>
    {
        failures.Add("timed out waiting for the Dispatcher");
        dispatcher.InvokeShutdown();
    }, dispatcher);

    dispatcher.BeginInvoke(DispatcherPriority.Normal, () =>
    {
        var (window, vm, list, box, add) = OpenWindow();
        viewModel = new WeakReference(vm);

        // Background runs after WPF's queued DataBind, Render and Loaded work.
        dispatcher.BeginInvoke(DispatcherPriority.Background, () =>
        {
            Check(vm.Items.Count == 3 && list.Items.Count == 3, "the ListBox shows the three seeded items");
            Check(!add.IsEnabled, "the Add button starts disabled");

            box.Text = "Ship the release";
            Check(vm.NewItemTitle == "Ship the release", "the TextBox binding writes the title to the VM");
            Check(add.IsEnabled, "typing a title enables the Add button");
            var invoke = (IInvokeProvider)new ButtonAutomationPeer(add).GetPattern(PatternInterface.Invoke)!;
            invoke.Invoke();

            // The automation click is queued at Input priority; Background runs after it.
            dispatcher.BeginInvoke(DispatcherPriority.Background, () =>
            {
                Check(vm.Items.Count == 4, $"Add left {vm.Items.Count} items");
                Check(list.Items.Count == 4, $"the ListBox shows {list.Items.Count} rows");
                Check(box.Text == string.Empty, "Add clears the bound TextBox");
                Check(!add.IsEnabled, "Add disables again for an empty title");

                window.Close();
                Check(vm.Items.All(item => item.VM.Status == VMx.Lifecycle.ConstructionStatus.Disposed),
                    "closing the window disposes every item");
                Check(!vm.AddCommand.CanExecute(null), "closing the window disposes the Add command");
                dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, () =>
                {
                    hangGuard.Stop();
                    dispatcher.InvokeShutdown();
                });
            });
        });
    });
    Dispatcher.Run();
});
ui.SetApartmentState(ApartmentState.STA);
ui.Start();
ui.Join();

// The Dispatcher has shut down, so only a leaked reference could keep the VM.
GC.Collect();
GC.WaitForPendingFinalizers();
GC.Collect();
Check(viewModel is { IsAlive: false }, "nothing keeps the closed window's view-model alive");

foreach (var line in trace)
    Console.WriteLine(line);
Console.WriteLine(failures.Count == 0 ? "WPF TodoApp host check passed." : "WPF TodoApp host check failed.");
return failures.Count == 0 ? 0 : 1;

[MethodImpl(MethodImplOptions.NoInlining)]
static (MainWindow Window, MainWindowViewModel Vm, ListBox List, TextBox Box, Button Add) OpenWindow()
{
    var window = new MainWindow();
    window.Show();
    var vm = (MainWindowViewModel)window.DataContext;
    return (window, vm, Find<ListBox>(window), (TextBox)window.FindName("NewItemBox"), Find<Button>(window));
}

static T Find<T>(DependencyObject root) where T : DependencyObject
{
    foreach (var child in LogicalTreeHelper.GetChildren(root).OfType<DependencyObject>())
    {
        if (child is T match)
            return match;
        if (FindOrNull<T>(child) is { } nested)
            return nested;
    }
    throw new InvalidOperationException($"no {typeof(T).Name} in the window");
}

static T? FindOrNull<T>(DependencyObject root) where T : DependencyObject
{
    foreach (var child in LogicalTreeHelper.GetChildren(root).OfType<DependencyObject>())
    {
        if (child is T match)
            return match;
        if (FindOrNull<T>(child) is { } nested)
            return nested;
    }
    return null;
}
