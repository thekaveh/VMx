using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Internal;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Groups;

/// <summary>
/// Cross-thread membership transactions on <see cref="GroupVM{VM}"/> (#718).
/// A group waits for another thread's transaction, unless that wait would
/// close a wait-for cycle: then the add is refused with
/// <see cref="InvalidOperationException"/> and changes nothing. A wait for a
/// child's ownership gate joins the same graph (#1047).
/// </summary>
public class GroupTransferWaitCycleTests
{
    private const int RaceIterations = 300;

    private static ComponentVM<string> Child(string name, Action? onConstruct = null)
    {
        var builder = ComponentVM<string>.Builder()
            .Name(name)
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Model(name);
        return (onConstruct is null ? builder : builder.OnConstruct(onConstruct)).Build();
    }

    private static GroupVM<ComponentVM<string>> Group(
        string name, bool autoConstructOnAdd = false, params ComponentVM<string>[] children)
    {
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .AutoConstructOnAdd(autoConstructOnAdd)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        foreach (var child in children) group.Add(child);
        return group;
    }

    private static Exception? Attempt(Action add)
    {
        try
        {
            add();
            return null;
        }
        catch (Exception error)
        {
            return error;
        }
    }

    private static async Task<(Exception? First, Exception? Second)> CompleteWithinHangGuard(
        Task<Exception?> first, Task<Exception?> second, string because)
    {
        var both = Task.WhenAll(first, second);
        (await Task.WhenAny(both, Task.Delay(HangGuard))).Should().BeSameAs(both, because);
        return (await first, await second);
    }

    private static void ShouldBeRefusal(Exception? error)
    {
        error.Should().NotBeNull();
        error.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Contain("membership transaction");
    }

    private static void ShouldBeOwnedBy(ComponentVM<string> child, GroupVM<ComponentVM<string>> owner,
        params GroupVM<ComponentVM<string>>[] others)
    {
        ((IComponentVMInternals)child).Parent.Should().BeSameAs(owner, $"{child.Name} has one parent");
        owner.Snapshot().Count(item => ReferenceEquals(item, child)).Should().Be(1);
        foreach (var other in others)
            other.Snapshot().Should().NotContain(item => ReferenceEquals(item, child));
    }

    private static void ShouldBeUnowned(ComponentVM<string> child,
        params GroupVM<ComponentVM<string>>[] groups)
    {
        ((IComponentVMInternals)child).Parent.Should().BeNull($"{child.Name} was never attached");
        foreach (var group in groups)
            group.Snapshot().Should().NotContain(item => ReferenceEquals(item, child));
    }

    // (a) + (b): opposing transfers race on two threads.
    [Fact]
    public async Task Opposing_Transfers_On_Two_Threads_Complete_With_Single_Ownership()
    {
        for (var iteration = 0; iteration < RaceIterations; iteration++)
        {
            var a = Child("a");
            var b = Child("b");
            var g1 = Group("g1", children: a);
            var g2 = Group("g2", children: b);
            using var barrier = new Barrier(2);

            var first = Task.Run(() =>
            {
                barrier.SignalAndWait(HangGuard);
                return Attempt(() => g1.Add(b));
            });
            var second = Task.Run(() =>
            {
                barrier.SignalAndWait(HangGuard);
                return Attempt(() => g2.Add(a));
            });
            var (firstError, secondError) = await CompleteWithinHangGuard(
                first, second, $"opposing adds must not deadlock (iteration {iteration})");

            (firstError is not null && secondError is not null)
                .Should().BeFalse("only the wait that closes the cycle is refused");
            if (firstError is null && secondError is null)
            {
                ShouldBeOwnedBy(b, g1, g2);
                ShouldBeOwnedBy(a, g2, g1);
                g1.Count.Should().Be(1);
                g2.Count.Should().Be(1);
            }
            else if (secondError is not null)
            {
                // g2.Add(a) was refused: it left both groups as g1.Add(b) made them.
                ShouldBeRefusal(secondError);
                ShouldBeOwnedBy(a, g1, g2);
                ShouldBeOwnedBy(b, g1, g2);
                g1.Snapshot().Should().Equal(a, b);
                g2.Count.Should().Be(0);
            }
            else
            {
                // g1.Add(b) was refused: it left both groups as g2.Add(a) made them.
                ShouldBeRefusal(firstError);
                ShouldBeOwnedBy(a, g2, g1);
                ShouldBeOwnedBy(b, g2, g1);
                g2.Snapshot().Should().Equal(b, a);
                g1.Count.Should().Be(0);
            }
        }
    }

