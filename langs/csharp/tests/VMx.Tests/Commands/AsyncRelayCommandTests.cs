using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using VMx.Commands;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Commands;

public class AsyncRelayCommandTests
{
    [Fact]
    public async Task Taskless_Execution_Is_A_NoOp()
    {
        var command = AsyncRelayCommand.Builder().Build();
        var notifications = 0;
        command.CanExecuteChanged += (_, _) => notifications++;

        command.Execute(null);
        await command.ExecuteAsync();

        command.IsExecuting.Should().BeFalse();
        notifications.Should().Be(0);
    }

    [Fact]
    public async Task Predicate_Can_Wait_For_Foreign_Dispose_Without_Deadlock()
    {
        using var disposeFinished = new ManualResetEventSlim();
        var disposeFinishedInsidePredicate = false;
        Thread? disposer = null;
        AsyncRelayCommand? command = null;
        command = AsyncRelayCommand.Builder()
            .Predicate(() =>
            {
                disposer = new Thread(() =>
                {
                    command!.Dispose();
                    disposeFinished.Set();
                });
                disposer.Start();
                disposeFinishedInsidePredicate = disposeFinished.Wait(HangGuard);
                return true;
            })
            .Task(_ => Task.CompletedTask)
            .Build();

        await command.ExecuteAsync();
        disposer!.Join(HangGuard).Should().BeTrue();

        disposeFinishedInsidePredicate.Should().BeTrue();
        command.IsExecuting.Should().BeFalse();
    }

    [Fact]
    public async Task Predicate_Disposal_Prevents_Task_Admission()
    {
        var calls = 0;
        AsyncRelayCommand? command = null;
        command = AsyncRelayCommand.Builder()
            .Predicate(() =>
            {
                command!.Dispose();
                return true;
            })
            .Task(_ =>
            {
                calls++;
                return Task.CompletedTask;
            })
            .Build();

        await command.ExecuteAsync();

        calls.Should().Be(0);
        command.IsExecuting.Should().BeFalse();
        command.CanExecute(null).Should().BeFalse();
    }

    [Fact]
    public async Task Reentrant_Predicate_Admits_Only_Outer_Execution()
    {
        var predicateCalls = 0;
        var taskCalls = 0;
        AsyncRelayCommand? command = null;
        command = AsyncRelayCommand.Builder()
            .Predicate(() =>
            {
                predicateCalls++;
                if (predicateCalls == 1)
                    _ = command!.ExecuteAsync();
                return true;
            })
            .Task(_ =>
            {
                taskCalls++;
                return Task.CompletedTask;
            })
            .Build();

        await command.ExecuteAsync();

        predicateCalls.Should().Be(1);
        taskCalls.Should().Be(1);
    }

