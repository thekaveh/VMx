using System.Collections.Specialized;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Collections;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Token-paged search over all notes in the workspace. Owns every result VM it
/// creates because <see cref="TokenPagedComposition{TVM, TToken}"/> does not own
/// item lifetimes.
/// </summary>
public sealed class GlobalSearchVM : ComponentVMBase
{
    private readonly INoteRepository _repo;
    private readonly IDispatcher _dispatcher;
    private readonly int _pageSize;
    private readonly SearchableState<string> _search;
    private readonly TokenPagedComposition<NoteVM, SearchCursor> _paged;
    private readonly object _ownedResultsGate = new();
    private readonly HashSet<NoteVM> _ownedResults = new(ReferenceEqualityComparer.Instance);
    // The search term that fetched each result.
    private readonly ConditionalWeakTable<NoteVM, string> _resultTerms = new();
    private bool _ownedResultsDisposed;
    private bool _ownDisposed;

    private GlobalSearchVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        INoteRepository repo,
        int pageSize,
        TimeSpan searchDebounce)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _repo = repo;
        _dispatcher = dispatcher;
        _pageSize = pageSize;
        _search = new SearchableState<string>(
            items: () => new[] { "global-search" },
            predicate: (_, _) => true,
            debounce: searchDebounce,
            scheduler: dispatcher.Foreground);
        _paged = new TokenPagedComposition<NoteVM, SearchCursor>(
            FetchNextAsync,
            autoConstructOnAdd: true,
            // Pages for different terms are never equal, so a refresh for a new
            // term replaces the loaded pages and their cursor.
            pagesEqual: (left, right) =>
                left.Count == right.Count
                && left.Zip(right).All(pair =>
                    pair.First.Model.Id == pair.Second.Model.Id
                    && TermOf(pair.First) == TermOf(pair.Second)));
        // A refresh replaces the loaded pages, so "Load more" is not available
        // until the refresh is complete. A call made during a refresh does
        // nothing. A load that starts during a refresh makes the composition
        // discard that refresh (spec 21 §6.2).
        LoadMoreCommand = AsyncRelayCommand.Builder()
            .Predicate(() => _paged.LoadMoreCommand.CanExecute(null) && !_paged.RefreshCommand.IsExecuting)
            .Task(_ => _paged.LoadMoreCommand.ExecuteAsync())
            .Build();
        _paged.CollectionChanged += OnPagedCollectionChanged;
        _paged.PropertyChanged += OnPagedPropertyChanged;
        _paged.LoadMoreCommand.CanExecuteChanged += OnPagedCommandCanExecuteChanged;
        _paged.RefreshCommand.CanExecuteChanged += OnPagedCommandCanExecuteChanged;
    }

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>All loaded matching notes.</summary>
    public IReadOnlyList<NoteVM> Results => _paged.Items;

    /// <summary>True when another result page can be loaded.</summary>
    public bool HasMore => _paged.HasMore;

    /// <summary>Refreshes the result set from the first page.</summary>
    public AsyncRelayCommand RefreshCommand => _paged.RefreshCommand;

    /// <summary>Loads and appends the next result page. It cannot run while a refresh runs.</summary>
    public AsyncRelayCommand LoadMoreCommand { get; }

    /// <summary>Current global search term.</summary>
    public string SearchTerm
    {
        get => _search.SearchTerm;
        set
        {
            if (string.Equals(_search.SearchTerm, value, StringComparison.Ordinal)) return;
            _search.SearchTerm = value;
            NotifyPropertyChanged(nameof(SearchTerm));
        }
    }

    /// <summary>Whether searching is currently available.</summary>
    public bool CanSearch() => _search.CanSearch();

    /// <summary>Forces an immediate refresh for the current search term.</summary>
    public void Search()
    {
        _search.Search();
        RefreshCommand.Execute(null);
    }

    private async Task<TokenPage<NoteVM, SearchCursor>> FetchNextAsync(SearchCursor? cursor)
    {
        // The first page uses the current term. A later page uses the term in
        // the cursor, so "Load more" continues the term of the loaded pages.
        var term = cursor?.Term ?? SearchTerm;
        var page = await _repo.SearchNotesAsync(term, cursor?.Offset, _pageSize).ConfigureAwait(false);
        var items = page.Items
            .Select(model => OwnResult(
                NoteVM.Builder()
                    .Name($"global-{model.Id}")
                    .Services(Hub, _dispatcher)
                    .Model(model)
                    .Build(),
                term))
            .ToList();
        var next = page.NextToken is null ? null : new SearchCursor(term, page.NextToken);
        return new TokenPage<NoteVM, SearchCursor>(items, next);
    }

    private NoteVM OwnResult(NoteVM result, string term)
    {
        bool disposeImmediately;
        lock (_ownedResultsGate)
        {
            disposeImmediately = _ownedResultsDisposed;
            if (!disposeImmediately)
            {
                _ownedResults.Add(result);
                _resultTerms.AddOrUpdate(result, term);
            }
        }
        if (disposeImmediately)
            result.Dispose();
        return result;
    }

    private string? TermOf(NoteVM result) =>
        _resultTerms.TryGetValue(result, out var term) ? term : null;

    private void DisposeOwnedResults()
    {
        NoteVM[] owned;
        lock (_ownedResultsGate)
        {
            _ownedResultsDisposed = true;
            owned = _ownedResults.ToArray();
            _ownedResults.Clear();
        }
        foreach (var result in owned)
            result.Dispose();
    }

    private void OnPagedCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        NotifyPropertyChanged(nameof(Results));
    }

    private void OnPagedPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(TokenPagedComposition<NoteVM, SearchCursor>.HasMore))
        {
            NotifyPropertyChanged(nameof(HasMore));
        }
    }

    private void OnPagedCommandCanExecuteChanged(object? sender, EventArgs e)
    {
        LoadMoreCommand.RaiseCanExecuteChanged();
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _paged.CollectionChanged -= OnPagedCollectionChanged;
        _paged.PropertyChanged -= OnPagedPropertyChanged;
        _paged.LoadMoreCommand.CanExecuteChanged -= OnPagedCommandCanExecuteChanged;
        _paged.RefreshCommand.CanExecuteChanged -= OnPagedCommandCanExecuteChanged;
        DisposeOwnedResults();
        LoadMoreCommand.Dispose();
        _paged.Dispose();
        _search.Dispose();
        base.Dispose();
    }

    /// <summary>Returns an empty builder.</summary>
    public static GlobalSearchVMBuilder Builder() => GlobalSearchVMBuilder.Empty;

    /// <summary>The cursor for the next page. It keeps the term of the loaded pages.</summary>
    private sealed record SearchCursor(string Term, string Offset);

    /// <summary>Immutable fluent builder.</summary>
    public sealed class GlobalSearchVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly INoteRepository? _repo;
        private readonly int _pageSize;
        private readonly TimeSpan _searchDebounce;

        internal static readonly GlobalSearchVMBuilder Empty = new();

        private GlobalSearchVMBuilder()
        {
            _hint = "";
            _pageSize = 5;
            _searchDebounce = TimeSpan.FromMilliseconds(150);
        }

        private GlobalSearchVMBuilder(
            string? name,
            string hint,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            INoteRepository? repo,
            int pageSize,
            TimeSpan searchDebounce)
        {
            _name = name;
            _hint = hint;
            _hub = hub;
            _dispatcher = dispatcher;
            _repo = repo;
            _pageSize = pageSize;
            _searchDebounce = searchDebounce;
        }

        public GlobalSearchVMBuilder Name(string name)
            => new(name, _hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce);

        public GlobalSearchVMBuilder Hint(string hint)
            => new(_name, hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce);

        public GlobalSearchVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _repo, _pageSize, _searchDebounce);

        public GlobalSearchVMBuilder Repository(INoteRepository repo)
            => new(_name, _hint, _hub, _dispatcher, repo, _pageSize, _searchDebounce);

        public GlobalSearchVMBuilder PageSize(int pageSize)
            => new(_name, _hint, _hub, _dispatcher, _repo, pageSize, _searchDebounce);

        public GlobalSearchVMBuilder SearchDebounce(TimeSpan debounce)
            => new(_name, _hint, _hub, _dispatcher, _repo, _pageSize, debounce);

        public GlobalSearchVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_repo, "Repository");
            return new GlobalSearchVM(
                _name!,
                _hint,
                _hub!,
                _dispatcher!,
                _repo!,
                _pageSize,
                _searchDebounce);
        }
    }
}
