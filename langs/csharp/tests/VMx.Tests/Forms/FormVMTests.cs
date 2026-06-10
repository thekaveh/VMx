using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Forms;

/// <summary>
/// Unit tests for <see cref="FormVM{TM}"/> — edge cases and implementation details.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class FormVMTests
{
    private sealed record Model(string Name, int Value);

    // ── Construction ─────────────────────────────────────────────────────────

    [Fact]
    public void Constructor_Requires_NonNull_Initial()
    {
        var act = () => new FormVM<Model>(null!, _ => Task.CompletedTask);
        act.Should().Throw<ArgumentNullException>().WithParameterName("initial");
    }

    [Fact]
    public void Constructor_Requires_NonNull_Persister_Delegate()
    {
        var act = () => new FormVM<Model>(new Model("A", 1), (Func<Model, Task>)null!);
        act.Should().Throw<ArgumentNullException>().WithParameterName("persister");
    }

    [Fact]
    public void Constructor_Requires_NonNull_Persister_Interface()
    {
        var act = () => new FormVM<Model>(new Model("A", 1), (IFormPersister<Model>)null!);
        act.Should().Throw<ArgumentNullException>().WithParameterName("persister");
    }

    [Fact]
    public void Constructor_With_IFormPersister_Delegates_To_PersistAsync()
    {
        var called = false;
        var persister = new LambdaPersister<Model>(m => { called = true; return Task.CompletedTask; });
        using var sut = new FormVM<Model>(new Model("A", 1), persister);

        sut.SetModel(new Model("B", 2));
        _ = sut.ApproveAsync();

        called.Should().BeTrue("IFormPersister wraps to delegate");
    }

    // ── Snapshot ─────────────────────────────────────────────────────────────

    [Fact]
    public void Snapshot_Is_Structurally_Equal_But_Different_Reference_For_Record()
    {
        var initial = new Model("Alice", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask);

        sut.Snapshot.Should().Be(initial, "value-equal to initial");
    }

    [Fact]
    public void Custom_Snapshotter_Used_For_Initial_Snapshot()
    {
        var snapshotterCalled = 0;
        Func<Model, Model> snapshotter = m =>
        {
            snapshotterCalled++;
            return m with { Name = m.Name + "-snap" };
        };

        var initial = new Model("Alice", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, snapshotter: snapshotter);

        snapshotterCalled.Should().Be(1, "snapshotter called once during construction");
        sut.Snapshot.Name.Should().Be("Alice-snap");
    }

    // ── SetModel ─────────────────────────────────────────────────────────────

    [Fact]
    public void SetModel_Requires_NonNull()
    {
        using var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask);
        var act = () => sut.SetModel(null!);
        act.Should().Throw<ArgumentNullException>().WithParameterName("model");
    }

    [Fact]
    public void SetModel_Multiple_Times_Tracks_Latest()
    {
        using var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask);

        sut.SetModel(new Model("B", 2));
        sut.SetModel(new Model("C", 3));

        sut.Model.Should().Be(new Model("C", 3));
        sut.IsDirty.Should().BeTrue();
    }

    // ── DenyCommand ───────────────────────────────────────────────────────────

    [Fact]
    public void DenyCommand_Noop_When_Not_Dirty()
    {
        var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var sub = hub.Messages.Subscribe(messages.Add);

        var initial = new Model("A", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, hub: hub);

        sut.DenyCommand.Execute(null);

        // Model unchanged, still not dirty.
        sut.Model.Should().Be(initial);
        sut.IsDirty.Should().BeFalse();

        // Hub messages are still published even when revert is a no-op by value.
        messages.Should().HaveCount(2, "hub messages published even when model == snapshot by value");
    }

    [Fact]
    public void DenyCommand_CanExecute_Is_Always_True()
    {
        using var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask);
        sut.DenyCommand.CanExecute(null).Should().BeTrue();
    }

    // ── ApproveAsync ─────────────────────────────────────────────────────────

    [Fact]
    public async Task ApproveAsync_Snapshot_Advances_After_Second_Approval()
    {
        var initial = new Model("A", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask);

        // First round.
        sut.SetModel(new Model("B", 2));
        await sut.ApproveAsync();
        sut.Snapshot.Should().Be(new Model("B", 2));

        // Second round.
        sut.SetModel(new Model("C", 3));
        await sut.ApproveAsync();
        sut.Snapshot.Should().Be(new Model("C", 3));
        sut.IsDirty.Should().BeFalse();
    }

    [Fact]
    public async Task ApproveAsync_When_Model_Identity_Unchanged_Snapshot_Advances()
    {
        // Re-approve without mutation — allowed in non-strict mode.
        var initial = new Model("A", 1);
        var approved = new List<Model>();

        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask);
        using var sub = sut.OnApproved.Subscribe(approved.Add);

        await sut.ApproveAsync();

        approved.Should().ContainSingle("OnApproved fires even when not dirty in non-strict mode");
    }

    [Fact]
    public async Task ApproveAsync_Persister_Receives_Current_Model()
    {
        var received = new List<Model>();
        var initial = new Model("A", 1);

        using var sut = new FormVM<Model>(initial, m => { received.Add(m); return Task.CompletedTask; });

        var updated = new Model("B", 2);
        sut.SetModel(updated);
        await sut.ApproveAsync();

        received.Should().ContainSingle().Which.Should().Be(updated);
    }

    // ── Strict mode ───────────────────────────────────────────────────────────

    [Fact]
    public async Task StrictMode_ApproveCanExecute_Transitions_On_SetModel_And_Deny()
    {
        var canExecuteChanges = new List<bool>();
        var initial = new Model("A", 1);

        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, strict: true);

        // Subscribe to CanExecuteChanged to track transitions.
        var eventCount = 0;
        sut.ApproveCommand.CanExecuteChanged += (_, _) => eventCount++;

        // Initial: not dirty → cannot approve.
        sut.ApproveCommand.CanExecute(null).Should().BeFalse();

        // Make dirty: should fire CanExecuteChanged.
        sut.SetModel(new Model("B", 2));
        eventCount.Should().BeGreaterThan(0, "CanExecuteChanged fired on dirtying");
        sut.ApproveCommand.CanExecute(null).Should().BeTrue();

        // Deny: should revert and fire CanExecuteChanged.
        var prevCount = eventCount;
        sut.DenyCommand.Execute(null);
        eventCount.Should().BeGreaterThan(prevCount, "CanExecuteChanged fired on revert");
        sut.ApproveCommand.CanExecute(null).Should().BeFalse("reverted to pristine");

        // Approve when dirty: CanExecuteChanged fires after snapshot advance.
        sut.SetModel(new Model("C", 3));
        prevCount = eventCount;
        await sut.ApproveAsync();
        eventCount.Should().BeGreaterThan(prevCount, "CanExecuteChanged fired after approve");
        sut.ApproveCommand.CanExecute(null).Should().BeFalse("pristine after approve");
    }

    // ── OnApproved ────────────────────────────────────────────────────────────

    [Fact]
    public async Task OnApproved_Completes_After_Dispose()
    {
        var completed = false;
        var initial = new Model("A", 1);
        var sut = new FormVM<Model>(initial, _ => Task.CompletedTask);
        using var sub = sut.OnApproved.Subscribe(_ => { }, () => completed = true);

        sut.Dispose();
        await Task.Yield();

        completed.Should().BeTrue("OnApproved observable completes on Dispose");
    }

    // ── IFormPersister overload ───────────────────────────────────────────────

    [Fact]
    public async Task IFormPersister_Interface_Works_End_To_End()
    {
        var persisted = new List<Model>();
        var persister = new LambdaPersister<Model>(m => { persisted.Add(m); return Task.CompletedTask; });

        var initial = new Model("A", 1);
        using var sut = new FormVM<Model>(initial, persister);

        sut.SetModel(new Model("B", 2));
        await sut.ApproveAsync();

        persisted.Should().ContainSingle().Which.Should().Be(new Model("B", 2));
        sut.Snapshot.Should().Be(new Model("B", 2));
    }

    // ── Hub messages ─────────────────────────────────────────────────────────

    [Fact]
    public void Hub_Messages_Sender_Is_FormVM_Instance()
    {
        var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var sub = hub.Messages.Subscribe(messages.Add);

        var initial = new Model("A", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, hub: hub);

        sut.SetModel(new Model("B", 2));
        sut.DenyCommand.Execute(null);

        var revert = messages.OfType<FormRevertedMessage>().Single();
        revert.Sender.Should().BeSameAs(sut);

        var propChange = messages.OfType<PropertyChangedMessage<FormVM<Model>>>().Single();
        propChange.Sender.Should().BeSameAs(sut);
        propChange.PropertyName.Should().Be("Model");
    }

    // ── Dispose races ─────────────────────────────────────────────────────────

    [Fact]
    public async Task Dispose_During_InFlight_Approve_Does_Not_Throw()
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var sut = new FormVM<Model>(new Model("A", 1), _ => gate.Task);
        sut.SetModel(new Model("B", 2));

        var approve = sut.ApproveAsync();   // parked on the persister
        sut.Dispose();                      // completes + disposes the subjects
        gate.SetResult();                   // persister finishes after dispose

        // The post-await path must observe _disposed and skip the emissions
        // instead of throwing ObjectDisposedException in an unobserved task.
        var completed = await Task.WhenAny(approve, Task.Delay(TimeSpan.FromSeconds(5)));
        completed.Should().BeSameAs(approve);
        await approve;
    }

    // ── Test double helpers ───────────────────────────────────────────────────

    private sealed class LambdaPersister<TM>(Func<TM, Task> action) : IFormPersister<TM>
    {
        public Task PersistAsync(TM model) => action(model);
    }
}
