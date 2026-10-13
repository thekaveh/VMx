using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-035..FORM-038 — failure-atomic model updates.
/// <c>SetModel</c> and deny prepare (equality, validators, snapshotter) before
/// they commit; a failing callback propagates with the form unchanged and
/// nothing published, and a preparation that a same-thread nested update or
/// disposal made stale commits nothing. Updates from other threads are
/// serialized, never dropped. See spec/20-form-vm.md §5.2/§5.4 and ADR-0144.
/// </summary>
public sealed class FORM_035_to_038_FailureAtomicUpdates_Tests
{
    private const string Poison = "poison";

    private sealed record Model(string Value);

    // A model whose equality fails for a marked value. FailAsArgument fails the
    // comparison with the live model (live.Equals(candidate)); FailAsReceiver
    // passes that comparison and fails the dirty comparison against the
    // snapshot (candidate.Equals(snapshot)) later in preparation.
    private sealed record Fragile(string Value)
    {
        public const string FailAsArgument = "fail-as-argument";
        public const string FailAsReceiver = "fail-as-receiver";

        public static readonly InvalidOperationException Failure = new("equality failed");

        public bool Equals(Fragile? other)
        {
            if (Value == FailAsReceiver || other?.Value == FailAsArgument) throw Failure;
            return other is not null && Value == other.Value;
        }

        public override int GetHashCode() => StringComparer.Ordinal.GetHashCode(Value);
    }

    private sealed record FormState<TM>(TM Model, TM Snapshot, string Errors, bool IsDirty, bool IsValid, bool CanApprove);

    // Records every notification an update may publish, in order: ErrorsChanged
    // (with its payload, and its completion on disposal),
    // ApproveCommand.CanExecuteChanged, and the form's FormRevertedMessage and
    // model PropertyChangedMessage on the hub. A model message also records the
    // form state its synchronous subscriber observed.
    private sealed class Probe<TM> : IDisposable
        where TM : notnull
    {
        private readonly List<IDisposable> _subscriptions = [];

        public Probe(FormVM<TM> form, IMessageHub hub)
        {
            _subscriptions.Add(form.ErrorsChanged.Subscribe(
                errors => Trace.Add("errors:" + Format(errors)),
                () => Trace.Add("errors_completed")));
            form.ApproveCommand.CanExecuteChanged += (_, _) => Trace.Add("can_execute");
            _subscriptions.Add(hub.Messages.Subscribe(message =>
            {
                if (message is FormRevertedMessage reverted && ReferenceEquals(reverted.Sender, form))
                {
                    Trace.Add("reverted");
                }
                else if (message is PropertyChangedMessage<FormVM<TM>> changed &&
                    ReferenceEquals(changed.Sender, form) && changed.PropertyName == "Model")
                {
                    Trace.Add("model");
                    Observed.Add(StateOf(form));
                }
            }));
        }

        public List<string> Trace { get; } = [];

        public List<FormState<TM>> Observed { get; } = [];

        public void Clear()
        {
            Trace.Clear();
            Observed.Clear();
        }

        public void Dispose()
        {
            foreach (var subscription in _subscriptions) subscription.Dispose();
        }
    }

    private static string Format(IReadOnlyDictionary<string, string> errors) =>
        string.Join(";", errors.OrderBy(kvp => kvp.Key, StringComparer.Ordinal).Select(kvp => $"{kvp.Key}={kvp.Value}"));

    private static FormState<TM> StateOf<TM>(FormVM<TM> form)
        where TM : notnull =>
        new(form.Model, form.Snapshot, Format(form.Errors), form.IsDirty, form.IsValid, form.ApproveCommand.CanExecute(null));

    // What a plain Dispose() publishes on the probe's channels (ErrorsChanged
    // completes and the approve command's teardown raises CanExecuteChanged).
    // An update abandoned by disposal must add nothing to this (spec/20 §5.4).
    private static List<string> DisposalOnlyTrace()
    {
        using var hub = new MessageHub();
        var form = new FormVM<Model>(
            new Model("initial"), _ => Task.CompletedTask, hub: hub, strict: true, snapshotter: model => model);
        using var probe = new Probe<Model>(form, hub);
        form.Dispose();
        return [.. probe.Trace];
    }

