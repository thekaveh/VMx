using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Regression tests for async-lifecycle termination and dispose races
/// (spec/02-lifecycle.md invariant 3: Disposed is terminal).
/// </summary>
public class ComponentVMLifecycleRaceTests
{
    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildBackgroundVm()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .Build();
        return (vm, hub, dispatcher);
    }

    [Fact]
    public void ConstructAsync_On_Already_Constructed_Background_Vm_Completes_Synchronously()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        vm.Status.Should().Be(ConstructionStatus.Constructed);

        var task = vm.ConstructAsync();

        task.IsCompletedSuccessfully.Should().BeTrue(
            "already-Constructed is an idempotent no-op that emits no status message to wait for");
    }

    [Fact]
    public void DestructAsync_On_Already_Destructed_Background_Vm_Completes_Synchronously()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        vm.Destruct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        vm.Status.Should().Be(ConstructionStatus.Destructed);

        var task = vm.DestructAsync();

        task.IsCompletedSuccessfully.Should().BeTrue(
            "already-Destructed is an idempotent no-op that emits no status message to wait for");
    }

    [Fact]
    public void Dispose_During_InFlight_Background_Construct_Does_Not_Resurrect()
    {
        var (vm, hub, dispatcher) = BuildBackgroundVm();
        var statuses = new List<ConstructionStatus>();
        using var sub = hub.Messages
            .OfType<IConstructionStatusChangedMessage>()
            .Where(m => ReferenceEquals(m.SenderObject, vm))
            .Subscribe(m => statuses.Add(m.Status));

        vm.Construct();                               // Constructing emitted; work scheduled
        vm.Dispose();                                 // terminal before background work runs
        dispatcher.BackgroundScheduler.AdvanceBy(1);  // background lambda must now no-op

        vm.Status.Should().Be(ConstructionStatus.Disposed);
        statuses.Should().NotContain(ConstructionStatus.Constructed,
            "a disposed VM must not publish post-dispose status messages");
        statuses[^1].Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public async Task ConstructAsync_Completes_When_Vm_Is_Disposed_Mid_Flight()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();

        var task = vm.ConstructAsync();
        vm.Dispose();
        dispatcher.BackgroundScheduler.AdvanceBy(1);

        var completed = await Task.WhenAny(task, Task.Delay(TimeSpan.FromSeconds(5)));
        completed.Should().BeSameAs(task,
            "the awaiter must observe the Disposed transition instead of hanging");
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
