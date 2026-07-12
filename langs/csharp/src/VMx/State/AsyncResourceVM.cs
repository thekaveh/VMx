using VMx.Commands;
using VMx.Components;
using VMx.Services;

namespace VMx.State;

/// <summary>The discriminant for <see cref="AsyncResourceState{T}"/>.</summary>
public enum AsyncResourceStatus
{
    /// <summary>No load has produced a current value or error.</summary>
    Idle,
    /// <summary>A loader is currently in flight.</summary>
    Loading,
    /// <summary>The current loader completed with an accepted value.</summary>
    Ready,
    /// <summary>The current loader completed with a captured failure.</summary>
    Error,
}

/// <summary>Controls whether a previously accepted value remains visible during reload.</summary>
public enum AsyncResourceRetention
{
    /// <summary>Relinquish an accepted value when reload begins.</summary>
    DiscardPrevious,
    /// <summary>Keep an accepted value visible while reload runs or fails.</summary>
    RetainPrevious,
}

/// <summary>Immutable, validated snapshot of one asynchronous resource.</summary>
public sealed class AsyncResourceState<T>
{
    private AsyncResourceState(
        AsyncResourceStatus status,
        bool hasValue,
        T? value,
        Exception? error)
    {
        Status = status;
        HasValue = hasValue;
        Value = value;
        Error = error;
    }

    /// <summary>Gets the state discriminant.</summary>
    public AsyncResourceStatus Status { get; }
    /// <summary>Gets whether this snapshot carries an accepted value.</summary>
    public bool HasValue { get; }
    /// <summary>Gets the accepted value when <see cref="HasValue"/> is true.</summary>
    public T? Value { get; }
    /// <summary>Gets the current loader failure in <see cref="AsyncResourceStatus.Error"/>.</summary>
    public Exception? Error { get; }

    internal static AsyncResourceState<T> Idle() =>
        new(AsyncResourceStatus.Idle, false, default, null);

    internal static AsyncResourceState<T> Loading() =>
        new(AsyncResourceStatus.Loading, false, default, null);

    internal static AsyncResourceState<T> Loading(T value) =>
        new(AsyncResourceStatus.Loading, true, value, null);

    internal static AsyncResourceState<T> Ready(T value) =>
        new(AsyncResourceStatus.Ready, true, value, null);

    internal static AsyncResourceState<T> Failed(Exception error) =>
        new(AsyncResourceStatus.Error, false, default, error);

    internal static AsyncResourceState<T> Failed(T value, Exception error) =>
        new(AsyncResourceStatus.Error, true, value, error);
}

/// <summary>
/// Component viewmodel for one cancellable asynchronously acquired presentation value.
/// See spec/23-async-resource-vm.md and ADR-0100.
/// </summary>
public sealed class AsyncResourceVM<T> : ComponentVMBase
{
    private readonly object _resourceGate = new();
    private readonly Func<CancellationToken, Task<T>> _loader;
    private readonly AsyncResourceRetention _retention;
    private readonly Action<T>? _cleanupValue;
    private AsyncResourceState<T> _state = AsyncResourceState<T>.Idle();
    private AsyncResourceState<T> _stableState = AsyncResourceState<T>.Idle();
    private ResourceOperation? _operation;
    private long _operationIdentity;
    private bool _resourceDisposed;

    /// <summary>Creates an async resource VM with explicit services and loader.</summary>
    public AsyncResourceVM(
        string name,
        Func<CancellationToken, Task<T>> loader,
        IMessageHub hub,
        IDispatcher dispatcher,
        string hint = "",
        AsyncResourceRetention retention = AsyncResourceRetention.DiscardPrevious,
        Action<T>? cleanupValue = null)
        : base(name, hint, hub, dispatcher, null, null)
    {
        _loader = loader ?? throw new ArgumentNullException(nameof(loader));
        _retention = retention;
        _cleanupValue = cleanupValue;

        LoadCommand = AsyncRelayCommand.Builder()
            .Task(LoadAsync)
            .Predicate(CanLoad)
            .Build();
        ReloadCommand = AsyncRelayCommand.Builder()
            .Task(ReloadAsync)
            .Predicate(CanReload)
            .Build();
        CancelCommand = RelayCommand.Builder()
            .Task(Cancel)
            .Predicate(CanCancel)
            .Build();
    }

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Gets the current immutable presentation snapshot.</summary>
    public AsyncResourceState<T> State
    {
        get
        {
            lock (_resourceGate) return _state;
        }
    }

