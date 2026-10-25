using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Forms;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-031..FORM-034 — single-flight approval admission.
/// See spec/20-form-vm.md §5.3 and ADR-0143. Every wait on the persister uses a
/// <see cref="TaskCompletionSource"/> gate bounded by <see cref="HangGuard"/>.
/// </summary>
public sealed class FORM_031_to_034_ApprovalAdmission_Tests
{
    private sealed record Model(string Value);

    private static readonly IReadOnlyDictionary<string, Func<Model, string?>> ValueRequired =
        new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model => model.Value.Length == 0 ? "required" : null,
        };

    // A persister whose every call blocks until the test settles it. Call
    // indexes follow invocation order. Settlement continuations run
    // asynchronously by default, so the form settles on a pool thread rather
    // than inline in the test; inline completion is opt-in for checks that need
    // the whole settlement to finish before Succeed/Fail returns.
    private sealed class GatedPersister(bool inlineCompletion = false)
    {
        private readonly object _lock = new();
        private readonly List<Model> _models = [];
        private readonly List<TaskCompletionSource> _entered = [];
        private readonly List<TaskCompletionSource> _releases = [];

        public Action<int, Model>? Inside { get; set; }

        public int Calls
        {
            get { lock (_lock) return _models.Count; }
        }

        public IReadOnlyList<Model> Models
        {
            get { lock (_lock) return [.. _models]; }
        }

        public Task Persist(Model model)
        {
            int call;
            TaskCompletionSource entered;
            TaskCompletionSource release;
            lock (_lock)
            {
                _models.Add(model);
                call = _models.Count - 1;
                entered = Slot(_entered, call, inline: false);
                release = Slot(_releases, call, inlineCompletion);
            }
            Inside?.Invoke(call, model);
            entered.TrySetResult();
            return release.Task;
        }

        public Task Entered(int call)
        {
            lock (_lock) return Slot(_entered, call, inline: false).Task.WaitAsync(HangGuard);
        }

        public void Succeed(int call) => Release(call).TrySetResult();

        public void Fail(int call, Exception error) => Release(call).TrySetException(error);

        public void Cancel(int call) => Release(call).TrySetCanceled();

        private TaskCompletionSource Release(int call)
        {
            lock (_lock) return Slot(_releases, call, inlineCompletion);
        }

        private static TaskCompletionSource Slot(List<TaskCompletionSource> slots, int call, bool inline)
        {
            while (slots.Count <= call)
            {
                slots.Add(new TaskCompletionSource(
                    inline ? TaskCreationOptions.None : TaskCreationOptions.RunContinuationsAsynchronously));
            }
            return slots[call];
        }
    }

    // Records every observable outcome a refused call must not produce.
    private sealed class Outcomes : IDisposable
    {
        private readonly List<IDisposable> _subscriptions = [];
        private int _canExecuteChanged;

        public Outcomes(FormVM<Model> form)
        {
            _subscriptions.Add(form.OnApproved.Subscribe(Approved.Enqueue));
            _subscriptions.Add(form.ApproveErrors.Subscribe(ApproveErrors.Enqueue));
            _subscriptions.Add(form.ErrorsChanged.Subscribe(ErrorsChanged.Enqueue));
            form.ApproveCommand.CanExecuteChanged += (_, _) => Interlocked.Increment(ref _canExecuteChanged);
        }

        public ConcurrentQueue<Model> Approved { get; } = new();
        public ConcurrentQueue<Exception> ApproveErrors { get; } = new();
        public ConcurrentQueue<IReadOnlyDictionary<string, string>> ErrorsChanged { get; } = new();
        public int CanExecuteChanged => Volatile.Read(ref _canExecuteChanged);

        public void Dispose()
        {
            foreach (var subscription in _subscriptions) subscription.Dispose();
        }
    }

    // Errors is a fresh copy on every read, so the state compares it by content.
    private static (Model Model, Model Snapshot, bool Dirty, string Errors) StateOf(FormVM<Model> form) =>
        (form.Model, form.Snapshot, form.IsDirty,
            string.Join(";", form.Errors.OrderBy(kvp => kvp.Key, StringComparer.Ordinal).Select(kvp => $"{kvp.Key}={kvp.Value}")));

    // ── FORM-031 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-031")]
    public async Task FORM_031_Approve_Calls_During_An_InFlight_Approval_Are_Refused()
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist, validators: ValueRequired);
        form.SetModel(new("first"));
        using var outcomes = new Outcomes(form);

        // The handler approves once, from the admission notification; the
        // persister approves once, from inside its first invocation.
        Task? fromHandler = null;
        Task? fromPersister = null;
        var handlerArmed = true;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (!handlerArmed) return;
            handlerArmed = false;
            fromHandler = form.ApproveAsync();
        };
        persister.Inside = (call, _) =>
        {
            if (call == 0) fromPersister = form.ApproveAsync();
        };

        var first = form.ApproveAsync();
        await persister.Entered(0);
        var inFlight = StateOf(form);

        var direct = form.ApproveAsync();
        form.ApproveCommand.Execute(null);
        Task? fromOtherThread = null;
        await Task.Run(() =>
        {
            fromOtherThread = form.ApproveAsync();
            form.ApproveCommand.Execute(null);
        }).WaitAsync(HangGuard);

        persister.Calls.Should().Be(1, "every approve call made while one is in flight is refused");
        foreach (var refused in new[] { direct, fromHandler, fromPersister, fromOtherThread })
        {
            refused.Should().NotBeNull();
            refused!.IsCompletedSuccessfully.Should().BeTrue("a refused call completes normally, without throwing");
        }
        StateOf(form).Should().Be(inFlight, "a refused call changes no model, snapshot, dirty, or error state");
        form.Model.Should().Be(new Model("first"));
        form.Snapshot.Should().Be(new Model("initial"));
        outcomes.Approved.Should().BeEmpty();
        outcomes.ApproveErrors.Should().BeEmpty();
        outcomes.ErrorsChanged.Should().BeEmpty();
        first.IsCompleted.Should().BeFalse("the admitted approval is still waiting in the persister");

        persister.Succeed(0);
        await first.WaitAsync(HangGuard);

        form.Snapshot.Should().Be(new Model("first"), "the snapshot advances to the first approval's captured model");
        outcomes.Approved.Should().Equal(new Model("first"));

        form.SetModel(new("second"));
        var second = form.ApproveAsync();
        await persister.Entered(1);
        persister.Models.Should().Equal(new Model("first"), new Model("second"));
        persister.Succeed(1);
        await second.WaitAsync(HangGuard);

        form.Snapshot.Should().Be(new Model("second"), "the next approval is admitted after settlement");
        outcomes.Approved.Should().Equal(new Model("first"), new Model("second"));
        outcomes.ApproveErrors.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "FORM-031")]
    public async Task FORM_031_Concurrent_Approve_Calls_Admit_Exactly_One()
    {
        const int Callers = 8;
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        form.SetModel(new("edited"));
        using var outcomes = new Outcomes(form);
        var approvals = new ConcurrentQueue<Task>();
        var failures = new ConcurrentQueue<Exception>();
        using var go = new ManualResetEventSlim();
        var threads = Enumerable.Range(0, Callers).Select(index => new Thread(() =>
        {
            try
            {
                go.Wait();
                if (index % 2 == 0)
                    approvals.Enqueue(form.ApproveAsync());
                else
                    form.ApproveCommand.Execute(null);
            }
            catch (Exception error)
            {
                failures.Enqueue(error);
            }
        })).ToList();
        threads.ForEach(thread => thread.Start());

        go.Set();
        foreach (var thread in threads)
            thread.Join(HangGuard).Should().BeTrue();
        await persister.Entered(0);

        failures.Should().BeEmpty();
        persister.Calls.Should().Be(1, "admission and the in-flight mark are one atomic step");
        approvals.Count(approval => !approval.IsCompleted).Should().BeLessThanOrEqualTo(1);

        persister.Succeed(0);
        await Task.WhenAll(approvals).WaitAsync(HangGuard);
        await WaitUntilAsync(() => !outcomes.Approved.IsEmpty);

        persister.Calls.Should().Be(1);
        outcomes.Approved.Should().Equal(new Model("edited"));
        outcomes.ApproveErrors.Should().BeEmpty();
        form.Snapshot.Should().Be(new Model("edited"));
    }

    // ── FORM-032 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-032")]
    public async Task FORM_032_ApproveCommand_Is_Disabled_While_InFlight_And_Notifies_Once_Per_Edge()
    {
        var boom = new InvalidOperationException("persist failed");
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist, validators: ValueRequired);
        form.SetModel(new("edited"));
        using var outcomes = new Outcomes(form);
        var notificationsAtPersist = new List<int>();
        persister.Inside = (_, _) => notificationsAtPersist.Add(outcomes.CanExecuteChanged);

        // Success.
        var before = outcomes.CanExecuteChanged;
        var approval = form.ApproveAsync();
        await persister.Entered(0);
        notificationsAtPersist[0].Should().Be(before + 1, "admission notifies once before the persister runs");
        form.ApproveCommand.CanExecute(null).Should().BeFalse("approval is disabled while in flight");
        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);
        outcomes.CanExecuteChanged.Should().Be(before + 2, "success settlement notifies exactly once");
        form.ApproveCommand.CanExecute(null).Should().BeTrue("valid and non-strict once settled");

        // Persister failure.
        before = outcomes.CanExecuteChanged;
        approval = form.ApproveAsync();
        await persister.Entered(1);
        notificationsAtPersist[1].Should().Be(before + 1);
        form.ApproveCommand.CanExecute(null).Should().BeFalse();
        persister.Fail(1, boom);
        (await approval.Invoking(task => task.WaitAsync(HangGuard)).Should().ThrowAsync<InvalidOperationException>())
            .Which.Should().BeSameAs(boom);
        outcomes.CanExecuteChanged.Should().Be(before + 2, "failure settlement notifies exactly once");
        form.ApproveCommand.CanExecute(null).Should().BeTrue();

        // Persister cancellation, through the command path.
        before = outcomes.CanExecuteChanged;
        form.ApproveCommand.Execute(null);
        await persister.Entered(2);
        notificationsAtPersist[2].Should().Be(before + 1);
        form.ApproveCommand.CanExecute(null).Should().BeFalse();
        persister.Cancel(2);
        await WaitUntilAsync(() => outcomes.CanExecuteChanged == before + 2);
        outcomes.CanExecuteChanged.Should().Be(before + 2, "cancellation settlement notifies exactly once");
        form.ApproveCommand.CanExecute(null).Should().BeTrue();
        persister.Calls.Should().Be(3);
    }

    [Fact, Trait("Conformance", "FORM-032")]
    public async Task FORM_032_Reset_Settlement_Notifies_Exactly_Once()
    {
        // A reset that throws after a successful persist settles once; the
        // strict gate still sees the unchanged dirty model afterwards.
        var boom = new InvalidOperationException("reset failed after persistence");
        var failingPersister = new GatedPersister();
        using var failing = new FormVM<Model>(
            new("initial"), failingPersister.Persist, strict: true, resetOnApproved: _ => throw boom);
        failing.SetModel(new("edited"));
        using var failingOutcomes = new Outcomes(failing);

        var approval = failing.ApproveAsync();
        await failingPersister.Entered(0);
        failing.ApproveCommand.CanExecute(null).Should().BeFalse();
        failingOutcomes.CanExecuteChanged.Should().Be(1);
        failingPersister.Succeed(0);
        (await approval.Invoking(task => task.WaitAsync(HangGuard)).Should().ThrowAsync<InvalidOperationException>())
            .Which.Should().BeSameAs(boom);

        failingOutcomes.CanExecuteChanged.Should().Be(2, "reset failure settlement notifies exactly once");
        failing.ApproveCommand.CanExecute(null).Should().BeTrue("still valid and dirty in strict mode");
        failingOutcomes.Approved.Should().BeEmpty();

        // A successful reset that flips both validity and strict dirtiness
        // still raises one settlement notification, after ErrorsChanged.
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(
            new("initial"), persister.Persist, strict: true, validators: ValueRequired, resetOnApproved: _ => new(""));
        form.SetModel(new("edited"));
        var trace = new List<string>();
        using var errors = form.ErrorsChanged.Subscribe(_ => trace.Add("errors"));
        form.ApproveCommand.CanExecuteChanged += (_, _) => trace.Add("can_execute");
        using var approved = form.OnApproved.Subscribe(_ => trace.Add("approved"));

        approval = form.ApproveAsync();
        await persister.Entered(0);
        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);

        trace.Should().Equal("can_execute", "errors", "can_execute", "approved");
        form.ApproveCommand.CanExecute(null).Should().BeFalse("the pristine, invalid reset disables approval");
    }

    // ── FORM-033 ──────────────────────────────────────────────────────────────

    [Theory, Trait("Conformance", "FORM-033")]
    [InlineData(false)]
    [InlineData(true)]
    public async Task FORM_033_OnApproved_Observer_Approval_Is_Admitted_With_The_Settled_Model(bool strict)
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(
            new("initial"), persister.Persist, strict: strict, resetOnApproved: model => new($"reset:{model.Value}"));
        form.SetModel(new("first"));
        Task? nested = null;
        (bool CanExecute, bool Valid, bool Dirty)? observed = null;
        using var subscription = form.OnApproved.Subscribe(_ =>
        {
            if (nested is not null) return;
            observed = (form.ApproveCommand.CanExecute(null), form.IsValid, form.IsDirty);
            nested = form.ApproveAsync();
        });

        var first = form.ApproveAsync();
        await persister.Entered(0);
        persister.Succeed(0);
        await first.WaitAsync(HangGuard);

        observed.Should().NotBeNull();
        observed!.Value.CanExecute.Should().Be(
            observed.Value.Valid && (!strict || observed.Value.Dirty),
            "the observer sees only the validity and strict-mode gates");
        await persister.Entered(1);
        persister.Models.Should().Equal(new Model("first"), new Model("reset:first"));
        persister.Succeed(1);
        await nested!.WaitAsync(HangGuard);
        form.Snapshot.Should().Be(new Model("reset:reset:first"));
    }

    [Fact, Trait("Conformance", "FORM-033")]
    public async Task FORM_033_Failed_Settlement_Keeps_The_Persister_Failure_First()
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        form.SetModel(new("first"));

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        var throwOnce = true;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (!throwOnce) return;
            throwOnce = false;
            throw new InvalidOperationException("observer-fail");
        };
        persister.Fail(0, new InvalidOperationException("persist-fail"));

        var failure = await approval.Invoking(task => task.WaitAsync(HangGuard))
            .Should().ThrowAsync<InvalidOperationException>();
        failure.WithMessage("persist-fail");
        throwOnce.Should().BeFalse("the settlement notification reached the observer");
    }

    [Fact, Trait("Conformance", "FORM-033")]
    public async Task FORM_033_Settlement_Clears_The_Mark_Before_Each_Notification()
    {
        // The model turns invalid during the persist and the reset makes it
        // valid again, so settlement publishes ErrorsChanged as well.
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(
            new("initial"), persister.Persist, validators: ValueRequired,
            resetOnApproved: model => new($"reset:{model.Value}"));
        form.SetModel(new("first"));
        var approval = form.ApproveAsync();
        await persister.Entered(0);
        form.SetModel(new(""));
        form.IsValid.Should().BeFalse();

        var trace = new List<(string Step, bool CanExecute)>();
        Task? fromSettlement = null;
        var approveFromSettlement = true;
        using var errors = form.ErrorsChanged.Subscribe(_ => trace.Add(("errors", form.ApproveCommand.CanExecute(null))));
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            trace.Add(("can_execute", form.ApproveCommand.CanExecute(null)));
            if (!approveFromSettlement) return;
            approveFromSettlement = false;
            fromSettlement = form.ApproveAsync();
        };
        var approved = new List<Model>();
        using var approvedSubscription = form.OnApproved.Subscribe(model =>
        {
            trace.Add(("approved", form.ApproveCommand.CanExecute(null)));
            approved.Add(model);
        });

        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);

        // The settlement CanExecuteChanged handler started an approval: it was
        // admitted (one admission notification, CanExecute now false) and runs
        // independently of the settled approval's OnApproved.
        trace.Should().Equal(
            ("errors", true),
            ("can_execute", true),
            ("can_execute", false),
            ("approved", false));
        approved.Should().Equal(new Model("first"));
        await persister.Entered(1);
        persister.Models.Should().Equal(new Model("first"), new Model("reset:first"));
        persister.Succeed(1);
        await fromSettlement!.WaitAsync(HangGuard);
        trace.Skip(4).Should().Equal(("can_execute", true), ("approved", true));
        approved.Should().Equal(new Model("first"), new Model("reset:first"));
        form.Snapshot.Should().Be(new Model("reset:reset:first"));
    }

    [Fact, Trait("Conformance", "FORM-032")]
    public async Task FORM_032_Cancelled_Command_Approval_Is_Routed_To_ApproveErrors()
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        form.SetModel(new("edited"));
        var errorSeen = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        var approved = 0;
        using var errors = form.ApproveErrors.Subscribe(error => errorSeen.TrySetResult(error));
        using var approvals = form.OnApproved.Subscribe(_ => Interlocked.Increment(ref approved));

        form.ApproveCommand.Execute(null);
        await persister.Entered(0);
        persister.Cancel(0);

        var error = await errorSeen.Task.WaitAsync(HangGuard);
        error.Should().BeAssignableTo<OperationCanceledException>();
        Volatile.Read(ref approved).Should().Be(0);
        form.ApproveCommand.CanExecute(null).Should().BeTrue();
        form.Snapshot.Should().Be(new Model("initial"));
    }

    [Fact, Trait("Conformance", "FORM-033")]
    public async Task FORM_033_Command_Failure_Routes_Once_And_Its_Observer_Approval_Is_Admitted()
    {
        var boom = new InvalidOperationException("persist failed");
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist, validators: ValueRequired);
        form.SetModel(new("edited"));
        var errors = new ConcurrentQueue<Exception>();
        var errorSeen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        (Model Model, Model Snapshot, bool Dirty, string Errors)? stateAtError = null;
        Task? retry = null;
        using var subscription = form.ApproveErrors.Subscribe(error =>
        {
            errors.Enqueue(error);
            if (retry is null)
            {
                stateAtError = StateOf(form);
                retry = form.ApproveAsync();
            }
            errorSeen.TrySetResult();
        });

        form.ApproveCommand.Execute(null);
        await persister.Entered(0);
        persister.Fail(0, boom);
        await errorSeen.Task.WaitAsync(HangGuard);

        errors.Should().ContainSingle().Which.Should().BeSameAs(boom);
        stateAtError.Should().NotBeNull();
        stateAtError!.Value.Model.Should().Be(new Model("edited"));
        stateAtError.Value.Snapshot.Should().Be(new Model("initial"));
        stateAtError.Value.Dirty.Should().BeTrue();
        stateAtError.Value.Errors.Should().BeEmpty();
        await persister.Entered(1);
        persister.Models.Should().Equal(new Model("edited"), new Model("edited"));

        persister.Succeed(1);
        await retry!.WaitAsync(HangGuard);
        errors.Should().ContainSingle("the awaitable retry emits nothing on ApproveErrors");
        form.Snapshot.Should().Be(new Model("edited"));
    }

    // #732: observers that saw the admission edge's false also see the release
    // when a later admission observer throws and abandons the approval.
    [Fact, Trait("Conformance", "FORM-032")]
    public async Task FORM_032_Throwing_Admission_Observer_Releases_Earlier_Observers()
    {
        var boom = new InvalidOperationException("admission observer failed");
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        var seen = new List<bool>();
        form.ApproveCommand.CanExecuteChanged += (_, _) => seen.Add(form.ApproveCommand.CanExecute(null));
        var failures = new Queue<Exception>([boom, new InvalidOperationException("release observer failed")]);
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (failures.Count > 0) throw failures.Dequeue();
        };

        var approve = () => form.ApproveAsync();

        (await approve.Should().ThrowAsync<InvalidOperationException>()).Which.Should().BeSameAs(
            boom, "a failing release notification does not replace the admission failure");
        failures.Clear();
        persister.Calls.Should().Be(0);
        seen.Should().HaveCountGreaterThan(1);
        seen[0].Should().BeFalse();
        seen[^1].Should().BeTrue("the release notification reports the form approvable again");

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);
        persister.Calls.Should().Be(1);
    }

    [Fact, Trait("Conformance", "FORM-033")]
    public async Task FORM_033_Awaiter_Of_A_Failed_Approval_Can_Approve_Again()
    {
        var boom = new InvalidOperationException("persist failed");
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        form.SetModel(new("edited"));
        using var outcomes = new Outcomes(form);

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        persister.Fail(0, boom);
        Exception? caught = null;
        Task? retry = null;
        try
        {
            await approval.WaitAsync(HangGuard);
        }
        catch (InvalidOperationException error)
        {
            caught = error;
            retry = form.ApproveAsync();
        }

        caught.Should().BeSameAs(boom);
        outcomes.ApproveErrors.Should().BeEmpty("the awaiter alone observes an awaited failure");
        outcomes.Approved.Should().BeEmpty();
        form.Snapshot.Should().Be(new Model("initial"));
        await persister.Entered(1);
        persister.Succeed(1);
        await retry!.WaitAsync(HangGuard);
        persister.Calls.Should().Be(2);
        outcomes.Approved.Should().Equal(new Model("edited"));
        outcomes.ApproveErrors.Should().BeEmpty();
    }

    // ── FORM-034 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-034")]
    public async Task FORM_034_SetModel_And_Deny_Proceed_During_An_InFlight_Approval()
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(new("initial"), persister.Persist);
        form.SetModel(new("captured"));
        using var outcomes = new Outcomes(form);

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        form.SetModel(new("newer"));
        form.Model.Should().Be(new Model("newer"), "edits are not blocked while an approval is in flight");
        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);

        form.Snapshot.Should().Be(new Model("captured"));
        form.Model.Should().Be(new Model("newer"));
        form.IsDirty.Should().BeTrue();
        outcomes.Approved.Should().Equal(new Model("captured"));

        approval = form.ApproveAsync();
        await persister.Entered(1);
        form.DenyCommand.Execute(null);
        form.Model.Should().Be(new Model("captured"), "deny reverts to the current snapshot");
        persister.Succeed(1);
        await approval.WaitAsync(HangGuard);

        form.Snapshot.Should().Be(new Model("newer"), "the approval still commits its captured value");
        form.Model.Should().Be(new Model("captured"));
        form.IsDirty.Should().BeTrue();
        outcomes.Approved.Should().Equal(new Model("captured"), new Model("newer"));
    }

    [Fact, Trait("Conformance", "FORM-034")]
    public async Task FORM_034_Reset_Replaces_An_Edited_Or_Reverted_Model()
    {
        var persister = new GatedPersister();
        using var form = new FormVM<Model>(
            new("initial"), persister.Persist, resetOnApproved: model => new($"reset:{model.Value}"));
        form.SetModel(new("saved"));
        using var outcomes = new Outcomes(form);

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        form.SetModel(new("racing-edit"));
        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);

        form.Model.Should().Be(new Model("reset:saved"));
        form.Snapshot.Should().Be(new Model("reset:saved"));
        form.IsDirty.Should().BeFalse();

        form.SetModel(new("again"));
        approval = form.ApproveAsync();
        await persister.Entered(1);
        form.DenyCommand.Execute(null);
        form.Model.Should().Be(new Model("reset:saved"));
        persister.Succeed(1);
        await approval.WaitAsync(HangGuard);

        form.Model.Should().Be(new Model("reset:again"));
        form.Snapshot.Should().Be(new Model("reset:again"));
        form.IsDirty.Should().BeFalse();
        outcomes.Approved.Should().Equal(new Model("saved"), new Model("again"));
    }

    [Fact, Trait("Conformance", "FORM-034")]
    public async Task FORM_034_Disposal_On_Another_Thread_Suppresses_Settlement()
    {
        var resets = 0;
        var persister = new GatedPersister();
        var form = new FormVM<Model>(
            new("initial"), persister.Persist, validators: ValueRequired,
            resetOnApproved: _ => { Interlocked.Increment(ref resets); return new(""); });
        form.SetModel(new("saved"));
        using var outcomes = new Outcomes(form);

        var approval = form.ApproveAsync();
        await persister.Entered(0);
        await Task.Run(form.Dispose).WaitAsync(HangGuard);
        var afterDispose = (outcomes.CanExecuteChanged, outcomes.ErrorsChanged.Count);

        persister.Succeed(0);
        await approval.WaitAsync(HangGuard);

        resets.Should().Be(0, "disposal suppresses the post-persist commit");
        form.Model.Should().Be(new Model("saved"));
        form.Snapshot.Should().Be(new Model("initial"));
        (outcomes.CanExecuteChanged, outcomes.ErrorsChanged.Count).Should().Be(afterDispose,
            "settlement publishes nothing after disposal");
        outcomes.Approved.Should().BeEmpty();
        outcomes.ApproveErrors.Should().BeEmpty();

        await form.ApproveAsync().WaitAsync(HangGuard);
        persister.Calls.Should().Be(1, "a disposed form never invokes the persister");
    }

    [Fact, Trait("Conformance", "FORM-034")]
    public async Task FORM_034_Disposal_Drops_A_Later_Persister_Failure()
    {
        var boom = new InvalidOperationException("persist failed after dispose");

        // Awaitable path: the awaiter still observes the failure (unchanged by
        // §5.3), and the disposed form emits nothing.
        var direct = new GatedPersister();
        var awaited = new FormVM<Model>(new("initial"), direct.Persist);
        using var awaitedOutcomes = new Outcomes(awaited);
        var approval = awaited.ApproveAsync();
        await direct.Entered(0);
        awaited.Dispose();
        var afterDispose = awaitedOutcomes.CanExecuteChanged;
        direct.Fail(0, boom);
        (await approval.Invoking(task => task.WaitAsync(HangGuard)).Should().ThrowAsync<InvalidOperationException>())
            .Which.Should().BeSameAs(boom);
        awaitedOutcomes.CanExecuteChanged.Should().Be(afterDispose);
        awaitedOutcomes.ApproveErrors.Should().BeEmpty();

        // Command path: inline completion runs the whole settlement before Fail
        // returns, so nothing can still be pending when the counts are read.
        var command = new GatedPersister(inlineCompletion: true);
        var fired = new FormVM<Model>(new("initial"), command.Persist);
        using var firedOutcomes = new Outcomes(fired);
        fired.ApproveCommand.Execute(null);
        await command.Entered(0);
        fired.Dispose();
        afterDispose = firedOutcomes.CanExecuteChanged;
        command.Fail(0, boom);

        firedOutcomes.CanExecuteChanged.Should().Be(afterDispose);
        firedOutcomes.ApproveErrors.Should().BeEmpty("a failure after disposal is not re-surfaced");
        await fired.ApproveAsync().WaitAsync(HangGuard);
        command.Calls.Should().Be(1);
    }

    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        using var deadline = new CancellationTokenSource(HangGuard);
        while (!condition())
            await Task.Delay(TimeSpan.FromMilliseconds(5), deadline.Token);
    }
}
