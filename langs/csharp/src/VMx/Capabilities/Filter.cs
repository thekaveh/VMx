namespace VMx.Capabilities;

// Capability interface from spec/14-capabilities.md §Filter and ADR-0022.
// Opt-in; not implemented by default by any core VM type.

/// <summary>Capability: the implementer accepts a typed predicate and exposes a filter action.</summary>
public interface IFilterable<TItem>
{
    /// <summary>The current filter predicate; <see langword="null"/> means no filter is applied.</summary>
    System.Predicate<TItem>? Filter { get; set; }

    /// <summary>Returns true when filtering is currently allowed.</summary>
    bool CanFilter();
}
