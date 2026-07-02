using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Aggregates;
using VMx.Builders;
using VMx.Commands;
using VMx.Components;
using VMx.Dialogs;
using VMx.Messages;
using VMx.Services;
using VMx.Notifications;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Root VM for the Notes Workspace. Composes six children via
/// <see cref="AggregateVM6{VM1,VM2,VM3,VM4,VM5,VM6}"/> (per ADR-0034):
/// notebooks tree, notes view, note form, status bar, notifications, capability
/// actions.
///
/// VMx-API adaptation (plan §3.a.11): AggregateVM6 is itself sealed (the
/// generic instantiation is sealed, not abstract), so we can't subclass it.
/// Instead, <see cref="WorkspaceVM"/> wraps an AggregateVM6 instance and
/// exposes its components directly. Lifecycle (Construct/Destruct/Dispose)
/// delegates to the inner aggregate — the cascade rules of ADR-0034 still
/// apply, just via composition rather than inheritance.
/// </summary>
public sealed class WorkspaceVM : IDisposable
{
    private readonly INoteRepository _repo;
    private readonly IDialogService _dialogService;
    private readonly INotificationHub _notificationHub;
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;

    private readonly AggregateVM6<
        NotebooksRootVM, NotesViewVM, NoteFormVM,
        StatusBarVM, NotificationsVM, CapabilityActionsVM> _agg;

    // VMX-129: the theme seam is a workspace-owned sibling of the six aggregate
    // children. Composing it as a seventh aggregate child would require an
    // AggregateVM7 in the core library (out of scope per ADR-0058); instead it
    // is held directly and lifecycle-driven alongside the inner aggregate. It
    // shares the workspace hub + dispatcher so its ThemeChangedMessage rides
    // the same bus, and the view binds the Avalonia ThemeAdapter to it.
    private readonly ThemeVM _theme;
    private readonly GlobalSearchVM _globalSearch;

    // Round-3 Critical-2: subscription that rebinds NoteForm whenever
    // NotesView.Current changes (e.g. user clicks a different note in the
    // list). Without this the right-pane editor stays empty in the running
    // app — unit tests called BindTo directly, masking the gap.
    private readonly IDisposable _currentNoteSubscription;
    // Pass-6 real-wiring audit: tree selection (TwoWay SelectedItem →
    // NotebooksRoot.Current) previously updated nothing — the centre pane
    // stayed on the first notebook forever.
    private readonly IDisposable _notebookSubscription;
    // Pass-6 real-wiring audit: refresh the saved note's list row.
    private readonly IDisposable _savedNoteSubscription;
    // Pushed whenever toolbar-command predicates may have flipped — without
    // a trigger CanExecuteChanged never fired and Avalonia cached
    // CanExecute()==false from before construction finished, leaving the
    // "+ Note" button permanently disabled.
    private readonly Subject<System.Reactive.Unit> _commandTrigger = new();
    // Most recent notebook-bind request (set synchronously) — dedupes the
    // construct-time duplicate without racing rapid A→B→A switches.
    private string? _requestedNotebookId;

    /// <summary>Notebooks tree (Component1).</summary>
    public NotebooksRootVM NotebooksRoot => _agg.Component1!;
    /// <summary>Notes view (Component2).</summary>
    public NotesViewVM NotesView => _agg.Component2!;
    /// <summary>Note form (Component3).</summary>
    public NoteFormVM NoteForm => _agg.Component3!;
    /// <summary>Status bar (Component4).</summary>
    public StatusBarVM StatusBar => _agg.Component4!;
    /// <summary>Notifications (Component5).</summary>
    public NotificationsVM Notifications => _agg.Component5!;
    /// <summary>Capability actions (Component6).</summary>
    public CapabilityActionsVM CapabilityActions => _agg.Component6!;
    /// <summary>
    /// Theme seam (THEME-001..005). Workspace-owned, not an aggregate child —
    /// the view binds <c>ThemeAdapter</c> to it at composition time so the
    /// scenario is exercised in the running app (VMX-129).
    /// </summary>
    public ThemeVM Theme => _theme;