    /// <summary>Gets the initial-load command.</summary>
    public AsyncRelayCommand LoadCommand { get; }
    /// <summary>Gets the retry/refresh command.</summary>
    public AsyncRelayCommand ReloadCommand { get; }
    /// <summary>Gets the active-operation cancellation command.</summary>
    public RelayCommand CancelCommand { get; }

    /// <summary>Starts the initial load when state is idle.</summary>
    public Task LoadAsync(CancellationToken cancellationToken = default) =>
        StartAsync(StartIntent.Load, cancellationToken);

    /// <summary>Starts or supersedes a reload when state is non-idle.</summary>
    public Task ReloadAsync(CancellationToken cancellationToken = default) =>
        StartAsync(StartIntent.Reload, cancellationToken);

    /// <summary>Cancels the current operation and restores its stable baseline.</summary>
    public void Cancel()
    {
        ResourceOperation? operation;
        lock (_resourceGate)
        {
            if (!CanCancelUnsafe() || _operation is null) return;
            operation = _operation;
        }

        operation.Cancel();
        LoadCommand.Cancel();
        ReloadCommand.Cancel();
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        ResourceOperation? operation;
        bool hasAccepted;
        T? accepted;
        lock (_resourceGate)
        {
            if (_resourceDisposed) return;
            _resourceDisposed = true;
            unchecked { _operationIdentity++; }
            operation = _operation;
            _operation = null;
            hasAccepted = TryGetValue(_stableState, out accepted);
            _stableState = AsyncResourceState<T>.Idle();
        }

        operation?.Cancel();
        LoadCommand.Cancel();
        ReloadCommand.Cancel();
        LoadCommand.Dispose();
        ReloadCommand.Dispose();
        CancelCommand.Dispose();
        if (hasAccepted) Cleanup(accepted!);
    }

    private bool CanLoad()
    {
        lock (_resourceGate)
            return !_resourceDisposed && _state.Status == AsyncResourceStatus.Idle;
    }

    private bool CanReload()
    {
        lock (_resourceGate)
            return !_resourceDisposed && _state.Status != AsyncResourceStatus.Idle;
    }

    private bool CanCancel()
    {
        lock (_resourceGate) return CanCancelUnsafe();
    }

    private bool CanCancelUnsafe() =>
        !_resourceDisposed && _state.Status == AsyncResourceStatus.Loading;

    private async Task StartAsync(StartIntent intent, CancellationToken externalToken)
    {
        ResourceOperation operation;
        ResourceOperation? previousOperation;
        bool cleanupDiscarded;
        T? discarded;

        lock (_resourceGate)
        {
            if (_resourceDisposed) return;
            if (externalToken.IsCancellationRequested) return;
            if (intent == StartIntent.Load && _state.Status != AsyncResourceStatus.Idle) return;
            if (intent == StartIntent.Reload && _state.Status == AsyncResourceStatus.Idle) return;

            previousOperation = _operation;
            unchecked { _operationIdentity++; }

            cleanupDiscarded = false;
            discarded = default;
            if (_retention == AsyncResourceRetention.DiscardPrevious &&
                TryGetValue(_stableState, out discarded))
            {
                cleanupDiscarded = true;
                _stableState = AsyncResourceState<T>.Idle();
            }

            var baseline = _stableState;
            var cts = CancellationTokenSource.CreateLinkedTokenSource(externalToken);
            operation = new ResourceOperation(_operationIdentity, baseline, cts);
            _operation = operation;

            _state = _retention == AsyncResourceRetention.RetainPrevious &&
                     TryGetValue(baseline, out var retained)
                ? AsyncResourceState<T>.Loading(retained!)
                : AsyncResourceState<T>.Loading();
        }

        previousOperation?.Cancel();
        if (cleanupDiscarded) Cleanup(discarded!);
        NotifyStateChanged();
        // Register only after Loading has been published. Registration invokes
        // synchronously if cancellation raced admission, so the handler then
        // publishes the restored baseline in the correct visible order.
        operation.Registration = operation.Cancellation.Token.Register(
            () => HandleCancellation(operation));

        if (operation.Cancelled.Task.IsCompleted)
        {
            operation.Dispose();
            return;
        }

        Task<T> loaderTask;
        try
        {
            loaderTask = _loader(operation.Cancellation.Token);
        }
        catch (Exception error)
        {
            loaderTask = Task.FromException<T>(error);
        }
        operation.LoaderTask = loaderTask;

        var completed = await Task.WhenAny(loaderTask, operation.Cancelled.Task)
            .ConfigureAwait(false);
        if (ReferenceEquals(completed, operation.Cancelled.Task))
        {
            ObserveLate(operation, loaderTask);
            return;
        }

        T value;
        try
        {
            value = await loaderTask.ConfigureAwait(false);
        }
        catch (Exception error)
        {
            if (!IsOperationCurrent(operation))
            {
                operation.Dispose();
                return;
            }
            if (error is OperationCanceledException && operation.Cancellation.IsCancellationRequested)
            {
                HandleCancellation(operation);
                operation.Dispose();
                return;
            }
            CompleteFailure(operation, error);
            operation.Dispose();
            return;
        }

        if (!CompleteSuccess(operation, value)) Cleanup(value);
        operation.Dispose();
    }

