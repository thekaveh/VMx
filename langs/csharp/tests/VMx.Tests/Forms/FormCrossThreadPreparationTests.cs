using FluentAssertions;
using VMx.Forms;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Forms;

/// <summary>
/// A form holds no lock while a consumer callback runs (spec/20 §5.4,
/// ADR-0215, #1427). Another thread's reads and calls do not wait for a
/// preparation. An update that another thread's commit overtakes runs again
/// as a new call. A call in its own pre-publication window does not wait for
/// another thread's scope (§5.5, #1426). Another thread's edit during the
/// post-persist commit commits at once, and the reset overwrites it (§5.3,
/// #1452).
/// </summary>
public class FormCrossThreadPreparationTests
{
    private sealed record Model(string Value);

    private static Thread Start(Action action)
    {
        var thread = new Thread(() => action()) { IsBackground = true };
        thread.Start();
        return thread;
    }

    // A validator that, on its first call for "1", runs `other` on another
    // thread and waits for it with a bound. The form is not disposed with
    // `using`: on a regression an implicit Dispose could block.
    private static (FormVM<Model> Form, Func<bool> Joined) FormThatRunsOnAnotherThread(
        Action<FormVM<Model>> other)
    {
        FormVM<Model>? form = null;
        var joined = false;
        var calls = 0;
        form = FormVM<Model>.Builder()
            .Initial(new Model("0"))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model)
            .Validator("Value", model =>
            {
                if (model.Value == "1" && calls++ == 0)
                    joined = Start(() => other(form!)).Join(HangGuard);
                return null;
            })
            .Build();
        return (form, () => joined);
    }

    [Fact]
    public void Another_Threads_SetModel_During_A_Validator_Commits_And_The_Overtaken_Update_Runs_Again()
    {
        var (form, joined) = FormThatRunsOnAnotherThread(f => f.SetModel(new Model("2")));

        form.SetModel(new Model("1"));

        joined().Should().BeTrue("the other thread's SetModel does not wait for the validator");
        form.Model.Should().Be(new Model("1"), "the overtaken update runs again after the other commit");
        form.Dispose();
    }

    [Fact]
    public void Another_Threads_Deny_During_A_Validator_Commits_And_The_Overtaken_Update_Runs_Again()
    {
        var (form, joined) = FormThatRunsOnAnotherThread(f => f.DenyCommand.Execute(null));

        form.SetModel(new Model("1"));

        joined().Should().BeTrue("the other thread's deny does not wait for the validator");
        form.Model.Should().Be(new Model("1"));
        form.Dispose();
    }

    [Fact]
    public void Another_Threads_Reads_During_A_Validator_Return_The_Committed_State()
    {
        object? read = null;
        var (form, joined) = FormThatRunsOnAnotherThread(f =>
            read = (f.Model, f.Snapshot, f.IsDirty, f.IsValid, f.Errors.Count, f.FieldError("Value"),
                f.ApproveCommand.CanExecute(null)));

        form.SetModel(new Model("1"));

        joined().Should().BeTrue("reads never wait for a callback");
        read.Should().Be((new Model("0"), new Model("0"), false, true, 0, (string?)null, true));
        form.Model.Should().Be(new Model("1"));
        form.Dispose();
    }

    [Fact]
    public void A_Dispose_From_Another_Thread_During_A_Validator_Returns_And_The_Update_Commits_Nothing()
    {
        var completedDuringPreparation = false;
        var completed = false;
        var (form, joined) = FormThatRunsOnAnotherThread(f =>
        {
            f.Dispose();
            completedDuringPreparation = completed;
        });
        using var subscription = form.ErrorsChanged.Subscribe(_ => { }, () => completed = true);

        form.SetModel(new Model("1"));

        joined().Should().BeTrue("Dispose() does not wait for a preparation");
        completedDuringPreparation.Should().BeFalse("the teardown waits for the preparing call");
        completed.Should().BeTrue("the teardown runs when the preparing call returns");
        form.Model.Should().Be(new Model("0"), "a disposed form commits nothing");
    }

    // IsDirty and strict CanExecute compare outside the lock: a comparison
    // that blocks does not block another thread's read.
    [Fact]
    public void A_Blocked_IsDirty_Comparison_Does_Not_Block_Another_Threads_Read()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var block = 0;
        var form = FormVM<Blocking>.Builder()
            .Initial(new Blocking("0", () =>
            {
                if (Interlocked.Exchange(ref block, 0) == 0) return;
                entered.Set();
                release.Wait(); // The test always sets it in a finally block.
            }))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model with { })
            .Build();
        Volatile.Write(ref block, 1);
        var dirty = Start(() => _ = form.IsDirty);
        try
        {
            entered.Wait(HangGuard).Should().BeTrue();
            var reader = Start(() => _ = form.Model);
            reader.Join(HangGuard).Should().BeTrue("the comparison holds no form lock");
        }
        finally
        {
            release.Set();
        }
        dirty.Join(HangGuard).Should().BeTrue();
        form.Dispose();
    }

    private sealed record Blocking(string Value, Action OnEquals)
    {
        public bool Equals(Blocking? other)
        {
            OnEquals();
            return other is not null && Value == other.Value;
        }

        public override int GetHashCode() => StringComparer.Ordinal.GetHashCode(Value);
    }

    // #1452: another thread's SetModel or deny while resetOnApproved runs
    // commits at once. The reset then overwrites it.
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Another_Threads_Edit_During_The_Reset_Commits_At_Once_And_The_Reset_Overwrites_It(bool deny)
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var form = FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ => Task.CompletedTask)
            .Snapshotter(model => model)
            .ResetOnApproved(_ =>
            {
                entered.Set();
                release.Wait(); // The test always sets it in a finally block.
                return new Model("reset");
            })
            .Build();
        form.SetModel(new Model("dirty"));
        var approval = Task.Run(form.ApproveAsync);
        entered.Wait(HangGuard).Should().BeTrue();
        Model? committed = null;
        try
        {
            var other = Start(() =>
            {
                if (deny) form.DenyCommand.Execute(null);
                else form.SetModel(new Model("other"));
                committed = form.Model;
            });
            other.Join(HangGuard).Should().BeTrue("the edit does not wait for the reset");
        }
        finally
        {
            release.Set();
        }
        await approval.WaitAsync(HangGuard);

        committed.Should().Be(deny ? new Model("initial") : new Model("other"), "the edit committed at once");
        form.Model.Should().Be(new Model("reset"), "the reset overwrites the edit");
        form.IsDirty.Should().BeFalse();
        form.Dispose();
    }

    // #1426 case 1: thread B holds an update scope. Thread A's call from its
    // own reset callback joins A's queue at once and replays after OnApproved.
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task An_Own_Window_Call_Does_Not_Wait_For_Another_Threads_Scope(bool deny)
    {
        using var holding = new ManualResetEventSlim();
        using var releaseB = new ManualResetEventSlim();
        using var returned = new ManualResetEventSlim();
        var persist = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var bThread = 0;
        FormVM<Model>? form = null;
        form = FormVM<Model>.Builder()
            .Initial(new Model("initial"))
            .Persister(_ => persist.Task)
            .Snapshotter(model => model)
            .Validator("Value", model => model.Value == "bad" ? "rejected" : null)
            .ResetOnApproved(_ =>
            {
                if (deny) form!.DenyCommand.Execute(null);
                else form!.SetModel(new Model("v"));
                returned.Set();
                return new Model("reset");
            })
            .Build();
        using var errors = form.ErrorsChanged.Subscribe(_ =>
        {
            if (Environment.CurrentManagedThreadId != Volatile.Read(ref bThread)) return;
            holding.Set();
            releaseB.Wait(HangGuard);
        });
        var approval = form.ApproveAsync();
        var b = Start(() =>
        {
            Volatile.Write(ref bThread, Environment.CurrentManagedThreadId);
            form.SetModel(new Model("bad"));
        });
        try
        {
            holding.Wait(HangGuard).Should().BeTrue();
            persist.SetResult();
            returned.Wait(HangGuard).Should().BeTrue("the call joins its own queue without waiting for B's scope");
        }
        finally
        {
            releaseB.Set();
        }
        b.Join(HangGuard).Should().BeTrue();
        await approval.WaitAsync(HangGuard);

        form.Model.Should().Be(deny ? new Model("reset") : new Model("v"), "the queued call replays after OnApproved");
        form.Dispose();
    }
}