    /// <summary>Token-paged all-notes search VM.</summary>
    public GlobalSearchVM GlobalSearch => _globalSearch;

    /// <summary>Public hub accessor.</summary>
    public IMessageHub Hub => _hub;

    /// <summary>Workspace name (proxied through the inner aggregate).</summary>
    public string Name => _agg.Name;

    /// <summary>Workspace lifecycle status.</summary>
    public VMx.Lifecycle.ConstructionStatus Status => _agg.Status;

    /// <summary>True once Construct has finished and all six children are Constructed.</summary>
    public bool IsConstructed => _agg.IsConstructed;

    /// <summary>Top-level toolbar command: add a notebook.</summary>
    public ICommand NewNotebookCommand { get; }

    /// <summary>Top-level toolbar command: add a note to the current notebook.</summary>
    public ICommand NewNoteCommand { get; }

    /// <summary>Top-level toolbar command: export workspace via the dialog service.</summary>
    public ICommand ExportCommand { get; }

    private object? _focused;
    private bool _disposed;

    private void TrackFocus(object? focused)
    {
        if (ReferenceEquals(_focused, focused)) return;
        _focused = focused;
        // CapabilityActions needs to refresh when focus changes.
        CapabilityActions.RecomputeActions();
        _commandTrigger.OnNext(System.Reactive.Unit.Default);
    }

