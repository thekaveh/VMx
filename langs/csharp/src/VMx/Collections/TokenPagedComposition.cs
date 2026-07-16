using System.Collections.Specialized;
using System.ComponentModel;
using System.Reactive;
using System.Reactive.Subjects;
using VMx.Commands;
using VMx.Components;

namespace VMx.Collections;

/// <summary>A single page returned by <see cref="TokenPagedComposition{TVM,TToken}"/>.</summary>
public sealed record TokenPage<TVM, TToken>(IReadOnlyList<TVM> Items, TToken? NextToken);

/// <summary>
/// Accumulates pages fetched by an opaque forward-only token.
/// </summary>
public sealed class TokenPagedComposition<TVM, TToken> :
    INotifyCollectionChanged,
    INotifyPropertyChanged,
    IDisposable
{
    private readonly Func<TToken?, Task<TokenPage<TVM, TToken>>> _fetchNext;
    private readonly bool _autoConstructOnAdd;
    private readonly Func<IReadOnlyList<TVM>, IReadOnlyList<TVM>, bool> _pagesEqual;
    private readonly object _gate = new();
    private readonly List<TVM> _items = [];
    // Shared re-signal for BOTH commands: a change driven by one command (e.g.
    // RefreshCommand flipping HasMore) must re-raise the other's CanExecuteChanged,
    // matching Python/TypeScript/Swift (a bound "Load More" re-enables immediately).
    private readonly ISubject<Unit> _commandChanged = Subject.Synchronize(new Subject<Unit>());
    private TToken? _currentToken;
    private bool _loadedOnce;
    private long _operationGeneration;
    private bool _disposed;

    /// <summary>
    /// Creates a token-paged composition.
    /// </summary>
    public TokenPagedComposition(
        Func<TToken?, Task<TokenPage<TVM, TToken>>> fetchNext,
        bool autoConstructOnAdd = false,
        Func<IReadOnlyList<TVM>, IReadOnlyList<TVM>, bool>? pagesEqual = null)
    {
        _fetchNext = fetchNext ?? throw new ArgumentNullException(nameof(fetchNext));
        _autoConstructOnAdd = autoConstructOnAdd;
        _pagesEqual = pagesEqual ?? DefaultPagesEqual;
        LoadMoreCommand = AsyncRelayCommand.Builder()
            .Predicate(CanLoadMore)
            .Task(_ => LoadMoreAsync())
            .Triggers(_commandChanged)
            .Build();
        RefreshCommand = AsyncRelayCommand.Builder()
            .Predicate(IsLive)
            .Task(_ => RefreshAsync())
            .Triggers(_commandChanged)
            .Build();
    }

    /// <summary>Accumulated items loaded so far.</summary>
    public IReadOnlyList<TVM> Items
    {
        get
        {
            lock (_gate)
            {
                return _items.ToArray();
            }
        }
    }

    /// <summary>The token to pass to the next load, or null after the terminal page.</summary>
    public TToken? CurrentToken
    {
        get
        {
            lock (_gate)
            {
                return _currentToken;
            }
        }
    }

    /// <summary>True before the first fetch or while the current token is non-null.</summary>
    public bool HasMore
    {
        get
        {
            lock (_gate)
            {
                return !_loadedOnce || _currentToken is not null;
            }
        }
    }

    /// <summary>Loads the next page and appends it to <see cref="Items"/>.</summary>
    public AsyncRelayCommand LoadMoreCommand { get; }

    /// <summary>Clears/replaces the accumulator by fetching from the initial token.</summary>
    public AsyncRelayCommand RefreshCommand { get; }

    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    private async Task LoadMoreAsync()
    {
        TToken? token;
        long generation;
        lock (_gate)
        {
            if (_disposed) return;
            generation = ++_operationGeneration;
            token = _currentToken;
        }
        var page = await _fetchNext(token).ConfigureAwait(false);
        var additions = page.Items.ToArray();
        lock (_gate)
        {
            if (_disposed || generation != _operationGeneration) return;
        }
        ConstructIfNeeded(additions);
        lock (_gate)
        {
            if (_disposed || generation != _operationGeneration) return;
            _items.AddRange(additions);
            _currentToken = page.NextToken;
            _loadedOnce = true;
        }
        NotifyResetIfLive();
    }

    private async Task RefreshAsync()
    {
        long generation;
        lock (_gate)
        {
            if (_disposed) return;
            generation = ++_operationGeneration;
        }
        var page = await _fetchNext(default).ConfigureAwait(false);
        var fresh = page.Items.ToArray();
        TVM[] head;
        lock (_gate)
        {
            if (_disposed || generation != _operationGeneration) return;
            head = _items.Take(fresh.Length).ToArray();
        }

        var pagesMatch = _pagesEqual(fresh, head);
        if (!pagesMatch)
            ConstructIfNeeded(fresh);

        lock (_gate)
        {
            if (_disposed || generation != _operationGeneration) return;
            if (!pagesMatch)
            {
                _items.Clear();
                _items.AddRange(fresh);
            }
            _currentToken = page.NextToken;
            _loadedOnce = true;
        }

        if (pagesMatch)
            NotifyPropertiesIfLive();
        else
            NotifyResetIfLive();
    }

    private void ConstructIfNeeded(IReadOnlyList<TVM> items)
    {
        if (!_autoConstructOnAdd) return;
        foreach (var item in items)
        {
            if (item is ComponentVMBase vm && !vm.IsConstructed)
                vm.Construct();
        }
    }

    private void NotifyResetIfLive()
    {
        if (!IsLive()) return;
        CollectionChanged?.Invoke(
            this,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        NotifyPropertiesIfLive();
    }

    private void NotifyPropertiesIfLive()
    {
        foreach (var name in new[] { nameof(Items), nameof(CurrentToken), nameof(HasMore) })
        {
            if (!IsLive()) return;
            OnPropertyChanged(name);
        }
        if (!IsLive()) return;
        // Re-signal both commands' CanExecuteChanged (parity with Python/TS/Swift).
        _commandChanged.OnNext(Unit.Default);
    }

    private bool CanLoadMore()
    {
        lock (_gate)
        {
            return !_disposed && (!_loadedOnce || _currentToken is not null);
        }
    }

    private bool IsLive()
    {
        lock (_gate)
        {
            return !_disposed;
        }
    }

    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    private static bool DefaultPagesEqual(IReadOnlyList<TVM> left, IReadOnlyList<TVM> right) =>
        left.SequenceEqual(right, EqualityComparer<TVM>.Default);

    /// <inheritdoc/>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
        }
        LoadMoreCommand.Dispose();
        RefreshCommand.Dispose();
        _commandChanged.OnCompleted();
    }
}