    // Opposing replacements take the indexer path, whose failure must also end
    // the group's transaction; otherwise a refusal there blocks later callers.
    [Fact]
    public async Task Opposing_Replacements_On_Two_Threads_Complete_And_Leave_No_Open_Transaction()
    {
        for (var iteration = 0; iteration < RaceIterations; iteration++)
        {
            var a = Child("a");
            var b = Child("b");
            var g1 = Group("g1", children: a);
            var g2 = Group("g2", children: b);
            using var barrier = new Barrier(2);

            var first = Task.Run(() =>
            {
                barrier.SignalAndWait(HangGuard);
                return Attempt(() => g1[0] = b);
            });
            var second = Task.Run(() =>
            {
                barrier.SignalAndWait(HangGuard);
                return Attempt(() => g2[0] = a);
            });
            var (firstError, secondError) = await CompleteWithinHangGuard(
                first, second, $"opposing replacements must not deadlock (iteration {iteration})");

            // A loser is either refused, or finds its slot gone because the
            // winner moved that child out of its group.
            foreach (var error in new[] { firstError, secondError })
            {
                if (error is ArgumentOutOfRangeException) continue;
                if (error is not null) ShouldBeRefusal(error);
            }
            foreach (var child in new[] { a, b })
            {
                var parent = ((IComponentVMInternals)child).Parent;
                foreach (var group in new[] { g1, g2 })
                    group.Snapshot().Count(item => ReferenceEquals(item, child))
                        .Should().Be(ReferenceEquals(parent, group) ? 1 : 0,
                            $"{child.Name}'s parent and memberships agree (iteration {iteration})");
            }

            // Neither group kept an open transaction: adds from another thread complete.
            var late = Task.Run(() =>
            {
                g1.Add(Child("late1"));
                g2.Add(Child("late2"));
            });
            (await Task.WhenAny(late, Task.Delay(HangGuard))).Should().BeSameAs(late,
                $"a refused replacement must end its transaction (iteration {iteration})");
            await late;
        }
    }

    // (b) + (c): both threads hold their group's transaction inside a construct
    // hook, then add to the other group. One wait closes the cycle every time.
    [Fact]
    public async Task Opposing_Adds_From_Construct_Hooks_Complete_And_Refusal_Changes_Nothing()
    {
        for (var iteration = 0; iteration < 20; iteration++)
        {
            var a = Child("a");
            var b = Child("b");
            var g1 = Group("g1", autoConstructOnAdd: true, a);
            var g2 = Group("g2", autoConstructOnAdd: true, b);
            g1.Construct();
            g2.Construct();
            var p = Child("p");
            var q = Child("q");
            using var barrier = new Barrier(2);
            var x = Child("x", () =>
            {
                barrier.SignalAndWait(HangGuard).Should().BeTrue();
                g2.Add(p);
            });
            var y = Child("y", () =>
            {
                barrier.SignalAndWait(HangGuard).Should().BeTrue();
                g1.Add(q);
            });

            var first = Task.Run(() => Attempt(() => g1.Add(x)));
            var second = Task.Run(() => Attempt(() => g2.Add(y)));
            var (firstError, secondError) = await CompleteWithinHangGuard(
                first, second, $"opposing hook adds must not deadlock (iteration {iteration})");

            ((firstError is null) ^ (secondError is null))
                .Should().BeTrue("exactly one wait closes the cycle and is refused");
            if (secondError is not null)
            {
                ShouldBeRefusal(secondError);
                g1.Snapshot().Should().Equal(a, x);
                g2.Snapshot().Should().Equal(b, p);
                ShouldBeOwnedBy(x, g1, g2);
                ShouldBeOwnedBy(p, g2, g1);
                ShouldBeUnowned(y, g1, g2);
                ShouldBeUnowned(q, g1, g2);
            }
            else
            {
                ShouldBeRefusal(firstError);
                g1.Snapshot().Should().Equal(a, q);
                g2.Snapshot().Should().Equal(b, y);
                ShouldBeOwnedBy(y, g2, g1);
                ShouldBeOwnedBy(q, g1, g2);
                ShouldBeUnowned(x, g1, g2);
                ShouldBeUnowned(p, g1, g2);
            }
            ShouldBeOwnedBy(a, g1, g2);
            ShouldBeOwnedBy(b, g2, g1);
        }
    }

