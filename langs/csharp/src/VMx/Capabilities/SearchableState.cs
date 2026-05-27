using System.Reactive;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Reactive.Subjects;

namespace VMx.Capabilities;

/// <summary>
/// Composition-friendly helper implementing <see cref="ISearchable"/> with
/// a debounced filter. See spec/06-composite-vm.md §Search / filter and
/// ADR-0014.
/// </summary>
public sealed class SearchableState<TItem> : ISearchable, IDisposable
{
    private readonly Func<IEnumerable<TItem>> _itemsSource;
    private readonly Func<TItem, string, bool> _predicate;
    private readonly BehaviorSubject<string> _termSubject = new("");
    private readonly BehaviorSubject<IReadOnlyList<TItem>> _filteredSubject;
    private readonly Subject<Unit> _forceSearchSubject = new();
    private readonly IDisposable _subscription;
    private bool _disposed;

    /// <summary>Creates a new <see cref="SearchableState{TItem}"/>.</summary>
    /// <param name="items">Source of items to filter.</param>
    /// <param name="predicate">User-supplied filter: <c>(item, term) =&gt; bool</c>.</param>
    /// <param name="debounce">Search-term debounce (default 1s; pass <see cref="TimeSpan.Zero"/> to disable).</param>
    /// <param name="scheduler">Optional scheduler for the debounce (default: immediate).</param>
    public SearchableState(
        Func<IEnumerable<TItem>> items,
        Func<TItem, string, bool> predicate,
        TimeSpan? debounce = null,
        IScheduler? scheduler = null)
    {
        _itemsSource = items;
        _predicate = predicate;
        var actualDebounce = debounce ?? TimeSpan.FromSeconds(1);
        var actualScheduler = scheduler ?? ImmediateScheduler.Instance;

        _filteredSubject = new BehaviorSubject<IReadOnlyList<TItem>>(ApplyFilter(""));

        var debouncedTerm = actualDebounce > TimeSpan.Zero
            ? _termSubject.Throttle(actualDebounce, actualScheduler)
            : _termSubject.AsObservable();

        var forceFilter = _forceSearchSubject.Select(_ => _termSubject.Value);
        var recomputeStream = debouncedTerm.Merge(forceFilter);

        _subscription = recomputeStream.Subscribe(term =>
        {
            _filteredSubject.OnNext(ApplyFilter(term));
        });
    }

    /// <inheritdoc/>
    public string SearchTerm
    {
        get => _termSubject.Value;
        set => _termSubject.OnNext(value);
    }

    /// <summary>Observable of the current filtered snapshot.</summary>
    public IObservable<IReadOnlyList<TItem>> Filtered => _filteredSubject;

    /// <inheritdoc/>
    public bool CanSearch() => _itemsSource().Any();

    /// <inheritdoc/>
    public void Search() => _forceSearchSubject.OnNext(Unit.Default);

    private List<TItem> ApplyFilter(string term)
    {
        var list = new List<TItem>();
        foreach (var item in _itemsSource())
            if (_predicate(item, term))
                list.Add(item);
        return list;
    }

    /// <summary>Completes <see cref="Filtered"/> and tears down internal subscriptions.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subscription.Dispose();
        _termSubject.OnCompleted();
        _termSubject.Dispose();
        _filteredSubject.OnCompleted();
        _filteredSubject.Dispose();
        _forceSearchSubject.OnCompleted();
        _forceSearchSubject.Dispose();
    }
}
