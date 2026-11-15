namespace VMx.Dialogs;

/// <summary>
/// Small base implementation for result-bearing VM-backed modals.
/// </summary>
/// <typeparam name="T">Modal result type.</typeparam>
public sealed class ModalVM<T> : IModalVM<T>
{
    private readonly TaskCompletionSource<T> _completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    // Guards the claim: the first Dismiss to take the lock sets _result and _isDismissed.
    private readonly object _gate = new();
    private bool _isDismissed;
    private T? _result;

    /// <summary>Creates a modal with the result used for cancellation/disposal.</summary>
    public ModalVM(T cancellationResult)
    {
        CancellationResult = cancellationResult;
    }

    /// <inheritdoc/>
    public T CancellationResult { get; }

    /// <inheritdoc/>
    public T? Result
    {
        get { lock (_gate) return _result; }
    }

    /// <inheritdoc/>
    public bool IsDismissed
    {
        get { lock (_gate) return _isDismissed; }
    }

    /// <inheritdoc/>
    public Task<T> Completion => _completion.Task;

    /// <inheritdoc/>
    public void Dismiss(T result)
    {
        lock (_gate)
        {
            if (_isDismissed) return;
            _result = result;
            _isDismissed = true;
        }
        _completion.TrySetResult(result);
    }

    /// <summary>Cancel the modal with <see cref="CancellationResult"/>. Idempotent.</summary>
    public void Dispose()
    {
        Dismiss(CancellationResult);
    }
}
