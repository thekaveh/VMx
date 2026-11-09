using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-041..FORM-042 — nested <c>FormVM</c> updates notify
/// at the outermost update. A <c>SetModel</c>, deny, or approve call made from
/// a preparation callback or an <c>ErrorsChanged</c> observer of another
/// update returns before its notifications. The outermost update sends them
/// before it returns: error maps first, then the rest in commit order. A
/// nested approval's persister starts after that. Once the form is disposed,
/// the queued notifications are dropped and the persister does not start.
/// See spec/20-form-vm.md §5.2/§5.3/§5.4/§10 and ADR-0180.
/// </summary>
public sealed class FORM_041_to_042_NestedUpdateNotifications_Tests
{
    private sealed record Model(string Value);

    // Records ErrorsChanged (with its payload, and its completion on
    // disposal), ApproveCommand.CanExecuteChanged, OnApproved, ApproveErrors,
    // and the form's FormRevertedMessage and model PropertyChangedMessage on
    // the hub. The test adds its own markers to the same log.
    private sealed class Probe : IDisposable
    {
        private readonly List<IDisposable> _subscriptions = [];

        public Probe(FormVM<Model> form, IMessageHub hub)
        {
            _subscriptions.Add(form.ErrorsChanged.Subscribe(
                errors => Log.Add("errors:" + Format(errors)),
                () => Log.Add("errors_completed")));
            form.ApproveCommand.CanExecuteChanged += (_, _) => Log.Add("can_execute");
            _subscriptions.Add(form.OnApproved.Subscribe(model => Log.Add($"approved:{model.Value}")));
            _subscriptions.Add(form.ApproveErrors.Subscribe(error => Log.Add($"approve_error:{error.Message}")));
            _subscriptions.Add(hub.Messages.Subscribe(message =>
            {
                if (message is FormRevertedMessage reverted && ReferenceEquals(reverted.Sender, form))
                    Log.Add("reverted");
                else if (message is PropertyChangedMessage<FormVM<Model>> changed &&
                    ReferenceEquals(changed.Sender, form) && changed.PropertyName == "Model")
                    Log.Add("model");
            }));
        }

        public List<string> Log { get; } = [];

        public void Dispose()
        {
            foreach (var subscription in _subscriptions) subscription.Dispose();
        }
    }

    private static string Format(IReadOnlyDictionary<string, string> errors) =>
        string.Join(";", errors.OrderBy(kvp => kvp.Key, StringComparer.Ordinal).Select(kvp => $"{kvp.Key}={kvp.Value}"));

    private static Dictionary<string, Func<Model, string?>> Validator(Func<Model, string?> validate) =>
        new() { ["Value"] = validate };

