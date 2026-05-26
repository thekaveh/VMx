namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §Container-current.

/// <summary>Capability: the implementer can delete its current selection.</summary>
public interface ICurrentDeletable
{
    /// <summary>Returns true when <see cref="DeleteCurrent"/> is valid to call.</summary>
    bool CanDeleteCurrent();

    /// <summary>Deletes the current selection.</summary>
    void DeleteCurrent();
}

/// <summary>Capability: the implementer can update its current selection.</summary>
public interface ICurrentUpdatable
{
    /// <summary>Returns true when <see cref="UpdateCurrent"/> is valid to call.</summary>
    bool CanUpdateCurrent();

    /// <summary>Updates the current selection.</summary>
    void UpdateCurrent();
}
