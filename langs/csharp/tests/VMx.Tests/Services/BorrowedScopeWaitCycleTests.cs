using System.Collections.Concurrent;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Internal;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Services;

/// <summary>
/// An open borrowed hub scope is a wait-for owner (spec/03 §4.2, ADR-0172,
/// #1159). Every wait for it records an edge to a borrower, so a cycle through
/// a borrowed scope is refused instead of hanging. A drainer with an empty
/// queue releases the drain to the scope's exit, and a send from inside a hub
/// callback waits like any other send (HUB-013).
/// </summary>
public class BorrowedScopeWaitCycleTests
{
    private sealed record Stub(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    // Dedicated threads: the waits block by design, so progress must not
    // depend on thread-pool injection under the parallel runner.
    private static Task Run(Action body) => Task.Factory.StartNew(
        body, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    private static async Task FinishWithin(Task all, string because)
    {
        (await Task.WhenAny(all, Task.Delay(HangGuard))).Should().BeSameAs(all, because);
        await all;
    }

    // The #1159 reproduction and its row-3 variants. P drains h2. Q, inside an
    // h3 batch, waits for P on h2: from an h drain ("q0"), or from its own h
    // batch. P borrows h (the cycle Q -> P), disposes h2 so Q wakes, and then
    // sends on h3. In the row-3 variants Q, after its h batch, sends on h,
    // batches on h or disposes h during P's borrow, so it waits for the
    // borrower P. Each of those waits records an edge to P, and P's h3 send
    // then sees the cycle instead of hanging.
    [Theory]
    [InlineData("q0")]
    [InlineData("send")]
    [InlineData("batch")]
    [InlineData("dispose")]
    public async Task Wait_For_A_Borrowed_Scope_Records_An_Edge_To_The_Borrower(string qStep)
    {
        var h = new MessageHub();
        var h2 = new MessageHub();
        var h3 = new MessageHub();
        var q = 0;
        var qFinished = false;
        var pm = 0;
        using var pDraining = new ManualResetEventSlim(false);
        using var recorder = h3.Messages.OfType<Stub>().Where(m => m.Tag == "pm")
            .Subscribe(_ => Interlocked.Increment(ref pm));
        using var s1 = h.Messages.OfType<Stub>().Where(m => m.Tag == "q0")
            .Subscribe(_ => h2.Send(new Stub("q1")));
        using var s2 = h2.Messages.OfType<Stub>().Where(m => m.Tag == "p0").Subscribe(_ =>
        {
            pDraining.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's drain of h2");
            h.Batch(() =>
            {
                h2.Dispose();
                // Give Q time to reach its wait for this borrowed scope.
                SpinWait.SpinUntil(
                    () => Volatile.Read(ref qFinished) ||
                        WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                    TimeSpan.FromMilliseconds(300));
                h3.Send(new Stub("pm"));
            });
        });

        var p = Run(() => h2.Send(new Stub("p0")));
        pDraining.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            h3.Batch(() =>
            {
                if (qStep == "q0")
                {
                    h.Send(new Stub("q0"));
                    return;
                }
                h.Batch(() => h2.Send(new Stub("q1")));
                switch (qStep)
                {
                    case "send": h.Send(new Stub("q2")); break;
                    case "batch": h.Batch(() => h.Send(new Stub("q2"))); break;
                    default: h.Dispose(); break;
                }
            });
            Volatile.Write(ref qFinished, true);
        });

        await FinishWithin(Task.WhenAll(p, qTask), "a wait for a borrowed scope must record an edge");
        Volatile.Read(ref pm).Should().Be(1);
        h.Dispose();
        h3.Dispose();
    }

