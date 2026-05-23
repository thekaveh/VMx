namespace VMx.Lifecycle;

/// <summary>
/// The five states of a VMx viewmodel's lifecycle state machine.
/// See spec/02-lifecycle.md for the full transition contract.
/// </summary>
public enum ConstructionStatus
{
    /// <summary>Terminal state. Once entered, cannot leave.</summary>
    Disposed = 0,

    /// <summary>Transient state during destruct().</summary>
    Destructing = 1,

    /// <summary>Initial state of a freshly built VM.</summary>
    Destructed = 2,

    /// <summary>Transient state during construct().</summary>
    Constructing = 3,

    /// <summary>Ready-to-use state.</summary>
    Constructed = 4,
}
