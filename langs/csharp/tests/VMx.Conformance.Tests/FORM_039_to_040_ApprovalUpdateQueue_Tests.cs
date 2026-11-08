using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-039..FORM-040 — <c>FormVM</c> queues updates made
/// during approval publication and replays them after <c>OnApproved</c>. A
/// <c>SetModel</c> or deny that the approving thread makes from the
/// post-persist commit or a settlement observer is prepared at call time,
/// publishes nothing, and replays in call order after the <c>OnApproved</c>
/// delivery returns. A replay failure does not stop later replays and reaches
/// the approval's own failure route, unless the approval already carries a
/// failure. See spec/20-form-vm.md §5.1/§5.3/§5.4 and ADR-0174.
/// </summary>
public sealed class FORM_039_to_040_ApprovalUpdateQueue_Tests
{
    private sealed record Model(string Value);

    private sealed record Number(int N);

    private sealed record FormState<TM>(TM Model, TM Snapshot, string Errors, bool IsDirty, bool IsValid);

    // Records, in order, every notification an update or an approval may
    // publish: ErrorsChanged (with its payload), ApproveCommand.CanExecuteChanged,
    // OnApproved (with the form state its observer saw), and the form's
    // FormRevertedMessage and model PropertyChangedMessage on the hub (with the
    // live model at that time).
    private sealed class Probe<TM> : IDisposable
        where TM : notnull
    {
        private readonly List<IDisposable> _subscriptions = [];

        public Probe(FormVM<TM> form, IMessageHub hub)
        {
            _subscriptions.Add(form.ErrorsChanged.Subscribe(errors =>
            {
                Trace.Enqueue("errors:" + Format(errors));
                LastErrors = Format(errors);
            }));
            form.ApproveCommand.CanExecuteChanged += (_, _) => Trace.Enqueue("can_execute");
            _subscriptions.Add(form.OnApproved.Subscribe(approved =>
            {
                Trace.Enqueue($"approved:{approved}");
                Approved.Enqueue(StateOf(form));
            }));
            _subscriptions.Add(hub.Messages.Subscribe(message =>
            {
                if (message is FormRevertedMessage reverted && ReferenceEquals(reverted.Sender, form))
                    Trace.Enqueue("reverted");
                else if (message is PropertyChangedMessage<FormVM<TM>> changed &&
                    ReferenceEquals(changed.Sender, form) && changed.PropertyName == "Model")
                    Trace.Enqueue($"model:{form.Model}");
            }));
        }

        public ConcurrentQueue<string> Trace { get; } = new();

        public ConcurrentQueue<FormState<TM>> Approved { get; } = new();

        public string? LastErrors { get; private set; }

        public void Clear() => Trace.Clear();

        public void Dispose()
        {
            foreach (var subscription in _subscriptions) subscription.Dispose();
        }
    }

    private static string Format(IReadOnlyDictionary<string, string> errors) =>
        string.Join(";", errors.OrderBy(kvp => kvp.Key, StringComparer.Ordinal).Select(kvp => $"{kvp.Key}={kvp.Value}"));

    private static FormState<TM> StateOf<TM>(FormVM<TM> form)
        where TM : notnull =>
        new(form.Model, form.Snapshot, Format(form.Errors), form.IsDirty, form.IsValid);

    // Runs a command-path approval and waits (bounded) for its outcome on
    // OnApproved or ApproveErrors.
    private static async Task<List<Exception>> ExecuteApproveCommand<TM>(FormVM<TM> form)
        where TM : notnull
    {
        var errors = new ConcurrentQueue<Exception>();
        var settled = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var errorSubscription = form.ApproveErrors.Subscribe(error =>
        {
            errors.Enqueue(error);
            settled.TrySetResult();
        });
        using var approvedSubscription = form.OnApproved.Subscribe(_ => settled.TrySetResult());
        form.ApproveCommand.Execute(null);
        (await Task.WhenAny(settled.Task, Task.Delay(HangGuard))).Should().BeSameAs(settled.Task);
        // A replay failure is routed after the replays, which run after the
        // OnApproved delivery; give that route a bounded moment to report.
        await Task.Delay(50);
        return [.. errors];
    }

    // ── FORM-039 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-039")]
    public async Task FORM_039_A_SetModel_From_The_Reset_Replays_After_OnApproved()
    {
        FormVM<Model>? form = null;
        using var hub = new MessageHub();
        form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .Hub(hub)
            .Validator("Value", model => model.Value == "x" ? "rejected" : null)
            .ResetOnApproved(_ =>
            {
                form!.SetModel(new("x"));
                return new("pristine");
            })
            .Build();
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new("saved"));
        probe.Clear();

