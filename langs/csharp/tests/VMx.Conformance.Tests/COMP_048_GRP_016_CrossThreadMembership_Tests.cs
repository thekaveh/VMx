using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// A membership change never waits for another thread's membership
/// transaction (spec/06 §4.2, spec/07 §1.1, ADR-0187): COMP-048 and GRP-016.
/// While one thread holds the container's transaction inside an add's
/// construct hook, every add, insert, index replacement, population, transfer
/// out, remove, removeAt and clear from another thread fails at once with the
/// "membership transaction in progress" error and changes nothing.
/// </summary>
public class COMP_048_GRP_016_CrossThreadMembership_Tests
{
    private static readonly IDispatcher Dispatcher = NullDispatcher.Instance;

    /// <summary>A composite whose population a test can start.</summary>
    private sealed class PopulatingComposite(IMessageHub hub)
        : CompositeVMBase<ComponentVM>("p", hub, Dispatcher, autoConstructOnAdd: true)
    {
        public override ViewModelType Type => ViewModelType.Composite;

        public void Populate(params ComponentVM[] children) => AttachPopulation(children);
    }

    /// <summary>A group whose population a test can start.</summary>
    private sealed class PopulatingGroup(IMessageHub hub)
        : GroupVMBase<ComponentVM>("g", hub, Dispatcher, autoConstructOnAdd: true)
    {
        public override ViewModelType Type => ViewModelType.Group;

        public void Populate(params ComponentVM[] children) => AttachPopulation(children);
    }

    /// <summary>The calls of one container that the rule covers.</summary>
    private sealed record Calls(
        IList<ComponentVM> List,
        Action<ComponentVM[]> Populate,
        Action<ComponentVM> TransferOut,
        Func<IReadOnlyList<ComponentVM>> Snapshot,
        Func<IReadOnlyList<ComponentVM>> DestinationSnapshot);

    private static ComponentVM Child(IMessageHub hub, string name, Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder().Name(name).Services(hub, Dispatcher);
        return (onConstruct is null ? builder : builder.OnConstruct(onConstruct)).Build();
    }

    private static Exception? Attempt(Action call)
    {
        try
        {
            call();
            return null;
        }
        catch (Exception error)
        {
            return error;
        }
    }

    /// <summary>Runs every covered call once; returns each call's error.</summary>
    private static Dictionary<string, Exception?> RunEveryCall(
        Calls calls, IMessageHub hub, ComponentVM existing)
    {
        return new Dictionary<string, Exception?>
        {
            ["add"] = Attempt(() => calls.List.Add(Child(hub, "y"))),
            ["insert"] = Attempt(() => calls.List.Insert(0, Child(hub, "w"))),
            ["replace"] = Attempt(() => calls.List[0] = Child(hub, "v")),
            ["population"] = Attempt(() => calls.Populate([Child(hub, "z")])),
            ["transfer"] = Attempt(() => calls.TransferOut(existing)),
            ["remove"] = Attempt(() => calls.List.Remove(existing)),
            ["removeAt"] = Attempt(() => calls.List.RemoveAt(0)),
            ["clear"] = Attempt(calls.List.Clear),
        };
    }

    /// <summary>
    /// Holds the container's transaction on one thread inside an add's
    /// construct hook, and runs every covered call from another thread.
    /// </summary>
    private static void AssertRefusedAtOnceThenAdmitted(
        TestHub hub,
        Calls calls,
        INotifyCollectionChanged container,
        INotifyCollectionChanged destination,
        ComponentVM existing,
        Func<object?>? current = null)
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var held = Child(hub, "x", () =>
        {
            entered.Set();
            // Longer than the bound below, so a waiting call fails the test.
            release.Wait(Liveness.HangGuard * 2);
        });
        var holder = Task.Run(() => calls.List.Add(held));
        try
        {
            entered.Wait(Liveness.HangGuard).Should().BeTrue("the add holds the transaction in its hook");
            var before = calls.Snapshot().ToArray();
            var destinationBefore = calls.DestinationSnapshot().ToArray();
            var currentBefore = current?.Invoke();
            var events = new List<NotifyCollectionChangedAction>();
            NotifyCollectionChangedEventHandler record = (_, args) =>
            {
                lock (events) events.Add(args.Action);
            };
            container.CollectionChanged += record;
            destination.CollectionChanged += record;

            var refused = Task.Run(() => RunEveryCall(calls, hub, existing));
            refused.Wait(Liveness.HangGuard).Should().BeTrue("no call waits for the open transaction");
            holder.IsCompleted.Should().BeFalse("the transaction is still open");

            container.CollectionChanged -= record;
            destination.CollectionChanged -= record;
            foreach (var (call, error) in refused.Result)
            {
                error.Should().BeOfType<InvalidOperationException>(call)
                    .Which.Message.Should().Contain("membership transaction", call);
            }
            calls.Snapshot().Should().Equal(before, "the refused calls change nothing");
            calls.DestinationSnapshot().Should().Equal(destinationBefore);
            ((IComponentVMInternals)existing).Parent.Should().BeSameAs(container);
            current?.Invoke().Should().BeSameAs(currentBefore);
            lock (events) events.Should().BeEmpty("a refused call publishes no collection change");
        }
        finally
        {
            release.Set();
        }

        holder.Wait(Liveness.HangGuard).Should().BeTrue();
        holder.IsCompletedSuccessfully.Should().BeTrue();

        // After the transaction ends, the same calls succeed.
        var admitted = RunEveryCall(calls, hub, existing);
        foreach (var (call, error) in admitted)
            error.Should().BeNull(call);
        calls.Snapshot().Should().BeEmpty("the last call clears the container");
        calls.DestinationSnapshot().Should().Contain(existing);
    }

    [Fact]
    [Trait("Conformance", "COMP-048")]
    public void Composite_Membership_Changes_Fail_At_Once_During_Another_Threads_Transaction()
    {
        var hub = new TestHub();
        var p = new PopulatingComposite(hub);
        var destination = CompositeVM<ComponentVM>.Builder().Name("q").Services(hub, Dispatcher)
            .Children(() => Array.Empty<ComponentVM>()).Build();
        var existing = Child(hub, "c0");
        var selected = Child(hub, "c1");
        p.Add(existing);
        p.Add(selected);
        p.Construct();
        destination.Construct();
        p.Current = selected;

        AssertRefusedAtOnceThenAdmitted(
            hub,
            new Calls(p, children => p.Populate(children), destination.Add, p.Snapshot, destination.Snapshot),
            p,
            destination,
            existing,
            () => p.Current);
    }

    [Fact]
    [Trait("Conformance", "GRP-016")]
    public void Group_Membership_Changes_Fail_At_Once_During_Another_Threads_Transaction()
    {
        var hub = new TestHub();
        var g = new PopulatingGroup(hub);
        var destination = GroupVM<ComponentVM>.Builder().Name("q").Services(hub, Dispatcher)
            .Children(() => Array.Empty<ComponentVM>()).Build();
        var existing = Child(hub, "c0");
        g.Add(existing);
        g.Construct();
        destination.Construct();

        AssertRefusedAtOnceThenAdmitted(
            hub,
            new Calls(g, children => g.Populate(children), destination.Add, g.Snapshot, destination.Snapshot),
            g,
            destination,
            existing);
    }
}
