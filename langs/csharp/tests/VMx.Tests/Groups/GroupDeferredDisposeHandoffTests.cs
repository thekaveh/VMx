using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Groups;

/// <summary>
/// A <c>Dispose()</c> from the owner thread inside its own membership
/// transaction is deferred; the owner runs it when the transaction ends. The
/// deferral stays set until that <c>Dispose()</c> admits the disposal, so no
/// other thread's structural change is admitted in the handoff (spec/06 §4.2,
/// spec/07, #1153). The <c>CompositeVM</c> twin is
/// <c>InitialCurrentForeignTransactionTests</c> (#1064).
/// </summary>
public class GroupDeferredDisposeHandoffTests
{
    private sealed class HookedGroup : GroupVMBase<ComponentVM>
    {
        public HookedGroup()
            : base("group", NullMessageHub.Instance, NullDispatcher.Instance)
        {
        }

        public Action? BeforeDispose { get; set; }

#pragma warning disable CA2215 // base.Dispose() runs after the hook.
        public override void Dispose()
#pragma warning restore CA2215
        {
            BeforeDispose?.Invoke();
            base.Dispose();
        }
    }

    private static ComponentVM Child(string name)
        => ComponentVM.Builder().Name(name).Services(NullMessageHub.Instance, NullDispatcher.Instance).Build();

    private static Thread Start(Action action, List<Exception> errors)
    {
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception error) { lock (errors) errors.Add(error); }
        })
        { IsBackground = true };
        thread.Start();
        return thread;
    }

    /// <summary>
    /// Builds a constructed group whose <c>CollectionChanged</c> handler disposes
    /// it on the calling thread only, so the main <c>Add</c> defers that disposal
    /// to its transaction end. The handoff is the second <c>Dispose()</c> call.
    /// </summary>
    private static HookedGroup DisposingGroup(int mainThread, params ComponentVM[] members)
    {
        var group = new HookedGroup();
        group.Construct();
        foreach (var member in members) group.Add(member);
        group.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == mainThread) group.Dispose();
        };
        return group;
    }

    private static bool Contains(HookedGroup group, ComponentVM child)
        => group.Any(item => ReferenceEquals(item, child));

    [Theory]
    [InlineData("add")]
    [InlineData("insert")]
    [InlineData("replace")]
    [InlineData("remove")]
    [InlineData("remove-at")]
    [InlineData("move")]
    [InlineData("clear")]
    public void Handoff_Admits_No_Structural_Change_From_Another_Thread(string operation)
    {
        // Variant A of #1153: the hook joins the worker inside the handoff.
        var mainThread = Environment.CurrentManagedThreadId;
        var a = Child("a");
        var b = Child("b");
        var x = Child("x");
        // A member added before the disposing handler is attached.
        var group = DisposingGroup(mainThread, a);
        a.Status.Should().NotBe(ConstructionStatus.Disposed);
        var errors = new List<Exception>();
        var calls = 0;
        var joined = false;
        group.BeforeDispose = () =>
        {
            if (Interlocked.Increment(ref calls) != 2) return; // the handoff from the transaction end
            Action change = operation switch
            {
                "add" => () => group.Add(x),
                "insert" => () => group.Insert(0, x),
                "replace" => () => group[0] = x,
                "remove" => () => group.Remove(a),
                "remove-at" => () => group.RemoveAt(0),
                "move" => () => group.Move(0, 1),
                "clear" => () => group.Clear(),
                _ => throw new ArgumentOutOfRangeException(nameof(operation)),
            };
            joined = Start(change, errors).Join(HangGuard);
        };

        group.Add(b);

        joined.Should().BeTrue();
        Volatile.Read(ref calls).Should().BeGreaterThanOrEqualTo(2);
        lock (errors) errors.Should().ContainSingle().Which.Should().BeOfType<ObjectDisposedException>();
        group.Status.Should().Be(ConstructionStatus.Disposed);
        Contains(group, x).Should().BeFalse();
        x.Status.Should().NotBe(ConstructionStatus.Disposed);
        group.Select(item => item.Name).Should().Equal("a", "b");
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Handoff_Does_Not_Wait_For_A_Foreign_Add_That_Waits_For_The_Owner()
    {
        // Variant C of #1153: the worker's handler waits for the main Add to
        // return, bounded only by the hang guard. An admitted worker Add would
        // make the handoff Dispose wait for it, and each thread would wait for
        // the other.
        var mainThread = Environment.CurrentManagedThreadId;
        var group = DisposingGroup(mainThread);
        var b = Child("b");
        var x = Child("x");
        using var workerInHandler = new ManualResetEventSlim();
        using var mainReturned = new ManualResetEventSlim();
        group.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == mainThread) return;
            workerInHandler.Set();
            mainReturned.Wait(HangGuard);
        };
        var errors = new List<Exception>();
        var calls = 0;
        Thread? worker = null;
        var workerSettled = false;
        group.BeforeDispose = () =>
        {
            if (Interlocked.Increment(ref calls) != 2) return; // the handoff from the transaction end
            var started = Start(() => group.Add(x), errors);
            worker = started;
            // Return while the worker waits in its handler, or once it was refused.
            workerSettled = SpinWait.SpinUntil(
                () => workerInHandler.IsSet || !started.IsAlive, HangGuard);
        };

        group.Add(b);
        mainReturned.Set();

        workerSettled.Should().BeTrue();
        worker.Should().NotBeNull();
        worker!.Join(HangGuard).Should().BeTrue();
        workerInHandler.IsSet.Should().BeFalse();
        lock (errors) errors.Should().ContainSingle().Which.Should().BeOfType<ObjectDisposedException>();
        group.Status.Should().Be(ConstructionStatus.Disposed);
        Contains(group, x).Should().BeFalse();
        x.Status.Should().NotBe(ConstructionStatus.Disposed);
    }
}