    private WorkspaceVM(
        INoteRepository repo,
        IDialogService dialogService,
        INotificationHub notificationHub,
        IMessageHub hub,
        IDispatcher dispatcher,
        string name,
        string hint)
    {
        _repo = repo;
        _dialogService = dialogService;
        _notificationHub = notificationHub;
        _hub = hub;
        _dispatcher = dispatcher;

        // Pre-build the children so the StatusBar / CapabilityActions can
        // wire to live references. They're added to the aggregate via lazy
        // factories that simply return the pre-built instances.
        var notebooks = NotebooksRootVM.Builder()
            .Name("notebooks").Services(hub, dispatcher).Repository(repo)
            .NotificationHub(notificationHub)
            .Build();
        var notesView = NotesViewVM.Builder()
            .Name("notes").Services(hub, dispatcher).Repository(repo).PageSize(5)
            .SearchScheduler(TaskPoolScheduler.Default)
            .DialogService(dialogService)
            .NotificationHub(notificationHub)
            .Build();
        var noteForm = NoteFormVM.Builder()
            .Name("form").Services(hub, dispatcher).Repository(repo).NotificationHub(notificationHub).Build();
        var statusBar = StatusBarVM.Builder()
            .Name("status").Services(hub, dispatcher)
            .NotesView(notesView).Notebooks(notebooks).NoteForm(noteForm)
            .Build();
        var notifications = NotificationsVM.Builder()
            .Name("notifications").Services(hub, dispatcher)
            .NotificationHub(notificationHub)
            .Scheduler(DefaultScheduler.Instance)
            .Build();
        var capabilities = CapabilityActionsVM.Builder()
            .Name("capabilities").Services(hub, dispatcher)
            .FocusedGetter(() => _focused)
            .CanAddNote(() => IsConstructed && NotebooksRoot.Current is not null && !NotesView.CurrentNotebookIsReadOnly)
            .AddNoteAction(() => _ = AddNewNoteToCurrentAsync())
            .Build();
        var globalSearch = GlobalSearchVM.Builder()
            .Name("global-search").Services(hub, dispatcher)
            .Repository(repo)
            .PageSize(5)
            .SearchDebounce(TimeSpan.FromMilliseconds(150))
            .Build();

        _agg = AggregateVM6<
                NotebooksRootVM, NotesViewVM, NoteFormVM,
                StatusBarVM, NotificationsVM, CapabilityActionsVM>
            .Builder()
            .Name(name).Hint(hint).Services(hub, dispatcher)
            .Component1(() => notebooks)
            .Component2(() => notesView)
            .Component3(() => noteForm)
            .Component4(() => statusBar)
            .Component5(() => notifications)
            .Component6(() => capabilities)
            .Build();

        // VMX-129: build the workspace-owned theme seam on the shared services.
        _theme = ThemeVM.Builder()
            .Name("theme").Services(hub, dispatcher)
            .Build();
        _globalSearch = globalSearch;

        // Round-3 Critical-2: when the user selects a note in the centre
        // pane, rebind the right-pane editor so it shows the selected note's
        // fields. NotesListView two-way binds SelectedItem={Binding Current}
        // — observing the hub PropertyChanged for "Current" keeps the
        // observation off the leaf VMs and matches the StatusBarVM pattern.
        //
        // Round-4 Important-1: when Current transitions to null (e.g. the
        // selected note is deleted in NotesViewVM.DeleteNoteAsyncInternal,
        // or the host explicitly clears selection) the form must be
        // unbound — otherwise the right pane keeps the title/body of the
        // deleted note and Save would attempt to persist a ghost.
        //
        // Round-4 Important-2: marshal the handler onto the foreground
        // scheduler so BindTo/Unbind (which raise PropertyChanged for the
        // XAML binding engine) always run on the UI thread. Today Current
        // is set from XAML TwoWay binding (already UI-thread) so this is
        // defensive, but it brings parity with the foreground-marshalling
        // pattern the spec requires for PropertyChanged delivery (THR-001).
        // VMX-017: the typed `WhenPropertyChanged` hub helper replaces the
        // hand-rolled OfType/Where(ReferenceEquals + PropertyName) filter.
        _currentNoteSubscription = notesView.Hub
            .WhenPropertyChanged(notesView, nameof(NotesViewVM.Current))
            .ObserveOn(_dispatcher.Foreground)
            .Subscribe(_ =>
            {
                var current = notesView.Current;
                if (current is not null)
                {
                    noteForm.BindTo(current.Model);
                    TrackFocus(current);
                }
                else
                {
                    noteForm.Unbind();
                    TrackFocus(notebooks.Current);
                }
            });

        // Pass-6 real-wiring audit: mirror the _currentNoteSubscription
        // pattern for notebook selection — the tree's TwoWay SelectedItem
        // binding sets NotebooksRoot.Current, and everything downstream
        // (focus, capability projection, notes rebind) flows from here.
        _notebookSubscription = notebooks.Hub
            .WhenPropertyChanged(notebooks, nameof(NotebooksRootVM.Current))
            .ObserveOn(_dispatcher.Foreground)
            .Subscribe(msg =>
            {
                var nb = notebooks.Current;
                if (nb is null) return;
                notesView.CurrentNotebookIsReadOnly = nb.Model.IsReadOnly;
                TrackFocus(nb);
                _commandTrigger.OnNext(System.Reactive.Unit.Default);
                if (string.Equals(_requestedNotebookId, nb.Model.Id, StringComparison.Ordinal)) return;
                _requestedNotebookId = nb.Model.Id;
                _ = BindNotesObservedAsync(nb.Model.Id);
            });

        // Pass-6 real-wiring audit: row labels (Title proxy / star marker)
        // were construction-time snapshots and went stale after every save.
        _savedNoteSubscription = noteForm.OnSaved
            .ObserveOn(_dispatcher.Foreground)
            .Subscribe(notesView.RefreshNote);

        NewNotebookCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed)
            .Task(() => _ = NotebooksRoot.AddNotebookAsync(parentId: null, name: "New Notebook"))
            .Triggers(_commandTrigger)
            .Build();
        NewNoteCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed && NotebooksRoot.Current is not null)
            .Task(() => _ = AddNewNoteToCurrentAsync())
            .Triggers(_commandTrigger)
            .Build();
        ExportCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed)
            .Task(() => _ = ExportInternalAsync())
            .Triggers(_commandTrigger)
            .Build();
    }

    private async Task BindNotesObservedAsync(string notebookId)
    {
        try
        {
            await NotesView.BindToAsync(notebookId).ConfigureAwait(false);
        }
        catch
        {
            // A failed bind must not pin _requestedNotebookId to the failed
            // id (the notebook would become permanently unselectable), and
            // the fire-and-forget discard must not leave the fault
            // unobserved (pass-7 review).
            if (string.Equals(_requestedNotebookId, notebookId, StringComparison.Ordinal))
            {
                _requestedNotebookId = null;
            }
        }
    }

    private async Task AddNewNoteToCurrentAsync()
    {
        var nb = NotebooksRoot.Current;
        if (nb is null) return;
        var note = new NoteModel(
            // "note-" + 5 random hex chars (10 chars total). See NotebooksRootVM
            // for the same suffix-length convention.
            Id: $"note-{Guid.NewGuid():N}"[..10],
            NotebookId: nb.Model.Id,
            Title: "Untitled",
            Tags: Array.Empty<string>(),
            Body: string.Empty,
            Starred: false,
            CreatedAt: DateTimeOffset.UtcNow,
            UpdatedAt: DateTimeOffset.UtcNow);
        await _repo.SaveNoteAsync(note).ConfigureAwait(false);
        await NotesView.BindToAsync(nb.Model.Id).ConfigureAwait(false);
    }

    private async Task ExportInternalAsync()
    {
        var path = await _dialogService.PickFileToSave(
            filter: null, title: "Export workspace", suggestedName: "notes-export.json")
            .ConfigureAwait(false);
        if (string.IsNullOrEmpty(path)) return;
        var (nbs, notes) = await _repo.LoadAllAsync().ConfigureAwait(false);
        await _repo.ExportAsync(nbs, notes, path).ConfigureAwait(false);
    }

    /// <summary>Synchronous construct — synchronous OnConstruct cascade.</summary>
    public void Construct()
    {
        _agg.Construct();
        _theme.Construct();
        _globalSearch.Construct();
    }

    /// <summary>
    /// Async construct: build the aggregate, populate notebooks, set the first
    /// root as current, and bind the notes view to it.
    /// </summary>
    public async Task ConstructAsync()
    {
        _agg.Construct();
        _theme.Construct();
        _globalSearch.Construct();
        await NotebooksRoot.PopulateAsync().ConfigureAwait(false);
        var first = NotebooksRoot.Roots.FirstOrDefault();
        if (first is not null)
        {
            // Bind BEFORE assigning Current (the notebook subscription
            // dedupes on _requestedNotebookId), and marshal the
            // INPC-raising tail — this continuation runs on a pool thread
            // after ConfigureAwait(false) and Current feeds a TwoWay
            // TreeView binding (real-wiring audit, pass 6).
            _requestedNotebookId = first.Model.Id;
            await NotesView.BindToAsync(first.Model.Id).ConfigureAwait(false);
            await NoteForm.RefreshTagSuggestionsAsync().ConfigureAwait(false);
            _dispatcher.Foreground.Schedule(() =>
            {
                if (_disposed) return; // queued tail may outlive the workspace
                NotesView.CurrentNotebookIsReadOnly = first.Model.IsReadOnly;
                NotebooksRoot.Current = first;
                TrackFocus(first);
                _commandTrigger.OnNext(System.Reactive.Unit.Default);
            });
        }
        else
        {
            _dispatcher.Foreground.Schedule(() =>
            {
                if (_disposed) return;
                _commandTrigger.OnNext(System.Reactive.Unit.Default);
            });
        }
    }

    /// <summary>Set the currently-focused VM (for capability-action projection).</summary>
    public void SetFocus(object focused) => TrackFocus(focused);

    /// <summary>Destructs the workspace, the theme seam, and all six children (cascade per ADR-0034).</summary>
    public void Destruct()
    {
        _theme.Destruct();
        _globalSearch.Destruct();
        _agg.Destruct();
    }

    /// <inheritdoc/>
    public void Dispose()
    {
        _disposed = true;
        _currentNoteSubscription.Dispose();
        _notebookSubscription.Dispose();
        _savedNoteSubscription.Dispose();
        _commandTrigger.OnCompleted();
        _commandTrigger.Dispose();
        (NewNotebookCommand as IDisposable)?.Dispose();
        (NewNoteCommand as IDisposable)?.Dispose();
        (ExportCommand as IDisposable)?.Dispose();
        _theme.Dispose();
        _globalSearch.Dispose();
        _agg.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static WorkspaceVMBuilder Builder() => WorkspaceVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class WorkspaceVMBuilder
    {
        private readonly string _name;
        private readonly string _hint;
        private readonly INoteRepository? _repo;
        private readonly IDialogService? _dialogService;
        private readonly INotificationHub? _notificationHub;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;

        internal static readonly WorkspaceVMBuilder Empty = new();
        private WorkspaceVMBuilder()
        {
            _name = "workspace";
            _hint = "";
        }
        private WorkspaceVMBuilder(
            string name, string hint,
            INoteRepository? repo, IDialogService? dialogService,
            INotificationHub? notificationHub,
            IMessageHub? hub, IDispatcher? dispatcher)
        {
            _name = name; _hint = hint;
            _repo = repo; _dialogService = dialogService;
            _notificationHub = notificationHub;
            _hub = hub; _dispatcher = dispatcher;
        }

        /// <summary>Sets the optional VM Name (default: "workspace").</summary>
        public WorkspaceVMBuilder Name(string name) => new(name, _hint, _repo, _dialogService, _notificationHub, _hub, _dispatcher);
        /// <summary>Sets the optional Hint.</summary>
        public WorkspaceVMBuilder Hint(string hint) => new(_name, hint, _repo, _dialogService, _notificationHub, _hub, _dispatcher);
        /// <summary>Sets the required Repository.</summary>
        public WorkspaceVMBuilder Repository(INoteRepository repo) => new(_name, _hint, repo, _dialogService, _notificationHub, _hub, _dispatcher);
        /// <summary>Sets the optional DialogService (default: <see cref="NullDialogService.Instance"/>).</summary>
        public WorkspaceVMBuilder DialogService(IDialogService dialogService) => new(_name, _hint, _repo, dialogService, _notificationHub, _hub, _dispatcher);
        /// <summary>Sets the optional NotificationHub (default: <see cref="NullNotificationHub.Instance"/>).</summary>
        public WorkspaceVMBuilder NotificationHub(INotificationHub notificationHub) => new(_name, _hint, _repo, _dialogService, notificationHub, _hub, _dispatcher);
        /// <summary>Sets the optional MessageHub (default: a fresh <see cref="MessageHub"/>).</summary>
        public WorkspaceVMBuilder MessageHub(IMessageHub hub) => new(_name, _hint, _repo, _dialogService, _notificationHub, hub, _dispatcher);
        /// <summary>Sets the optional Dispatcher (default: <see cref="RxDispatcher.Immediate"/>).</summary>
        public WorkspaceVMBuilder Dispatcher(IDispatcher dispatcher) => new(_name, _hint, _repo, _dialogService, _notificationHub, _hub, dispatcher);

        /// <summary>Builds the VM after validation. Composes sensible defaults for optional services.</summary>
        public WorkspaceVM Build()
        {
            BuilderValidationException.Require(_repo, "Repository");
            return new WorkspaceVM(
                _repo!,
                _dialogService ?? NullDialogService.Instance,
                _notificationHub ?? new NotificationHub(),
                _hub ?? new VMx.Services.MessageHub(),
                _dispatcher ?? RxDispatcher.Immediate(),
                _name,
                _hint);
        }
    }
}
