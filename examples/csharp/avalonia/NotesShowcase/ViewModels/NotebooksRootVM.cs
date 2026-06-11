using System.Collections.ObjectModel;
using System.Reactive.Concurrency;
using System.Windows.Input;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Notifications;
using VMx.Services;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Root of the notebooks tree.
///
/// VMx-API adaptation (plan §3.a.7): the plan asked for
/// <c>HierarchicalVM&lt;NotebookModel, NotebookVM&gt;</c>, but
/// <see cref="HierarchicalVM{TModel,TVM}"/> materializes its children from a
/// factory at construct time and is awkward to mutate dynamically (it has
/// <c>AddChild</c>, but no first-class "current selection" / "walk" surface
/// the plan assumed). Instead we own a flat list of <see cref="NotebookVM"/>
/// instances, exposing <see cref="Roots"/> and <see cref="Walk"/> for the
/// view; <see cref="AddNotebookAsync"/> persists via the repo and re-publishes
/// a <see cref="TreeStructureChangedMessage"/> on the hub so subscribers
/// observe structural changes the same way they would on
/// <see cref="HierarchicalVM{TModel,TVM}"/>.
/// </summary>
public sealed class NotebooksRootVM
    : ComponentVMBase,
      INewCreatable,
      IReconstructable
{
    private readonly INoteRepository _repo;
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;
    private readonly INotificationHub? _notificationHub;
    private readonly ObservableCollection<NotebookVM> _all = new();
    private NotebookVM? _current;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>All notebooks (flat, ordered).</summary>
    public ObservableCollection<NotebookVM> All => _all;

    /// <summary>Root notebooks (no parent).</summary>
    public IReadOnlyList<NotebookVM> Roots
        => _all.Where(nb => nb.Model.ParentId is null).ToList();

    /// <summary>Iterates every notebook in the tree (parents-before-children, repo order).</summary>
    public IEnumerable<NotebookVM> Walk() => _all;

    /// <summary>Children of <paramref name="parent"/> (by ParentId).</summary>
    public IReadOnlyList<NotebookVM> ChildrenOf(NotebookVM parent)
        => _all.Where(nb => nb.Model.ParentId == parent.Model.Id).ToList();

    /// <summary>Currently selected notebook (two-way bindable).</summary>
    public NotebookVM? Current
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

    // ── INewCreatable ──────────────────────────────────────────────────────

    /// <inheritdoc/>
    public bool CanCreateNew() => Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <inheritdoc/>
    public void CreateNew()
    {
        // Synchronous capability — schedules a default "New Notebook" via fire-and-forget.
        _ = AddNotebookAsync(parentId: null, name: "New Notebook");
    }

    /// <summary>
    /// View-facing command parity with the plan: bound to a toolbar button.
    /// Same default behavior as <see cref="CreateNew"/>.
    /// </summary>
    public ICommand AddNotebookCommand { get; }

    /// <summary>
    /// Persists a new notebook via the repository and re-publishes a
    /// <see cref="TreeStructureChangedMessage"/> so subscribers refresh.
    /// </summary>
    public async Task AddNotebookAsync(string? parentId, string name, CancellationToken ct = default)
    {
        // "nb-" + 5 random hex chars (8 chars total). Same suffix length as
        // notes ("note-" + 5 chars = 10 total) — only the prefix differs.
        var id = $"nb-{Guid.NewGuid():N}"[..8];
        var model = new NotebookModel(id, name, parentId);
        await _repo.AddNotebookAsync(model, ct).ConfigureAwait(false);
        var vm = NotebookVM.Builder()
            .Name($"nb:{id}")
            .Model(model)
            .Services(_hub, _dispatcher)
            .ChildrenGetter(ChildrenOf)
            .Build();
        vm.Construct();
        _all.Add(vm);
        // Phase 5.a binding gap #2: tell the new VM's parent (if any) to
        // refresh its Children view so an already-bound TreeView picks up
        // the new nested node.
        if (parentId is not null)
        {
            var parent = _all.FirstOrDefault(nb => nb.Model.Id == parentId);
            parent?.NotifyChildrenChanged();
        }
        else
        {
            // Root-level add: Roots is a computed snapshot, so an
            // already-bound TreeView only re-reads it on an explicit raise.
            // Marshal to the foreground — this continuation runs off the UI
            // thread after ConfigureAwait(false).
            _dispatcher.Foreground.Schedule(() => RaisePropertyChanged(nameof(Roots)));
        }
        // Index is the new tail of _all (we just appended).
        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: TreeStructureChange.Added,
            Affected: vm,
            Index: _all.Count - 1));
        // Spec §6.2: publish a "Notebook added" notification so the toast
        // region surfaces it. No-op when no hub is wired.
        if (_notificationHub is not null)
        {
            _ = _notificationHub.Post(new Notification(
                NotificationType.Notification,
                $"Notebook added: “{name}”"));
        }
    }

    /// <summary>
    /// Loads notebooks from the repository, replaces the internal collection,
    /// and constructs each child VM. Called by <see cref="WorkspaceVM"/> during
    /// async OnConstruct (plan §3.a.11).
    /// </summary>
    public async Task PopulateAsync(CancellationToken ct = default)
    {
        var (notebooks, _) = await _repo.LoadAllAsync(ct).ConfigureAwait(false);

        // Dispose previous children before replacing.
        foreach (var prev in _all) prev.Dispose();
        _all.Clear();
        _current = null;

        foreach (var nb in notebooks)
        {
            var vm = NotebookVM.Builder()
                .Name($"nb:{nb.Id}")
                .Model(nb)
                .Services(_hub, _dispatcher)
                .ChildrenGetter(ChildrenOf)
                .Build();
            vm.Construct();
            _all.Add(vm);
        }

        // Reset notification — subscribers refresh their tree projections.
        Hub.Send(new TreeStructureChangedMessage(
            Source: this,
            Change: TreeStructureChange.Added,
            Affected: this,
            Index: -1));

        // Roots is a computed snapshot: a TreeView bound before this populate
        // completed (the App sets DataContext without awaiting ConstructAsync)
        // only re-reads it on an explicit raise. Marshal to the foreground —
        // this continuation runs off the UI thread after ConfigureAwait(false).
        _dispatcher.Foreground.Schedule(() => RaisePropertyChanged(nameof(Roots)));
    }

    private NotebooksRootVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        INoteRepository repo,
        INotificationHub? notificationHub)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _repo = repo;
        _hub = hub;
        _dispatcher = dispatcher;
        _notificationHub = notificationHub;

        AddNotebookCommand = RelayCommand.Builder()
            .Predicate(CanCreateNew)
            .Task(CreateNew)
            .Build();
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        foreach (var nb in _all) nb.Destruct();
        base.OnDestruct();
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        foreach (var nb in _all) nb.Dispose();
        (AddNotebookCommand as IDisposable)?.Dispose();
        base.OnDispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static NotebooksRootVMBuilder Builder() => NotebooksRootVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class NotebooksRootVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly INoteRepository? _repo;
        private readonly INotificationHub? _notificationHub;

        internal static readonly NotebooksRootVMBuilder Empty = new();
        private NotebooksRootVMBuilder() { _hint = ""; }
        private NotebooksRootVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher, INoteRepository? repo,
            INotificationHub? notificationHub)
        {
            _name = name; _hint = hint; _hub = hub; _dispatcher = dispatcher;
            _repo = repo; _notificationHub = notificationHub;
        }

        /// <summary>Sets the required Name.</summary>
        public NotebooksRootVMBuilder Name(string name) => new(name, _hint, _hub, _dispatcher, _repo, _notificationHub);
        /// <summary>Sets the optional Hint.</summary>
        public NotebooksRootVMBuilder Hint(string hint) => new(_name, hint, _hub, _dispatcher, _repo, _notificationHub);
        /// <summary>Sets the required Services.</summary>
        public NotebooksRootVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _repo, _notificationHub);
        /// <summary>Sets the required repository.</summary>
        public NotebooksRootVMBuilder Repository(INoteRepository repo)
            => new(_name, _hint, _hub, _dispatcher, repo, _notificationHub);
        /// <summary>
        /// Sets the optional notification hub. When set,
        /// <see cref="AddNotebookAsync"/> publishes a "Notebook added"
        /// notification (spec §6.2).
        /// </summary>
        public NotebooksRootVMBuilder NotificationHub(INotificationHub notificationHub)
            => new(_name, _hint, _hub, _dispatcher, _repo, notificationHub);

        /// <summary>Builds the VM after validation.</summary>
        public NotebooksRootVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_repo, "Repository");
            return new NotebooksRootVM(_name!, _hint, _hub!, _dispatcher!, _repo!, _notificationHub);
        }
    }
}
