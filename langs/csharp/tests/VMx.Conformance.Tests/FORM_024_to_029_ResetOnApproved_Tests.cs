using System.Reactive.Linq;
using FluentAssertions;
using VMx.Forms;
using Xunit;

namespace VMx.Conformance.Tests;

public class FORM_024_to_029_ResetOnApproved_Tests
{
    private sealed record Model(string Value, List<int>? Nested = null);

    [Fact, Trait("Conformance", "FORM-024")]
    public async Task FORM_024_Reset_Runs_After_Persist_And_Approved_Uses_Captured_Model()
    {
        var order = new List<string>();
        using var form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(model => { order.Add($"persist:{model.Value}"); return Task.CompletedTask; })
            .ResetOnApproved(model => { order.Add($"reset:{model.Value}"); return new("reset"); })
            .Build();
        var approved = new List<Model>();
        using var subscription = form.OnApproved.Subscribe(model =>
        {
            order.Add($"approved:{model.Value}");
            form.Model.Should().Be(new Model("reset"));
            form.Snapshot.Should().Be(new Model("reset"));
            form.IsDirty.Should().BeFalse();
            approved.Add(model);
        });
        form.SetModel(new("saved"));

        await form.ApproveAsync();

        order.Should().Equal("persist:saved", "reset:saved", "approved:saved");
        form.Model.Should().Be(new Model("reset"));
        form.Snapshot.Should().Be(new Model("reset"));
        form.IsDirty.Should().BeFalse();
        approved.Should().Equal(new Model("saved"));
    }

