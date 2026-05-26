namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §Expansion.

/// <summary>Capability: the implementer can be expanded (e.g., a tree node).</summary>
public interface IExpandable
{
    /// <summary>Current expansion state.</summary>
    bool IsExpanded { get; }

    /// <summary>Returns true when <see cref="Expand"/> is valid to call.</summary>
    bool CanExpand();

    /// <summary>Performs the expand action.</summary>
    void Expand();
}

/// <summary>Capability: the implementer can be collapsed.</summary>
public interface ICollapsible
{
    /// <summary>Returns true when <see cref="Collapse"/> is valid to call.</summary>
    bool CanCollapse();

    /// <summary>Performs the collapse action.</summary>
    void Collapse();
}

/// <summary>Capability: the implementer's expansion state can be toggled.</summary>
public interface IExpansionTogglable
{
    /// <summary>Returns true when <see cref="ToggleExpansion"/> is valid to call.</summary>
    bool CanToggleExpansion();

    /// <summary>Toggles the implementer's expansion state.</summary>
    void ToggleExpansion();
}
