namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §Lifecycle.
// These three are baseline: every VM in the core library trivially satisfies
// them. See spec rule 2 in chapter 14 — the only capabilities the base VM
// types declare. Async variants follow ADR-0008 (C#-specific affordance).

/// <summary>Capability: the implementer has a construct lifecycle operation.</summary>
public interface IConstructable
{
    /// <summary>Returns true when <see cref="Construct"/> is valid to call.</summary>
    bool CanConstruct();

    /// <summary>Performs the construct operation.</summary>
    void Construct();

    /// <summary>
    /// Performs the construct operation asynchronously. Hook and deferred-child
    /// failures fault the task after transactional rollback.
    /// </summary>
    Task ConstructAsync();
}

/// <summary>Capability: the implementer has a destruct lifecycle operation.</summary>
public interface IDestructable
{
    /// <summary>Returns true when <see cref="Destruct"/> is valid to call.</summary>
    bool CanDestruct();

    /// <summary>Performs the destruct operation.</summary>
    void Destruct();

    /// <summary>
    /// Performs the destruct operation asynchronously. Hook and deferred-child
    /// failures fault the task after transactional rollback.
    /// </summary>
    Task DestructAsync();
}

/// <summary>Capability: the implementer has a reconstruct lifecycle operation.</summary>
public interface IReconstructable
{
    /// <summary>Returns true when <see cref="Reconstruct"/> is valid to call.</summary>
    bool CanReconstruct();

    /// <summary>Performs the reconstruct operation.</summary>
    void Reconstruct();

    /// <summary>
    /// Performs the reconstruct operation asynchronously. Hook and deferred-child
    /// failures fault the task after transactional rollback.
    /// </summary>
    Task ReconstructAsync();
}
