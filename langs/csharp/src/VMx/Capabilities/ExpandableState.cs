using System.Reactive.Linq;
using System.Reactive.Subjects;

namespace VMx.Capabilities;

/// <summary>
/// Composition-friendly helper that bundles <see cref="IExpandable"/>,
/// <see cref="ICollapsible"/>, and <see cref="IExpansionTogglable"/> with a
/// change observable. See spec/05-component-vm.md §IExpandable integration
/// and ADR-0015.
/// </summary>
public sealed class ExpandableState : IExpandable, ICollapsible, IExpansionTogglable, IDisposable
{
    private readonly Subject<bool> _changes = new();
    private bool _isExpanded;
    private bool _disposed;

    /// <summary>Creates a new <see cref="ExpandableState"/> (initial: collapsed).</summary>
    public ExpandableState(bool initiallyExpanded = false)
    {
        _isExpanded = initiallyExpanded;
    }

    /// <inheritdoc/>
    public bool IsExpanded => _isExpanded;

    /// <summary>Emits the new value every time <see cref="IsExpanded"/> changes.</summary>
    public IObservable<bool> IsExpandedChanged => _changes.AsObservable();

    /// <inheritdoc/>
    public bool CanExpand() => !_isExpanded;

    /// <inheritdoc/>
    public void Expand()
    {
        if (_disposed) return;
        if (_isExpanded) return;
        _isExpanded = true;
        _changes.OnNext(true);
    }

    /// <inheritdoc/>
    public bool CanCollapse() => _isExpanded;

    /// <inheritdoc/>
    public void Collapse()
    {
        if (_disposed) return;
        if (!_isExpanded) return;
        _isExpanded = false;
        _changes.OnNext(false);
    }

    /// <inheritdoc/>
    public bool CanToggleExpansion() => true;

    /// <inheritdoc/>
    public void ToggleExpansion()
    {
        if (_isExpanded) Collapse(); else Expand();
    }

    /// <summary>Completes the <see cref="IsExpandedChanged"/> observable.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _changes.OnCompleted();
        _changes.Dispose();
    }
}
