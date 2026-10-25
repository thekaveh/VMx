using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Groups;

/// <summary>
/// A cross-thread <c>Dispose()</c> waits for the container's open membership
/// transaction (ADR-0122), unless that wait would close a wait-for cycle: then
/// it records its intent, and the transaction owner disposes the container
/// when its transaction ends (#717).
/// </summary>
public class ContainerDisposalWaitCycleTests
{
    private static ComponentVM<string> Child(string name) => ComponentVM<string>.Builder()
        .Name(name)
        .Services(NullMessageHub.Instance, NullDispatcher.Instance)
        .Model(name)
        .Build();

    private static GroupVM<ComponentVM<string>> Group(string name) => GroupVM<ComponentVM<string>>.Builder()
        .Name(name)
        .Services(NullMessageHub.Instance, NullDispatcher.Instance)
        .Children(() => Array.Empty<ComponentVM<string>>())
        .Build();

    private static CompositeVM<ComponentVM<string>> Composite(string name) => CompositeVM<ComponentVM<string>>.Builder()
        .Name(name)
        .Services(NullMessageHub.Instance, NullDispatcher.Instance)
        .Children(() => Array.Empty<ComponentVM<string>>())
        .Build();

    public static IEnumerable<object[]> Destinations()
    {
        yield return ["group"];
        yield return ["composite"];
    }

    private static IList<ComponentVM<string>> Destination(string kind)
        => kind == "group" ? Group("x") : Composite("x");

    private static bool Contains(IList<ComponentVM<string>> container, ComponentVM<string> child)
        => container.Any(item => ReferenceEquals(item, child));

    // Thread B adds to Y and blocks in Y's CollectionChanged handler, inside
    // Y's transaction. Thread A adds Y's child c to X, so A holds X's
    // transaction and waits for Y's. B's handler then disposes X.
    [Theory]
    [MemberData(nameof(Destinations))]
    public async Task Disposal_That_Would_Close_A_Membership_Cycle_Defers_To_The_Owner(string kind)
    {
        var y = Group("y");
        var c = Child("c");
        y.Add(c);
        var x = Destination(kind);
        using var bInHandler = new ManualResetEventSlim();
        using var aWaiting = new ManualResetEventSlim();
        var blockOnce = 1;
        ((INotifyCollectionChanged)y).CollectionChanged += (_, _) =>
        {
            if (Interlocked.Exchange(ref blockOnce, 0) == 0) return;
            bInHandler.Set();
            aWaiting.Wait(HangGuard);
            ((IDisposable)x).Dispose();
        };

        var b = Task.Run(() => y.Add(Child("e")));
        bInHandler.Wait(HangGuard).Should().BeTrue();
        var a = Task.Run(() =>
        {
            try { x.Add(c); }
            catch (InvalidOperationException) { }
        });
        // A blocks in its transfer wait for Y's transaction, which B holds.
        await Task.Delay(200);
        aWaiting.Set();

        var both = Task.WhenAll(a, b);
        (await Task.WhenAny(both, Task.Delay(HangGuard))).Should().BeSameAs(both, "neither thread may hang");
        await both;
        ((IComponentVM)x).Status.Should().Be(ConstructionStatus.Disposed);
        new[] { Contains(x, c), Contains(y, c) }.Count(found => found).Should().Be(1,
            "c is a child of exactly one container");
    }
    // Without a cycle, a cross-thread Dispose() waits for the add to end, and
    // its child snapshot includes the added child (ADR-0122).
    [Theory]
    [MemberData(nameof(Destinations))]
    public async Task Disposal_Waits_For_An_Add_On_Another_Thread(string kind)
    {
        var x = Destination(kind);
        var added = Child("added");
        using var aInHandler = new ManualResetEventSlim();
        using var releaseA = new ManualResetEventSlim();
        var addEnded = 0;
        ((INotifyCollectionChanged)x).CollectionChanged += (_, _) =>
        {
            aInHandler.Set();
            releaseA.Wait(HangGuard);
            Volatile.Write(ref addEnded, 1);
        };

        var a = Task.Run(() => x.Add(added));
        aInHandler.Wait(HangGuard).Should().BeTrue();
        var addEndedBeforeDispose = -1;
        var b = Task.Run(() =>
        {
            ((IDisposable)x).Dispose();
            addEndedBeforeDispose = Volatile.Read(ref addEnded);
        });
        await Task.Delay(200);
        b.IsCompleted.Should().BeFalse("Dispose() waits for the open transaction");
        releaseA.Set();

        var both = Task.WhenAll(a, b);
        (await Task.WhenAny(both, Task.Delay(HangGuard))).Should().BeSameAs(both, "neither thread may hang");
        await both;
        addEndedBeforeDispose.Should().Be(1, "Dispose() returns only after the add ends");
        ((IComponentVM)x).Status.Should().Be(ConstructionStatus.Disposed);
        ((IComponentVM)added).Status.Should().Be(ConstructionStatus.Disposed,
            "the disposal snapshot includes the added child");
    }
}