    // What a plain Dispose() publishes on the probe's channels: ErrorsChanged
    // completes, and the approve command's teardown raises CanExecuteChanged.
    // A dropped notification adds nothing to this.
    private static List<string> DisposalOnlyLog()
    {
        using var hub = new MessageHub();
        var form = new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, hub: hub, snapshotter: m => m);
        using var probe = new Probe(form, hub);
        form.Dispose();
        return [.. probe.Log];
    }

    // ── FORM-041 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-041")]
    public void FORM_041_A_Nested_SetModel_From_A_Validator_Notifies_After_It_Returns()
    {
        FormVM<Model>? form = null;
        Probe? probe = null;
        var nestedCalls = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "a" && nestedCalls++ == 0)
            {
                form!.SetModel(new Model("b"));
                probe!.Log.Add("nested returned");
            }
            return model.Value == "b" ? "b is rejected" : null;
        });
        using var hub = new MessageHub();
        form = new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, hub: hub, snapshotter: m => m, validators: validators);
        using var disposeForm = form;
        using var disposeProbe = probe = new Probe(form, hub);

        form.SetModel(new Model("a"));
        probe.Log.Add("outer returned");

        probe.Log.Should().Equal(
            "nested returned", "errors:Value=b is rejected", "can_execute", "model", "outer returned");
        form.Model.Should().Be(new Model("b"));
        form.Errors.Should().Equal(new Dictionary<string, string> { ["Value"] = "b is rejected" });
    }

    [Fact, Trait("Conformance", "FORM-041")]
    public void FORM_041_A_Nested_Deny_From_A_Validator_Notifies_After_It_Returns()
    {
        FormVM<Model>? form = null;
        Probe? probe = null;
        var nestedCalls = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "a" && nestedCalls++ == 0)
            {
                form!.DenyCommand.Execute(null);
                probe!.Log.Add("nested returned");
            }
            return model.Value == "x" ? "x is rejected" : null;
        });
        using var hub = new MessageHub();
        form = new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, hub: hub, snapshotter: m => m, validators: validators);
        using var disposeForm = form;
        form.SetModel(new Model("x"));
        form.IsDirty.Should().BeTrue();
        form.IsValid.Should().BeFalse();
        using var disposeProbe = probe = new Probe(form, hub);

        form.SetModel(new Model("a"));
        probe.Log.Add("outer returned");

        probe.Log.Should().Equal(
            "nested returned", "errors:", "reverted", "model", "can_execute", "outer returned");
        form.Model.Should().Be(form.Snapshot);
        form.IsValid.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "FORM-041")]
    public void FORM_041_A_SetModel_From_An_ErrorsChanged_Observer_Notifies_After_The_Outer_Update()
    {
        FormVM<Model>? form = null;
        var maps = new List<IReadOnlyDictionary<string, string>>();
        var validators = Validator(model => model.Value == "a" ? "a is rejected" : null);
        using var hub = new MessageHub();
        form = new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, hub: hub, snapshotter: m => m, validators: validators);
        using var disposeForm = form;
        using var probe = new Probe(form, hub);
        using var nesting = form.ErrorsChanged.Subscribe(errors =>
        {
            maps.Add(errors);
            if (maps.Count != 1) return;
            form.SetModel(new Model("c"));
            probe.Log.Add("nested returned");
        });

        form.SetModel(new Model("a"));
        probe.Log.Add("outer returned");

        probe.Log.Should().Equal(
            "errors:Value=a is rejected", "nested returned", "errors:",
            "can_execute", "model", "can_execute", "model", "outer returned");
        maps.Should().HaveCount(2);
        maps[0].Should().Equal(new Dictionary<string, string> { ["Value"] = "a is rejected" });
        maps[1].Should().BeEmpty();
        form.Model.Should().Be(new Model("c"));
    }

    // ── FORM-042 ──────────────────────────────────────────────────────────────

    [Fact, Trait("Conformance", "FORM-042")]
    public async Task FORM_042_A_Nested_Approval_Followed_By_Dispose_Never_Calls_The_Persister()
    {
        FormVM<Model>? form = null;
        var persisted = 0;
        var nestedCalls = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "trigger" && nestedCalls++ == 0)
            {
                form!.ApproveCommand.Execute(null);
                form.Dispose();
            }
            return null;
        });
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: m => m,
            validators: validators);
        using var probe = new Probe(form, hub);

        form.SetModel(new Model("trigger"));
        await Task.Delay(TimeSpan.FromMilliseconds(100));

        Volatile.Read(ref persisted).Should().Be(0, "a Dispose() before the persister starts prevents the call");
        probe.Log.Should().Equal(DisposalOnlyLog(), "no queued notification, outcome, or approve error is sent");
    }

    [Fact, Trait("Conformance", "FORM-042")]
    public async Task FORM_042_A_Nested_ApproveAsync_Followed_By_Dispose_Completes_Normally()
    {
        FormVM<Model>? form = null;
        Task? approval = null;
        var persisted = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "trigger" && approval is null)
            {
                approval = form!.ApproveAsync();
                form.Dispose();
            }
            return null;
        });
        using var hub = new MessageHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: m => m,
            validators: validators);
        using var probe = new Probe(form, hub);

        form.SetModel(new Model("trigger"));

        approval.Should().NotBeNull();
        await approval!.WaitAsync(HangGuard);
        Volatile.Read(ref persisted).Should().Be(0);
        probe.Log.Should().Equal(DisposalOnlyLog());
    }

    [Fact, Trait("Conformance", "FORM-042")]
    public void FORM_042_Queued_Notifications_Of_A_Nested_SetModel_Are_Dropped_After_Dispose()
    {
        FormVM<Model>? form = null;
        var nestedCalls = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "a" && nestedCalls++ == 0)
            {
                form!.SetModel(new Model("b"));
                form.Dispose();
            }
            return model.Value == "b" ? "b is rejected" : null;
        });
        using var hub = new MessageHub();
        form = new FormVM<Model>(new Model("initial"), _ => Task.CompletedTask, hub: hub, snapshotter: m => m, validators: validators);
        using var probe = new Probe(form, hub);

        form.Invoking(f => f.SetModel(new Model("a"))).Should().NotThrow();

        probe.Log.Should().Equal(
            DisposalOnlyLog(),
            "no ErrorsChanged, CanExecuteChanged, or model message of the nested call is delivered");
    }

    [Fact, Trait("Conformance", "FORM-042")]
    public async Task FORM_042_Dispose_After_The_Command_Returns_Leaves_The_Persister_Count_Unchanged()
    {
        var persisted = 0;
        using var hub = new MessageHub();
        var form = new FormVM<Model>(
            new Model("initial"),
            _ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: m => m);

        form.ApproveCommand.Execute(null);
        var n = Volatile.Read(ref persisted);
        form.Dispose();
        await Task.Delay(TimeSpan.FromMilliseconds(100));

        n.Should().Be(1, "the C# command path calls the persister before Execute() returns");
        Volatile.Read(ref persisted).Should().Be(n);
    }
}
