using FluentAssertions;
using VMx.Commands;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: CMDD-014..CMDD-017 — a <see cref="ConfirmationDecoratorCommand"/>
/// over an asynchronous inner command. See spec/04-commands.md §8.3.2 and ADR-0145.
/// Every blocked inner body waits on a <see cref="TaskCompletionSource"/> gate, and
/// every wait that should succeed is bounded by <see cref="HangGuard"/>.
/// </summary>
public sealed class CMDD_014_to_017_ConfirmationAsyncInner_Tests
{
    // Short window for checks that something did NOT happen afterwards.
    private static readonly TimeSpan QuietWindow = TimeSpan.FromMilliseconds(50);

    private static TaskCompletionSource Gate() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static TaskCompletionSource<T> Gate<T>() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    // An IAsyncCommand that records every entry point. ExecuteAsync blocks until
    // Release completes; Execute only records, so a call through the synchronous
    // entry point is visible on its own.
    private sealed class RecordingAsyncCommand : IAsyncCommand, IDisposable
    {
        private readonly TaskCompletionSource _entered = Gate();
        private int _executeCalls;
        private int _executeAsyncCalls;
        private int _cancelCalls;
        private int _disposeCalls;

        public TaskCompletionSource Release { get; } = Gate();

        public int ExecuteCalls => Volatile.Read(ref _executeCalls);

        public int ExecuteAsyncCalls => Volatile.Read(ref _executeAsyncCalls);

        public int CancelCalls => Volatile.Read(ref _cancelCalls);

        public int DisposeCalls => Volatile.Read(ref _disposeCalls);

        public object? LastParameter { get; private set; }

        public CancellationToken LastToken { get; private set; }

        public Task Entered => _entered.Task.WaitAsync(HangGuard);

        public bool IsExecuting => ExecuteAsyncCalls > 0 && !Release.Task.IsCompleted;

        public event EventHandler? CanExecuteChanged
        {
            add { }
            remove { }
        }

        public bool CanExecute(object? parameter) => true;

        public void Execute(object? parameter)
        {
            LastParameter = parameter;
            Interlocked.Increment(ref _executeCalls);
        }

        public Task ExecuteAsync(object? parameter = null, CancellationToken cancellationToken = default)
        {
            LastParameter = parameter;
            LastToken = cancellationToken;
            Interlocked.Increment(ref _executeAsyncCalls);
            _entered.TrySetResult();
            return Release.Task;
        }

        public void Cancel() => Interlocked.Increment(ref _cancelCalls);

        public void Dispose() => Interlocked.Increment(ref _disposeCalls);
    }

    // An AsyncRelayCommand whose body signals Entered, then blocks on Release and
    // finally runs the optional tail. Runs counts body entries.
    private sealed class GatedRelay
    {
        private readonly TaskCompletionSource _entered = Gate();
        private int _runs;

        public GatedRelay(Action? tail = null, bool throwOnCancel = false)
        {
            Command = AsyncRelayCommand.Builder()
                .Task(async token =>
                {
                    Interlocked.Increment(ref _runs);
                    LastToken = token;
                    _entered.TrySetResult();
                    await Release.Task.ConfigureAwait(false);
                    tail?.Invoke();
                })
                .ThrowOnCancel(throwOnCancel)
                .Build();
        }

        public AsyncRelayCommand Command { get; }

        public TaskCompletionSource Release { get; } = Gate();

        public int Runs => Volatile.Read(ref _runs);

        public CancellationToken LastToken { get; private set; }

        public Task Entered => _entered.Task.WaitAsync(HangGuard);
    }

