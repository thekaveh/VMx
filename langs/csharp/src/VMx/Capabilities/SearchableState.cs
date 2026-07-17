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
    /// <param name="scheduler">Optional scheduler for the debounce (default:
    /// <see cref="DefaultScheduler.Instance"/> — required for real time
    /// delays without blocking the calling thread. Pass <see cref="ImmediateScheduler.Instance"/>
    /// or a <c>TestScheduler</c> in tests that need synchronous / virtual-time
    /// behaviour).</param>
    /// <param name="sourceChanged">Optional payload-free invalidation signal.
    /// Each value immediately re-reads <paramref name="items"/> with the current
    /// term. Completion or failure stops automatic source refresh without
    /// terminating <see cref="Filtered"/>.</param>
    public SearchableState(
        Func<IEnumerable<TItem>> items,
        Func<TItem, string, bool> predicate,
        TimeSpan? debounce = null,
        IScheduler? scheduler = null,
        IObservable<Unit>? sourceChanged = null)
    {
        _itemsSource = items;
        _predicate = predicate;
        var actualDebounce = debounce ?? TimeSpan.FromSeconds(1);
        var actualScheduler = scheduler ?? DefaultScheduler.Instance;

        _filteredSubject = new BehaviorSubject<IReadOnlyList<TItem>>(ApplyFilter(""));

        var debouncedTerm = actualDebounce > TimeSpan.Zero
            ? _termSubject.Throttle(actualDebounce, actualScheduler)
            : _termSubject.AsObservable();

        var forceFilter = _forceSearchSubject.Select(_ => _termSubject.Value);
        var sourceFilter = sourceChanged is null
            ? Observable.Empty<string>()
            : sourceChanged
                .Select(_ => _termSubject.Value)
                .Catch<string, Exception>(_ => Observable.Empty<string>());
        var recomputeStream = debouncedTerm.Merge(forceFilter).Merge(sourceFilter);

        _subscription = recomputeStream.Subscribe(term =>
        {
            // The debounce runs on DefaultScheduler; Dispose() can dispose
            // _filteredSubject while a recompute is between ApplyFilter and
            // OnNext (subscription disposal does not wait for an in-flight
            // callback on another thread). Post-dispose Subject.OnNext throws
            // ObjectDisposedException, so drop that fault — a disposed searchable
            // has no observers to notify (mirrors AsyncRelayCommand.EmitError).
            try
            {
                _filteredSubject.OnNext(ApplyFilter(term));
            }
            catch (ObjectDisposedException)
            {
            }
        });

        // Close the initial snapshot/attach gap. No caller can observe the
        // constructor-only first value, while a signal arriving after the
        // subscription is installed is handled by the merged stream.
        if (sourceChanged is not null)
            _filteredSubject.OnNext(ApplyFilter(_termSubject.Value));
    }

    /// <inheritdoc/>
    public string SearchTerm
    {
        get => _disposed ? string.Empty : _termSubject.Value;
        set
        {
            if (_disposed) return;
            // Spec wording is "emission on a new value" — guard against no-op
            // re-sets so debounce + recompute don't fire when nothing changed.
            if (string.Equals(_termSubject.Value, value, StringComparison.Ordinal)) return;
            _termSubject.OnNext(value);
        }
    }

    /// <summary>Observable of the current filtered snapshot.</summary>
    public IObservable<IReadOnlyList<TItem>> Filtered => _filteredSubject.AsObservable();

    /// <inheritdoc/>
    public bool CanSearch() => _itemsSource().Any();

    /// <inheritdoc/>
    public void Search()
    {
        if (_disposed) return;
        _forceSearchSubject.OnNext(Unit.Default);
    }

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
