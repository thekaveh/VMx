using System.Collections.Specialized;
using System.ComponentModel;
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
    private TToken? _currentToken;
    private bool _loadedOnce;
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
            .Predicate(() => HasMore && !_disposed)
            .Task(_ => LoadMoreAsync())
            .Build();
        RefreshCommand = AsyncRelayCommand.Builder()
            .Predicate(() => !_disposed)
            .Task(_ => RefreshAsync())
            .Build();
    }

    /// <summary>Accumulated items loaded so far.</summary>
    public IReadOnlyList<TVM> Items => _items.ToArray();

    /// <summary>The token to pass to the next load, or null after the terminal page.</summary>
    public TToken? CurrentToken => _currentToken;

    /// <summary>True before the first fetch or while the current token is non-null.</summary>
    public bool HasMore => !_loadedOnce || _currentToken is not null;

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
        var page = await _fetchNext(_currentToken).ConfigureAwait(false);
        lock (_gate)
        {
            if (_disposed) return;
            _items.AddRange(page.Items);
            ConstructIfNeeded(page.Items);
            _currentToken = page.NextToken;
            _loadedOnce = true;
            NotifyReset();
        }
    }

    private async Task RefreshAsync()
    {
        var page = await _fetchNext(default).ConfigureAwait(false);
        lock (_gate)
        {
            if (_disposed) return;
            var head = _items.Take(page.Items.Count).ToArray();
            if (_pagesEqual(page.Items, head))
            {
                _currentToken = page.NextToken;
                _loadedOnce = true;
                NotifyProperties();
                return;
            }

            _items.Clear();
            _items.AddRange(page.Items);
            ConstructIfNeeded(page.Items);
            _currentToken = page.NextToken;
            _loadedOnce = true;
            NotifyReset();
        }
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

    private void NotifyReset()
    {
        CollectionChanged?.Invoke(
            this,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        NotifyProperties();
    }

    private void NotifyProperties()
    {
        OnPropertyChanged(nameof(Items));
        OnPropertyChanged(nameof(CurrentToken));
        OnPropertyChanged(nameof(HasMore));
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
    }
}