        await form.ApproveAsync();

        probe.Trace.Should().Equal(
            "can_execute",
            "can_execute",
            "approved:Model { Value = saved }",
            "errors:Value=rejected",
            "can_execute",
            "model:Model { Value = x }");
        probe.Approved.Should().Equal(new FormState<Model>(new("pristine"), new("pristine"), "", false, true));
        StateOf(form).Should().Be(new FormState<Model>(new("x"), new("pristine"), "Value=rejected", true, false));
        probe.LastErrors.Should().Be(Format(form.Errors));
    }

    [Fact, Trait("Conformance", "FORM-039")]
    public async Task FORM_039_A_Deny_From_A_Settlement_Observer_Replays_After_OnApproved()
    {
        using var hub = new MessageHub();
        var persisting = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(async _ =>
            {
                persisting.TrySetResult();
                await release.Task.ConfigureAwait(false);
            })
            .Hub(hub)
            .Build();
        using var probe = new Probe<Model>(form, hub);
        var armed = 0;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            if (Interlocked.Exchange(ref armed, 0) == 1)
                form.DenyCommand.Execute(null);
        };
        form.SetModel(new("saved"));

        var approval = form.ApproveAsync();
        (await Task.WhenAny(persisting.Task, Task.Delay(HangGuard))).Should().BeSameAs(persisting.Task);
        form.SetModel(new("newer"));
        probe.Clear();
        Volatile.Write(ref armed, 1);
        release.SetResult();
        (await Task.WhenAny(approval, Task.Delay(HangGuard))).Should().BeSameAs(approval);
        await approval;

        probe.Trace.Should().Equal(
            "can_execute",
            "approved:Model { Value = saved }",
            "reverted",
            "model:Model { Value = saved }");
        probe.Approved.Should().Equal(new FormState<Model>(new("newer"), new("saved"), "", true, true));
        StateOf(form).Should().Be(new FormState<Model>(new("saved"), new("saved"), "", false, true));
    }

    [Fact, Trait("Conformance", "FORM-039")]
    public async Task FORM_039_Calls_From_The_Reset_Replay_In_Call_Order()
    {
        FormVM<Model>? form = null;
        using var hub = new MessageHub();
        form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .Hub(hub)
            .ResetOnApproved(_ =>
            {
                form!.SetModel(new("a"));
                form.DenyCommand.Execute(null);
                return new("pristine");
            })
            .Build();
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new("saved"));
        probe.Clear();

        await form.ApproveAsync();

        probe.Trace.Should().Equal(
            "can_execute",
            "can_execute",
            "approved:Model { Value = saved }",
            "model:Model { Value = a }",
            "reverted",
            "model:Model { Value = pristine }");
        StateOf(form).Should().Be(new FormState<Model>(new("pristine"), new("pristine"), "", false, true));
    }

    // The window opens with the post-persist commit (spec/20 §5.3): when that
    // commit fails, the calls it already queued replay after the failed
    // settlement's CanExecuteChanged and before the failure reaches its
    // channel, and the commit failure wins.
    [Fact, Trait("Conformance", "FORM-039")]
    public async Task FORM_039_Calls_Queued_By_A_Failed_Reset_Replay_Before_The_Failure_Is_Routed()
    {
        var boom = new InvalidOperationException("reset failed");
        FormVM<Model>? form = null;
        using var hub = new MessageHub();
        form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .Hub(hub)
            .ResetOnApproved(_ =>
            {
                form!.SetModel(new("a"));
                throw boom;
            })
            .Build();
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        form.SetModel(new("saved"));
        probe.Clear();

        var thrown = await form.Invoking(f => f.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();
        thrown.Which.Should().BeSameAs(boom);
        probe.Trace.Should().Equal("can_execute", "can_execute", "model:Model { Value = a }");
        StateOf(form).Should().Be(new FormState<Model>(new("a"), new("initial"), "", true, true));
    }

    // ── FORM-040 ──────────────────────────────────────────────────────────────

    private static readonly InvalidOperationException Boom13 = new("validator failed for 13");

    // A form at model 2 whose validator throws for 13. The next
    // ApproveCommand.CanExecuteChanged runs the action passed to `arm` once.
    // Tests arm an action on the admission edge that arms the observer for the
    // settlement edge.
    private static FormVM<Number> NumberForm(
        IMessageHub hub,
        Func<int, string?>? extraValidation,
        out Action<Action<FormVM<Number>>> arm)
    {
        Action<FormVM<Number>>? armed = null;
        FormVM<Number>? form = null;
        form = FormVM<Number>.Builder()
            .Initial(new(1))
            .Persister(_ => Task.CompletedTask)
            .Hub(hub)
            .Validator("N", model =>
            {
                if (model.N == 13) throw Boom13;
                return extraValidation?.Invoke(model.N);
            })
            .Build();
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            var observer = Interlocked.Exchange(ref armed, null);
            observer?.Invoke(form);
        };
        arm = observer => Volatile.Write(ref armed, observer);
        form.SetModel(new(2));
        return form;
    }

    [Theory, Trait("Conformance", "FORM-040")]
    [InlineData(false)]
    [InlineData(true)]
    public async Task FORM_040_A_Failing_Queued_SetModel_Fails_At_Call_Time(bool commandPath)
    {
        using var hub = new MessageHub();
        using var form = NumberForm(hub, null, out var arm);
        using var probe = new Probe<Number>(form, hub);
        var caught = new List<Exception>();
        var approvedValues = new List<Number>();
        using var approvedSubscription = form.OnApproved.Subscribe(approvedValues.Add);
        // The admission edge arms the observer for the settlement edge.
        arm(_ => arm(f =>
        {
            try { f.SetModel(new(13)); }
            catch (Exception error) { caught.Add(error); }
            f.SetModel(new(42));
        }));

        List<Exception> commandErrors = [];
        if (commandPath)
            commandErrors = await ExecuteApproveCommand(form);
        else
            await form.ApproveAsync();

        caught.Should().Equal([Boom13], "the queued call's preparation failed at call time");
        approvedValues.Should().Equal(new Number(2));
        probe.Approved.Should().ContainSingle().Which.Model.Should().Be(new Number(2));
        commandErrors.Should().BeEmpty();
        form.Model.Should().Be(new Number(42));
    }

    [Fact, Trait("Conformance", "FORM-040")]
    public async Task FORM_040_Equality_Never_Skips_The_Enqueue()
    {
        using var hub = new MessageHub();
        using var form = NumberForm(hub, null, out var arm);
        using var probe = new Probe<Number>(form, hub);
        arm(_ => arm(f =>
        {
            f.SetModel(new(5));
            f.SetModel(new(2));
        }));
        probe.Clear();

        await form.ApproveAsync();

        form.Model.Should().Be(new Number(2));
        probe.Trace.Should().Equal(
            "can_execute",
            "can_execute",
            "approved:Number { N = 2 }",
            "model:Number { N = 5 }",
            "model:Number { N = 2 }");
    }

    [Theory, Trait("Conformance", "FORM-040")]
    [InlineData(false)]
    [InlineData(true)]
    public async Task FORM_040_A_Replay_Failure_Does_Not_Stop_Later_Replays(bool commandPath)
    {
        // 7 passes its call-time preparation and fails when it replays: the
        // OnApproved observer poisons it in between.
        var poisoned = false;
        var boom7 = new InvalidOperationException("validator failed for 7 at replay");
        using var hub = new MessageHub();
        using var form = NumberForm(hub, n => n == 7 && Volatile.Read(ref poisoned) ? throw boom7 : null, out var arm);
        using var probe = new Probe<Number>(form, hub);
        var approvedValues = new List<Number>();
        using var approvedSubscription = form.OnApproved.Subscribe(model =>
        {
            approvedValues.Add(model);
            Volatile.Write(ref poisoned, true);
        });
        arm(_ => arm(f =>
        {
            f.SetModel(new(7));
            f.SetModel(new(8));
        }));

        if (commandPath)
        {
            var commandErrors = await ExecuteApproveCommand(form);
            commandErrors.Should().Equal([boom7], "the first replay failure is emitted once on ApproveErrors");
        }
        else
        {
            var thrown = await form.Invoking(f => f.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();
            thrown.Which.Should().BeSameAs(boom7, "the first replay failure reaches the awaiter");
        }

        approvedValues.Should().Equal(new Number(2));
        form.Snapshot.Should().Be(new Number(2), "the settled approval's commit stands");
        form.Model.Should().Be(new Number(8), "the later replay still commits");
    }

    [Fact, Trait("Conformance", "FORM-040")]
    public async Task FORM_040_A_Failing_Observer_Of_A_Replayed_Update_Does_Not_Stop_Later_Replays()
    {
        var observerBoom = new InvalidOperationException("ErrorsChanged observer failed");
        using var hub = new MessageHub();
        using var form = NumberForm(hub, n => n == 7 ? "seven" : null, out var arm);
        using var errorsSubscription = form.ErrorsChanged.Subscribe(errors =>
        {
            if (errors.ContainsKey("N")) throw observerBoom;
        });
        arm(_ => arm(f =>
        {
            f.SetModel(new(7));
            f.SetModel(new(8));
        }));

        var thrown = await form.Invoking(f => f.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();

        thrown.Which.Should().BeSameAs(observerBoom);
        form.Snapshot.Should().Be(new Number(2));
        form.Model.Should().Be(new Number(8));
        form.IsValid.Should().BeTrue();
    }

    [Theory, Trait("Conformance", "FORM-040")]
    [InlineData(false)]
    [InlineData(true)]
    public async Task FORM_040_An_OnApproved_Subscriber_Failure_Wins_Over_A_Replay_Failure(bool commandPath)
    {
        var poisoned = false;
        var boom7 = new InvalidOperationException("validator failed for 7 at replay");
        var approvedBoom = new InvalidOperationException("OnApproved subscriber failed");
        using var hub = new MessageHub();
        using var form = NumberForm(hub, n => n == 7 && Volatile.Read(ref poisoned) ? throw boom7 : null, out var arm);
        var approvedCount = 0;
        using var approvedSubscription = form.OnApproved.Subscribe(_ =>
        {
            Interlocked.Increment(ref approvedCount);
            Volatile.Write(ref poisoned, true);
            throw approvedBoom;
        });
        arm(_ => arm(f =>
        {
            f.SetModel(new(7));
            f.SetModel(new(8));
        }));

        if (commandPath)
        {
            var errors = new ConcurrentQueue<Exception>();
            var reported = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            using var errorSubscription = form.ApproveErrors.Subscribe(error =>
            {
                errors.Enqueue(error);
                reported.TrySetResult();
            });
            form.ApproveCommand.Execute(null);
            (await Task.WhenAny(reported.Task, Task.Delay(HangGuard))).Should().BeSameAs(reported.Task);
            await Task.Delay(50);
            errors.Should().Equal([approvedBoom], "the approval's own failure is reported once");
        }
        else
        {
            var thrown = await form.Invoking(f => f.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();
            thrown.Which.Should().BeSameAs(approvedBoom, "the approval's own failure wins over the replay failure");
        }

        approvedCount.Should().Be(1);
        form.Model.Should().Be(new Number(8), "every replay still runs");
    }

    // Call-time preparation keeps the §5.4 staleness rule: a validator that
    // re-enters and makes another update (here queued) makes the outer call
    // return without queueing, so only the nested update replays.
    [Fact, Trait("Conformance", "FORM-040")]
    public async Task FORM_040_A_Nested_Queued_Update_Makes_The_Outer_Call_Stale()
    {
        using var hub = new MessageHub();
        FormVM<Number>? form = null;
        var reentered = false;
        using var created = NumberForm(hub, n =>
        {
            if (n == 5 && !reentered)
            {
                reentered = true;
                form!.SetModel(new(6));
            }
            return null;
        }, out var arm);
        form = created;
        using var probe = new Probe<Number>(form, hub);
        arm(_ => arm(f => f.SetModel(new(5))));
        probe.Clear();

        await form.ApproveAsync();

        reentered.Should().BeTrue();
        form.Model.Should().Be(new Number(6));
        probe.Trace.Should().Equal(
            "can_execute",
            "can_execute",
            "approved:Number { N = 2 }",
            "model:Number { N = 6 }");
    }

    // A queued deny prepares at call time as well: a failing snapshotter
    // propagates to the caller, and nothing is queued for it.
    [Fact, Trait("Conformance", "FORM-040")]
    public async Task FORM_040_A_Failing_Queued_Deny_Fails_At_Call_Time()
    {
        var snapshotBoom = new InvalidOperationException("snapshotter failed");
        var failSnapshot = false;
        using var hub = new MessageHub();
        FormVM<Model>? form = null;
        form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .Hub(hub)
            .Snapshotter(model => Volatile.Read(ref failSnapshot) ? throw snapshotBoom : model)
            .Build();
        using var disposeForm = form;
        using var probe = new Probe<Model>(form, hub);
        var caught = new List<Exception>();
        var edges = 0;
        form.ApproveCommand.CanExecuteChanged += (_, _) =>
        {
            // The second edge is the settlement edge.
            if (++edges != 2) return;
            Volatile.Write(ref failSnapshot, true);
            try { form.DenyCommand.Execute(null); }
            catch (Exception error) { caught.Add(error); }
            Volatile.Write(ref failSnapshot, false);
        };
        form.SetModel(new("saved"));
        probe.Clear();

        await form.ApproveAsync();

        caught.Should().Equal([snapshotBoom]);
        probe.Trace.Should().Equal("can_execute", "can_execute", "approved:Model { Value = saved }");
        StateOf(form).Should().Be(new FormState<Model>(new("saved"), new("saved"), "", false, true));
    }
}
