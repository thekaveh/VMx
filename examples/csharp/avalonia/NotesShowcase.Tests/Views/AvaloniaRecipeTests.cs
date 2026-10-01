using System.Reactive.Concurrency;
using Avalonia.Controls;
using Avalonia.Data;
using Avalonia.Headless.XUnit;
using Avalonia.Threading;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Integration;
using Xunit;

namespace NotesShowcase.Tests.Views;

/// <summary>
/// Executes the Avalonia integration recipe (docs/content/integration/avalonia.md)
/// on Avalonia's headless UI thread. The shared XAML adapter,
/// langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs, is linked into this
/// project and drives real Avalonia bindings; <c>make docs-check</c> keeps the
/// page's fences identical to their sources. No conformance-ID markers
/// (integration recipe).
/// </summary>
public sealed class AvaloniaRecipeTests
{
    private sealed record Note(string Title);

    private static ComponentVM<Note> CreateVm(MessageHub hub)
    {
        return ComponentVM<Note>.Builder()
            .Name("note")
            .Services(hub, RxDispatcher.Immediate())
            .Model(new Note("draft"))
            .Build();
    }

    private static BindableVm<Note> CreateAdapter(ComponentVM<Note> vm)
    {
        // On Avalonia's UI thread, SynchronizationContext.Current posts to
        // Dispatcher.UIThread, so no extra scheduler dependency is needed.
        // docs-snippet:start avalonia-create-adapter
        var adapter = new BindableVm<Note>(
            vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
        // docs-snippet:end avalonia-create-adapter
        return adapter;
    }

    private static TextBlock Bound(BindableVm<Note> adapter, string path)
    {
        var text = new TextBlock { DataContext = adapter };
        text.Bind(TextBlock.TextProperty, new ReflectionBinding(path));
        return text;
    }

    [AvaloniaFact]
    public void The_Ui_Thread_Context_Posts_To_Avalonias_Dispatcher()
    {
        Assert.IsType<AvaloniaSynchronizationContext>(SynchronizationContext.Current);
        Assert.True(Dispatcher.UIThread.CheckAccess());
    }

    [AvaloniaFact]
    public void Bindings_Show_The_Current_Values_At_Once()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        vm.Construct();
        using var adapter = CreateAdapter(vm);

        var title = Bound(adapter, "Model.Title");
        var name = Bound(adapter, nameof(BindableVm<Note>.Name));
        var status = Bound(adapter, nameof(BindableVm<Note>.Status));

        Assert.Equal("draft", title.Text);
        Assert.Equal("note", name.Text);
        Assert.Equal(nameof(ConstructionStatus.Constructed), status.Text);
        vm.Dispose();
    }

    [AvaloniaFact]
    public void A_Worker_Change_Reaches_The_Binding_Once_On_The_Ui_Thread()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        vm.Construct();
        using var adapter = CreateAdapter(vm);
        var title = Bound(adapter, "Model.Title");
        var uiThread = Environment.CurrentManagedThreadId;
        var notifications = new List<(string? Name, int Thread)>();
        adapter.PropertyChanged += (_, e) =>
            notifications.Add((e.PropertyName, Environment.CurrentManagedThreadId));

        var worker = new Thread(() => vm.Model = new Note("from a worker"));
        worker.Start();
        worker.Join();

        // The change waits on Dispatcher.UIThread; nothing touched the binding
        // on the worker thread.
        Assert.Equal("draft", title.Text);
        Assert.Empty(notifications);

        Dispatcher.UIThread.RunJobs();

        Assert.Equal("from a worker", title.Text);
        Assert.Equal([("Model", uiThread)], notifications);
        vm.Dispose();
    }

    [AvaloniaFact]
    public void Status_Follows_The_Lifecycle_Through_The_Dispatcher()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        using var adapter = CreateAdapter(vm);
        var status = Bound(adapter, nameof(BindableVm<Note>.Status));
        Assert.Equal(nameof(ConstructionStatus.Destructed), status.Text);

        vm.Construct();
        Dispatcher.UIThread.RunJobs();
        Assert.Equal(nameof(ConstructionStatus.Constructed), status.Text);

        vm.Destruct();
        Dispatcher.UIThread.RunJobs();
        Assert.Equal(nameof(ConstructionStatus.Destructed), status.Text);
        vm.Dispose();
    }

    [AvaloniaFact]
    public void Dispose_Detaches_The_Adapter_And_Leaves_The_Vm_To_Its_Owner()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        vm.Construct();
        var adapter = CreateAdapter(vm);
        var title = Bound(adapter, "Model.Title");

        adapter.Dispose();
        vm.Model = new Note("after detach");
        Dispatcher.UIThread.RunJobs();

        Assert.Equal("draft", title.Text);
        Assert.Equal(ConstructionStatus.Constructed, vm.Status);
        vm.Dispose();
    }
}
