using System.ComponentModel;
using System.Reactive.Linq;
using System.Reflection;
using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using VMx.State;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public sealed class AsyncResourceVMConformanceTests
{
    [Fact, Trait("Conformance", "ARES-001")]
    public void ARES_001_Initial_State_And_Commands()
    {
        using var hub = new MessageHub();
        var calls = 0;
        var vm = Create(hub, _ => { calls++; return Task.FromResult(1); });
        var changes = new List<string?>();
        vm.PropertyChanged += (_, e) => changes.Add(e.PropertyName);

        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        vm.State.HasValue.Should().BeFalse();
        vm.State.Error.Should().BeNull();
        calls.Should().Be(0);
        changes.Should().BeEmpty();
        vm.LoadCommand.CanExecute(null).Should().BeTrue();
        vm.ReloadCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "ARES-002")]
    public async Task ARES_002_Success_Publishes_Ordinary_State_Pairs()
    {
        using var hub = new MessageHub();
        var result = NewSource<int>();
        var vm = Create(hub, _ => result.Task);
        var local = new List<string?>();
        var shared = new List<string>();
        vm.PropertyChanged += (_, e) => local.Add(e.PropertyName);
        using var subscription = hub.Messages
            .OfType<IPropertyChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.SenderObject, vm))
            .Subscribe(message => shared.Add(message.PropertyName));

        var load = vm.LoadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Loading);
        result.SetResult(42);
        await load;

        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(42);
        local.Should().Equal(nameof(vm.State), nameof(vm.State));
        shared.Should().Equal(local!);
        vm.LoadCommand.CanExecute(null).Should().BeFalse();
        vm.ReloadCommand.CanExecute(null).Should().BeTrue();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact]
    public async Task Start_Notification_Failure_Rolls_Back_Without_Invoking_Loader()
    {
        using var hub = new MessageHub();
        var calls = 0;
        var vm = Create(hub, _ =>
        {
            calls++;
            return Task.FromResult(42);
        });
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
            throw new InvalidOperationException("observer");

        Func<Task> act = () => vm.LoadAsync();

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("observer");
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        calls.Should().Be(0);
        vm.LoadCommand.CanExecute(null).Should().BeTrue();
        vm.ReloadCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact]
    public async Task Awaited_Command_Preserves_Start_Notification_Failure_And_Rolls_Back()
    {
        using var hub = new MessageHub();
        var calls = 0;
        var vm = Create(hub, _ =>
        {
            calls++;
            return Task.FromResult(42);
        });
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Loading)
                throw new InvalidOperationException("start observer");
        };

        Func<Task> act = () => vm.LoadCommand.ExecuteAsync();

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("start observer");
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        calls.Should().Be(0);
    }

    [Fact]
    public async Task Fire_And_Forget_Routes_Start_Notification_Failure_After_Rollback()
    {
        using var hub = new MessageHub();
        var observed = NewSource<Exception>();
        var vm = Create(hub, _ => Task.FromResult(42));
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Loading)
                throw new InvalidOperationException("start observer");
        };
        using var subscription = vm.LoadCommand.Errors.Subscribe(observed.SetResult);

        vm.LoadCommand.Execute(null);
        var error = await observed.Task.WaitAsync(TimeSpan.FromSeconds(2));

        error.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Be("start observer");
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
    }

    [Fact]
    public async Task Completion_Notification_Failure_Keeps_Ready_Disposes_And_Notifies_All()
    {
        using var hub = new MessageHub();
        var result = NewSource<int>();
        var vm = Create(hub, _ => result.Task);
        var reloadNotifications = 0;
        var cancelNotifications = 0;
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Ready)
                throw new InvalidOperationException("completion observer");
        };
        vm.ReloadCommand.CanExecuteChanged += (_, _) => reloadNotifications++;
        vm.CancelCommand.CanExecuteChanged += (_, _) => cancelNotifications++;

        var load = vm.LoadAsync();
        var cancellation = CurrentCancellation(vm);
        result.SetResult(42);
        Func<Task> act = async () => await load;

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("completion observer");
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(42);
        reloadNotifications.Should().Be(2);
        cancelNotifications.Should().Be(2);
        Action accessDisposedSource = () => _ = cancellation.Token;
        accessDisposedSource.Should().Throw<ObjectDisposedException>();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Command_Routes_Completion_Notification_Failure_With_Ready_State(
        bool fireAndForget)
    {
        using var hub = new MessageHub();
        var observed = NewSource<Exception>();
        var vm = Create(hub, _ => Task.FromResult(42));
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Ready)
                throw new InvalidOperationException("completion observer");
        };
        using var subscription = vm.LoadCommand.Errors.Subscribe(observed.SetResult);

        if (fireAndForget)
        {
            vm.LoadCommand.Execute(null);
            var error = await observed.Task.WaitAsync(TimeSpan.FromSeconds(2));
            error.Should().BeOfType<InvalidOperationException>()
                .Which.Message.Should().Be("completion observer");
        }
        else
        {
            Func<Task> act = () => vm.LoadCommand.ExecuteAsync();
            await act.Should().ThrowAsync<InvalidOperationException>()
                .WithMessage("completion observer");
            observed.Task.IsCompleted.Should().BeFalse();
        }

        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(42);
    }

    [Fact]
    public async Task Failure_Notification_Exception_Still_Disposes_Operation()
    {
        using var hub = new MessageHub();
        var result = NewSource<int>();
        var vm = Create(hub, _ => result.Task);
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Error)
                throw new InvalidOperationException("failure observer");
        };

        var load = vm.LoadAsync();
        var cancellation = CurrentCancellation(vm);
        result.SetException(new ArgumentException("loader"));
        Func<Task> act = async () => await load;

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("failure observer");
        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        vm.State.Error.Should().BeOfType<ArgumentException>();
        Action accessDisposedSource = () => _ = cancellation.Token;
        accessDisposedSource.Should().Throw<ObjectDisposedException>();
    }

    [Fact]
    public async Task Superseding_Start_Rolls_Back_When_Previous_Cancellation_Callback_Throws()
    {
        using var hub = new MessageHub();
        var first = NewSource<int>();
        var cleaned = new List<int>();
        var calls = 0;
        var vm = Create(
            hub,
            token =>
            {
                calls++;
                token.Register(() => throw new InvalidOperationException("cancel callback"));
                return first.Task;
            },
            cleanup: cleaned.Add);
        var older = vm.LoadAsync();

        Func<Task> act = () => vm.ReloadAsync();

        var thrown = await act.Should().ThrowAsync<AggregateException>();
        thrown.Which.InnerExceptions.Should().ContainSingle()
            .Which.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Be("cancel callback");
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        calls.Should().Be(1);
        vm.LoadCommand.CanExecute(null).Should().BeTrue();
        vm.ReloadCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();

        first.SetResult(42);
        await WaitUntilAsync(() => cleaned.Count == 1);
        await older;
        cleaned.Should().Equal(42);
    }

    [Fact, Trait("Conformance", "ARES-003")]
    public async Task ARES_003_Failure_Is_State_Not_Command_Error()
    {
        using var hub = new MessageHub();
        var failure = new InvalidOperationException("offline");
        var vm = Create(hub, _ => Task.FromException<int>(failure));
        var commandErrors = new List<Exception>();
        using var subscription = vm.LoadCommand.Errors.Subscribe(commandErrors.Add);

        vm.LoadCommand.Execute(null);
        await WaitUntilAsync(() => vm.State.Status == AsyncResourceStatus.Error);

        vm.State.Error.Should().BeSameAs(failure);
        vm.State.HasValue.Should().BeFalse();
        commandErrors.Should().BeEmpty();
        vm.ReloadCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact, Trait("Conformance", "ARES-004")]
    public async Task ARES_004_Retry_Replaces_Error_With_Ready()
    {
        using var hub = new MessageHub();
        var attempt = 0;
        var vm = Create(hub, _ => ++attempt == 1
            ? Task.FromException<int>(new InvalidOperationException("first"))
            : Task.FromResult(7));

        await vm.LoadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        await vm.ReloadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(7);
        vm.State.Error.Should().BeNull();
    }

    [Fact, Trait("Conformance", "ARES-005")]
    public async Task ARES_005_Cancel_Initial_Load_Restores_Idle()
    {
        using var hub = new MessageHub();
        var observedCancellation = NewSource();
        var vm = Create(hub, async token =>
        {
            try
            {
                await Task.Delay(Timeout.Infinite, token);
                return 0;
            }
            catch (OperationCanceledException)
            {
                observedCancellation.TrySetResult();
                throw;
            }
        });

        var load = vm.LoadAsync();
        vm.CancelCommand.Execute(null);
        await load;
        await observedCancellation.Task;

        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        vm.State.Error.Should().BeNull();
        vm.Cancel();
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);

        using var alreadyCancelled = new CancellationTokenSource();
        alreadyCancelled.Cancel();
        var invoked = false;
        var preCancelled = Create(hub, _ =>
        {
            invoked = true;
            return Task.FromResult(1);
        });
        await preCancelled.LoadAsync(alreadyCancelled.Token);
        invoked.Should().BeFalse();
        preCancelled.State.Status.Should().Be(AsyncResourceStatus.Idle);
    }

    [Fact, Trait("Conformance", "ARES-006")]
    public async Task ARES_006_Retains_Previous_Through_Cancel_And_Failure()
    {
        using var hub = new MessageHub();
        var second = NewSource<int>();
        var failure = new InvalidOperationException("refresh");
        var attempt = 0;
        var vm = Create(hub, _ => ++attempt switch
        {
            1 => Task.FromResult(3),
            2 => second.Task,
            _ => Task.FromException<int>(failure),
        }, AsyncResourceRetention.RetainPrevious);

        await vm.LoadAsync();
        var reload = vm.ReloadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Loading);
        vm.State.Value.Should().Be(3);
        vm.Cancel();
        await reload;
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(3);

        await vm.ReloadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        vm.State.Value.Should().Be(3);
        vm.State.Error.Should().BeSameAs(failure);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Public_Cancel_Suppresses_Rollback_Observer_Failure(bool useCommand)
    {
        using var hub = new MessageHub();
        var started = NewSource();
        var result = NewSource<int>();
        var cleaned = new List<int>();
        var rollbackFailures = 0;
        var vm = Create(hub, token =>
        {
            started.TrySetResult();
            token.Register(() => result.TrySetResult(42));
            return result.Task;
        }, cleanup: cleaned.Add);
        vm.LoadCommand.CanExecuteChanged += (_, _) =>
        {
            if (vm.State.Status == AsyncResourceStatus.Idle && rollbackFailures == 0)
            {
                rollbackFailures = 1;
                throw new InvalidOperationException("cancel rollback observer");
            }
        };
        var load = vm.LoadAsync();
        await started.Task;

        var cancel = () =>
        {
            if (useCommand) vm.CancelCommand.Execute(null);
            else vm.Cancel();
        };
        cancel.Should().NotThrow();
        await load;
        await WaitUntilAsync(() => cleaned.Count == 1);

        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        cleaned.Should().Equal(42);
        rollbackFailures.Should().Be(1);
        vm.LoadCommand.CanExecute(null).Should().BeTrue();
        vm.ReloadCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "ARES-007")]
    public async Task ARES_007_Discard_Cleans_Before_Loading()
    {
        using var hub = new MessageHub();
        var second = NewSource<int>();
        var cleaned = new List<int>();
        var attempt = 0;
        var vm = Create(hub, _ => ++attempt switch
        {
            1 => Task.FromResult(5),
            2 => second.Task,
            _ => Task.FromException<int>(new InvalidOperationException("offline")),
        }, cleanup: cleaned.Add);

        await vm.LoadAsync();
        var reload = vm.ReloadAsync();
        cleaned.Should().Equal(5);
        vm.State.Status.Should().Be(AsyncResourceStatus.Loading);
        vm.State.HasValue.Should().BeFalse();
        vm.Cancel();
        await reload;
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        await vm.LoadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        vm.State.HasValue.Should().BeFalse();
    }

    [Fact]
    public async Task DiscardCleanupThatStartsNewReloadSuppressesSupersededNotification()
    {
        using var hub = new MessageHub();
        AsyncResourceVM<int>? vm = null;
        Task reentrantReload = Task.CompletedTask;
        var reentered = false;
        var nextValue = 0;
        var changes = new List<string?>();
        vm = Create(hub, _ => Task.FromResult(++nextValue), cleanup: value =>
        {
            if (value == 1 && !reentered)
            {
                reentered = true;
                reentrantReload = vm!.ReloadAsync();
            }
        });
        vm.PropertyChanged += (_, e) => changes.Add(e.PropertyName);

        await vm.LoadAsync();
        changes.Clear();
        await vm.ReloadAsync();
        await reentrantReload;

        changes.Should().Equal(nameof(vm.State), nameof(vm.State));
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(2);
        nextValue.Should().Be(2);
    }

    [Fact]
    public async Task ReplacementCleanupThatStartsNewReloadSuppressesSupersededNotification()
    {
        using var hub = new MessageHub();
        AsyncResourceVM<int>? vm = null;
        Task reentrantReload = Task.CompletedTask;
        var reentered = false;
        var nextValue = 0;
        var changes = new List<string?>();
        vm = Create(
            hub,
            _ => Task.FromResult(++nextValue),
            AsyncResourceRetention.RetainPrevious,
            value =>
            {
                if (value == 1 && !reentered)
                {
                    reentered = true;
                    reentrantReload = vm!.ReloadAsync();
                }
            });
        vm.PropertyChanged += (_, e) => changes.Add(e.PropertyName);

        await vm.LoadAsync();
        changes.Clear();
        await vm.ReloadAsync();
        await reentrantReload;

        changes.Should().Equal(nameof(vm.State), nameof(vm.State), nameof(vm.State));
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(3);
        nextValue.Should().Be(3);
    }

    [Fact, Trait("Conformance", "ARES-008")]
    public async Task ARES_008_Latest_Start_Wins()
    {
        using var hub = new MessageHub();
        var first = NewSource<int>();
        var second = NewSource<int>();
        var tokens = new List<CancellationToken>();
        var attempt = 0;
        var vm = Create(hub, token =>
        {
            tokens.Add(token);
            return ++attempt == 1 ? first.Task : second.Task;
        });

        var older = vm.LoadAsync();
        var newer = vm.ReloadAsync();
        tokens[0].IsCancellationRequested.Should().BeTrue();
        first.SetResult(1);
        await older;
        vm.State.Status.Should().Be(AsyncResourceStatus.Loading);
        second.SetResult(2);
        await newer;
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        vm.State.Value.Should().Be(2);
    }

    [Fact, Trait("Conformance", "ARES-009")]
    public async Task ARES_009_Stale_Success_Cleans_Without_Notification()
    {
        using var hub = new MessageHub();
        var first = NewSource<int>();
        var second = NewSource<int>();
        var cleaned = new List<int>();
        var changes = new List<PropertyChangedEventArgs>();
        var attempt = 0;
        var vm = Create(hub, _ => ++attempt == 1 ? first.Task : second.Task, cleanup: cleaned.Add);
        vm.PropertyChanged += (_, e) => changes.Add(e);

        var older = vm.LoadAsync();
        var newer = vm.ReloadAsync();
        second.SetResult(2);
        await newer;
        var count = changes.Count;
        first.SetResult(1);
        await WaitUntilAsync(() => cleaned.Count == 1);

        cleaned.Should().Equal(1);
        changes.Should().HaveCount(count);
        vm.State.Value.Should().Be(2);
        await older;
    }

    [Fact, Trait("Conformance", "ARES-010")]
    public async Task ARES_010_Replacement_And_Disposal_Cleanup_Once()
    {
        using var hub = new MessageHub();
        var value = 0;
        var cleaned = new List<int>();
        var vm = Create(hub, _ => Task.FromResult(++value),
            AsyncResourceRetention.RetainPrevious, cleaned.Add);

        await vm.LoadAsync();
        await vm.ReloadAsync();
        cleaned.Should().Equal(1);
        vm.Dispose();
        vm.Dispose();
        cleaned.Should().Equal(1, 2);
    }

    [Fact, Trait("Conformance", "ARES-010")]
    public async Task ARES_010_Disposal_Cleans_Accepted_Value_When_Command_Observer_Throws()
    {
        using var hub = new MessageHub();
        var cleaned = new List<int>();
        var vm = Create(hub, _ => Task.FromResult(7), cleanup: cleaned.Add);
        await vm.LoadAsync();
        vm.CancelCommand.CanExecuteChanged += (_, _) =>
            throw new InvalidOperationException("terminal observer");

        Action dispose = vm.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        cleaned.Should().ContainSingle("accepted values require cleanup even when observers fail")
            .Which.Should().Be(7);
    }

    [Fact, Trait("Conformance", "ARES-011")]
    public async Task ARES_011_Disposal_Cancels_And_Late_Completion_Is_Inert()
    {
        using var hub = new MessageHub();
        var late = NewSource<int>();
        var cleaned = new List<int>();
        var changes = 0;
        var calls = 0;
        CancellationToken token = default;
        var vm = Create(hub, currentToken =>
        {
            calls++;
            token = currentToken;
            return late.Task;
        }, cleanup: cleaned.Add);
        vm.PropertyChanged += (_, _) => changes++;

        var load = vm.LoadAsync();
        vm.Dispose();
        vm.Dispose();
        var count = changes;
        token.IsCancellationRequested.Should().BeTrue();
        vm.LoadCommand.CanExecute(null).Should().BeFalse();
        vm.ReloadCommand.CanExecute(null).Should().BeFalse();
        vm.CancelCommand.CanExecute(null).Should().BeFalse();
        late.SetResult(9);
        await WaitUntilAsync(() => cleaned.Count == 1);
        await vm.LoadAsync();
        await vm.ReloadAsync();
        vm.Cancel();

        cleaned.Should().Equal(9);
        changes.Should().Be(count);
        calls.Should().Be(1);
        await load;
    }

    private static AsyncResourceVM<int> Create(
        IMessageHub hub,
        Func<CancellationToken, Task<int>> loader,
        AsyncResourceRetention retention = AsyncResourceRetention.DiscardPrevious,
        Action<int>? cleanup = null) =>
        new("resource", loader, hub, new TestDispatcher(), retention: retention,
            cleanupValue: cleanup);

    private static TaskCompletionSource<T> NewSource<T>() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static TaskCompletionSource NewSource() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static CancellationTokenSource CurrentCancellation(AsyncResourceVM<int> vm)
    {
        var operation = typeof(AsyncResourceVM<int>)
            .GetField("_operation", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(vm)!;
        return (CancellationTokenSource)operation.GetType()
            .GetProperty("Cancellation", BindingFlags.Instance | BindingFlags.Public)!
            .GetValue(operation)!;
    }

    private static async Task WaitUntilAsync(Func<bool> predicate)
    {
        for (var i = 0; i < 1000 && !predicate(); i++)
            await Task.Delay(1);
        predicate().Should().BeTrue("the asynchronous condition should settle");
    }
}
