namespace VMx.Lifecycle;

/// <summary>
/// Thrown when a lifecycle operation is invoked on a VM whose current
/// <see cref="ConstructionStatus"/> forbids that operation.
/// See spec/02-lifecycle.md §Invariants 3 and 5.
/// </summary>
public sealed class StatusTransitionException : InvalidOperationException
{
    /// <summary>The status the VM was in when the operation was attempted.</summary>
    public ConstructionStatus CurrentStatus { get; }

    /// <summary>The name of the operation that was attempted (e.g., "construct").</summary>
    public string AttemptedOperation { get; }

    /// <summary>Initializes a new instance of <see cref="StatusTransitionException"/>.</summary>
    public StatusTransitionException(ConstructionStatus currentStatus, string attemptedOperation)
        : base($"Cannot {attemptedOperation} from state {currentStatus}.")
    {
        CurrentStatus = currentStatus;
        AttemptedOperation = attemptedOperation;
    }
}