    // ── CMDD-014 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-014: the awaited call stays pending while the async inner body
    /// is blocked, completes after it is released, and reaches the inner only through
    /// its awaitable entry point, once, with no decorator-owned cancellation token.</summary>
    [Fact, Trait("Conformance", "CMDD-014")]
    public async Task CMDD_014_Awaited_Call_Completes_When_The_Async_Inner_Completes()
    {
        var inner = new RecordingAsyncCommand();
        var decision = Gate<bool>();
        using var decorator = new ConfirmationDecoratorCommand(inner, () => decision.Task);

        var awaited = decorator.ExecuteAsync("payload");
        inner.ExecuteAsyncCalls.Should().Be(0, "the inner waits for the confirmation");

        decision.SetResult(true);
        await inner.Entered;
        awaited.IsCompleted.Should().BeFalse("the inner operation is still blocked");

        inner.Release.SetResult();
        await awaited.WaitAsync(HangGuard);

        inner.ExecuteAsyncCalls.Should().Be(1);
        inner.ExecuteCalls.Should().Be(0, "an async inner is never also run through Execute");
        inner.LastParameter.Should().Be("payload");
        inner.LastToken.CanBeCanceled.Should().BeFalse(
            "the decorator passes no cancellation token of its own");
    }

    /// <summary>CMDD-014: over a real <see cref="AsyncRelayCommand"/>, the awaited
    /// call completes only after the body finishes, and the body ran once.</summary>
    [Fact, Trait("Conformance", "CMDD-014")]
    public async Task CMDD_014_Awaited_Call_Waits_For_An_AsyncRelayCommand_Body()
    {
        var finished = 0;
        var relay = new GatedRelay(tail: () => Interlocked.Increment(ref finished));
        using var decorator = new ConfirmationDecoratorCommand(
            relay.Command, () => Task.FromResult(true));

        var awaited = decorator.ExecuteAsync(null);
        await relay.Entered;
        awaited.IsCompleted.Should().BeFalse();
        relay.Command.IsExecuting.Should().BeTrue();

        relay.Release.SetResult();
        await awaited.WaitAsync(HangGuard);

        Volatile.Read(ref finished).Should().Be(1, "the awaiter resumes after the body finishes");
        relay.Runs.Should().Be(1);
        relay.Command.IsExecuting.Should().BeFalse();
    }

    /// <summary>CMDD-014: a false confirmation completes the awaiter without invoking
    /// either inner entry point.</summary>
    [Fact, Trait("Conformance", "CMDD-014")]
    public async Task CMDD_014_False_Confirmation_Completes_Without_Invoking_The_Inner()
    {
        var inner = new RecordingAsyncCommand();
        var decision = Gate<bool>();
        using var decorator = new ConfirmationDecoratorCommand(inner, () => decision.Task);

        var awaited = decorator.ExecuteAsync(null);
        decision.SetResult(false);
        await awaited.WaitAsync(HangGuard);

        inner.ExecuteAsyncCalls.Should().Be(0);
        inner.ExecuteCalls.Should().Be(0);
    }

    /// <summary>CMDD-014: a synchronous inner runs once through <c>Execute</c> and the
    /// awaiter completes only after that call returns.</summary>
    [Fact, Trait("Conformance", "CMDD-014")]
    public async Task CMDD_014_Sync_Inner_Runs_Once_And_The_Awaiter_Waits_For_It()
    {
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var runs = 0;
        var returned = 0;
        var inner = RelayCommand.Builder()
            .Task(() =>
            {
                Interlocked.Increment(ref runs);
                entered.Set();
                release.Wait(HangGuard);
                Interlocked.Increment(ref returned);
            })
            .Build();
        var decision = Gate<bool>();
        using var decorator = new ConfirmationDecoratorCommand(inner, () => decision.Task);

        var awaited = decorator.ExecuteAsync(null);
        // The confirmation continuation runs the synchronous body on a pool thread.
        decision.SetResult(true);
        entered.Wait(HangGuard).Should().BeTrue();
        awaited.IsCompleted.Should().BeFalse("the synchronous inner has not returned yet");

        release.Set();
        await awaited.WaitAsync(HangGuard);

        Volatile.Read(ref runs).Should().Be(1);
        Volatile.Read(ref returned).Should().Be(1);
    }

