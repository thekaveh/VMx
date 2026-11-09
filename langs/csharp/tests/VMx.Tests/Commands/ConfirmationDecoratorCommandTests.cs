using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using VMx.Commands;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Commands;

public class ConfirmationDecoratorCommandTests
{
    [Fact]
    public void Dispose_Disposes_Error_Channel_When_Completion_Observer_Throws()
    {
        var inner = RelayCommand.Builder().Build();
        var command = new ConfirmationDecoratorCommand(
            inner,
            () => Task.FromResult(true));
        using var subscription = command.Errors.Subscribe(
            _ => { },
            () => throw new InvalidOperationException("terminal observer"));

        Action dispose = command.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        var errors = (Subject<Exception>)typeof(ConfirmationDecoratorCommand)
            .GetField("_errors", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(command)!;
        errors.IsDisposed.Should().BeTrue();
        dispose.Should().NotThrow("all terminal cleanup completed before rethrowing");
    }

    [Fact]
    public async Task Dispose_Waits_For_InFlight_Error_Delivery()
    {
        using var observerEntered = new ManualResetEventSlim();
        using var releaseObserver = new ManualResetEventSlim();
        using var disposeStarted = new ManualResetEventSlim();
        var inner = RelayCommand.Builder().Task(() => { }).Build();
        var command = new ConfirmationDecoratorCommand(
            inner,
            () => Task.FromException<bool>(new InvalidOperationException("boom")));
        using var subscription = command.Errors.Subscribe(_ =>
        {
            observerEntered.Set();
            releaseObserver.Wait();
        });

        var execute = Task.Run(() => command.Execute(null));
        observerEntered.Wait(HangGuard).Should().BeTrue();
        var dispose = Task.Run(() =>
        {
            disposeStarted.Set();
            command.Dispose();
        });
        disposeStarted.Wait(HangGuard).Should().BeTrue();

        try
        {
            var first = await Task.WhenAny(dispose, Task.Delay(TimeSpan.FromMilliseconds(100)));
            first.Should().NotBeSameAs(dispose,
                "error-channel teardown must serialize with an admitted delivery");
        }
        finally
        {
            releaseObserver.Set();
        }

        await Task.WhenAll(execute, dispose);
    }

    // ADR-0195 D1/D3: a completed confirmation does not run the inner command
    // inside Execute(), and the deferred run is not posted to the caller's
    // SynchronizationContext (VMx does not marshal; spec/11 §3.1).
    [Fact]
    public async Task Execute_With_Completed_Confirmation_Defers_Inner_Without_Posting_To_Caller_Context()
    {
        var ran = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        var callerThread = Environment.CurrentManagedThreadId;
        var insideExecute = false;
        var ranInside = false;
        using var inner = RelayCommand.Builder()
            .Task(() =>
            {
                ranInside = insideExecute && Environment.CurrentManagedThreadId == callerThread;
                ran.TrySetResult(Environment.CurrentManagedThreadId);
            })
            .Build();
        using var command = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true));
        var context = new RecordingSynchronizationContext();
        var previous = SynchronizationContext.Current;

        SynchronizationContext.SetSynchronizationContext(context);
        insideExecute = true;
        try
        {
            command.Execute(null);
        }
        finally
        {
            insideExecute = false;
            SynchronizationContext.SetSynchronizationContext(previous);
        }

        await ran.Task.WaitAsync(HangGuard);
        ranInside.Should().BeFalse("Execute() never runs the inner command inside its own call");
        context.Posts.Should().Be(0, "VMx does not marshal the confirmed inner command to the caller's context");
    }

    private sealed class RecordingSynchronizationContext : SynchronizationContext
    {
        private int _posts;

        public int Posts => Volatile.Read(ref _posts);

        public override void Post(SendOrPostCallback d, object? state)
        {
            Interlocked.Increment(ref _posts);
            base.Post(d, state);
        }
    }
}
