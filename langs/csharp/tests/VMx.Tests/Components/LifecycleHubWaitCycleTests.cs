using System.Collections.Concurrent;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Internal;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Components;

/// <summary>
/// Lifecycle publication waits and hook-lease waits are edges of the one
/// shared wait-for graph, with hub, membership and ownership waits (spec/03
/// §4.1, spec/02 §2.4, ADR-0172). A cycle that crosses a lifecycle wait and a
/// hub wait is refused like any other (#1156). The thread that finishes a
/// delivery or a hook removes the edges on it before it wakes the waiters, so
/// an ended wait never makes a foreign <c>Dispose()</c> skip its wait (#1183).
/// </summary>
public class LifecycleHubWaitCycleTests
{
    private sealed record Marker(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    private sealed class HookVM(
        string name,
        IMessageHub hub,
        Action? onConstruct = null,
        Action? onDispose = null) : ComponentVMBase(name, hub, NullDispatcher.Instance)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnConstruct() => onConstruct?.Invoke();

        protected override void OnDispose() => onDispose?.Invoke();
    }

    private static ComponentVM<string> Leaf(IMessageHub hub, string name) => ComponentVM<string>.Builder()
        .Name(name)
        .Services(hub, NullDispatcher.Instance)
        .Model(name)
        .Build();

