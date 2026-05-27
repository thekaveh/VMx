namespace VMx.Capabilities;

// Capability interface from spec/14-capabilities.md §Search.

/// <summary>Capability: the implementer accepts a search term and exposes a search action.</summary>
public interface ISearchable
{
    /// <summary>The current search term.</summary>
    string SearchTerm { get; set; }

    /// <summary>Returns true when <see cref="Search"/> is valid to call.</summary>
    bool CanSearch();

    /// <summary>Applies the current <see cref="SearchTerm"/>.</summary>
    void Search();
}
