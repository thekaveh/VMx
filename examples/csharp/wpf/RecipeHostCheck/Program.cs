using System.Reactive.Concurrency;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Integration;

// A worker thread constructs the VM and replaces its model while two TextBlocks
// are bound to the adapter. Both changes must reach the bindings on the WPF
// Dispatcher thread, and disposing the adapter must leave the VM constructed.
var failures = new List<string>();
void Check(bool condition, string failure)
{
    if (!condition)
        failures.Add(failure);
}

var ui = new Thread(() =>
{
    var dispatcher = Dispatcher.CurrentDispatcher;
    SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
    var uiThread = Environment.CurrentManagedThreadId;

    using var hub = new MessageHub();
    var vm = ComponentVM<Note>.Builder()
        .Name("note")
        .Services(hub, RxDispatcher.Immediate())
        .Model(new Note("draft"))
        .Build();
    var adapter = new BindableVm<Note>(vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
    var offThread = 0;
    adapter.PropertyChanged += (_, _) =>
    {
        if (Environment.CurrentManagedThreadId != uiThread)
            offThread++;
    };

    var title = new TextBlock();
    title.SetBinding(TextBlock.TextProperty, new Binding("Model.Title") { Source = adapter });
    var status = new TextBlock();
    status.SetBinding(TextBlock.TextProperty, new Binding(nameof(BindableVm<Note>.Status)) { Source = adapter });
    Check(title.Text == "draft", $"initial title was '{title.Text}'");
    Check(status.Text == vm.Status.ToString(), $"initial status was '{status.Text}'");

    var hangGuard = new DispatcherTimer(TimeSpan.FromSeconds(30), DispatcherPriority.Normal, (_, _) =>
    {
        failures.Add("timed out waiting for the Dispatcher");
        dispatcher.InvokeShutdown();
    }, dispatcher);

    var worker = new Thread(() =>
    {
        vm.Construct();
        vm.Model = new Note("from worker");
        // Background priority runs after the Normal-priority posts that
        // SynchronizationContextScheduler made for the changes above.
        dispatcher.BeginInvoke(DispatcherPriority.Background, () =>
        {
            hangGuard.Stop();
            Check(title.Text == "from worker", $"title after the worker was '{title.Text}'");
            Check(status.Text == nameof(ConstructionStatus.Constructed), $"status after the worker was '{status.Text}'");
            Check(offThread == 0, $"{offThread} notifications ran off the Dispatcher thread");
            adapter.Dispose();
            Check(vm.Status == ConstructionStatus.Constructed, $"disposing the adapter changed the VM to {vm.Status}");
            dispatcher.InvokeShutdown();
        });
    });
    worker.Start();
    Dispatcher.Run();
});
ui.SetApartmentState(ApartmentState.STA);
ui.Start();
ui.Join();

foreach (var failure in failures)
    Console.Error.WriteLine($"FAIL: {failure}");
Console.WriteLine(failures.Count == 0 ? "WPF recipe host check passed." : "WPF recipe host check failed.");
return failures.Count == 0 ? 0 : 1;

/// <summary>The model shown by the check.</summary>
public sealed record Note(string Title);
