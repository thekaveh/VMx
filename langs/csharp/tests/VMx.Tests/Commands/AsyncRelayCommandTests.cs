using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

public class AsyncRelayCommandTests
{
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
        var error = await observed.Task.WaitAsync(TimeSpan.FromSeconds(2));

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