    // ── CMDD-015 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-015: an awaited async-inner failure reaches the awaiter
    /// unchanged and is emitted on neither the decorator's nor the inner's
    /// <c>Errors</c>.</summary>
    [Fact, Trait("Conformance", "CMDD-015")]
    public async Task CMDD_015_Awaited_Inner_Failure_Reaches_Only_The_Awaiter()
    {
        var boom = new InvalidOperationException("inner failed");
        var relay = new GatedRelay(tail: () => throw boom);
        using var decorator = new ConfirmationDecoratorCommand(
            relay.Command, () => Task.FromResult(true));
        var decoratorErrors = new List<Exception>();
        var innerErrors = new List<Exception>();
        using var decoratorSubscription = decorator.Errors.Subscribe(e => { lock (decoratorErrors) decoratorErrors.Add(e); });
        using var innerSubscription = relay.Command.Errors.Subscribe(e => { lock (innerErrors) innerErrors.Add(e); });

        var awaited = decorator.ExecuteAsync(null);
        await relay.Entered;
        awaited.IsCompleted.Should().BeFalse();
        relay.Release.SetResult();

        (await FluentActions.Awaiting(() => awaited.WaitAsync(HangGuard))
                .Should().ThrowAsync<InvalidOperationException>())
            .Which.Should().BeSameAs(boom);
        await Task.Delay(QuietWindow);
        lock (decoratorErrors) decoratorErrors.Should().BeEmpty();
        lock (innerErrors) innerErrors.Should().BeEmpty();
    }

    /// <summary>CMDD-015: the fire-and-forget path starts an async inner through the
    /// inner's own <c>Execute</c>; the inner's failure reaches the inner's
    /// <c>Errors</c> exactly once and the decorator's <c>Errors</c> not at all.</summary>
    [Fact, Trait("Conformance", "CMDD-015")]
    public async Task CMDD_015_Fire_And_Forget_Inner_Failure_Reaches_Only_The_Inner_Errors()
    {
        var boom = new InvalidOperationException("inner failed");
        var relay = new GatedRelay(tail: () => throw boom);
        using var decorator = new ConfirmationDecoratorCommand(
            relay.Command, () => Task.FromResult(true));
        var decoratorErrors = new List<Exception>();
        var innerErrors = new List<Exception>();
        var innerFailed = Gate<Exception>();
        using var decoratorSubscription = decorator.Errors.Subscribe(e => { lock (decoratorErrors) decoratorErrors.Add(e); });
        using var innerSubscription = relay.Command.Errors.Subscribe(e =>
        {
            lock (innerErrors) innerErrors.Add(e);
            innerFailed.TrySetResult(e);
        });

        decorator.Execute(null);
        await relay.Entered;
        relay.Release.SetResult();

        (await innerFailed.Task.WaitAsync(HangGuard)).Should().BeSameAs(boom);
        await Task.Delay(QuietWindow);
        lock (innerErrors) innerErrors.Should().ContainSingle().Which.Should().BeSameAs(boom);
        lock (decoratorErrors) decoratorErrors.Should().BeEmpty();
        relay.Runs.Should().Be(1);
    }