    private void HandleCancellation(ResourceOperation operation)
    {
        var notify = false;
        lock (_resourceGate)
        {
            operation.Cancelled.TrySetResult(true);
            if (IsCurrentUnsafe(operation))
            {
                unchecked { _operationIdentity++; }
                _operation = null;
                _state = operation.Baseline;
                notify = true;
            }
        }
        if (notify) NotifyStateChanged();
    }

    private bool CompleteSuccess(ResourceOperation operation, T value)
    {
        bool hasPrevious;
        T? previous;
        lock (_resourceGate)
        {
            if (!IsCurrentUnsafe(operation)) return false;
            _operation = null;
            hasPrevious = TryGetValue(_stableState, out previous);
            _stableState = AsyncResourceState<T>.Ready(value);
            _state = _stableState;
        }
        if (hasPrevious) Cleanup(previous!);
        NotifyStateChanged();
        return true;
    }

    private void CompleteFailure(ResourceOperation operation, Exception error)
    {
        lock (_resourceGate)
        {
            if (!IsCurrentUnsafe(operation)) return;
            _operation = null;
            _stableState = _retention == AsyncResourceRetention.RetainPrevious &&
                           TryGetValue(_stableState, out var previous)
                ? AsyncResourceState<T>.Failed(previous!, error)
                : AsyncResourceState<T>.Failed(error);
            _state = _stableState;
        }
        NotifyStateChanged();
    }

    private bool IsOperationCurrent(ResourceOperation operation)
    {
        lock (_resourceGate) return IsCurrentUnsafe(operation);
    }

    private bool IsCurrentUnsafe(ResourceOperation operation) =>
        !_resourceDisposed && _operationIdentity == operation.Identity &&
        ReferenceEquals(_operation, operation);

    private void ObserveLate(ResourceOperation operation, Task<T> loaderTask) =>
        _ = loaderTask.ContinueWith(
            task =>
            {
                try
                {
                    if (task.Status == TaskStatus.RanToCompletion) Cleanup(task.Result);
                    _ = task.Exception;
                }
                finally
                {
                    operation.Dispose();
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);

    private void NotifyStateChanged()
    {
        NotifyPropertyChanged(nameof(State));
        LoadCommand.RaiseCanExecuteChanged();
        ReloadCommand.RaiseCanExecuteChanged();
        CancelCommand.RaiseCanExecuteChanged();
    }

    private void Cleanup(T value)
    {
        try { _cleanupValue?.Invoke(value); }
        catch { /* best-effort ownership cleanup, matching ComponentVMBase.Own */ }
    }

    private static bool TryGetValue(AsyncResourceState<T> state, out T? value)
    {
        value = state.Value;
        return state.HasValue;
    }

    private enum StartIntent
    {
        Load,
        Reload,
    }

    private sealed class ResourceOperation : IDisposable
    {
        public ResourceOperation(
            long identity,
            AsyncResourceState<T> baseline,
            CancellationTokenSource cancellation)
        {
            Identity = identity;
            Baseline = baseline;
            Cancellation = cancellation;
            Cancelled = new TaskCompletionSource<bool>(
                TaskCreationOptions.RunContinuationsAsynchronously);
        }

        public long Identity { get; }
        public AsyncResourceState<T> Baseline { get; }
        public CancellationTokenSource Cancellation { get; }
        public TaskCompletionSource<bool> Cancelled { get; }
        public CancellationTokenRegistration Registration { get; set; }
        public Task<T>? LoaderTask { get; set; }

        public void Cancel()
        {
            try { Cancellation.Cancel(); }
            catch (ObjectDisposedException) { }
            // The token callback restores the stable baseline before the
            // prompt-return sentinel can release StartAsync. Otherwise a fast
            // loader cancellation can dispose this registration first.
            Cancelled.TrySetResult(true);
        }

        public void Dispose()
        {
            Registration.Dispose();
            Cancellation.Dispose();
        }
    }
}
