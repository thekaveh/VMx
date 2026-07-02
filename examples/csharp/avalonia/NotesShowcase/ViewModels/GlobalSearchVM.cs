using System.Collections.Specialized;
using System.ComponentModel;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Collections;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>Token-paged search over all notes in the workspace.</summary>
public sealed class GlobalSearchVM : ComponentVMBase
{
    private readonly INoteRepository _repo;
    private readonly IDispatcher _dispatcher;
    private readonly int _pageSize;
    private readonly SearchableState<string> _search;
    private readonly TokenPagedComposition<NoteVM, string> _paged;
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
        _paged = new TokenPagedComposition<NoteVM, string>(
            FetchNextAsync,
            autoConstructOnAdd: true,
            pagesEqual: (left, right) =>
                left.Count == right.Count
                && left.Zip(right).All(pair => pair.First.Model.Id == pair.Second.Model.Id));
        _paged.CollectionChanged += OnPagedCollectionChanged;
        _paged.PropertyChanged += OnPagedPropertyChanged;
    }

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>All loaded matching notes.</summary>
    public IReadOnlyList<NoteVM> Results => _paged.Items;

    /// <summary>True when another result page can be loaded.</summary>
    public bool HasMore => _paged.HasMore;

    /// <summary>Refreshes the result set from the first page.</summary>
    public AsyncRelayCommand RefreshCommand => _paged.RefreshCommand;

    /// <summary>Loads and appends the next result page.</summary>
    public AsyncRelayCommand LoadMoreCommand => _paged.LoadMoreCommand;

    /// <summary>Current global search term.</summary>
    public string SearchTerm
    {
        get => _search.SearchTerm;
        set
        {
            if (string.Equals(_search.SearchTerm, value, StringComparison.Ordinal)) return;
            _search.SearchTerm = value;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(SearchTerm)));
            RaisePropertyChanged(nameof(SearchTerm));
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

    private async Task<TokenPage<NoteVM, string>> FetchNextAsync(string? token)
    {
        var page = await _repo.SearchNotesAsync(SearchTerm, token, _pageSize).ConfigureAwait(false);
        var items = page.Items
            .Select(model => NoteVM.Builder()
                .Name($"global-{model.Id}")
                .Services(Hub, _dispatcher)
                .Model(model)
                .Build())
            .ToList();
        return new TokenPage<NoteVM, string>(items, page.NextToken);
    }

    private void OnPagedCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Results)));
        RaisePropertyChanged(nameof(Results));
    }

    private void OnPagedPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(TokenPagedComposition<NoteVM, string>.HasMore))
        {
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(HasMore)));
            RaisePropertyChanged(nameof(HasMore));
        }
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _paged.CollectionChanged -= OnPagedCollectionChanged;
        _paged.PropertyChanged -= OnPagedPropertyChanged;
        foreach (var result in _paged.Items)
            result.Dispose();
        _paged.Dispose();
        _search.Dispose();
        base.Dispose();
    }

    /// <summary>Returns an empty builder.</summary>
    public static GlobalSearchVMBuilder Builder() => GlobalSearchVMBuilder.Empty;

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
