using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Internal;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Services;

/// <summary>
/// A hub drain and a container membership transaction share one wait-for
/// graph (#1055). Thread B drains the hub and, inside a subscriber, waits for
/// the container that thread A changes; thread A owns that container's
/// transaction and waits to send on the hub. The wait that closes the cycle
/// takes its escape instead of hanging both threads.
/// </summary>
public class HubMembershipWaitCycleTests
{
    private sealed record Marker(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    private static ComponentVM<string> Child(IMessageHub hub, string name) => ComponentVM<string>.Builder()
        .Name(name)
        .Services(hub, NullDispatcher.Instance)
        .Model(name)
        .Build();

    private static IList<ComponentVM<string>> Container(IMessageHub hub, string kind) => kind == "group"
        ? GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(hub, NullDispatcher.Instance)
            .AutoConstructOnAdd(true).Children(() => Array.Empty<ComponentVM<string>>()).Build()
        : CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, NullDispatcher.Instance)
            .AutoConstructOnAdd(true).Children(() => Array.Empty<ComponentVM<string>>()).Build();

    [Theory]
    [InlineData("group", "add")]
    [InlineData("group", "dispose")]
    [InlineData("composite", "dispose")]
    public async Task Hub_Drain_And_Membership_Transaction_Do_Not_Deadlock(string kind, string step3)
    {
        // Disposed only after both threads finish: a Dispose on a regression
        // would wait for the stuck drainer and hang the run.
        var hub = new MessageHub();
        var container = Container(hub, kind);
        ((IComponentVM)container).Construct();
        var x = Child(hub, "x");
        var y = Child(hub, "y");
        var ownerThread = 0;
        Exception? step3Error = null;
        using var drainerEntered = new ManualResetEventSlim(false);
        using var subscription = hub.Messages.OfType<Marker>().Subscribe(_ =>
        {
            // Thread B drains the hub here.
            drainerEntered.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref ownerThread) != 0 &&
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref ownerThread)),
                HangGuard).Should().BeTrue("thread A waits to send on the hub");
            try
            {
                if (step3 == "add") container.Add(y);
                else ((IDisposable)container).Dispose();
            }
            catch (Exception error)
            {
                step3Error = error;
            }
        });

        var drainer = Task.Factory.StartNew(
            () => hub.Send(new Marker("b")),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        drainerEntered.Wait(HangGuard).Should().BeTrue();
        Exception? ownerError = null;
        var owner = Task.Factory.StartNew(
            () =>
            {
                Volatile.Write(ref ownerThread, Environment.CurrentManagedThreadId);
                // Auto-constructs x, which sends on the hub inside the transaction.
                try { container.Add(x); }
                catch (Exception error) { ownerError = error; }
            },
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

        var both = Task.WhenAll(drainer, owner);
        (await Task.WhenAny(both, Task.Delay(HangGuard))).Should().BeSameAs(both,
            "the hub drain and the membership transaction must not deadlock");
        await both;
        hub.Dispose();

        if (step3 == "add")
        {
            ownerError.Should().BeNull();
            x.Status.Should().Be(ConstructionStatus.Constructed);
            container.Should().Contain(x);
            if (step3Error is null) container.Should().Contain(y);
            else step3Error.Should().BeOfType<InvalidOperationException>();
        }
        else
        {
            // The disposal defers to A's transaction, so A's add, not yet
            // admitted, fails as the container is disposing.
            step3Error.Should().BeNull();
            ownerError.Should().BeOfType<ObjectDisposedException>();
            container.Should().NotContain(x);
            SpinWait.SpinUntil(() => ((IComponentVM)container).Status == ConstructionStatus.Disposed, HangGuard)
                .Should().BeTrue();
        }
    }

    // #1055 review: B disposes the hub, so A's send returns and A's
    // transaction ends. B's add must then wait for that transaction, not be
    // refused through A's edge to the disposed hub.
    [Theory]
    [InlineData("group")]
    [InlineData("composite")]
    public async Task Drainer_That_Disposes_The_Hub_Then_Adds_Is_Not_Refused(string kind)
    {
        var hub = new MessageHub();
        var container = Container(hub, kind);
        ((IComponentVM)container).Construct();
        var x = Child(hub, "x");
        var y = Child(hub, "y");
        var ownerThread = 0;
        var ownerEdgeAfterDispose = true;
        Exception? step3Error = null;
        using var drainerEntered = new ManualResetEventSlim(false);
        using var subscription = hub.Messages.OfType<Marker>().Subscribe(_ =>
        {
            drainerEntered.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref ownerThread) != 0 &&
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref ownerThread)),
                HangGuard).Should().BeTrue("thread A waits to send on the hub");
            hub.Dispose();
            ownerEdgeAfterDispose = WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref ownerThread));
            try { container.Add(y); }
            catch (Exception error) { step3Error = error; }
        });

        var drainer = Task.Factory.StartNew(
            () => hub.Send(new Marker("b")),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        drainerEntered.Wait(HangGuard).Should().BeTrue();
        Exception? ownerError = null;
        var owner = Task.Factory.StartNew(
            () =>
            {
                Volatile.Write(ref ownerThread, Environment.CurrentManagedThreadId);
                try { container.Add(x); }
                catch (Exception error) { ownerError = error; }
            },
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

        var both = Task.WhenAll(drainer, owner);
        (await Task.WhenAny(both, Task.Delay(HangGuard))).Should().BeSameAs(both,
            "the disposed hub releases A, so B's add waits for A's transaction");
        await both;

        ownerEdgeAfterDispose.Should().BeFalse("disposing the hub drops every wait edge on it");
        ownerError.Should().BeNull();
        container.Should().Contain(x);
        if (kind == "group")
        {
            step3Error.Should().BeNull("no cycle remains once the hub is disposed");
            container.Should().Contain(y);
        }
        else if (step3Error is null)
        {
            container.Should().Contain(y);
        }
        else
        {
            // A composite add never waits for another thread's transaction: it
            // fails fast while A's transaction is still open.
            step3Error.Should().BeOfType<InvalidOperationException>()
                .Which.Message.Should().Contain("already in progress");
        }
    }
}