    // The update throws exactly `failure`, every observable piece of form state
    // keeps its value, and nothing is published.
    private static void AssertFailureIsAtomic<TM>(FormVM<TM> form, Probe<TM> probe, Action update, Exception failure)
        where TM : notnull
    {
        probe.Clear();
        var before = StateOf(form);

        update.Should().Throw<Exception>().Which.Should().BeSameAs(failure, "the failure propagates unchanged");

        StateOf(form).Should().Be(before, "a failed update commits nothing");
        probe.Trace.Should().BeEmpty("a failed update publishes nothing");
    }

    // ── FORM-035 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-035")]
    public void FORM_035_A_Failing_Field_Validator_Leaves_The_Form_Unchanged()
    {
        var failure = new InvalidOperationException("field validator failed");
        var runs = new List<string>();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                runs.Add(model.Value);
                if (model.Value == Poison) throw failure;
                return model.Value.Length == 0 ? "required" : null;
            },
        };
        using var hub = new MessageHub();
        using var form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var probe = new Probe<Model>(form, hub);

        // The validator's first run after construction fails: pristine and valid.
        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Model(Poison)), failure);
        runs.Should().Equal("initial", Poison);
        StateOf(form).Should().Be(new FormState<Model>(new Model("initial"), new Model("initial"), "", false, true, false));

        // After earlier successful runs: dirty, valid, and approvable.
        form.SetModel(new Model("edited"));
        probe.Trace.Should().Equal("can_execute", "model");
        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Model(Poison)), failure);
        StateOf(form).Should().Be(new FormState<Model>(new Model("edited"), new Model("initial"), "", true, true, true));

        // Dirty and invalid: the field error survives; the failure is not
        // turned into a validation error.
        form.SetModel(new Model(""));
        probe.Trace.Should().Equal("errors:Value=required", "can_execute", "model");
        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Model(Poison)), failure);
        StateOf(form).Should().Be(new FormState<Model>(new Model(""), new Model("initial"), "Value=required", true, false, false));
        runs.Should().Equal("initial", Poison, "edited", Poison, "", Poison);

        // A later candidate the validator accepts settles and publishes as
        // FORM-030 requires: one message, observed after the state settled.
        probe.Clear();
        form.SetModel(new Model("fixed"));
        var settled = new FormState<Model>(new Model("fixed"), new Model("initial"), "", true, true, true);
        StateOf(form).Should().Be(settled);
        probe.Trace.Should().Equal("errors:", "can_execute", "model");
        probe.Observed.Should().Equal(settled);
    }

    // ── FORM-036 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-036")]
    public void FORM_036_A_Failing_Model_Validator_Leaves_The_Form_Unchanged()
    {
        var failure = new InvalidOperationException("model validator failed");
        var fieldRuns = 0;
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = _ =>
            {
                fieldRuns++;
                return null;
            },
        };
        using var hub = new MessageHub();
        using var form = new FormVM<Model>(
            new Model(""),
            _ => Task.CompletedTask,
            hub: hub,
            snapshotter: model => model,
            validators: validators,
            modelValidator: model =>
            {
                if (model.Value == Poison) throw failure;
                return new Dictionary<string, string?> { ["Value"] = model.Value.Length == 0 ? "required" : null };
            });
        using var probe = new Probe<Model>(form, hub);

        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Model(Poison)), failure);
        fieldRuns.Should().Be(2, "the field validator ran before the model validator failed");
        StateOf(form).Should().Be(new FormState<Model>(new Model(""), new Model(""), "Value=required", false, false, false));

        probe.Clear();
        form.SetModel(new Model("ok"));
        var settled = new FormState<Model>(new Model("ok"), new Model(""), "", true, true, true);
        StateOf(form).Should().Be(settled);
        probe.Trace.Should().Equal("errors:", "can_execute", "model");
        probe.Observed.Should().Equal(settled);
    }

    [Fact, Trait("Conformance", "FORM-036")]
    public void FORM_036_A_Failing_Model_Equality_Leaves_The_Form_Unchanged()
    {
        var validated = new List<string>();
        var validators = new Dictionary<string, Func<Fragile, string?>>
        {
            ["Value"] = model =>
            {
                validated.Add(model.Value);
                return model.Value.Length == 0 ? "required" : null;
            },
        };
        using var hub = new MessageHub();
        using var form = new FormVM<Fragile>(
            new Fragile("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var probe = new Probe<Fragile>(form, hub);
        form.SetModel(new Fragile("edited"));
        validated.Clear();

        // The comparison with the live model fails, before any validation.
        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Fragile(Fragile.FailAsArgument)), Fragile.Failure);
        validated.Should().BeEmpty("equality with the live model is compared before validation");

        // The comparison with the snapshot fails after the live comparison passed.
        AssertFailureIsAtomic(form, probe, () => form.SetModel(new Fragile(Fragile.FailAsReceiver)), Fragile.Failure);
        StateOf(form).Should().Be(new FormState<Fragile>(new Fragile("edited"), new Fragile("initial"), "", true, true, true));

        probe.Clear();
        form.SetModel(new Fragile(""));
        var settled = new FormState<Fragile>(new Fragile(""), new Fragile("initial"), "Value=required", true, false, false);
        StateOf(form).Should().Be(settled);
        probe.Trace.Should().Equal("errors:Value=required", "can_execute", "model");
        probe.Observed.Should().Equal(settled);
    }

    [Fact, Trait("Conformance", "FORM-036")]
    public void FORM_036_Deny_With_A_Failing_Validator_Reverts_Nothing()
    {
        var failure = new InvalidOperationException("validator failed for the snapshot");
        var failOnSnapshot = false;
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                if (failOnSnapshot && model.Value == "initial") throw failure;
                return model.Value.Length == 0 ? "required" : null;
            },
        };
        using var hub = new MessageHub();
        using var form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new Model(""));

        failOnSnapshot = true;
        AssertFailureIsAtomic(form, probe, () => form.DenyCommand.Execute(null), failure);
        StateOf(form).Should().Be(new FormState<Model>(new Model(""), new Model("initial"), "Value=required", true, false, false));

        failOnSnapshot = false;
        probe.Clear();
        form.DenyCommand.Execute(null);
        var reverted = new FormState<Model>(new Model("initial"), new Model("initial"), "", false, true, false);
        StateOf(form).Should().Be(reverted);
        probe.Trace.Should().Equal("errors:", "reverted", "model", "can_execute");
        probe.Observed.Should().ContainSingle().Which.Model.Should().Be(new Model("initial"));
    }

    [Fact, Trait("Conformance", "FORM-036")]
    public void FORM_036_Deny_With_A_Failing_Snapshotter_Reverts_Nothing()
    {
        var failure = new InvalidOperationException("snapshotter failed");
        var failSnapshot = false;
        var snapshotterRuns = 0;
        Model Snapshotter(Model model)
        {
            snapshotterRuns++;
            if (failSnapshot) throw failure;
            return model;
        }

        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model => model.Value.Length == 0 ? "required" : null,
        };
        using var hub = new MessageHub();
        using var form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: Snapshotter,
            validators: validators);
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new Model(""));

        failSnapshot = true;
        AssertFailureIsAtomic(form, probe, () => form.DenyCommand.Execute(null), failure);
        snapshotterRuns.Should().Be(2, "construction and the failed deny each ran the snapshotter once");
        StateOf(form).Should().Be(new FormState<Model>(new Model(""), new Model("initial"), "Value=required", true, false, false));

        failSnapshot = false;
        probe.Clear();
        form.DenyCommand.Execute(null);
        StateOf(form).Should().Be(new FormState<Model>(new Model("initial"), new Model("initial"), "", false, true, false));
        probe.Trace.Should().Equal("errors:", "reverted", "model", "can_execute");
    }

    // ── FORM-037 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-037")]
    public void FORM_037_A_Nested_SetModel_From_A_Validator_Wins()
    {
        FormVM<Model>? form = null;
        var nestedCalls = 0;
        var validated = new List<string>();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                validated.Add(model.Value);
                if (model.Value == "a" && nestedCalls++ == 0) form!.SetModel(new Model("b"));
                return model.Value == "b" ? "b is rejected" : null;
            },
        };
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        validated.Clear();

        form.SetModel(new Model("a"));

        nestedCalls.Should().Be(1);
        validated.Should().Equal("a", "b");
        var nested = new FormState<Model>(new Model("b"), new Model("initial"), "Value=b is rejected", true, false, false);
        StateOf(form).Should().Be(nested, "the nested assignment is the newest committed state");
        probe.Trace.Should().Equal(
            ["errors:Value=b is rejected", "can_execute", "model"],
            "only the nested assignment commits and publishes; the outer call publishes nothing after it");
        probe.Observed.Should().Equal(nested);

        // The form stays usable after the abandoned outer call.
        probe.Clear();
        form.SetModel(new Model("c"));
        StateOf(form).Should().Be(new FormState<Model>(new Model("c"), new Model("initial"), "", true, true, true));
        probe.Trace.Should().Equal("errors:", "can_execute", "model");
    }

    // Deny and an approval commit made from a validator are also "another update
    // committed during preparation" (spec/20 §5.4): the outer SetModel is stale.
    [Fact]
    public async Task A_Nested_Deny_Or_Approval_Commit_From_A_Validator_Also_Wins()
    {
        FormVM<Model>? form = null;
        Action? reenter = null;
        var persisted = new List<Model>();
        var approved = new List<Model>();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                if (model.Value == "a")
                {
                    var action = reenter;
                    reenter = null;
                    action?.Invoke();
                }
                return null;
            },
        };
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            model =>
            {
                persisted.Add(model);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: model => model,
            validators: validators);
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        using var approvedSubscription = form.OnApproved.Subscribe(approved.Add);

        form.SetModel(new Model("edited"));
        reenter = () => form.DenyCommand.Execute(null);
        probe.Clear();
        form.SetModel(new Model("a"));
        StateOf(form).Should().Be(new FormState<Model>(new Model("initial"), new Model("initial"), "", false, true, true));
        probe.Trace.Should().Equal("reverted", "model");

        form.SetModel(new Model("edited"));
        Task? approval = null;
        reenter = () => approval = form.ApproveAsync();
        probe.Clear();
        form.SetModel(new Model("a"));
        approval.Should().NotBeNull();
        await approval!;
        StateOf(form).Should().Be(new FormState<Model>(new Model("edited"), new Model("edited"), "", false, true, true));
        persisted.Should().Equal(new Model("edited"));
        approved.Should().Equal(new Model("edited"));
        probe.Trace.Should().Equal(
            ["can_execute", "can_execute"],
            "approval admission and settlement each raise CanExecuteChanged; the stale SetModel publishes nothing");
    }

    // ── FORM-038 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-038")]
    public async Task FORM_038_A_Validator_That_Disposes_During_SetModel_Commits_Nothing()
    {
        FormVM<Model>? form = null;
        var persisted = new List<Model>();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                if (model.Value == Poison)
                {
                    form!.Dispose();
                    return "rejected";
                }
                return null;
            },
        };
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            model =>
            {
                persisted.Add(model);
                return Task.CompletedTask;
            },
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new Model("edited"));
        probe.Clear();

        form.Invoking(f => f.SetModel(new Model(Poison))).Should().NotThrow();

        probe.Trace.Should().Equal(
            DisposalOnlyTrace(),
            "disposal's own effects occur and the abandoned assignment adds no notification of its own");
        form.Model.Should().Be(new Model("edited"), "the candidate is not committed");
        form.Snapshot.Should().Be(new Model("initial"));
        form.Errors.Should().BeEmpty("the candidate's validation result is not committed");
        form.IsDirty.Should().BeTrue();

        // FORM-014: the disposed form is inert.
        await form.Invoking(f => f.ApproveAsync()).Should().NotThrowAsync();
        form.Invoking(f => f.DenyCommand.Execute(null)).Should().NotThrow();
        form.Invoking(f => f.SetModel(new Model("late"))).Should().NotThrow();
        persisted.Should().BeEmpty("the persister never runs on a disposed form");
        form.Model.Should().Be(new Model("edited"), "neither deny nor a later assignment changes a disposed form");
        probe.Trace.Should().Equal(DisposalOnlyTrace());
    }

    [Fact, Trait("Conformance", "FORM-038")]
    public void FORM_038_A_Validator_That_Disposes_During_Deny_Reverts_Nothing()
    {
        FormVM<Model>? form = null;
        var disposeOnSnapshot = false;
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                if (disposeOnSnapshot && model.Value == "initial") form!.Dispose();
                return model.Value.Length == 0 ? "required" : null;
            },
        };
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new Model(""));
        probe.Clear();

        disposeOnSnapshot = true;
        form.Invoking(f => f.DenyCommand.Execute(null)).Should().NotThrow();

        probe.Trace.Should().Equal(
            DisposalOnlyTrace(),
            "no FormRevertedMessage, model message, or other deny notification follows the disposal");
        form.Model.Should().Be(new Model(""), "the model is not reverted");
        form.Errors.Should().Equal(new Dictionary<string, string> { ["Value"] = "required" });
        form.IsDirty.Should().BeTrue();
    }

    // ── Serialization (spec/20 §5.4) ──────────────────────────────────────────

    // Updates are serialized: another thread's SetModel waits for the update in
    // progress, preparation included, and then applies. Only same-thread
    // re-entry makes a preparation stale, so a concurrent edit is never dropped.
    [Fact]
    public async Task Another_Threads_SetModel_Waits_For_The_Update_In_Progress()
    {
        using var releaseValidation = new ManualResetEventSlim();
        var firstValidating = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var secondCalling = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var validated = new ConcurrentQueue<string>();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                validated.Enqueue(model.Value);
                if (model.Value == "first")
                {
                    firstValidating.SetResult();
                    releaseValidation.Wait(HangGuard).Should().BeTrue();
                }
                return null;
            },
        };
        using var hub = new MessageHub();
        var modelMessages = 0;
        using var subscription = hub.Messages
            .Subscribe(message =>
            {
                if (message is PropertyChangedMessage<FormVM<Model>> { PropertyName: "Model" })
                    Interlocked.Increment(ref modelMessages);
            });
        using var form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            snapshotter: model => model,
            validators: validators);
        validated.Clear();

        var first = Task.Run(() => form.SetModel(new Model("first")));
        await firstValidating.Task.WaitAsync(HangGuard);
        var second = Task.Run(() =>
        {
            secondCalling.SetResult();
            form.SetModel(new Model("second"));
        });
        bool secondFinishedWhileFirstPrepared;
        try
        {
            await secondCalling.Task.WaitAsync(HangGuard);
            secondFinishedWhileFirstPrepared = await Task.WhenAny(
                second,
                Task.Delay(TimeSpan.FromMilliseconds(100))) == second;
        }
        finally
        {
            releaseValidation.Set();
        }

        await Task.WhenAll(first, second).WaitAsync(HangGuard);
        secondFinishedWhileFirstPrepared.Should().BeFalse("the second update waits for the first to finish");
        validated.Should().Equal("first", "second");
        form.Model.Should().Be(new Model("second"), "the concurrent edit is applied, not dropped");
        Volatile.Read(ref modelMessages).Should().Be(2);
    }

    // ── Construction (spec/20 §5.4) ───────────────────────────────────────────

    [Fact]
    public void Construction_Fails_When_A_Preparation_Callback_Fails()
    {
        var failure = new InvalidOperationException("preparation failed");
        var failingField = new Dictionary<string, Func<Model, string?>> { ["Value"] = _ => throw failure };

        var field = () => new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, validators: failingField);
        var model = () => new FormVM<Model>(
            new Model("initial"), _ => Task.CompletedTask, modelValidator: _ => throw failure);
        var snapshot = () => new FormVM<Model>(
            new Model("initial"), _ => Task.CompletedTask, snapshotter: _ => throw failure);
        var built = () => FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ => Task.CompletedTask)
            .Validator("Value", _ => throw failure)
            .Build();

        field.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(failure);
        model.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(failure);
        snapshot.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(failure);
        built.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(failure);
    }
}
