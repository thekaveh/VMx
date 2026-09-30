using System.Reactive.Concurrency;
using System.Reflection;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Integration;

/// <summary>
/// Executes the WPF and MAUI adapter recipe. docs/content/integration/wpf.md and
/// maui.md embed <see cref="BindableVm{M}"/>, and tools/tests/test_host_recipe_sync.py
/// keeps them identical. No conformance-ID markers (integration recipe).
/// </summary>
public class XamlRecipeTests
{
    private static readonly TimeSpan HangGuard = TimeSpan.FromSeconds(30);

    private sealed record Note(string Title);

    private static ComponentVM<Note> CreateVm(MessageHub hub, bool construct = true)
    {
        var vm = ComponentVM<Note>.Builder()
            .Name("note")
            .Services(hub, RxDispatcher.Immediate())
            .Model(new Note("draft"))
            .Build();
        if (construct)
            vm.Construct();
        return vm;
    }

    private static List<string> RecordNames(BindableVm<Note> source)
    {
        var names = new List<string>();
        source.PropertyChanged += (_, e) => names.Add(e.PropertyName ?? string.Empty);
        return names;
    }

    private static int PropertyChangedHandlerCount(ComponentVM<Note> vm)
    {
        // The field-like event's backing delegate is private; reading it is the
        // only direct way to prove the adapter left no handler behind.
        var field = typeof(ComponentVMBase).GetField(
            nameof(ComponentVMBase.PropertyChanged),
            BindingFlags.Instance | BindingFlags.NonPublic);
        return (field?.GetValue(vm) as Delegate)?.GetInvocationList().Length ?? 0;
    }

    [Fact]
    public void Model_Name_And_Status_Are_Readable_Right_After_Binding()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);

        using var adapter = new BindableVm<Note>(vm, new TestScheduler());

        adapter.Model.Title.Should().Be("draft");
        adapter.Name.Should().Be("note");
        adapter.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Construct_Destruct_And_Dispose_Reach_The_Binding_As_Status_Notifications()
    {
        using var hub = new MessageHub();
        var hubPropertyNames = new List<string>();
        var hubStatuses = new List<ConstructionStatus>();
        using var hubSubscription = hub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<object> changed)
                hubPropertyNames.Add(changed.PropertyName);
            if (message is ConstructionStatusChangedMessage status)
                hubStatuses.Add(status.Status);
        });
        var vm = CreateVm(hub, construct: false);
        var host = new TestScheduler();
        using var adapter = new BindableVm<Note>(vm, host);
        var shown = new List<ConstructionStatus>();
        adapter.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(BindableVm<Note>.Status))
                shown.Add(adapter.Status);
        };

        vm.Construct();
        host.Start();
        adapter.Status.Should().Be(ConstructionStatus.Constructed);
        vm.Destruct();
        host.Start();
        adapter.Status.Should().Be(ConstructionStatus.Destructed);
        vm.Dispose();
        host.Start();
        adapter.Status.Should().Be(ConstructionStatus.Disposed);

        // One Status notification per lifecycle message; each one is handled
        // after its transition completed, so it shows the current status.
        shown.Should().HaveCount(hubStatuses.Count);
        shown.Distinct().Should().Equal(
            ConstructionStatus.Constructed,
            ConstructionStatus.Destructed,
            ConstructionStatus.Disposed);
        hubPropertyNames.Should().NotContain(nameof(ComponentVMBase.Status));
    }

    [Fact]
    public void Each_Model_Assignment_Notifies_The_Binding_Once()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        var host = new TestScheduler();
        using var adapter = new BindableVm<Note>(vm, host);
        var names = RecordNames(adapter);

        vm.Model = new Note("first");
        vm.Model = new Note("second");
        host.Start();

        names.Count(name => name == nameof(BindableVm<Note>.Model)).Should().Be(2);
        adapter.Model.Title.Should().Be("second");
    }

    [Fact]
    public void A_Worker_Thread_Change_Waits_For_The_Host_Scheduler()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        var host = new TestScheduler();
        using var adapter = new BindableVm<Note>(vm, host);
        var deliveredOn = new List<int>();
        adapter.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(BindableVm<Note>.Model))
                deliveredOn.Add(Environment.CurrentManagedThreadId);
        };

        var worker = new Thread(() => vm.Model = new Note("from worker"));
        worker.Start();
        worker.Join();

        deliveredOn.Should().BeEmpty("bound state is only touched on the host thread");
        host.Start();
        deliveredOn.Should().Equal(Environment.CurrentManagedThreadId);
        adapter.Model.Title.Should().Be("from worker");
    }

    [Fact]
    public void A_Worker_Thread_Change_Is_Delivered_On_A_Running_Host_Loop()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        using var host = new EventLoopScheduler(start => new Thread(start) { Name = "vmx-host", IsBackground = true });
        using var delivered = new ManualResetEventSlim();
        string? deliveredOn = null;
        using var adapter = new BindableVm<Note>(vm, host);
        adapter.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName != nameof(BindableVm<Note>.Model))
                return;
            deliveredOn = Thread.CurrentThread.Name;
            delivered.Set();
        };

        var worker = new Thread(() => vm.Model = new Note("from worker")) { Name = "vmx-worker" };
        worker.Start();
        worker.Join();

        delivered.Wait(HangGuard).Should().BeTrue();
        deliveredOn.Should().Be("vmx-host");
        adapter.Model.Title.Should().Be("from worker");
    }

    [Fact]
    public void Dispose_Detaches_The_Adapter_And_Leaves_The_Vm_To_Its_Owner()
    {
        using var hub = new MessageHub();
        var vm = CreateVm(hub);
        var host = new TestScheduler();
        var adapter = new BindableVm<Note>(vm, host);
        var names = RecordNames(adapter);
        PropertyChangedHandlerCount(vm).Should().Be(1);

        adapter.Dispose();
        vm.Model = new Note("after teardown");
        host.Start();

        PropertyChangedHandlerCount(vm).Should().Be(0);
        names.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }
}