    // (d): a cross-thread add that closes no cycle waits, then succeeds. The
    // thread that ended the awaited transaction can then add to the waiter's
    // group at once: the waiter's finished wait no longer counts (#736).
    [Fact]
    public async Task Cross_Thread_Add_Without_Cycle_Waits_Then_Succeeds()
    {
        for (var iteration = 0; iteration < 20; iteration++)
        {
            var b = Child("b");
            var f = Child("f");
            var g1 = Group("g1");
            var g2 = Group("g2", autoConstructOnAdd: true, b);
            g2.Construct();
            using var entered = new ManualResetEventSlim();
            using var release = new ManualResetEventSlim();
            var y = Child("y", () =>
            {
                entered.Set();
                release.Wait(HangGuard).Should().BeTrue();
            });

            var holder = Task.Run(() => Attempt(() =>
            {
                g2.Add(y);
                g1.Add(f);
            }));
            (await Task.Run(() => entered.Wait(HangGuard))).Should().BeTrue();

            var waiter = Task.Run(() => Attempt(() => g1.Add(b)));
            (await Task.WhenAny(waiter, Task.Delay(TimeSpan.FromMilliseconds(100))))
                .Should().NotBeSameAs(waiter, "g2's transaction is still open on another thread");
            g1.Count.Should().Be(0);

            release.Set();
            var (holderError, waiterError) = await CompleteWithinHangGuard(
                holder, waiter, $"the waiter must resume (iteration {iteration})");

            holderError.Should().BeNull();
            waiterError.Should().BeNull();
            g1.Count.Should().Be(2);
            g2.Snapshot().Should().Equal(y);
            ShouldBeOwnedBy(b, g1, g2);
            ShouldBeOwnedBy(f, g1, g2);
            ShouldBeOwnedBy(y, g2, g1);
        }
    }

