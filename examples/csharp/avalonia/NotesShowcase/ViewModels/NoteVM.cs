using System.Windows.Input;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
using VMx.Notifications;
using VMx.Services;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Leaf VM for a single note.
///
/// Capabilities (plan §3.a.6, scenario §6.2):
///   <see cref="ISelectable"/>, <see cref="IClosable"/>,
///   <see cref="IDeletable{NoteVM}"/>, <see cref="ISavable{NoteVM}"/>,
///   <see cref="IReconstructable"/>.
///
/// <see cref="CloseCommand"/> invokes a host-supplied close callback (the host
/// wires it to <c>NotesViewVM.Current = null</c> so the form clears). This
/// avoids back-references from the leaf to its container.
/// </summary>
public sealed class NoteVM
    : ComponentVMBase,
      ISelectable,
      IClosable,
      IDeletable<NoteVM>,
      ISavable<NoteVM>,
      IReconstructable
{
    private readonly Action<NoteVM>? _onClose;
    private readonly Func<NoteVM, Task>? _onDelete;
    private readonly Func<NoteVM, Task>? _onSave;
    private readonly Func<NoteVM, Task<bool>>? _confirmDelete;
    private readonly INotificationHub? _notificationHub;
    private readonly AsyncRelayCommand _innerDeleteCommand;
    private NoteModel _model;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor — see <see cref="NotebookVM.Hub"/> for rationale.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>Current note model. Equality-guarded setter — emits hub messages on change.</summary>
    public NoteModel Model
    {
        get => _model;
        set
        {
            if (EqualityComparer<NoteModel>.Default.Equals(_model, value)) return;
            var oldTitle = _model.Title;
            var oldStarred = _model.Starred;
            _model = value;
            NotifyPropertyChanged(nameof(Model));
            if (!string.Equals(oldTitle, value.Title, StringComparison.Ordinal))
            {
                NotifyPropertyChanged(nameof(Title));
            }
            if (oldStarred != value.Starred)
            {
                NotifyPropertyChanged(nameof(Starred));
            }
        }
    }

    /// <summary>Note id (proxy on <see cref="Model"/>).</summary>
    public string NoteId => _model.Id;

    /// <summary>Note title (proxy on <see cref="Model"/>).</summary>
    public string Title => _model.Title;

    /// <summary>Note body (proxy on <see cref="Model"/>).</summary>
    public string Body => _model.Body;

    /// <summary>Whether the note is starred (proxy on <see cref="Model"/>).</summary>
    public bool Starred => _model.Starred;

    /// <summary>Tag list (proxy on <see cref="Model"/>).</summary>
    public IReadOnlyList<string> Tags => _model.Tags;

    // ── IClosable / IDeletable / ISavable ──────────────────────────────────

    /// <inheritdoc cref="IClosable.CanClose"/>
    public bool CanClose() => Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <inheritdoc cref="IClosable.Close"/>
    public void Close() => _onClose?.Invoke(this);

    /// <inheritdoc cref="IDeletable{T}.CanDelete"/>
    public bool CanDelete(NoteVM item) => ReferenceEquals(item, this) && Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <inheritdoc cref="IDeletable{T}.Delete"/>
    public void Delete(NoteVM item)
    {
        if (!CanDelete(item)) return;
        _innerDeleteCommand.Execute(null);
    }

    /// <inheritdoc cref="ISavable{T}.CanSave"/>
    public bool CanSave(NoteVM item) => ReferenceEquals(item, this) && Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <inheritdoc cref="ISavable{T}.Save"/>
    public void Save(NoteVM item)
    {
        if (!CanSave(item)) return;
        SaveCommand.Execute(null);
    }

    /// <summary>
    /// Convenience command wrapper for <see cref="Close"/> — the view binds
    /// <see cref="CloseCommand"/> directly without going through capability
    /// dispatch.
    /// </summary>
    public ICommand CloseCommand { get; }

    /// <summary>Convenience command wrapper for <see cref="Save"/>.</summary>
    public ICommand SaveCommand { get; }

    /// <summary>Convenience command wrapper for <see cref="Delete"/>.</summary>
    public ICommand DeleteCommand { get; }

    private NoteVM(
        string name,
        string hint,
        NoteModel model,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action<NoteVM>? onClose,
        Func<NoteVM, Task>? onDelete,
        Func<NoteVM, Task>? onSave,
        Func<NoteVM, Task<bool>>? confirmDelete,
        INotificationHub? notificationHub)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _model = model;
        _onClose = onClose;
        _onDelete = onDelete;
        _onSave = onSave;
        _confirmDelete = confirmDelete;
        _notificationHub = notificationHub;

        CloseCommand = RelayCommand.Builder()
            .Predicate(CanClose)
            .Task(Close)
            .Build();
        SaveCommand = AsyncRelayCommand.Builder()
            .Predicate(() => CanSave(this))
            .Task(_ => PerformSaveAsync(this))
            .Build();
        // Spec §5.2.8 / §6.2: Delete must be a ConfirmationDecoratorCommand.
        // When a confirm delegate is wired, wrap the inner delete command; if
        // accepted, post a "Note deleted" notification (if a hub is wired) and
        // invoke the host delete callback. Without a confirm delegate the
        // command stays plain — preserves tests that exercise the raw delete
        // path (e.g. NoteVMTests.DeleteCommand_invokes_OnDelete_callback).
        _innerDeleteCommand = AsyncRelayCommand.Builder()
            .Predicate(() => CanDelete(this))
            .Task(_ => PerformDeleteAsync(this))
            .Build();
        DeleteCommand = _confirmDelete is null
            ? _innerDeleteCommand
            : new ConfirmationDecoratorCommand(_innerDeleteCommand, () => _confirmDelete(this));
    }

    private async Task PerformDeleteAsync(NoteVM item)
    {
        if (!CanDelete(item)) return;
        if (_onDelete is not null)
            await _onDelete(item).ConfigureAwait(false);
        if (_notificationHub is not null)
        {
            _ = _notificationHub.Post(new Notification(
                NotificationType.Notification,
                $"Note deleted: “{item.Title}”"));
        }
    }

    private async Task PerformSaveAsync(NoteVM item)
    {
        if (!CanSave(item)) return;
        if (_onSave is not null)
            await _onSave(item).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        (CloseCommand as IDisposable)?.Dispose();
        (SaveCommand as IDisposable)?.Dispose();
        // Dispose the decorator (detaches its CanExecuteChanged relay) AND the
        // inner RelayCommand: ConfirmationDecoratorCommand.Dispose does not
        // dispose its inner command, so disposing only DeleteCommand would leak
        // the inner command in the decorated path. Idempotent when DeleteCommand
        // IS the inner (no confirm delegate wired).
        (DeleteCommand as IDisposable)?.Dispose();
        (_innerDeleteCommand as IDisposable)?.Dispose();
        base.OnDispose();
    }

    /// <summary>Returns a new empty builder for <see cref="NoteVM"/>.</summary>
    public static NoteVMBuilder Builder() => NoteVMBuilder.Empty;

    /// <summary>Immutable fluent builder (spec ch. 10).</summary>
    public sealed class NoteVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly NoteModel? _model;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Action<NoteVM>? _onClose;
        private readonly Func<NoteVM, Task>? _onDelete;
        private readonly Func<NoteVM, Task>? _onSave;
        private readonly Func<NoteVM, Task<bool>>? _confirmDelete;
        private readonly INotificationHub? _notificationHub;

        internal static readonly NoteVMBuilder Empty = new();

        private NoteVMBuilder() { _hint = ""; }

        private NoteVMBuilder(
            string? name, string hint, NoteModel? model,
            IMessageHub? hub, IDispatcher? dispatcher,
            Action<NoteVM>? onClose, Func<NoteVM, Task>? onDelete, Func<NoteVM, Task>? onSave,
            Func<NoteVM, Task<bool>>? confirmDelete, INotificationHub? notificationHub)
        {
            _name = name; _hint = hint; _model = model;
            _hub = hub; _dispatcher = dispatcher;
            _onClose = onClose; _onDelete = onDelete; _onSave = onSave;
            _confirmDelete = confirmDelete; _notificationHub = notificationHub;
        }

        /// <summary>Sets the required Name.</summary>
        public NoteVMBuilder Name(string name) => new(name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets the optional Hint.</summary>
        public NoteVMBuilder Hint(string hint) => new(_name, hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets the required note model.</summary>
        public NoteVMBuilder Model(NoteModel model) => new(_name, _hint, model, _hub, _dispatcher, _onClose, _onDelete, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets the required Services.</summary>
        public NoteVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, _model, hub, dispatcher, _onClose, _onDelete, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets the optional close callback (NotesViewVM.Current = null).</summary>
        public NoteVMBuilder OnClose(Action<NoteVM> handler) => new(_name, _hint, _model, _hub, _dispatcher, handler, _onDelete, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets a synchronous delete callback.</summary>
        public NoteVMBuilder OnDelete(Action<NoteVM> handler) =>
            OnDelete(vm => { handler(vm); return Task.CompletedTask; });
        /// <summary>Sets an asynchronous delete callback (route to repo).</summary>
        public NoteVMBuilder OnDelete(Func<NoteVM, Task> handler) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, handler, _onSave, _confirmDelete, _notificationHub);
        /// <summary>Sets a synchronous save callback.</summary>
        public NoteVMBuilder OnSave(Action<NoteVM> handler) =>
            OnSave(vm => { handler(vm); return Task.CompletedTask; });
        /// <summary>Sets an asynchronous save callback (route to repo).</summary>
        public NoteVMBuilder OnSave(Func<NoteVM, Task> handler) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, handler, _confirmDelete, _notificationHub);
        /// <summary>
        /// Sets the optional confirm-delete delegate (spec §5.2.8 / §6.2).
        /// When set, <see cref="DeleteCommand"/> is wrapped in a
        /// <see cref="ConfirmationDecoratorCommand"/> that awaits this delegate
        /// before invoking the inner delete. Typically wires to
        /// <c>IDialogService.Confirm($"Delete “{n.Title}”?")</c> — matches the
        /// curly-quote emission used by NotesViewVM (and the Py/TS flavors).
        /// </summary>
        public NoteVMBuilder ConfirmDelete(Func<NoteVM, Task<bool>> confirm) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave, confirm, _notificationHub);
        /// <summary>
        /// Sets the optional notification hub. When set, a successful delete
        /// (i.e. one that survived the confirm gate, if any) publishes a
        /// "Note deleted" notification.
        /// </summary>
        public NoteVMBuilder NotificationHub(INotificationHub hub) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave, _confirmDelete, hub);

        /// <summary>Builds the VM after validating required fields.</summary>
        public NoteVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_model, "Model");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            return new NoteVM(_name!, _hint, _model!, _hub!, _dispatcher!, _onClose, _onDelete, _onSave, _confirmDelete, _notificationHub);
        }
    }
}
