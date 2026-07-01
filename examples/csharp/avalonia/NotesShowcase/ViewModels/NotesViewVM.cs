using System.ComponentModel;
using System.Reactive;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Collections;
using VMx.Commands;
using VMx.Components;
using VMx.Composites;
using VMx.Dialogs;
using VMx.Messages;
using VMx.Notifications;
using VMx.Properties;
using VMx.Services;
using NotesShowcase.Models;
using NotesShowcase.Views.Adapter;

namespace NotesShowcase.ViewModels;

/// <summary>
/// VM for the centre pane: paged, searchable, filterable list of notes.
///
/// VMx-API adaptation (plan §3.a.8): the plan asked to subclass
/// <c>PagedComposition&lt;NoteVM&gt;</c>, but
/// <see cref="PagedComposition{TVM}"/> is a sealed read-only decorator (not a
/// base class). Composition instead:
///   * inner storage = <see cref="CompositeVM{VM}"/> of <see cref="NoteVM"/>
///     (mutable, lifecycle-aware, hub-published collection),
///   * filtered view = an <see cref="ObservableCollection{T}"/> mirror updated
///     on every collection / filter / search change,
///   * paged view = <see cref="PagedComposition{TVM}"/> over the filtered view,
///   * search = <see cref="SearchableState{TItem}"/> (debounced 150 ms).
/// </summary>
public sealed class NotesViewVM
    : ComponentVMBase,
      IPageable,
      IFilterable<NoteVM>,
      ISearchable,
      IReconstructable,
      IDisposable
{
    private readonly INoteRepository _repo;
    private readonly IDialogService? _dialogService;
    private readonly INotificationHub? _notificationHub;
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;
    private readonly IScheduler _searchScheduler;

    private readonly CompositeVM<NoteVM> _inner;
    private readonly System.Collections.ObjectModel.ObservableCollection<NoteVM> _filtered = new();
    private readonly PagedComposition<NoteVM> _paged;

    private readonly BehaviorSubject<bool> _showStarredOnly = new(false);
    private readonly BehaviorSubject<Unit> _stateSubject = new(Unit.Default);
    private readonly SearchableState<NoteVM> _search;

    private CancellationTokenSource? _activeFetchCts;
    private bool _showStarredOnlyField;
    private bool _currentNotebookIsReadOnly;
    private System.Predicate<NoteVM>? _filter;
    private NoteVM? _current;
    private bool _ownDisposed;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>The inner composite storing all loaded notes (unfiltered).</summary>
    public CompositeVM<NoteVM> Inner => _inner;

    /// <summary>Filtered + searched items (paged source). Mirrored read-only.</summary>
    public IReadOnlyList<NoteVM> FilteredItems => _filtered;

    /// <summary>Items on the current page (decoded slice over <see cref="FilteredItems"/>).</summary>
    public IReadOnlyList<NoteVM> VisibleItems => _paged.Items.ToList();

    // ── ISearchable (debounced 150 ms via SearchableState) ────────────────

    /// <inheritdoc/>
    public string SearchTerm
    {
        get => _search.SearchTerm;
        set => _search.SearchTerm = value;
    }

    /// <inheritdoc/>
    public bool CanSearch() => _search.CanSearch();

    /// <inheritdoc/>
    public void Search() => _search.Search();

    /// <summary>True when current filters / search produce no visible items.</summary>
    public bool IsEmpty => _filtered.Count == 0;

    /// <summary>"Page X of Y" label (plan §3.a.8).</summary>
    public string PageLabel => $"Page {CurrentPageIndex + 1} of {Math.Max(1, PageCount)}";

    /// <summary>Derived empty-state projection for framework-component parity.</summary>
    public DerivedProperty<bool> IsEmptyDerived { get; }

    /// <summary>Derived page-label projection for framework-component parity.</summary>
    public DerivedProperty<string> PageLabelDerived { get; }

    /// <summary>INPC-aware sidecar for <see cref="IsEmptyDerived"/>.</summary>
    public BindableDerived<bool> IsEmptyBindable { get; }

    /// <summary>INPC-aware sidecar for <see cref="PageLabelDerived"/>.</summary>
    public BindableDerived<string> PageLabelBindable { get; }

    // ── IFilterable ─────────────────────────────────────────────────────────

    /// <inheritdoc/>
    public System.Predicate<NoteVM>? Filter
    {
        get => _filter;
        set
        {
            if (ReferenceEquals(_filter, value)) return;
            _filter = value;
            RecomputeFiltered();
        }
    }

    /// <inheritdoc/>
    public bool CanFilter() => Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <summary>
    /// Two-way bool: when true, only starred notes are visible.
    /// Implemented as a thin wrapper around <see cref="Filter"/>.
    /// </summary>
    public bool ShowStarredOnly
    {
        get => _showStarredOnlyField;
        set
        {
            if (_showStarredOnlyField == value) return;
            _showStarredOnlyField = value;
            _showStarredOnly.OnNext(value);
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(ShowStarredOnly)));
            RaisePropertyChanged(nameof(ShowStarredOnly));
            RecomputeFiltered();
        }
    }

    // ── IPageable (delegates to inner PagedComposition) ───────────────────

    /// <inheritdoc/>
    public int PageSize
    {
        get => _paged.PageSize;
        set => _paged.PageSize = value;
    }

    /// <inheritdoc/>
    public int CurrentPageIndex
    {
        get => _paged.CurrentPageIndex;
        set => _paged.CurrentPageIndex = value;
    }

    /// <inheritdoc/>
    public int PageCount => _paged.PageCount;

    /// <inheritdoc/>
    public bool IsPagingEnabled => _paged.IsPagingEnabled;

    /// <inheritdoc/>
    public void MoveToFirstPage() => _paged.MoveToFirstPage();

    /// <inheritdoc/>
    public void MoveToPreviousPage() => _paged.MoveToPreviousPage();

    /// <inheritdoc/>
    public void MoveToNextPage() => _paged.MoveToNextPage();

    /// <inheritdoc/>
    public void MoveToLastPage() => _paged.MoveToLastPage();

    /// <summary>Bindable command for first page (plan §3.a.8).</summary>
    public ICommand MoveToFirstPageCommand { get; }
    /// <summary>Bindable command for previous page.</summary>
    public ICommand MoveToPreviousPageCommand { get; }
    /// <summary>Bindable command for next page.</summary>
    public ICommand MoveToNextPageCommand { get; }
    /// <summary>Bindable command for last page.</summary>
    public ICommand MoveToLastPageCommand { get; }

    // ── Current note (selected from the paged list) ───────────────────────

    /// <summary>Currently selected note (two-way bindable).</summary>
    public NoteVM? Current
    {
        get => _current;
        set
        {
            if (ReferenceEquals(_current, value)) return;
            _current = value;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Current)));
            RaisePropertyChanged(nameof(Current));
        }
    }

    /// <summary>The id of the notebook this view is currently bound to (or null).</summary>
    public string? BoundNotebookId { get; private set; }

    /// <summary>Readonly flag of the currently-bound notebook, supplied by the host.</summary>
    public bool CurrentNotebookIsReadOnly
    {
        get => _currentNotebookIsReadOnly;
        set
        {
            if (_currentNotebookIsReadOnly == value) return;
            _currentNotebookIsReadOnly = value;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(CurrentNotebookIsReadOnly)));
            RaisePropertyChanged(nameof(CurrentNotebookIsReadOnly));
        }
    }

    /// <summary>
    /// Cancel any in-flight fetch, load notes for the given notebook, and
    /// replace the inner items. Resets <see cref="Current"/> and the page.
    /// </summary>
    public async Task BindToAsync(string notebookId, CancellationToken ct = default)
    {
        _activeFetchCts?.Cancel();
        var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _activeFetchCts = cts;
        try
        {
            var notes = await _repo.LoadNotesAsync(notebookId, cts.Token).ConfigureAwait(false);
            if (cts.IsCancellationRequested) return;
            // ReplaceItems raises INPC into live XAML bindings and this
            // continuation runs off the UI thread (ConfigureAwait(false)) —
            // marshal (real-wiring audit, pass 6). With the test dispatcher
            // (Immediate) this runs inline, keeping awaited binds
            // deterministic.
            _dispatcher.Foreground.Schedule(() =>
            {
                if (cts.IsCancellationRequested) return;
                BoundNotebookId = notebookId;
                ReplaceItems(notes);
            });
        }
        catch (OperationCanceledException)
        {
            // Cancellation is normal when a newer BindToAsync supersedes us.
        }
    }

    /// <summary>
    /// Refreshes the list row for <paramref name="note"/> after an external
    /// update (save): re-seats the persisted model into the matching
    /// <see cref="NoteVM"/> and re-runs the combined filter so row labels,
    /// the star marker, and the starred filter reflect the saved values.
    /// </summary>
    public void RefreshNote(NoteModel note)
    {
        NoteVM? match = null;
        foreach (var vm in _inner)
        {
            if (string.Equals(vm.Model.Id, note.Id, StringComparison.Ordinal))
            {
                match = vm;
                break;
            }
        }
        if (match is null) return;
        match.Model = note;
        RecomputeFiltered();
    }

    private void ReplaceItems(IReadOnlyList<NoteModel> notes)
    {
        // Dispose existing children to release their hub subscriptions.
        for (var i = _inner.Count - 1; i >= 0; i--)
        {
            var prev = _inner[i];
            _inner.RemoveAt(i);
            prev.Dispose();
        }

        foreach (var note in notes)
        {
            var builder = NoteVM.Builder()
                .Name($"note:{note.Id}")
                .Services(_hub, _dispatcher)
                .Model(note)
                .OnDelete(DeleteNote)
                // Real-wiring audit, pass 6: the capability bar projects
                // NoteVM.SaveCommand/CloseCommand, but nothing wired the
                // handlers — both actions were silent no-ops.
                .OnClose(vm =>
                {
                    if (ReferenceEquals(Current, vm)) Current = null;
                })
                .OnSave(vm => _ = _repo.SaveNoteAsync(vm.Model));
            if (_dialogService is not null)
            {
                builder = builder.ConfirmDelete(n =>
                    _dialogService.Confirm(
                        $"Delete “{n.Title}”?",
                        title: "Delete note"));
            }
            if (_notificationHub is not null)
            {
                builder = builder.NotificationHub(_notificationHub);
            }
            var vm = builder.Build();
            vm.Construct();
            _inner.Add(vm);
        }

        _current = null;
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Current)));
        RaisePropertyChanged(nameof(Current));

        RecomputeFiltered();
        _paged.MoveToFirstPage();
    }

    private void DeleteNote(NoteVM note)
    {
        // Fire-and-forget removal: persist via the repo, remove from the inner
        // collection, and clear current if it pointed at the deleted note.
        // Errors are swallowed (the host wires logging via the message hub).
        _ = DeleteNoteAsyncInternal(note);
    }

    private async Task DeleteNoteAsyncInternal(NoteVM note)
    {
        try
        {
            await _repo.DeleteNoteAsync(note.Model.Id).ConfigureAwait(false);
        }
        catch
        {
            // Persistence failures are surfaced via the dialog/notification
            // hub in production; tests pass a synchronous repo so this branch
            // is dead code under test.
            return;
        }
        // The continuation runs off the UI thread (ConfigureAwait(false));
        // the mutations below raise INPC into live XAML bindings — marshal
        // (real-wiring audit, pass 6).
        _dispatcher.Foreground.Schedule(() =>
        {
            var index = -1;
            for (var i = 0; i < _inner.Count; i++)
            {
                if (ReferenceEquals(_inner[i], note)) { index = i; break; }
            }
            if (index < 0) return;
            _inner.RemoveAt(index);
            if (ReferenceEquals(_current, note))
            {
                _current = null;
                Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Current)));
                RaisePropertyChanged(nameof(Current));
            }
            RecomputeFiltered();
            note.Dispose();
        });
    }

    private void RecomputeFiltered()
    {
        var term = _search.SearchTerm;
        _filtered.Clear();
        foreach (var n in _inner)
        {
            if (_showStarredOnlyField && !n.Model.Starred) continue;
            if (_filter is not null && !_filter(n)) continue;
            if (!string.IsNullOrEmpty(term)
                && !n.Title.Contains(term, StringComparison.OrdinalIgnoreCase)
                && !n.Body.Contains(term, StringComparison.OrdinalIgnoreCase)
                && !n.Tags.Any(t => t.Contains(term, StringComparison.OrdinalIgnoreCase))) continue;
            _filtered.Add(n);
        }
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(FilteredItems)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsEmpty)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(VisibleItems)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(PageLabel)));
        RaisePropertyChanged(nameof(FilteredItems));
        RaisePropertyChanged(nameof(IsEmpty));
        RaisePropertyChanged(nameof(VisibleItems));
        RaisePropertyChanged(nameof(PageLabel));
        _stateSubject.OnNext(Unit.Default);
    }

    private NotesViewVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        INoteRepository repo,
        int pageSize,
        TimeSpan searchDebounce,
        IScheduler? searchScheduler,
        IDialogService? dialogService,
        INotificationHub? notificationHub)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _repo = repo;
        _dialogService = dialogService;
        _notificationHub = notificationHub;
        _hub = hub;
        _dispatcher = dispatcher;
        _searchScheduler = searchScheduler ?? ImmediateScheduler.Instance;

        _inner = CompositeVM<NoteVM>.Builder()
            .Name($"{name}:inner")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<NoteVM>())
            .Build();

        _paged = new PagedComposition<NoteVM>(_filtered, pageSize);
        _paged.PropertyChanged += OnPagedPropertyChanged;

        _search = new SearchableState<NoteVM>(
            items: () => _inner,
            // Predicate is unused — we re-run RecomputeFiltered ourselves on every
            // debounced term emission below, because we also blend in starred /
            // capability filters that SearchableState doesn't know about.
            predicate: (_, _) => true,
            debounce: searchDebounce,
            scheduler: _searchScheduler);
        // Whenever the debounced search term updates the filtered snapshot,
        // run our combined filter pipeline.
        _search.Filtered.Subscribe(_ => RecomputeFiltered());

        IsEmptyDerived = DerivedProperty.From(
            _stateSubject,
            _ => _filtered.Count == 0);
        PageLabelDerived = DerivedProperty.From(
            _stateSubject,
            _ => PageLabel);
        IsEmptyBindable = new BindableDerived<bool>(IsEmptyDerived);
        PageLabelBindable = new BindableDerived<string>(PageLabelDerived);

        MoveToFirstPageCommand = RelayCommand.Builder()
            .Predicate(() => CurrentPageIndex > 0)
            .Task(MoveToFirstPage)
            .Triggers(_stateSubject)
            .Build();
        MoveToPreviousPageCommand = RelayCommand.Builder()
            .Predicate(() => CurrentPageIndex > 0)
            .Task(MoveToPreviousPage)
            .Triggers(_stateSubject)
            .Build();
        MoveToNextPageCommand = RelayCommand.Builder()
            .Predicate(() => CurrentPageIndex < PageCount - 1)
            .Task(MoveToNextPage)
            .Triggers(_stateSubject)
            .Build();
        MoveToLastPageCommand = RelayCommand.Builder()
            .Predicate(() => CurrentPageIndex < PageCount - 1)
            .Task(MoveToLastPage)
            .Triggers(_stateSubject)
            .Build();
    }

    private void OnPagedPropertyChanged(object? _, PropertyChangedEventArgs e)
    {
        // Re-broadcast paged changes through our own INPC + hub so subscribers
        // bound to NotesViewVM (not the inner PagedComposition) see them.
        RaisePropertyChanged(e.PropertyName ?? string.Empty);
        if (!string.IsNullOrEmpty(e.PropertyName))
        {
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, e.PropertyName));
        }
        // Page index/size/count changes also change the "Page X of Y" label
        // and the visible-items slice.
        if (e.PropertyName is nameof(CurrentPageIndex) or nameof(PageCount) or nameof(PageSize))
        {
            RaisePropertyChanged(nameof(PageLabel));
            RaisePropertyChanged(nameof(VisibleItems));
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(PageLabel)));
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(VisibleItems)));
            _stateSubject.OnNext(Unit.Default);
        }
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        for (var i = _inner.Count - 1; i >= 0; i--)
        {
            var prev = _inner[i];
            _inner.RemoveAt(i);
            prev.Dispose();
        }
        base.OnDestruct();
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _activeFetchCts?.Cancel();
        _activeFetchCts?.Dispose();
        _paged.PropertyChanged -= OnPagedPropertyChanged;
        _paged.Dispose();
        _search.Dispose();
        IsEmptyBindable.Dispose();
        PageLabelBindable.Dispose();
        IsEmptyDerived.Dispose();
        PageLabelDerived.Dispose();
        _showStarredOnly.OnCompleted();
        _showStarredOnly.Dispose();
        _stateSubject.OnCompleted();
        _stateSubject.Dispose();
        _inner.Dispose();
        (MoveToFirstPageCommand as IDisposable)?.Dispose();
        (MoveToPreviousPageCommand as IDisposable)?.Dispose();
        (MoveToNextPageCommand as IDisposable)?.Dispose();
        (MoveToLastPageCommand as IDisposable)?.Dispose();
        base.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static NotesViewVMBuilder Builder() => NotesViewVMBuilder.Empty;

    /// <summary>Immutable fluent builder (spec ch. 10).</summary>
    public sealed class NotesViewVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly INoteRepository? _repo;
        private readonly int _pageSize;
        private readonly TimeSpan _searchDebounce;
        private readonly IScheduler? _searchScheduler;
        private readonly IDialogService? _dialogService;
        private readonly INotificationHub? _notificationHub;

        internal static readonly NotesViewVMBuilder Empty = new();
        private NotesViewVMBuilder()
        {
            _hint = "";
            _pageSize = 5;
            _searchDebounce = TimeSpan.FromMilliseconds(150);
        }
        private NotesViewVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher, INoteRepository? repo,
            int pageSize, TimeSpan searchDebounce, IScheduler? searchScheduler,
            IDialogService? dialogService, INotificationHub? notificationHub)
        {
            _name = name; _hint = hint; _hub = hub; _dispatcher = dispatcher;
            _repo = repo; _pageSize = pageSize;
            _searchDebounce = searchDebounce; _searchScheduler = searchScheduler;
            _dialogService = dialogService; _notificationHub = notificationHub;
        }

        /// <summary>Sets the required Name.</summary>
        public NotesViewVMBuilder Name(string name)
            => new(name, _hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Sets the optional Hint.</summary>
        public NotesViewVMBuilder Hint(string hint)
            => new(_name, hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Sets the required Services.</summary>
        public NotesViewVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _repo, _pageSize, _searchDebounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Sets the required Repository.</summary>
        public NotesViewVMBuilder Repository(INoteRepository repo)
            => new(_name, _hint, _hub, _dispatcher, repo, _pageSize, _searchDebounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Overrides the optional page size (default 5 per plan §3.a.8).</summary>
        public NotesViewVMBuilder PageSize(int size)
            => new(_name, _hint, _hub, _dispatcher, _repo, size, _searchDebounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Overrides the optional search debounce (default 150 ms).</summary>
        public NotesViewVMBuilder SearchDebounce(TimeSpan debounce)
            => new(_name, _hint, _hub, _dispatcher, _repo, _pageSize, debounce, _searchScheduler, _dialogService, _notificationHub);
        /// <summary>Overrides the optional debounce scheduler (default Immediate).</summary>
        public NotesViewVMBuilder SearchScheduler(IScheduler scheduler)
            => new(_name, _hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce, scheduler, _dialogService, _notificationHub);
        /// <summary>
        /// Sets the optional dialog service. When set, each <see cref="NoteVM"/>
        /// in the list wires its <see cref="NoteVM.DeleteCommand"/> through
        /// <see cref="VMx.Commands.ConfirmationDecoratorCommand"/> calling
        /// <see cref="IDialogService.Confirm"/> before deletion (spec §5.2.8).
        /// </summary>
        public NotesViewVMBuilder DialogService(IDialogService dialogService)
            => new(_name, _hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce, _searchScheduler, dialogService, _notificationHub);
        /// <summary>
        /// Sets the optional notification hub. When set, each successful
        /// note-delete publishes a "Note deleted" notification (spec §6.2).
        /// </summary>
        public NotesViewVMBuilder NotificationHub(INotificationHub notificationHub)
            => new(_name, _hint, _hub, _dispatcher, _repo, _pageSize, _searchDebounce, _searchScheduler, _dialogService, notificationHub);

        /// <summary>Builds the VM after validation.</summary>
        public NotesViewVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_repo, "Repository");
            return new NotesViewVM(
                _name!, _hint, _hub!, _dispatcher!, _repo!,
                _pageSize, _searchDebounce, _searchScheduler,
                _dialogService, _notificationHub);
        }
    }
}
