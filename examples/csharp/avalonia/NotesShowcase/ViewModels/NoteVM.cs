using System.Windows.Input;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
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
    private readonly Action<NoteVM>? _onDelete;
    private readonly Action<NoteVM>? _onSave;
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
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Model)));
            RaisePropertyChanged(nameof(Model));
            if (!string.Equals(oldTitle, value.Title, StringComparison.Ordinal))
            {
                Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Title)));
                RaisePropertyChanged(nameof(Title));
            }
            if (oldStarred != value.Starred)
            {
                Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Starred)));
                RaisePropertyChanged(nameof(Starred));
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
        _onDelete?.Invoke(item);
    }

    /// <inheritdoc cref="ISavable{T}.CanSave"/>
    public bool CanSave(NoteVM item) => ReferenceEquals(item, this) && Status == VMx.Lifecycle.ConstructionStatus.Constructed;

    /// <inheritdoc cref="ISavable{T}.Save"/>
    public void Save(NoteVM item)
    {
        if (!CanSave(item)) return;
        _onSave?.Invoke(item);
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
        Action<NoteVM>? onDelete,
        Action<NoteVM>? onSave)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _model = model;
        _onClose = onClose;
        _onDelete = onDelete;
        _onSave = onSave;

        CloseCommand = RelayCommand.Builder()
            .Predicate(CanClose)
            .Task(Close)
            .Build();
        SaveCommand = RelayCommand.Builder()
            .Predicate(() => CanSave(this))
            .Task(() => Save(this))
            .Build();
        DeleteCommand = RelayCommand.Builder()
            .Predicate(() => CanDelete(this))
            .Task(() => Delete(this))
            .Build();
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        (CloseCommand as IDisposable)?.Dispose();
        (SaveCommand as IDisposable)?.Dispose();
        (DeleteCommand as IDisposable)?.Dispose();
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
        private readonly Action<NoteVM>? _onDelete;
        private readonly Action<NoteVM>? _onSave;

        internal static readonly NoteVMBuilder Empty = new();

        private NoteVMBuilder() { _hint = ""; }

        private NoteVMBuilder(
            string? name, string hint, NoteModel? model,
            IMessageHub? hub, IDispatcher? dispatcher,
            Action<NoteVM>? onClose, Action<NoteVM>? onDelete, Action<NoteVM>? onSave)
        {
            _name = name; _hint = hint; _model = model;
            _hub = hub; _dispatcher = dispatcher;
            _onClose = onClose; _onDelete = onDelete; _onSave = onSave;
        }

        /// <summary>Sets the required Name.</summary>
        public NoteVMBuilder Name(string name) => new(name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave);
        /// <summary>Sets the optional Hint.</summary>
        public NoteVMBuilder Hint(string hint) => new(_name, hint, _model, _hub, _dispatcher, _onClose, _onDelete, _onSave);
        /// <summary>Sets the required note model.</summary>
        public NoteVMBuilder Model(NoteModel model) => new(_name, _hint, model, _hub, _dispatcher, _onClose, _onDelete, _onSave);
        /// <summary>Sets the required Services.</summary>
        public NoteVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, _model, hub, dispatcher, _onClose, _onDelete, _onSave);
        /// <summary>Sets the optional close callback (NotesViewVM.Current = null).</summary>
        public NoteVMBuilder OnClose(Action<NoteVM> handler) => new(_name, _hint, _model, _hub, _dispatcher, handler, _onDelete, _onSave);
        /// <summary>Sets the optional delete callback (route to repo).</summary>
        public NoteVMBuilder OnDelete(Action<NoteVM> handler) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, handler, _onSave);
        /// <summary>Sets the optional save callback (route to repo).</summary>
        public NoteVMBuilder OnSave(Action<NoteVM> handler) => new(_name, _hint, _model, _hub, _dispatcher, _onClose, _onDelete, handler);

        /// <summary>Builds the VM after validating required fields.</summary>
        public NoteVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_model, "Model");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            return new NoteVM(_name!, _hint, _model!, _hub!, _dispatcher!, _onClose, _onDelete, _onSave);
        }
    }
}