    // #1047: T1 holds b's ownership gate and waits for g2's transaction; T2
    // owns that transaction and waits for b's ownership gate. The gate wait
    // joins the wait graph, so the wait that closes the cycle is refused.
    [Fact]
    public async Task Ownership_Gate_Wait_That_Closes_A_Cycle_With_A_Group_Transaction_Is_Refused()
    {
        var b = Child("b");
        var g1 = Group("g1", autoConstructOnAdd: true);
        var g3 = Group("g3", autoConstructOnAdd: true);
        var g2 = Group("g2", autoConstructOnAdd: true, b);
        g1.Construct();
        g3.Construct();
        g2.Construct();
        using var hookEntered = new ManualResetEventSlim(false);
        var firstThread = 0;
        var y = Child("y", onConstruct: () =>
        {
            // The hook runs inside g2's transaction on the second thread.
            hookEntered.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref firstThread) != 0 &&
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref firstThread)),
                HangGuard).Should().BeTrue("the first thread waits for g2's transaction");
            g3.Add(b);
        });

        var second = Task.Run(() => Attempt(() => g2.Add(y)));
        hookEntered.Wait(HangGuard).Should().BeTrue();
        var first = Task.Run(() =>
        {
            Volatile.Write(ref firstThread, Environment.CurrentManagedThreadId);
            return Attempt(() => g1.Add(b));
        });
        var (firstError, secondError) = await CompleteWithinHangGuard(
            first, second, "the gate wait and the group transaction must not deadlock");

        new[] { firstError, secondError }.Should().Contain(error => error is InvalidOperationException);
        foreach (var error in new[] { firstError, secondError })
            if (error is not null) error.Should().BeOfType<InvalidOperationException>();
        var owner = ((IComponentVMInternals)b).Parent;
        owner.Should().BeOneOf(g1, g2, g3);
        foreach (var group in new[] { g1, g2, g3 })
            group.Snapshot().Count(item => ReferenceEquals(item, b))
                .Should().Be(ReferenceEquals(owner, group) ? 1 : 0, $"b has exactly one parent ({group.Name})");
    }

    // #1047: a cycle through two children's ownership gates only. T1 holds aa
    // and waits for bb; T2 holds bb and then waits for aa, which is refused.
    [Fact]
    public async Task Ownership_Gate_Wait_That_Closes_A_Cycle_Of_Gates_Is_Refused()
    {
        var g1 = Group("g1", autoConstructOnAdd: true);
        var g2 = Group("g2", autoConstructOnAdd: true);
        var g3 = Group("g3", autoConstructOnAdd: true);
        var g4 = Group("g4", autoConstructOnAdd: true);
        foreach (var group in new[] { g1, g2, g3, g4 }) group.Construct();
        using var aaEntered = new ManualResetEventSlim(false);
        using var bbEntered = new ManualResetEventSlim(false);
        var firstThread = 0;
        var aaRuns = 0;
        var bbRuns = 0;
        ComponentVM<string>? bb = null;
        var aa = Child("aa", onConstruct: () =>
        {
            // Runs on the first thread, which holds aa's ownership gate.
            if (Interlocked.Increment(ref aaRuns) != 1) return;
            Volatile.Write(ref firstThread, Environment.CurrentManagedThreadId);
            aaEntered.Set();
            bbEntered.Wait(HangGuard).Should().BeTrue();
            g3.Add(bb!);
        });
        bb = Child("bb", onConstruct: () =>
        {
            // Runs on the second thread, which holds bb's ownership gate. After
            // the refusal it runs again on the first thread, as g3 adds bb.
            if (Interlocked.Increment(ref bbRuns) != 1) return;
            bbEntered.Set();
            aaEntered.Wait(HangGuard).Should().BeTrue();
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref firstThread)),
                HangGuard).Should().BeTrue("the first thread waits for bb");
            g4.Add(aa);
        });

        var first = Task.Run(() => Attempt(() => g1.Add(aa)));
        var second = Task.Run(() => Attempt(() => g2.Add(bb)));
        var (firstError, secondError) = await CompleteWithinHangGuard(
            first, second, "two gate holders must not deadlock");

        firstError.Should().BeNull();
        secondError.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Contain("ownership transaction");
        ShouldBeOwnedBy(aa, g1, g2, g4);
        ShouldBeOwnedBy(bb!, g3, g1, g2, g4);
    }

    [Fact]
    public void Wait_Graph_Refuses_Only_The_Edge_That_Closes_A_Cycle()
    {
        var graph = new WaitForGraph();
        object g1 = new(), g2 = new(), g3 = new();
        const int a = 1, b = 2, c = 3;
        graph.Acquire(g1, a);
        graph.Acquire(g2, b);
        graph.Acquire(g3, c);

        graph.TryBeginWait(g2, a).Should().BeTrue("a -> b closes no cycle");
        graph.TryBeginWait(g3, b).Should().BeTrue("b -> c closes no cycle");
        graph.TryBeginWait(g1, c).Should().BeFalse("c -> a closes a -> b -> c");
        graph.TryBeginWait(g1, b).Should().BeFalse("b -> a closes a -> b");

        graph.EndWait(a);
        graph.TryBeginWait(g1, c).Should().BeTrue("a no longer waits");
    }

    [Fact]
    public void Wait_Graph_Ignores_A_Wait_Whose_Transaction_Has_Ended()
    {
        // #736: a waiter that was woken but has not yet removed its edge must
        // not make the thread that ended the transaction see a cycle.
        var graph = new WaitForGraph();
        object g1 = new(), g2 = new();
        const int a = 1, b = 2;
        graph.Acquire(g1, a);
        graph.Acquire(g2, b);
        graph.TryBeginWait(g2, a).Should().BeTrue();

        graph.Release(g2);

        graph.TryBeginWait(g1, b).Should().BeTrue("a waits for an ended transaction");
        graph.EndWait(b);
        graph.Acquire(g2, a);
        graph.TryBeginWait(g1, b).Should().BeTrue("a now owns g2, so b -> a closes no cycle");
    }

    [Fact]
    public void Wait_Graph_Sees_A_Cycle_That_Crosses_A_Hub_Wait()
    {
        // #1055: a hub wait names its owner thread; a membership wait names its
        // container. One graph sees a cycle that uses both kinds of edge.
        var graph = new WaitForGraph();
        object container = new(), hub = new();
        const int owner = 1, drainer = 2;
        graph.Acquire(container, owner);

        graph.TryBeginWait(hub, drainer, owner).Should().BeTrue("the owner waits to send on the hub");
        graph.TryBeginWait(container, drainer).Should().BeFalse("drainer -> owner -> drainer");
    }

    [Fact]
    public void Wait_Graph_Sees_A_Hub_Wait_That_Closes_A_Cycle_Through_A_Container()
    {
        // The reverse order: the drainer waits for the container first, then
        // the container's owner tries to wait for the drainer's hub.
        var graph = new WaitForGraph();
        object container = new(), hub = new();
        const int owner = 1, drainer = 2;
        graph.Acquire(container, owner);

        graph.TryBeginWait(container, drainer).Should().BeTrue("the drainer waits for the transaction");
        graph.TryBeginWait(hub, drainer, owner).Should().BeFalse("owner -> drainer -> container(owner)");
    }

    [Fact]
    public void Wait_Graph_Release_Waiters_Keeps_Waits_On_A_Current_Owner()
    {
        var graph = new WaitForGraph();
        object hub = new();
        const int a = 1, b = 2, drainer = 3, former = 4;
        graph.TryBeginWait(hub, drainer, a).Should().BeTrue();
        graph.TryBeginWait(hub, former, b).Should().BeTrue();

        graph.ReleaseWaiters(hub, drainer);

        graph.IsWaitingForTesting(a).Should().BeTrue("its owner still drains the hub");
        graph.IsWaitingForTesting(b).Should().BeFalse("its owner no longer owns the hub");
    }

    [Fact]
    public void Wait_Graph_Release_Waiters_Drops_Only_Hub_Waits_On_That_Hub()
    {
        var graph = new WaitForGraph();
        object container = new(), hub = new(), otherHub = new();
        const int a = 1, b = 2, c = 3, d = 4;
        graph.Acquire(container, d);
        graph.TryBeginWait(hub, d, a).Should().BeTrue();
        graph.TryBeginWait(otherHub, d, b).Should().BeTrue();
        graph.TryBeginWait(container, c).Should().BeTrue();

        graph.ReleaseWaiters(hub);

        graph.IsWaitingForTesting(a).Should().BeFalse("its hub woke it");
        graph.IsWaitingForTesting(b).Should().BeTrue("another hub");
        graph.IsWaitingForTesting(c).Should().BeTrue("a membership wait is released through its owner");
    }
}
