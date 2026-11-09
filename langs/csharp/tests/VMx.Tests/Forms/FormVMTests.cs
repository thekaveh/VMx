using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Forms;

/// <summary>
/// Unit tests for <see cref="FormVM{TM}"/> — edge cases and implementation details.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class FormVMTests
{
    private sealed record Model(string Name, int Value);

    // A model with a NESTED mutable object, for default-snapshot deep-clone tests.
    private sealed record Address
    {
        public string City { get; set; } = "";
    }

    private sealed record Person(string Name, Address Home);

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
    public void Default_Snapshot_Is_Deep_So_Nested_Mutation_Makes_Dirty()
    {
        // The default snapshotter must DEEP-clone: the snapshot must not share
        // the nested Address with the live model, otherwise an in-place
        // mutation of the nested object is invisible to IsDirty (VMX-064).
        using var sut = new FormVM<Person>(new Person("Alice", new Address { City = "NYC" }), _ => Task.CompletedTask);
        sut.IsDirty.Should().BeFalse("pristine immediately after construction");

        sut.Model.Home.City = "LA"; // mutate nested object in place

        sut.IsDirty.Should().BeTrue("a nested mutation must dirty the form (VMX-064)");
    }

    [Fact]
    public void Default_Snapshot_Deny_Restores_Nested_Mutation()
    {
        using var sut = new FormVM<Person>(new Person("Alice", new Address { City = "NYC" }), _ => Task.CompletedTask);
        sut.Model.Home.City = "LA";

        sut.DenyCommand.Execute(null);

        sut.Model.Home.City.Should().Be("NYC", "deny must restore the nested object (VMX-064)");
        sut.IsDirty.Should().BeFalse();
    }

    [Fact]
    public void Injected_Snapshotter_Overrides_Deep_Default()
    {
        // The injectable Snapshotter remains the documented escape hatch.
        var calls = 0;
        Func<Person, Person> snapshotter = m =>
        {
            calls++;
            return new Person(m.Name, new Address { City = m.Home.City });
        };

        using var sut = new FormVM<Person>(
            new Person("Alice", new Address { City = "NYC" }), _ => Task.CompletedTask, snapshotter: snapshotter);

        calls.Should().Be(1, "injected snapshotter used at construction, not the JSON default");

        sut.Model.Home.City = "LA";
        sut.IsDirty.Should().BeTrue();
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

        var propChanges = messages.OfType<PropertyChangedMessage<FormVM<Model>>>().ToList();
        propChanges.Should().HaveCount(2, "set-model and deny each publish the settled model");
        propChanges.Should().OnlyContain(message =>
            ReferenceEquals(message.Sender, sut) && message.PropertyName == "Model");
    }

    // ── Deferred teardown failure precedence (#448) ───────────────────────────

    private static readonly IReadOnlyDictionary<string, Func<Model, string?>> NameRequired =
        new Dictionary<string, Func<Model, string?>>
        {
            ["Name"] = m => m.Name.Length == 0 ? "required" : null,
        };

    // An ErrorsChanged observer runs inside the admitted mutation, so disposing
    // the form there defers teardown to the mutation's end. The OnApproved
    // completion observer then makes that deferred teardown fail.
    private static (FormVM<Model> Form, Func<bool> ErrorsCompleted) FormWhoseTeardownFails(
        Exception teardownError, Exception? mutationError)
    {
        var form = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask, validators: NameRequired);
        var errorsCompleted = false;
        form.OnApproved.Subscribe(_ => { }, () => throw teardownError);
        // Rx detaches an observer whose OnNext throws, so a separate observer
        // shows that the steps after the failing one still ran.
        form.ErrorsChanged.Subscribe(_ => { }, () => errorsCompleted = true);
        form.ErrorsChanged.Subscribe(_ =>
        {
            form.Dispose();
            if (mutationError is not null) throw mutationError;
        });
        return (form, () => errorsCompleted);
    }

    [Fact]
    public void SetModel_InFlight_Error_Survives_A_Failing_Deferred_Teardown()
    {
        var teardownError = new InvalidOperationException("teardown");
        var mutationError = new InvalidOperationException("mutation");
        var (sut, errorsCompleted) = FormWhoseTeardownFails(teardownError, mutationError);

        var act = () => sut.SetModel(new Model("", 1));

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(mutationError);
        errorsCompleted().Should().BeTrue("every teardown step still runs after the failing one");
    }

    [Fact]
    public void SetModel_Success_Surfaces_A_Failing_Deferred_Teardown()
    {
        var teardownError = new InvalidOperationException("teardown");
        var (sut, errorsCompleted) = FormWhoseTeardownFails(teardownError, mutationError: null);

        var act = () => sut.SetModel(new Model("", 1));

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(teardownError);
        errorsCompleted().Should().BeTrue();
    }

    [Fact]
    public void Deny_InFlight_Error_Survives_A_Failing_Deferred_Teardown()
    {
        var teardownError = new InvalidOperationException("teardown");
        var mutationError = new InvalidOperationException("mutation");
        var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask, validators: NameRequired);
        sut.SetModel(new Model("", 1));
        var errorsCompleted = false;
        sut.OnApproved.Subscribe(_ => { }, () => throw teardownError);
        sut.ErrorsChanged.Subscribe(_ => { }, () => errorsCompleted = true);
        sut.ErrorsChanged.Subscribe(_ =>
        {
            sut.Dispose();
            throw mutationError;
        });

        var act = () => sut.DenyCommand.Execute(null);

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(mutationError);
        errorsCompleted.Should().BeTrue("every teardown step still runs after the failing one");
    }

    [Fact]
    public void Deny_Success_Surfaces_A_Failing_Deferred_Teardown()
    {
        var teardownError = new InvalidOperationException("teardown");
        var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask, validators: NameRequired);
        sut.SetModel(new Model("", 1));
        var errorsCompleted = false;
        sut.OnApproved.Subscribe(_ => { }, () => throw teardownError);
        sut.ErrorsChanged.Subscribe(_ => sut.Dispose(), () => errorsCompleted = true);

        var act = () => sut.DenyCommand.Execute(null);

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(teardownError);
        errorsCompleted.Should().BeTrue();
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
        var completed = await Task.WhenAny(approve, Task.Delay(HangGuard));
        completed.Should().BeSameAs(approve);
        await approve;
    }

    [Fact]
    public void Deny_After_Dispose_Is_NoOp()
    {
        var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask);
        sut.SetModel(new Model("B", 2));
        sut.Dispose();

        sut.DenyCommand.Execute(null);

        sut.Model.Should().Be(new Model("B", 2), "deny on a disposed form must not revert");
    }

    [Fact]
    public async Task Admitted_Deny_Finishes_Before_Concurrent_Dispose()
    {
        using var releaseSnapshot = new ManualResetEventSlim();
        var snapshotStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var disposeFinished = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var pauseSnapshot = false;
        Model Snapshotter(Model model)
        {
            if (pauseSnapshot)
            {
                snapshotStarted.SetResult();
                // The test thread owns releaseSnapshot.Set() below; wait without a
                // fixed deadline so CI thread-pool starvation can't trip a spurious
                // timeout here. The outer WhenAll(...).WaitAsync() bounds the test.
                releaseSnapshot.Wait();
            }

            return model;
        }

        var sut = new FormVM<Model>(
            new Model("A", 1),
            _ => Task.CompletedTask,
            snapshotter: Snapshotter);
        sut.SetModel(new Model("B", 2));
        pauseSnapshot = true;

        var denier = Task.Run(() => sut.DenyCommand.Execute(null));
        await snapshotStarted.Task.WaitAsync(HangGuard);

        var disposer = Task.Run(() =>
        {
            sut.Dispose();
            disposeFinished.SetResult();
        });
        var disposedDuringSnapshot = await Task.WhenAny(
            disposeFinished.Task,
            Task.Delay(TimeSpan.FromMilliseconds(100))) == disposeFinished.Task;
        releaseSnapshot.Set();

        await Task.WhenAll(denier, disposer).WaitAsync(HangGuard);
        disposedDuringSnapshot.Should().BeFalse();
        sut.Model.Should().Be(new Model("A", 1));
    }

    [Fact]
    public async Task Approve_After_Dispose_Does_Not_Invoke_Persister()
    {
        // The persister is an external side effect and must not run on a
        // disposed form (symmetric with the Deny guard).
        var persisted = new List<Model>();
        var sut = new FormVM<Model>(new Model("A", 1), m => { persisted.Add(m); return Task.CompletedTask; });
        sut.Dispose();

        await sut.ApproveAsync();

        persisted.Should().BeEmpty();
    }

    // ── Approve error channel (VMX-008) ───────────────────────────────────────

    [Fact]
    public async Task ApproveCommand_Surfaces_Persister_Failure_On_ApproveErrors()
    {
        // ApproveCommand.Execute() is fire-and-forget (ICommand.Execute is void),
        // so a persister failure cannot propagate to the caller. It must be
        // surfaced on ApproveErrors rather than discarded with the faulted Task
        // (VMX-008).
        var boom = new InvalidOperationException("persist failed");
        var observed = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);

        using var sut = new FormVM<Model>(new Model("A", 1), _ => Task.FromException(boom));
        using var sub = sut.ApproveErrors.Subscribe(e => observed.TrySetResult(e));
        sut.SetModel(new Model("B", 2));

        sut.ApproveCommand.Execute(null); // fire-and-forget

        var completed = await Task.WhenAny(observed.Task, Task.Delay(HangGuard));
        completed.Should().BeSameAs(observed.Task, "the persister failure must be observed on ApproveErrors");
        (await observed.Task).Should().BeSameAs(boom, "the original persister exception is surfaced");
        sut.IsDirty.Should().BeTrue("a failed persist must not advance the snapshot");
    }

    [Fact]
    public void ApproveErrors_Completes_On_Dispose()
    {
        var completed = false;
        var sut = new FormVM<Model>(new Model("A", 1), _ => Task.CompletedTask);
        using var sub = sut.ApproveErrors.Subscribe(_ => { }, () => completed = true);

        sut.Dispose();

        completed.Should().BeTrue("ApproveErrors completes on Dispose");
    }

    // spec/20 §5.5 (ADR-0176): the ApproveErrors delivery opens no scope, so
    // another thread's Dispose does not wait for it. The teardown is deferred
    // until the delivery returns, so the channel never completes under a
    // running observer.
    [Fact]
    public async Task Dispose_Defers_Teardown_Until_InFlight_ApproveError_Delivery_Returns()
    {
        using var observerEntered = new ManualResetEventSlim();
        using var releaseObserver = new ManualResetEventSlim();
        var completed = 0;
        var completedDuringDelivery = false;
        var sut = new FormVM<Model>(
            new Model("A", 1),
            _ => Task.FromException(new InvalidOperationException("boom")));
        using var subscription = sut.ApproveErrors.Subscribe(
            _ =>
            {
                observerEntered.Set();
                releaseObserver.Wait(HangGuard).Should().BeTrue();
                completedDuringDelivery = Volatile.Read(ref completed) != 0;
            },
            () => Interlocked.Exchange(ref completed, 1));

        var execute = Task.Run(() => sut.ApproveCommand.Execute(null));
        observerEntered.Wait(HangGuard).Should().BeTrue();
        try
        {
            await Task.Run(sut.Dispose).WaitAsync(HangGuard);
            Volatile.Read(ref completed).Should().Be(0, "the delivery in progress defers the teardown");
        }
        finally
        {
            releaseObserver.Set();
        }

        await execute.WaitAsync(HangGuard);
        SpinWait.SpinUntil(() => Volatile.Read(ref completed) != 0, HangGuard).Should().BeTrue();
        completedDuringDelivery.Should().BeFalse();
    }

    // spec/20 §5.5: only a nested approval's OnApproved delivery suspends the
    // outer pre-publication window. An update from a nested failed
    // settlement's CanExecuteChanged observer is queued, as in Python and Rust.
    [Fact]
    public async Task Nested_Failed_Settlement_Keeps_The_Outer_Window()
    {
        var persists = 0;
        using var form = new FormVM<Model>(new Model("initial", 0), _ =>
            Interlocked.Increment(ref persists) == 2
                ? Task.FromException(new InvalidOperationException("inner"))
                : Task.CompletedTask);
        form.SetModel(new Model("edited", 0));
        var edges = 0;
        Model? insideOuter = null;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            edges++;
            if (edges == 2)
            {
                // Outer settlement step 3: a nested approval fails at once.
                form.ApproveAsync().IsFaulted.Should().BeTrue();
                insideOuter = form.Model;
            }
            else if (edges == 4)
            {
                // The nested failed settlement's notification.
                form.SetModel(new Model("from-inner-failure", 0));
            }
        };

        await form.ApproveAsync().WaitAsync(HangGuard);

        edges.Should().BeGreaterThanOrEqualTo(4);
        insideOuter.Should().Be(new Model("edited", 0), "the update joined the outer queue");
        form.Model.Should().Be(new Model("from-inner-failure", 0), "it replays after OnApproved");
    }

    // spec/20 §5.4, ADR-0180: an approval admitted from an ErrorsChanged
    // observer of an update is nested. Its admission notification follows the
    // update's own notifications, and its persister starts after them, before
    // the update returns.
    [Fact]
    public async Task An_Approval_From_An_ErrorsChanged_Observer_Starts_After_The_Update_Notifies()
    {
        var log = new List<string>();
        Task? approval = null;
        using var hub = new MessageHub();
        using var form = new FormVM<Model>(
            new Model("x", 0),
            model =>
            {
                log.Add($"persist:{model.Name}");
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: model => model,
            validators: new Dictionary<string, Func<Model, string?>>
            {
                ["Name"] = model => model.Name == "x" ? "rejected" : null,
            });
        using var errors = form.ErrorsChanged.Subscribe(map =>
        {
            log.Add($"errors:{map.Count}");
            approval ??= form.ApproveAsync();
            log.Add("nested returned");
        });
        form.ApproveCommand.CanExecuteChanged += (_, _) => log.Add("can_execute");
        using var approved = form.OnApproved.Subscribe(model => log.Add($"approved:{model.Name}"));
        using var messages = hub.Messages.Subscribe(message =>
        {
            if (message is PropertyChangedMessage<FormVM<Model>> { PropertyName: "Model" }) log.Add("model");
        });

        form.SetModel(new Model("ok", 0));
        log.Add("outer returned");

        approval.Should().NotBeNull();
        await approval!.WaitAsync(HangGuard);
        log.Should().Equal(
            "errors:0", "nested returned", "can_execute", "model", "can_execute",
            "persist:ok", "can_execute", "approved:ok", "outer returned");
        form.Snapshot.Should().Be(new Model("ok", 0));
    }

    // spec/20 §5.3, ADR-0180: a nested approval whose admission observer
    // throws never calls the persister, as a top-level admission does (#732).
    // The failure reaches the outermost update's caller, the in-flight mark is
    // released, and observers that saw the admission edge see a release edge.
    [Fact]
    public void A_Nested_Approval_Whose_Admission_Observer_Throws_Never_Persists()
    {
        var persisted = 0;
        var canExecuteCalls = 0;
        var nested = false;
        FormVM<Model>? form = null;
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("x", 0),
            _ =>
            {
                persisted++;
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: model => model,
            validators: new Dictionary<string, Func<Model, string?>>
            {
                ["Name"] = model =>
                {
                    if (model.Name == "a" && !nested)
                    {
                        nested = true;
                        form!.ApproveCommand.Execute(null);
                    }
                    return null;
                },
            });
        using var owned = form;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (++canExecuteCalls == 1) throw new InvalidOperationException("admission observer");
        };

        var act = () => form.SetModel(new Model("a", 0));

        act.Should().Throw<InvalidOperationException>().WithMessage("admission observer");
        persisted.Should().Be(0);
        canExecuteCalls.Should().Be(2, "the release edge follows the failed admission edge");
        form.ApproveCommand.CanExecute(null).Should().BeTrue("the in-flight mark is released");
    }

    // ── Test double helpers ───────────────────────────────────────────────────

    private sealed class LambdaPersister<TM>(Func<TM, Task> action) : IFormPersister<TM>
    {
        public Task PersistAsync(TM model) => action(model);
    }
}
