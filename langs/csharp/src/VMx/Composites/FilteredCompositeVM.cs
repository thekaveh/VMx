using System.Collections.Specialized;
using VMx.Components;

namespace VMx.Composites;

/// <summary>Cursor behavior when the current item is filtered out.</summary>
public enum FilteredCursorPolicy
{
    /// <summary>Move current to the first visible item, or null when none are visible.</summary>
    SnapToFirst,

    /// <summary>Clear current to null.</summary>
    Clear,

    /// <summary>Keep current only while it remains visible; otherwise clear it.</summary>
    PreserveIfVisible,
}

/// <summary>Maintains a filtered visible projection over a source composite.</summary>
public class FilteredCompositeVM<VM> : IDisposable
    where VM : class, IComponentVM
{
    private readonly Func<VM, bool> _defaultPredicate;
    private readonly FilteredCursorPolicy _cursorPolicy;
    private readonly List<VM> _visible = [];
    private Func<VM, bool> _predicate;
    private VM? _current;
    private bool _disposed;

    /// <summary>Create a filtered projection.</summary>
    public FilteredCompositeVM(
        CompositeVMBase<VM> source,
        Func<VM, bool>? predicate = null,
        FilteredCursorPolicy cursorPolicy = FilteredCursorPolicy.SnapToFirst)
        : this(source, predicate, cursorPolicy, deferInitialRecompute: false)
    {
    }

    /// <summary>Constructor variant used by subclasses that need to initialize first.</summary>
    protected FilteredCompositeVM(
        CompositeVMBase<VM> source,
        Func<VM, bool>? predicate,
        FilteredCursorPolicy cursorPolicy,
        bool deferInitialRecompute)
    {
        Source = source ?? throw new ArgumentNullException(nameof(source));
        _defaultPredicate = _ => true;
        _predicate = predicate ?? _defaultPredicate;
        _cursorPolicy = cursorPolicy;
        Source.CollectionChanged += OnSourceCollectionChanged;
        if (!deferInitialRecompute) Recompute();
    }

    /// <summary>The source composite.</summary>
    protected CompositeVMBase<VM> Source { get; }

    /// <summary>The visible projection snapshot.</summary>
    public IReadOnlyList<VM> Visible => _visible.ToArray();

    /// <summary>Number of visible items.</summary>
    public int VisibleCount => _visible.Count;

    /// <summary>Current item in the visible domain.</summary>
    public VM? Current
    {
        get => _current;
        set => SetCurrent(value);
    }

    /// <summary>Fires whenever projection or current state changes.</summary>
    public event EventHandler? Changed;

    /// <summary>Replace the predicate and recompute the projection.</summary>
    public void SetPredicate(Func<VM, bool> predicate)
    {
        _predicate = predicate ?? throw new ArgumentNullException(nameof(predicate));
        Recompute();
    }

    /// <summary>Set current to null or a currently visible item.</summary>
    public void SetCurrent(VM? item)
    {
        if (item is not null && VisibleIndexOf(item) < 0)
            throw new InvalidOperationException("Current must be null or a visible item.");
        if (ReferenceEquals(_current, item)) return;
        _current = item;
        Changed?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>Move to the next visible item, clamped at the last item.</summary>
    public void MoveToNextVisible()
    {
        if (_visible.Count == 0)
        {
            SetCurrent(null);
            return;
        }
        if (_current is null)
        {
            SetCurrent(_visible[0]);
            return;
        }
        var index = VisibleIndexOf(_current);
        if (index < 0)
        {
            SetCurrent(_visible[0]);
            return;
        }
        SetCurrent(_visible[Math.Min(index + 1, _visible.Count - 1)]);
    }

    /// <summary>Move to the previous visible item, clamped at the first item.</summary>
    public void MoveToPreviousVisible()
    {
        if (_visible.Count == 0)
        {
            SetCurrent(null);
            return;
        }
        if (_current is null)
        {
            SetCurrent(_visible[0]);
            return;
        }
        var index = VisibleIndexOf(_current);
        if (index < 0)
        {
            SetCurrent(_visible[0]);
            return;
        }
        SetCurrent(_visible[Math.Max(index - 1, 0)]);
    }

    /// <summary>Computes the ordered visible projection.</summary>
    protected virtual IReadOnlyList<VM> OrderedVisible() =>
        Source.Where(_predicate).ToArray();

    /// <summary>Recompute projection and reconcile current.</summary>
    protected void Recompute()
    {
        _visible.Clear();
        _visible.AddRange(OrderedVisible());
        if (_current is not null && VisibleIndexOf(_current) < 0)
        {
            _current = _cursorPolicy == FilteredCursorPolicy.SnapToFirst
                ? _visible.FirstOrDefault()
                : null;
        }
        else if (_current is null && _cursorPolicy == FilteredCursorPolicy.SnapToFirst)
        {
            _current = _visible.FirstOrDefault();
        }
        Changed?.Invoke(this, EventArgs.Empty);
    }

    private int VisibleIndexOf(VM item) =>
        _visible.FindIndex(candidate => ReferenceEquals(candidate, item));

    private void OnSourceCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) => Recompute();

    /// <inheritdoc/>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Source.CollectionChanged -= OnSourceCollectionChanged;
    }
}