    [Fact, Trait("Conformance", "FORM-025")]
    public async Task FORM_025_Reset_Is_Snapshotted_Twice_And_Revalidated()
    {
        var calls = 0;
        using var form = FormVM<Model>.Builder()
            .Initial(new("initial", []))
            .Persister(_ => Task.CompletedTask)
            .Strict(true)
            .Snapshotter(model => { calls++; return new(model.Value, [.. model.Nested ?? []]); })
            .Validator("value", model => model.Value.Length == 0 ? "required" : null)
            .ResetOnApproved(_ => new("", [1]))
            .Build();
        calls = 0;
        form.SetModel(new("saved"));

        await form.ApproveAsync();

        calls.Should().Be(2);
        ReferenceEquals(form.Model, form.Snapshot).Should().BeFalse();
        ReferenceEquals(form.Model.Nested, form.Snapshot.Nested).Should().BeFalse();
        form.FieldError("value").Should().Be("required");
        form.IsValid.Should().BeFalse();
        form.ApproveCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "FORM-026")]
    public async Task FORM_026_Reset_Failure_Is_Atomic_And_Has_One_Observer()
    {
        var boom = new InvalidOperationException("reset failed after persistence");
        var persisted = 0;
        using var direct = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => { persisted++; return Task.CompletedTask; })
            .ResetOnApproved(_ => throw boom)
            .Build();
        direct.SetModel(new("saved"));
        var approved = 0;
        var commandErrors = 0;
        using var approvedSub = direct.OnApproved.Subscribe(_ => approved++);
        using var errorsSub = direct.ApproveErrors.Subscribe(_ => commandErrors++);

        var thrown = await direct.Invoking(form => form.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();

        thrown.Which.Should().BeSameAs(boom);
        persisted.Should().Be(1);
        direct.Model.Should().Be(new Model("saved"));
        direct.Snapshot.Should().Be(new Model("initial"));
        approved.Should().Be(0);
        commandErrors.Should().Be(0);

        using var command = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .ResetOnApproved(_ => throw boom)
            .Build();
        command.SetModel(new("saved"));
        var observed = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var commandSub = command.ApproveErrors.Subscribe(error => observed.TrySetResult(error));
        command.ApproveCommand.Execute(null);
        var completed = await Task.WhenAny(observed.Task, Task.Delay(TimeSpan.FromSeconds(5)));
        completed.Should().BeSameAs(observed.Task);
        (await observed.Task).Should().BeSameAs(boom);
    }

    [Fact, Trait("Conformance", "FORM-027")]
    public async Task FORM_027_Reset_Is_Skipped_Without_Successful_Approval()
    {
        var calls = 0;
        Func<Model, Model> reset = model => { calls++; return model; };
        using var invalid = FormVM<Model>.Builder().Initial(new("")).Persister(_ => Task.CompletedTask)
            .Validator("value", model => model.Value.Length == 0 ? "required" : null).ResetOnApproved(reset).Build();
        await invalid.ApproveAsync();
        using var failed = FormVM<Model>.Builder().Initial(new("initial"))
            .Persister(_ => Task.FromException(new InvalidOperationException("fail"))).ResetOnApproved(reset).Build();
        await failed.Invoking(form => form.ApproveAsync()).Should().ThrowAsync<InvalidOperationException>();
        using var canceled = FormVM<Model>.Builder().Initial(new("initial"))
            .Persister(_ => Task.FromCanceled(new CancellationToken(true))).ResetOnApproved(reset).Build();
        await canceled.Invoking(form => form.ApproveAsync()).Should().ThrowAsync<OperationCanceledException>();
        using var denied = FormVM<Model>.Builder().Initial(new("initial")).Persister(_ => Task.CompletedTask)
            .ResetOnApproved(reset).Build();
        denied.SetModel(new("edited"));
        denied.DenyCommand.Execute(null);

        calls.Should().Be(0);
    }

    [Fact, Trait("Conformance", "FORM-028")]
    public async Task FORM_028_Disposal_During_Persist_Suppresses_Reset()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        var form = FormVM<Model>.Builder().Initial(new("initial"))
            .Persister(async _ => { entered.SetResult(); await release.Task; })
            .ResetOnApproved(model => { calls++; return model; }).Build();
        form.SetModel(new("saved"));

        var approval = form.ApproveAsync();
        await entered.Task;
        form.Dispose();
        release.SetResult();
        await approval;

        calls.Should().Be(0);
        form.Model.Should().Be(new Model("saved"));
        form.Snapshot.Should().Be(new Model("initial"));
    }

    [Fact, Trait("Conformance", "FORM-029")]
    public async Task FORM_029_Reset_Wins_Racing_Model_Mutation()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Model? resetInput = null;
        using var form = FormVM<Model>.Builder().Initial(new("initial"))
            .Persister(async _ => { entered.SetResult(); await release.Task; })
            .ResetOnApproved(model => { resetInput = model; return new($"reset:{model.Value}"); }).Build();
        form.SetModel(new("saved"));

        var approval = form.ApproveAsync();
        await entered.Task;
        form.SetModel(new("racing-edit"));
        release.SetResult();
        await approval;

        resetInput.Should().Be(new Model("saved"));
        form.Model.Should().Be(new Model("reset:saved"));
        form.Snapshot.Should().Be(new Model("reset:saved"));
        form.IsDirty.Should().BeFalse();
    }

    [Fact]
    public async Task Reset_Commit_Remains_Pristine_Through_Approved_Publication()
    {
        using var form = FormVM<Model>.Builder().Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .ResetOnApproved(model => new($"reset:{model.Value}"))
            .Build();
        form.SetModel(new("saved"));
        Task? racingSetter = null;
        using var setterStarted = new ManualResetEventSlim();
        using var subscription = form.OnApproved.Subscribe(_ =>
        {
            racingSetter = Task.Run(() =>
            {
                setterStarted.Set();
                form.SetModel(new("racing"));
            });
            setterStarted.Wait();
            racingSetter.Wait(TimeSpan.FromMilliseconds(50)).Should().BeFalse(
                "a racing setter cannot interleave with approval publication");
            form.Model.Should().Be(new Model("reset:saved"));
            form.Snapshot.Should().Be(new Model("reset:saved"));
            form.IsDirty.Should().BeFalse();
        });

        await form.ApproveAsync();
        await racingSetter!;

        form.Model.Should().Be(new Model("racing"));
        form.Snapshot.Should().Be(new Model("reset:saved"));
        form.IsDirty.Should().BeTrue();
    }

    [Fact]
    public async Task Dispose_From_Reset_Error_Observer_Stops_Remaining_Publication()
    {
        var form = FormVM<Model>.Builder()
            .Initial(new("initial"))
            .Persister(_ => Task.CompletedTask)
            .Validator("value", model => model.Value.Length == 0 ? "required" : null)
            .ResetOnApproved(_ => new(""))
            .Build();
        form.SetModel(new("saved"));
        var approved = new List<Model>();
        using var approvedSubscription = form.OnApproved.Subscribe(approved.Add);
        using var errorsSubscription = form.ErrorsChanged.Subscribe(_ => form.Dispose());

        await form.ApproveAsync();

        form.Model.Should().Be(new Model(""));
        form.Snapshot.Should().Be(new Model(""));
        approved.Should().BeEmpty();
    }
}