    // Dedicated threads: the waits block by design, so progress must not
    // depend on thread-pool injection under the parallel runner.
    private static Task Run(Action body) => Task.Factory.StartNew(
        body, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    private static async Task FinishWithin(Task all, string because)
    {
        (await Task.WhenAny(all, Task.Delay(HangGuard))).Should().BeSameAs(all, because);
        await all;
    }

    // #1156 publication path. B drains the hub and waits until A, which drains
    // x's Constructing publication, waits to send on that hub. B then disposes
    // x, so B's wait for A's delivery of Disposed closes the cycle and is
    // refused. The control disposes an unrelated y, which closes no cycle.
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Publication_Wait_And_Hub_Wait_Form_One_Cycle(bool disposeUnrelated)
    {
        var hub = new MessageHub();
        var x = Leaf(hub, "x");
        var y = Leaf(hub, "y");
        var statuses = new ConcurrentQueue<ConstructionStatus>();
        var a = 0;
        Exception? bError = null;
        using var bDraining = new ManualResetEventSlim(false);
        using var recorder = hub.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => ReferenceEquals(message.SenderObject, x))
            .Subscribe(message => statuses.Enqueue(message.Status));
        using var drain = hub.Messages.OfType<Marker>().Subscribe(_ =>
        {
            bDraining.Set();
            try
            {
                SpinWait.SpinUntil(
                    () => Volatile.Read(ref a) != 0 &&
                        WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref a)),
                    HangGuard).Should().BeTrue("A waits to send x's Constructing on the hub");
                if (disposeUnrelated) y.Dispose();
                else x.Dispose();
            }
            catch (Exception error)
            {
                bError = error;
            }
        });

        var b = Run(() => hub.Send(new Marker("b")));
        bDraining.Wait(HangGuard).Should().BeTrue();
        var aTask = Run(() =>
        {
            Volatile.Write(ref a, Environment.CurrentManagedThreadId);
            x.Construct();
        });

        await FinishWithin(Task.WhenAll(b, aTask), "a publication wait and a hub wait must not deadlock");
        bError.Should().BeNull();
        hub.Dispose();
        if (disposeUnrelated)
        {
            y.Status.Should().Be(ConstructionStatus.Disposed);
            x.Status.Should().Be(ConstructionStatus.Constructed);
            statuses.Should().Equal(ConstructionStatus.Constructing, ConstructionStatus.Constructed);
        }
        else
        {
            x.Status.Should().Be(ConstructionStatus.Disposed);
            statuses.Should().Equal(ConstructionStatus.Constructing, ConstructionStatus.Disposed);
        }
    }

    // #1156 publication path in the reverse order. B drains h2 and waits for
    // A's delivery of x's Disposed. A then sends on h2 from inside x's
    // publication, and that hub wait closes the cycle: the send enqueues for
    // B's drain instead of waiting.
    [Fact]
    public async Task Hub_Send_Takes_The_Escape_When_A_Publication_Wait_Came_First()
    {
        var hx = new MessageHub();
        var h2 = new MessageHub();
        var x = Leaf(hx, "x");
        var b = 0;
        var markerDeliveries = 0;
        var markerThread = 0;
        using var aDelivering = new ManualResetEventSlim(false);
        using var bDraining = new ManualResetEventSlim(false);
        using var publication = hx.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => ReferenceEquals(message.SenderObject, x) &&
                message.Status == ConstructionStatus.Constructing)
            .Subscribe(_ =>
            {
                aDelivering.Set();
                SpinWait.SpinUntil(
                    () => Volatile.Read(ref b) != 0 &&
                        WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref b)),
                    HangGuard).Should().BeTrue("B waits for A's delivery of x's Disposed");
                h2.Send(new Marker("a"));
            });
        using var drain = h2.Messages.OfType<Marker>().Subscribe(message =>
        {
            if (message.Tag == "a")
            {
                Interlocked.Increment(ref markerDeliveries);
                Volatile.Write(ref markerThread, Environment.CurrentManagedThreadId);
                return;
            }
            bDraining.Set();
            aDelivering.Wait(HangGuard).Should().BeTrue();
            x.Dispose();
        });

        var aTask = Run(() => x.Construct());
        var bTask = Run(() =>
        {
            Volatile.Write(ref b, Environment.CurrentManagedThreadId);
            aDelivering.Wait(HangGuard);
            h2.Send(new Marker("b"));
        });

        await FinishWithin(Task.WhenAll(aTask, bTask), "a hub wait and a publication wait must not deadlock");
        x.Status.Should().Be(ConstructionStatus.Disposed);
        Volatile.Read(ref markerDeliveries).Should().Be(1);
        Volatile.Read(ref markerThread).Should().Be(Volatile.Read(ref b), "B's drain delivers A's deferred send");
        hx.Dispose();
        h2.Dispose();
    }

    // #1156 hook-lease path. x's OnConstruct hook on A waits to send on the
    // hub that B drains. B disposes x, so B's wait for A's hook lease closes
    // the cycle: terminal cleanup is deferred to the hook's completion.
    [Fact]
    public async Task Hook_Lease_Wait_And_Hub_Wait_Form_One_Cycle()
    {
        var hub = new MessageHub();
        var order = new ConcurrentQueue<string>();
        var a = 0;
        var disposeCalls = 0;
        using var hookRunning = new ManualResetEventSlim(false);
        using var bDraining = new ManualResetEventSlim(false);
        var x = new HookVM("x", hub,
            onConstruct: () =>
            {
                hookRunning.Set();
                bDraining.Wait(HangGuard).Should().BeTrue();
                hub.Send(new Marker("a"));
                order.Enqueue("OnConstruct returned");
            },
            onDispose: () =>
            {
                Interlocked.Increment(ref disposeCalls);
                order.Enqueue("OnDispose");
            });
        using var drain = hub.Messages.OfType<Marker>().Where(m => m.Tag == "b").Subscribe(_ =>
        {
            bDraining.Set();
            SpinWait.SpinUntil(
                () => WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref a)),
                HangGuard).Should().BeTrue("A's hook waits to send on the hub");
            x.Dispose();
        });

        var aTask = Run(() =>
        {
            Volatile.Write(ref a, Environment.CurrentManagedThreadId);
            x.Construct();
        });
        hookRunning.Wait(HangGuard).Should().BeTrue();
        var bTask = Run(() => hub.Send(new Marker("b")));

        await FinishWithin(Task.WhenAll(aTask, bTask), "a hook-lease wait and a hub wait must not deadlock");
        x.Status.Should().Be(ConstructionStatus.Disposed);
        Volatile.Read(ref disposeCalls).Should().Be(1);
        order.Should().Equal("OnConstruct returned", "OnDispose");
        hub.Dispose();
    }

    // #1183 form 1, the hook-lease path. P runs a's construct hook; Q runs b's
    // and disposes a, so Q waits for P's lease on a. The test holds Q after
    // P's lease release ends that wait and before Q removes its own edge, until
    // P's b.Dispose() has decided whether to wait for Q's lease on b. With a
    // stale Q -> P edge, P saw a cycle that had ended and deferred b's
    // cleanup to Q.
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Foreign_Dispose_Waits_For_A_Hook_After_An_Ended_Lease_Wait(bool throwingOnDispose)
    {
        int p = 0, q = 0;
        var pDisposeReturned = false;
        var bHookReturned = false;
        var onDisposeCalls = 0;
        var onDisposeThread = 0;
        var onDisposeAfterHook = false;
        var onDisposeBeforeReturn = false;
        Exception? pError = null;
        using var aHookRunning = new ManualResetEventSlim(false);
        HookVM? b = null;
        var a = new HookVM("a", new MessageHub(), onConstruct: () =>
        {
            aHookRunning.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 &&
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P's lease on a");
        });
        b = new HookVM("b", new MessageHub(),
            onConstruct: () =>
            {
                aHookRunning.Wait(HangGuard).Should().BeTrue();
                a.Dispose();
                Thread.Sleep(300);
                Volatile.Write(ref bHookReturned, true);
            },
            onDispose: () =>
            {
                Interlocked.Increment(ref onDisposeCalls);
                Volatile.Write(ref onDisposeThread, Environment.CurrentManagedThreadId);
                Volatile.Write(ref onDisposeAfterHook, Volatile.Read(ref bHookReturned));
                Volatile.Write(ref onDisposeBeforeReturn, !Volatile.Read(ref pDisposeReturned));
                if (throwingOnDispose) throw new InvalidOperationException("b cleanup failure");
            });
        a.AfterLifecycleWaitWokenForTesting = () =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref q)) return;
            SpinWait.SpinUntil(
                () => Volatile.Read(ref pDisposeReturned) ||
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref p)),
                HangGuard).Should().BeTrue("P's b.Dispose() decides whether to wait");
        };

        var pTask = Run(() =>
        {
            Volatile.Write(ref p, Environment.CurrentManagedThreadId);
            a.Construct();
            try { b.Dispose(); }
            catch (Exception error) { pError = error; }
            Volatile.Write(ref pDisposeReturned, true);
        });
        aHookRunning.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            b.Construct();
        });

        await FinishWithin(Task.WhenAll(pTask, qTask), "an ended lease wait must not deadlock");
        Volatile.Read(ref onDisposeCalls).Should().Be(1);
        Volatile.Read(ref onDisposeThread).Should().Be(Volatile.Read(ref p), "P waits for b's hook");
        Volatile.Read(ref onDisposeAfterHook).Should().BeTrue("OnDispose runs after b's hook returns");
        Volatile.Read(ref onDisposeBeforeReturn).Should().BeTrue("OnDispose runs before b.Dispose() returns");
        if (throwingOnDispose)
            pError.Should().BeOfType<InvalidOperationException>().Which.Message.Should().Be("b cleanup failure");
        else
            pError.Should().BeNull();
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // #1183 form 2, the publication path. P drains a's Constructing, and Q,
    // which drains b's Constructing, disposes a, so Q waits for P's delivery
    // of a's Disposed. The test holds Q after that delivery ends Q's wait and
    // before Q removes its own edge, until P's b.Dispose() has decided whether
    // to wait for Q's delivery of b's Disposed.
    [Fact]
    public async Task Foreign_Dispose_Waits_For_A_Publication_After_An_Ended_Delivery_Wait()
    {
        int p = 0, q = 0;
        var pDisposeReturned = false;
        var onDisposeRan = false;
        var onDisposeCalls = 0;
        var onDisposeThread = 0;
        var disposedBeforeOnDispose = 0;
        var disposedBeforeReturn = 0;
        var disposedMessages = 0;
        var hubA = new MessageHub();
        var hubB = new MessageHub();
        var a = Leaf(hubA, "a");
        var b = new HookVM("b", hubB, onDispose: () =>
        {
            Interlocked.Increment(ref onDisposeCalls);
            Volatile.Write(ref onDisposeThread, Environment.CurrentManagedThreadId);
            Volatile.Write(ref onDisposeRan, true);
        });
        using var pDelivering = new ManualResetEventSlim(false);
        using var aPublication = hubA.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => ReferenceEquals(message.SenderObject, a) &&
                message.Status == ConstructionStatus.Constructing)
            .Subscribe(_ =>
            {
                pDelivering.Set();
                SpinWait.SpinUntil(
                    () => Volatile.Read(ref q) != 0 &&
                        WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                    HangGuard).Should().BeTrue("Q waits for P's delivery of a's Disposed");
            });
        using var bPublication = hubB.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => ReferenceEquals(message.SenderObject, b))
            .Subscribe(message =>
            {
                if (message.Status == ConstructionStatus.Constructing)
                {
                    pDelivering.Wait(HangGuard).Should().BeTrue();
                    a.Dispose();
                    Thread.Sleep(200);
                }
                else if (message.Status == ConstructionStatus.Disposed)
                {
                    Interlocked.Increment(ref disposedMessages);
                    if (!Volatile.Read(ref onDisposeRan)) Interlocked.Increment(ref disposedBeforeOnDispose);
                    if (!Volatile.Read(ref pDisposeReturned)) Interlocked.Increment(ref disposedBeforeReturn);
                }
            });
        a.AfterLifecycleWaitWokenForTesting = () =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref q)) return;
            SpinWait.SpinUntil(
                () => Volatile.Read(ref pDisposeReturned) ||
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref p)),
                HangGuard).Should().BeTrue("P's b.Dispose() decides whether to wait");
        };

        var pTask = Run(() =>
        {
            Volatile.Write(ref p, Environment.CurrentManagedThreadId);
            a.Construct();
            b.Dispose();
            Volatile.Write(ref pDisposeReturned, true);
        });
        pDelivering.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            b.Construct();
        });

        await FinishWithin(Task.WhenAll(pTask, qTask), "an ended delivery wait must not deadlock");
        Volatile.Read(ref disposedMessages).Should().Be(1);
        Volatile.Read(ref disposedBeforeOnDispose).Should().Be(1, "Disposed reaches subscribers before OnDispose");
        Volatile.Read(ref disposedBeforeReturn).Should().Be(1, "Disposed reaches subscribers before b.Dispose() returns");
        Volatile.Read(ref onDisposeCalls).Should().Be(1);
        Volatile.Read(ref onDisposeThread).Should().Be(Volatile.Read(ref p));
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        hubA.Dispose();
        hubB.Dispose();
    }

    // #1183 real-cycle controls. P calls b.Dispose() while it still holds a's
    // lease (form 1) or still drains a (form 2), and Q waits for P. That cycle
    // is live, so P takes the escape and neither thread hangs.
    [Theory]
    [InlineData("lease")]
    [InlineData("publication")]
    public async Task Foreign_Dispose_Takes_The_Escape_For_A_Live_Cycle(string form)
    {
        var q = 0;
        var onDisposeCalls = 0;
        using var pRunning = new ManualResetEventSlim(false);
        var hubA = new MessageHub();
        var hubB = new MessageHub();
        HookVM? b = null;
        void DisposeBOnceQWaits()
        {
            pRunning.Set();
            SpinWait.SpinUntil(
                () => Volatile.Read(ref q) != 0 &&
                    WaitForGraph.Shared.IsWaitingForTesting(Volatile.Read(ref q)),
                HangGuard).Should().BeTrue("Q waits for P");
            b!.Dispose();
        }
        var a = new HookVM("a", hubA, onConstruct: form == "lease" ? DisposeBOnceQWaits : null);
        using var aPublication = hubA.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => form == "publication" && ReferenceEquals(message.SenderObject, a) &&
                message.Status == ConstructionStatus.Constructing)
            .Subscribe(_ => DisposeBOnceQWaits());
        b = new HookVM("b", hubB,
            onConstruct: form == "lease"
                ? () =>
                {
                    pRunning.Wait(HangGuard).Should().BeTrue();
                    a.Dispose();
                }
        : null,
            onDispose: () => Interlocked.Increment(ref onDisposeCalls));
        using var bPublication = hubB.Messages.OfType<IConstructionStatusChangedMessage>()
            .Where(message => form == "publication" && ReferenceEquals(message.SenderObject, b) &&
                message.Status == ConstructionStatus.Constructing)
            .Subscribe(_ =>
            {
                pRunning.Wait(HangGuard).Should().BeTrue();
                a.Dispose();
            });

        var pTask = Run(() => a.Construct());
        pRunning.Wait(HangGuard).Should().BeTrue();
        var qTask = Run(() =>
        {
            Volatile.Write(ref q, Environment.CurrentManagedThreadId);
            b.Construct();
        });

        await FinishWithin(Task.WhenAll(pTask, qTask), "a live lifecycle cycle takes the escape");
        SpinWait.SpinUntil(() => Volatile.Read(ref onDisposeCalls) == 1, HangGuard).Should().BeTrue();
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
        Volatile.Read(ref onDisposeCalls).Should().Be(1);
        hubA.Dispose();
        hubB.Dispose();
    }
}
