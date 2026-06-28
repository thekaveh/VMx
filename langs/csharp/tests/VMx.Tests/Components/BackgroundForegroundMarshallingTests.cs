using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// VMX-025 regression: a background <c>Construct()</c>/<c>Destruct()</c> must
/// marshal its terminal status emission (the <c>Constructed</c>/<c>Destructed</c>
/// <see cref="ConstructionStatusChangedMessage"/> + INPC) onto
/// <see cref="IDispatcher.Foreground"/> so UI subscribers observe the terminal
/// transition on the foreground thread, not the background (pool) thread.
///
/// The <c>OnConstruct()</c>/<c>OnDestruct()</c> work still runs on the background
/// scheduler (THR-002); only the terminal emission hops to the foreground. The
/// disposed re-check stays atomic — a Dispose() that lands before the marshalled
/// emission runs still aborts it (no resurrection, no post-dispose publish).
/// </summary>
public class BackgroundForegroundMarshallingTests
{
    [Fact]
    public void Background_Construct_Marshals_Constructed_Emission_Onto_Foreground_Scheduler()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        using var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .Build();

        var constructedSeen = new List<ConstructionStatus>();
        using var sub = hub.Messages
            .OfType<IConstructionStatusChangedMessage>()
            .Where(m => ReferenceEquals(m.SenderObject, vm) &&
                        m.Status == ConstructionStatus.Constructed)
            .Subscribe(m => constructedSeen.Add(m.Status));

        vm.Construct();

        // Run the background work (OnConstruct). The terminal Constructed emission
        // is now queued on the FOREGROUND scheduler — NOT emitted inline on the
        // background thread — so neither the status nor the hub message has reached
        // Constructed yet.
        dispatcher.BackgroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Constructing,
            "the terminal Constructed emission is marshalled onto the foreground scheduler (VMX-025)");
        constructedSeen.Should().BeEmpty(
            "the Constructed ConstructionStatusChangedMessage must be delivered via the foreground " +
            "scheduler, not inline on the background (pool) thread");

        // Advance the foreground scheduler — the marshalled terminal emission runs.
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Constructed,
            "after the foreground scheduler advances, the terminal transition completes");
        constructedSeen.Should().ContainSingle()
            .Which.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Background_Destruct_Marshals_Destructed_Emission_Onto_Foreground_Scheduler()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        using var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .Build();

        // Bring the VM to Constructed (background construct, drained on both schedulers).
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        dispatcher.ForegroundScheduler.AdvanceBy(1);
        vm.Status.Should().Be(ConstructionStatus.Constructed);

        var destructedSeen = new List<ConstructionStatus>();
        using var sub = hub.Messages
            .OfType<IConstructionStatusChangedMessage>()
            .Where(m => ReferenceEquals(m.SenderObject, vm) &&
                        m.Status == ConstructionStatus.Destructed)
            .Subscribe(m => destructedSeen.Add(m.Status));

        vm.Destruct();

        // Run the background OnDestruct work; the terminal Destructed emission is
        // queued on the foreground scheduler.
        dispatcher.BackgroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Destructing,
            "the terminal Destructed emission is marshalled onto the foreground scheduler (VMX-025)");
        destructedSeen.Should().BeEmpty(
            "the Destructed ConstructionStatusChangedMessage must be delivered via the foreground scheduler");

        dispatcher.ForegroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Destructed);
        destructedSeen.Should().ContainSingle()
            .Which.Should().Be(ConstructionStatus.Destructed);
    }
}