    // #1159 row 4: P's h3 send waits for Q first, and Q's h subscriber returns
    // only after that. Q's queue on h is then empty, so Q releases the drain
    // instead of waiting for P's borrowed scope (spec/03 §4.2 rule 2).
    [Fact]
    public async Task Drainer_With_An_Empty_Queue_Does_Not_Wait_For_A_Borrowed_Scope()
    {
        var h = new MessageHub();
        var h2 = new MessageHub();
        var h3 = new MessageHub();
        int p = 0, q = 0;
        var pm = 0;
        using var pDraining = new ManualResetEventSlim(false);
        using var recorder = h3.Messages.OfType<Stub>().Where(m => m.Tag == "pm")
            .Subscribe(_ => Interlocked.Increment(ref pm));
        using var s1 = h.Messages.OfType<Stub>().Where(m => m.Tag == "q0").Subscribe(_ =>
        {
            h2.Send(new Stub("q1"));
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref p)),
                HangGuard).Should().BeTrue("P's h3 send waits for Q's h3 batch");
        });
        using var s2 = h2.Messages.OfType<Stub>().Where(m => m.Tag == "p0").Subscribe(_ =>
        {
            pDraining.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's drain of h2");
            h.Batch(() =>
            {
                h2.Dispose();
                h3.Send(new Stub("pm"));
            });
        });

        var pTask = Run(() =>
        {
            Volatile.Write(ref p, Environment.CurrentManagedThreadId);
            h2.Send(new Stub("p0"));
        });
        pDraining.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            h3.Batch(() => h.Send(new Stub("q0")));
        });

        await FinishWithin(Task.WhenAll(pTask, qTask), "an empty-queue drainer releases the drain");
        Volatile.Read(ref pm).Should().Be(1);
        h.Dispose();
        h3.Dispose();
    }

    // spec/03 §4.2 rule 5: as in row 4, but Q's h queue still holds "qx" when
    // Q's subscriber returns. Q's wait for P's borrowed scope would close the
    // cycle P -> Q (h3) -> P (h), so Q releases the drain with qx queued. Q's
    // outermost send returns before qx is delivered, and the exit of P's
    // borrowed scope delivers qx on P's thread before that exit returns.
    [Fact]
    public async Task Drainer_With_Queued_Messages_Releases_The_Drain_On_A_Refused_Borrow_Wait()
    {
        var h = new MessageHub();
        var h2 = new MessageHub();
        var h3 = new MessageHub();
        int p = 0, q = 0;
        var events = new ConcurrentQueue<string>();
        var qxThread = 0;
        using var pDraining = new ManualResetEventSlim(false);
        using var recorder = h.Messages.OfType<Stub>().Where(m => m.Tag == "qx").Subscribe(_ =>
        {
            Volatile.Write(ref qxThread, Environment.CurrentManagedThreadId);
            events.Enqueue("qx delivered");
        });
        using var s1 = h.Messages.OfType<Stub>().Where(m => m.Tag == "q0").Subscribe(_ =>
        {
            // Q drains h, so this send only enqueues.
            h.Send(new Stub("qx"));
            h2.Send(new Stub("q1"));
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref p)),
                HangGuard).Should().BeTrue("P's h3 send waits for Q's h3 batch");
        });
        using var s2 = h2.Messages.OfType<Stub>().Where(m => m.Tag == "p0").Subscribe(_ =>
        {
            pDraining.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's drain of h2");
            h.Batch(() =>
            {
                h2.Dispose();
                h3.Send(new Stub("pm"));
            });
            events.Enqueue("P's borrow exited");
        });

        var pTask = Run(() =>
        {
            Volatile.Write(ref p, Environment.CurrentManagedThreadId);
            h2.Send(new Stub("p0"));
        });
        pDraining.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            h3.Batch(() =>
            {
                h.Send(new Stub("q0"));
                events.Enqueue("Q's send returned");
            });
        });

        await FinishWithin(Task.WhenAll(pTask, qTask), "the drainer releases the drain to the borrowed scope's exit");
        events.Should().Equal("Q's send returned", "qx delivered", "P's borrow exited");
        Volatile.Read(ref qxThread).Should().Be(Volatile.Read(ref p));
        h.Dispose();
        h3.Dispose();
    }

    // #1159 review: a send from inside an unrelated hub callback waits for an
    // open borrowed scope like any other send, so it stays synchronous
    // (HUB-013). Q's cycle with P's borrowed scope has ended when R sends.
    [Fact]
    public async Task Send_From_A_Callback_Waits_For_A_Borrowed_Scope()
    {
        var h = new MessageHub();
        var h2 = new MessageHub();
        var x = new MessageHub();
        int q = 0, r = 0;
        var qFinished = false;
        var rReturned = false;
        var observed = 0;
        var observedBeforeReturn = false;
        using var pDraining = new ManualResetEventSlim(false);
        using var rStart = new ManualResetEventSlim(false);
        using var recorder = h.Messages.OfType<Stub>().Where(m => m.Tag == "r")
            .Subscribe(_ => Interlocked.Increment(ref observed));
        using var callback = x.Messages.OfType<Stub>().Subscribe(_ =>
        {
            h.Send(new Stub("r"));
            Volatile.Write(ref observedBeforeReturn, Volatile.Read(ref observed) == 1);
            Volatile.Write(ref rReturned, true);
        });
        using var s2 = h2.Messages.OfType<Stub>().Where(m => m.Tag == "p0").Subscribe(_ =>
        {
            pDraining.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's drain of h2");
            h.Batch(() =>
            {
                h2.Dispose();
                SpinWait.SpinUntil(() => Volatile.Read(ref qFinished), HangGuard).Should().BeTrue();
                rStart.Set();
                SpinWait.SpinUntil(
                    () => Volatile.Read(ref rReturned) ||
                        (Volatile.Read(ref r) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref r))),
                    HangGuard).Should().BeTrue("R's send reaches the borrowed scope");
            });
        });

        var p = Run(() => h2.Send(new Stub("p0")));
        pDraining.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            h.Batch(() => h2.Send(new Stub("q1")));
            Volatile.Write(ref qFinished, true);
        });
        var rTask = Run(() =>
        {
            Volatile.Write(ref r, Environment.CurrentManagedThreadId);
            rStart.Wait(HangGuard).Should().BeTrue();
            x.Send(new Stub("x0"));
        });

        await FinishWithin(Task.WhenAll(p, qTask, rTask), "R waits for the borrowed scope and then delivers");
        Volatile.Read(ref observed).Should().Be(1);
        Volatile.Read(ref observedBeforeReturn).Should().BeTrue("R's send delivers before it returns");
        h.Dispose();
        x.Dispose();
    }

    // #1159 GroupVM variant. Q adds x to a group on h, so x's Constructing
    // publication drains h, and its h subscriber waits for P on h2. P borrows
    // h, disposes h2, and adds y to the group. Q's later send of x's status
    // waits for P's borrowed scope with an edge, so P's membership wait for
    // Q's transaction is refused instead of hanging.
    [Fact]
    public async Task Group_Add_During_A_Borrowed_Scope_Does_Not_Deadlock()
    {
        var h = new MessageHub();
        var h2 = new MessageHub();
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(h, NullDispatcher.Instance)
            .AutoConstructOnAdd(true).Children(() => Array.Empty<ComponentVM<string>>()).Build();
        group.Construct();
        ComponentVM<string> Child(string name) => ComponentVM<string>.Builder()
            .Name(name).Services(h, NullDispatcher.Instance).Model(name).Build();
        var x = Child("x");
        var y = Child("y");
        var q = 0;
        Exception? addError = null;
        Exception? qError = null;
        using var pDraining = new ManualResetEventSlim(false);
        using var s1 = h.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(m => ReferenceEquals(m.SenderObject, x) && m.Status == ConstructionStatus.Constructing)
            .Subscribe(_ => h2.Send(new Stub("q1")));
        using var s2 = h2.Messages.OfType<Stub>().Where(m => m.Tag == "p0").Subscribe(_ =>
        {
            pDraining.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 && WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's drain of h2");
            h.Batch(() =>
            {
                h2.Dispose();
                SpinWait.SpinUntil(
                    () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                    TimeSpan.FromMilliseconds(300));
                try { group.Add(y); }
                catch (Exception error) { addError = error; }
            });
        });

        var p = Run(() => h2.Send(new Stub("p0")));
        pDraining.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            try { group.Add(x); }
            catch (Exception error) { qError = error; }
        });

        await FinishWithin(Task.WhenAll(p, qTask), "a group transaction and a borrowed scope must not deadlock");
        qError.Should().BeNull();
        x.Status.Should().Be(ConstructionStatus.Constructed);
        group.Should().Contain(x);
        if (addError is null) group.Should().Contain(y);
        else addError.Should().BeOfType<InvalidOperationException>();
        h.Dispose();
    }
}