    [Fact]
    public async Task External_Cancellation_Remains_Throwing_When_Command_Cancel_Follows()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellationSeen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var external = new CancellationTokenSource();
        using var command = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                started.SetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, token);
                }
                catch (OperationCanceledException)
                {
                    cancellationSeen.SetResult();
                    await release.Task;
                    throw;
                }
            })
            .Build();
        var run = command.ExecuteAsync(null, external.Token);
        await started.Task;

        external.Cancel();
        await cancellationSeen.Task;
        command.Cancel();
        release.SetResult();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => await run);
    }

    [Fact]
    public async Task Command_Cancellation_Remains_Nonthrowing_When_External_Cancel_Follows()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellationSeen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var external = new CancellationTokenSource();
        using var command = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                started.SetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, token);
                }
                catch (OperationCanceledException)
                {
                    cancellationSeen.SetResult();
                    await release.Task;
                    throw;
                }
            })
            .Build();
        var run = command.ExecuteAsync(null, external.Token);
        await started.Task;

        command.Cancel();
        await cancellationSeen.Task;
        external.Cancel();
        release.SetResult();

        await run;
    }

    [Fact]
    public async Task Cancel_Racing_Completion_Does_Not_Hide_External_Cancellation_Of_The_Next_Execution()
    {
        // #1342: Cancel() tags the cancellation origin under the gate that swaps
        // executions. The probe pauses Cancel() after it releases the gate. In
        // that window execution A completes and execution B starts with an
        // external token. A late tag would mark B as cancelled by the command,
        // and B would then swallow its external cancellation.
        var limit = TimeSpan.FromSeconds(30);
        var aStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var aRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var bStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var runs = 0;
        using var external = new CancellationTokenSource();
        using var command = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                if (Interlocked.Increment(ref runs) == 1)
                {
                    aStarted.SetResult();
                    await aRelease.Task;
                    return;
                }
                bStarted.SetResult();
                await Task.Delay(Timeout.Infinite, token);
            })
            .Build();
        using var paused = new ManualResetEventSlim();
        using var resume = new ManualResetEventSlim();
        command.AfterCancelReleasesGateForTesting = () =>
        {
            command.AfterCancelReleasesGateForTesting = null;
            paused.Set();
            resume.Wait(limit).Should().BeTrue("the test resumes Cancel()");
        };

        var a = command.ExecuteAsync();
        await aStarted.Task.WaitAsync(limit);
        var cancel = Task.Run(command.Cancel);
        paused.Wait(limit).Should().BeTrue("Cancel() reaches the probe");

        aRelease.SetResult();
        await a.WaitAsync(limit);
        var b = command.ExecuteAsync(null, external.Token);
        await bStarted.Task.WaitAsync(limit);

        resume.Set();
        await cancel.WaitAsync(limit);
        command.IsExecuting.Should().BeTrue("the paused Cancel() captured A's source, not B's");

        external.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => await b.WaitAsync(limit));
    }

    [Fact]
    public async Task Start_Observer_Failure_Restores_Idle_Without_Running_Task()
    {
        var calls = 0;
        var command = AsyncRelayCommand.Builder()
            .Task(_ =>
            {
                calls++;
                return Task.CompletedTask;
            })
            .Build();
        command.CanExecuteChanged += (_, _) => throw new InvalidOperationException("start observer");

        Func<Task> act = () => command.ExecuteAsync();

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("start observer");
        calls.Should().Be(0);
        command.IsExecuting.Should().BeFalse();
        command.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public async Task Body_Failure_Precedes_Completion_Observer_Failure()
    {
        var notifications = 0;
        var command = AsyncRelayCommand.Builder()
            .Task(_ => Task.FromException(new ArgumentException("body failure")))
            .Build();
        command.CanExecuteChanged += (_, _) =>
        {
            notifications++;
            if (notifications == 2)
                throw new InvalidOperationException("completion observer");
        };

        Func<Task> act = () => command.ExecuteAsync();

        await act.Should().ThrowAsync<ArgumentException>()
            .WithMessage("body failure");
        command.IsExecuting.Should().BeFalse();
        command.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public async Task Fire_And_Forget_Routes_Body_Failure_Before_Completion_Observer()
    {
        var notifications = 0;
        var observed = new TaskCompletionSource<Exception>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var command = AsyncRelayCommand.Builder()
            .Task(_ => Task.FromException(new ArgumentException("body failure")))
            .Build();
        command.CanExecuteChanged += (_, _) =>
        {
            notifications++;
            if (notifications == 2)
                throw new InvalidOperationException("completion observer");
        };
        using var subscription = command.Errors.Subscribe(observed.SetResult);

        command.Execute(null);
        var error = await observed.Task.WaitAsync(HangGuard);

        error.Should().BeOfType<ArgumentException>()
            .Which.Message.Should().Be("body failure");
    }

    [Fact]
    public void Dispose_Disposes_Error_Channel_When_Completion_Observer_Throws()
    {
        var command = AsyncRelayCommand.Builder().Build();
        using var subscription = command.Errors.Subscribe(
            _ => { },
            () => throw new InvalidOperationException("terminal observer"));

        Action dispose = command.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        var errors = (Subject<Exception>)typeof(AsyncRelayCommand)
            .GetField("_errors", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(command)!;
        errors.IsDisposed.Should().BeTrue();
        dispose.Should().NotThrow("all terminal cleanup completed before rethrowing");
    }
}
