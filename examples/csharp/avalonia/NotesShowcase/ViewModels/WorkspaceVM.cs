using System.Reactive.Concurrency;
using System.Reactive.Linq;
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

    // Round-3 Critical-2: subscription that rebinds NoteForm whenever
    // NotesView.Current changes (e.g. user clicks a different note in the
    // list). Without this the right-pane editor stays empty in the running
    // app — unit tests called BindTo directly, masking the gap.
    private readonly IDisposable _currentNoteSubscription;

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

    private void TrackFocus(object focused)
    {
        if (ReferenceEquals(_focused, focused)) return;
        _focused = focused;
        // CapabilityActions needs to refresh when focus changes.
        CapabilityActions.RecomputeActions();
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
        _currentNoteSubscription = notesView.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, notesView)
                && string.Equals(m.PropertyName, nameof(NotesViewVM.Current), StringComparison.Ordinal))
            .ObserveOn(_dispatcher.Foreground)
            .Subscribe(_ =>
            {
                var current = notesView.Current;
                if (current is not null)
                {
                    noteForm.BindTo(current.Model);
                }
                else
                {
                    noteForm.Unbind();
                }
            });

        NewNotebookCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed)
            .Task(() => _ = NotebooksRoot.AddNotebookAsync(parentId: null, name: "New Notebook"))
            .Build();
        NewNoteCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed && NotebooksRoot.Current is not null)
            .Task(() => _ = AddNewNoteToCurrentAsync())
            .Build();
        ExportCommand = RelayCommand.Builder()
            .Predicate(() => IsConstructed)
            .Task(() => _ = ExportInternalAsync())
            .Build();
    }

    private async Task AddNewNoteToCurrentAsync()
    {
        var nb = NotebooksRoot.Current;
        if (nb is null) return;
        var note = new NoteModel(
            Id: $"note-{Guid.NewGuid():N}".Substring(0, 10),
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
    public void Construct() => _agg.Construct();

    /// <summary>
    /// Async construct: build the aggregate, populate notebooks, set the first
    /// root as current, and bind the notes view to it.
    /// </summary>
    public async Task ConstructAsync()
    {
        _agg.Construct();
        await NotebooksRoot.PopulateAsync().ConfigureAwait(false);
        var first = NotebooksRoot.Roots.FirstOrDefault();
        if (first is not null)
        {
            NotebooksRoot.Current = first;
            TrackFocus(first);
            await NotesView.BindToAsync(first.Model.Id).ConfigureAwait(false);
        }
    }

    /// <summary>Set the currently-focused VM (for capability-action projection).</summary>
    public void SetFocus(object focused) => TrackFocus(focused);

    /// <summary>Destructs the workspace and all six children (cascade per ADR-0034).</summary>
    public void Destruct() => _agg.Destruct();

    /// <inheritdoc/>
    public void Dispose()
    {
        _currentNoteSubscription.Dispose();
        (NewNotebookCommand as IDisposable)?.Dispose();
        (NewNoteCommand as IDisposable)?.Dispose();
        (ExportCommand as IDisposable)?.Dispose();
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