    /// <summary>CMDD-015: on the fire-and-forget path the decorator reaches an async
    /// inner only through its synchronous <c>Execute</c>.</summary>
    [Fact, Trait("Conformance", "CMDD-015")]
    public void CMDD_015_Fire_And_Forget_Starts_An_Async_Inner_Through_Its_Own_Execute()
    {
        var inner = new RecordingAsyncCommand();
        using var decorator = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true));

        // A completed confirmation runs the whole flow inline.
        decorator.Execute("payload");

        inner.ExecuteCalls.Should().Be(1);
        inner.ExecuteAsyncCalls.Should().Be(0);
        inner.LastParameter.Should().Be("payload");
    }

    /// <summary>CMDD-015: a failing confirmation on the fire-and-forget path reaches
    /// the decorator's <c>Errors</c> exactly once and invokes no inner entry point.</summary>
    [Fact, Trait("Conformance", "CMDD-015")]
    public async Task CMDD_015_Fire_And_Forget_Confirm_Failure_Reaches_The_Decorator_Errors_Once()
    {
        var boom = new InvalidOperationException("confirm failed");
        var inner = new RecordingAsyncCommand();
        using var decorator = new ConfirmationDecoratorCommand(
            inner, () => Task.FromException<bool>(boom));
        var decoratorErrors = new List<Exception>();
        var observed = Gate<Exception>();
        using var subscription = decorator.Errors.Subscribe(e =>
        {
            lock (decoratorErrors) decoratorErrors.Add(e);
            observed.TrySetResult(e);
        });

        decorator.Execute(null);

        (await observed.Task.WaitAsync(HangGuard)).Should().BeSameAs(boom);
        await Task.Delay(QuietWindow);
        lock (decoratorErrors) decoratorErrors.Should().ContainSingle();
        inner.ExecuteCalls.Should().Be(0);
        inner.ExecuteAsyncCalls.Should().Be(0);
    }

    // ── CMDD-016 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-016: an <see cref="AsyncRelayCommand"/> that becomes busy while
    /// the confirmation is pending drops the confirmed call; its body runs no second
    /// time and the awaiter completes while the first run is still blocked.</summary>
    [Fact, Trait("Conformance", "CMDD-016")]
    public async Task CMDD_016_Busy_Inner_Drops_The_Confirmed_Call()
    {
        var relay = new GatedRelay();
        var decision = Gate<bool>();
        using var decorator = new ConfirmationDecoratorCommand(relay.Command, () => decision.Task);

        var awaited = decorator.ExecuteAsync(null);
        var direct = relay.Command.ExecuteAsync();
        await relay.Entered;
        relay.Command.IsExecuting.Should().BeTrue();

        decision.SetResult(true);
        await awaited.WaitAsync(HangGuard);

        direct.IsCompleted.Should().BeFalse("the first run is still blocked");
        relay.Runs.Should().Be(1, "the busy inner dropped the confirmed call");

        relay.Release.SetResult();
        await direct.WaitAsync(HangGuard);
        relay.Runs.Should().Be(1);
    }

    /// <summary>CMDD-016: cancelling the inner while an awaited decorator call is in
    /// flight gives the awaiter the inner's own outcome: normal completion by
    /// default, or the inner's cancellation exception, the same instance, under
    /// <c>ThrowOnCancel</c>.</summary>
    [Theory, Trait("Conformance", "CMDD-016")]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CMDD_016_Inner_Cancel_Outcome_Reaches_The_Awaiter_Unchanged(bool throwOnCancel)
    {
        var cancelled = new OperationCanceledException("inner cancelled");
        var entered = Gate();
        var inner = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                entered.TrySetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    throw cancelled;
                }
            })
            .ThrowOnCancel(throwOnCancel)
            .Build();
        using var decorator = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true));
        var decoratorErrors = new List<Exception>();
        var innerErrors = new List<Exception>();
        using var decoratorSubscription = decorator.Errors.Subscribe(e => { lock (decoratorErrors) decoratorErrors.Add(e); });
        using var innerSubscription = inner.Errors.Subscribe(e => { lock (innerErrors) innerErrors.Add(e); });

        var awaited = decorator.ExecuteAsync(null);
        await entered.Task.WaitAsync(HangGuard);
        awaited.IsCompleted.Should().BeFalse();

        inner.Cancel();

        if (throwOnCancel)
        {
            (await FluentActions.Awaiting(() => awaited.WaitAsync(HangGuard))
                    .Should().ThrowAsync<OperationCanceledException>())
                .Which.Should().BeSameAs(cancelled);
        }
        else
        {
            await awaited.WaitAsync(HangGuard);
        }
        inner.IsExecuting.Should().BeFalse();
        lock (decoratorErrors) decoratorErrors.Should().BeEmpty();
        lock (innerErrors) innerErrors.Should().BeEmpty();
    }

    // ── CMDD-017 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-017: an outer decorator over an inner decorator over a blocking
    /// async command awaits both confirmations and the inner operation, which runs
    /// once through its awaitable entry point.</summary>
    [Fact, Trait("Conformance", "CMDD-017")]
    public async Task CMDD_017_Nested_Wrappers_Are_Awaited_End_To_End()
    {
        var command = new RecordingAsyncCommand();
        var innerAsked = Gate();
        var innerDecision = Gate<bool>();
        var outerDecision = Gate<bool>();
        using var innerWrapper = new ConfirmationDecoratorCommand(command, () =>
        {
            innerAsked.TrySetResult();
            return innerDecision.Task;
        });
        using var outerWrapper = new ConfirmationDecoratorCommand(innerWrapper, () => outerDecision.Task);

        var awaited = outerWrapper.ExecuteAsync("payload");
        outerDecision.SetResult(true);
        await innerAsked.Task.WaitAsync(HangGuard);
        awaited.IsCompleted.Should().BeFalse("the inner wrapper's confirmation is pending");
        command.ExecuteAsyncCalls.Should().Be(0);

        innerDecision.SetResult(true);
        await command.Entered;
        awaited.IsCompleted.Should().BeFalse("the body is still blocked");

        command.Release.SetResult();
        await awaited.WaitAsync(HangGuard);

        command.ExecuteAsyncCalls.Should().Be(1);
        command.ExecuteCalls.Should().Be(0);
        command.LastParameter.Should().Be("payload");
    }

    /// <summary>CMDD-017: disposing the decorator while its async inner body is
    /// blocked neither cancels nor disposes the inner, and the awaiter still
    /// completes when the body is released.</summary>
    [Fact, Trait("Conformance", "CMDD-017")]
    public async Task CMDD_017_Disposal_During_The_Inner_Operation_Does_Not_Own_The_Inner()
    {
        var inner = new RecordingAsyncCommand();
        var decorator = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true));
        var errorsCompleted = false;
        using var subscription = decorator.Errors.Subscribe(_ => { }, () => errorsCompleted = true);

        var awaited = decorator.ExecuteAsync(null);
        await inner.Entered;
        decorator.Dispose();

        errorsCompleted.Should().BeTrue();
        awaited.IsCompleted.Should().BeFalse("disposal does not end the inner operation");
        inner.CancelCalls.Should().Be(0);
        inner.DisposeCalls.Should().Be(0);
        inner.LastToken.IsCancellationRequested.Should().BeFalse();

        inner.Release.SetResult();
        await awaited.WaitAsync(HangGuard);
        inner.CancelCalls.Should().Be(0);
        inner.DisposeCalls.Should().Be(0);
        inner.ExecuteAsyncCalls.Should().Be(1);
    }

    /// <summary>CMDD-017: over a real <see cref="AsyncRelayCommand"/>, disposal
    /// during the body leaves its token uncancelled and the command usable.</summary>
    [Fact, Trait("Conformance", "CMDD-017")]
    public async Task CMDD_017_Disposal_During_An_AsyncRelayCommand_Run_Leaves_It_Running_And_Usable()
    {
        var relay = new GatedRelay();
        var decorator = new ConfirmationDecoratorCommand(relay.Command, () => Task.FromResult(true));

        var awaited = decorator.ExecuteAsync(null);
        await relay.Entered;
        decorator.Dispose();

        relay.Command.IsExecuting.Should().BeTrue();
        relay.LastToken.IsCancellationRequested.Should().BeFalse();
        awaited.IsCompleted.Should().BeFalse();

        relay.Release.SetResult();
        await awaited.WaitAsync(HangGuard);

        relay.Command.IsExecuting.Should().BeFalse();
        relay.Command.CanExecute(null).Should().BeTrue("the inner was not disposed");
        await relay.Command.ExecuteAsync().WaitAsync(HangGuard);
        relay.Runs.Should().Be(2);
    }

    /// <summary>CMDD-017: disposing the decorator while its confirmation is pending
    /// means a later <c>true</c> starts no inner work on either path.</summary>
    [Fact, Trait("Conformance", "CMDD-017")]
    public async Task CMDD_017_Disposal_During_A_Pending_Confirmation_Starts_No_Inner_Work()
    {
        var inner = new RecordingAsyncCommand();
        // Continuations run inline in SetResult, so both execution paths have
        // finished once the resolving task completes.
        var decision = new TaskCompletionSource<bool>();
        var decorator = new ConfirmationDecoratorCommand(inner, () => decision.Task);
        var errors = new List<Exception>();
        using var subscription = decorator.Errors.Subscribe(e => { lock (errors) errors.Add(e); });

        decorator.Execute(null);
        var awaited = decorator.ExecuteAsync(null);
        decorator.Dispose();
        await Task.Run(() => decision.SetResult(true));
        await awaited.WaitAsync(HangGuard);

        inner.ExecuteAsyncCalls.Should().Be(0);
        inner.ExecuteCalls.Should().Be(0);
        inner.CancelCalls.Should().Be(0);
        inner.DisposeCalls.Should().Be(0);
        lock (errors) errors.Should().BeEmpty();
    }
}
