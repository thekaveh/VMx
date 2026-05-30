using System.Windows.Input;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using VMx.Notifications;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// VM for the note editor pane.
///
/// VMx-API adaptation (plan §3.a.9): the plan asked to subclass
/// <c>FormVM&lt;NoteModel&gt;</c>, but <see cref="FormVM{TM}"/> is sealed.
/// Composition instead: this VM owns a <see cref="FormVM{TM}"/> in strict mode
/// and exposes its <see cref="Draft"/>, <see cref="Snapshot"/>,
/// <see cref="IsDirty"/>, <see cref="ApproveCommand"/>, <see cref="DenyCommand"/>
/// surface directly, layered with <see cref="IsValid"/>, tag mutation commands,
/// and a "Saved" notification post-approve.
/// </summary>
public sealed class NoteFormVM : ComponentVMBase, IReconstructable
{
    private readonly INoteRepository _repo;
    private readonly INotificationHub? _notificationHub;
    private FormVM<NoteModel>? _form;
    private NoteModel? _bound;
    private string _tagDraft = string.Empty;
    private bool _ownDisposed;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>True once a note is bound (form constructed).</summary>
    public bool HasBoundNote => _form is not null;

    /// <summary>
    /// Live, editable note (the form's mutable model). Returns the original
    /// bound note before <see cref="BindTo"/> has been called.
    /// </summary>
    public NoteModel Draft
    {
        get => _form?.Model ?? _bound ?? Empty;
        set
        {
            if (_form is null) return;
            _form.SetModel(value);
            EmitDraftChanges();
        }
    }

    /// <summary>The form's snapshot (advances on each successful Approve).</summary>
    public NoteModel Snapshot => _form?.Snapshot ?? _bound ?? Empty;

    /// <summary>True when the draft differs from the snapshot.</summary>
    public bool IsDirty => _form?.IsDirty ?? false;

    /// <summary>True when the draft passes validation (non-empty title).</summary>
    public bool IsValid => !string.IsNullOrWhiteSpace(Draft.Title);

    /// <summary>Approve = persist via repo + publish "Saved" notification.</summary>
    public ICommand ApproveCommand { get; }

    /// <summary>Deny = revert draft to snapshot.</summary>
    public ICommand DenyCommand => _form?.DenyCommand ?? _noopCommand;

    private static readonly ICommand _noopCommand = RelayCommand.Builder().Build();

    /// <summary>Buffer text for "add tag" input.</summary>
    public string TagDraft
    {
        get => _tagDraft;
        set
        {
            if (string.Equals(_tagDraft, value, StringComparison.Ordinal)) return;
            _tagDraft = value;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(TagDraft)));
            RaisePropertyChanged(nameof(TagDraft));
        }
    }

    /// <summary>Append <see cref="TagDraft"/> to the draft's tag list.</summary>
    public ICommand AddTagCommand { get; }

    /// <summary>Remove a tag from the draft's tag list.</summary>
    public ICommand RemoveTagCommand { get; }

    /// <summary>
    /// Binds the form to <paramref name="note"/> (creates / replaces the inner
    /// <see cref="FormVM{TM}"/> with a fresh snapshot).
    /// </summary>
    public void BindTo(NoteModel note)
    {
        _form?.Dispose();
        _bound = note;
        _form = new FormVM<NoteModel>(
            initial: note,
            persister: PersistAsync,
            hub: Hub,
            strict: true);
        EmitDraftChanges();
    }

    /// <summary>
    /// Awaitable approve cycle — persists via the repo and (on success)
    /// publishes a "Saved" notification. Useful in tests.
    /// </summary>
    public async Task ApproveAsync()
    {
        if (_form is null) return;
        await _form.ApproveAsync().ConfigureAwait(false);
        EmitDraftChanges();
        if (_notificationHub is not null)
        {
            _ = _notificationHub.Post(new Notification(
                NotificationType.Notification,
                $"Saved “{_form.Snapshot.Title}”"));
        }
    }

    private async Task PersistAsync(NoteModel note)
    {
        await _repo.SaveNoteAsync(note).ConfigureAwait(false);
    }

    private void AddTag()
    {
        if (string.IsNullOrWhiteSpace(_tagDraft)) return;
        var trimmed = _tagDraft.Trim();
        if (Draft.Tags.Contains(trimmed, StringComparer.OrdinalIgnoreCase)) return;
        Draft = Draft with { Tags = Draft.Tags.Concat(new[] { trimmed }).ToArray() };
        TagDraft = string.Empty;
    }

    private void RemoveTag(string? tag)
    {
        if (string.IsNullOrEmpty(tag)) return;
        Draft = Draft with { Tags = Draft.Tags.Where(t => !string.Equals(t, tag, StringComparison.OrdinalIgnoreCase)).ToArray() };
    }

    private void EmitDraftChanges()
    {
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Draft)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Snapshot)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsDirty)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsValid)));
        RaisePropertyChanged(nameof(Draft));
        RaisePropertyChanged(nameof(Snapshot));
        RaisePropertyChanged(nameof(IsDirty));
        RaisePropertyChanged(nameof(IsValid));
    }

    private NoteFormVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        INoteRepository repo,
        INotificationHub? notificationHub)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _repo = repo;
        _notificationHub = notificationHub;
        ApproveCommand = RelayCommand.Builder()
            .Predicate(() => IsDirty && IsValid)
            .Task(() => _ = ApproveAsync())
            .Build();
        AddTagCommand = RelayCommand.Builder()
            .Predicate(() => HasBoundNote && !string.IsNullOrWhiteSpace(_tagDraft))
            .Task(AddTag)
            .Build();
        RemoveTagCommand = RelayCommand<string?>.Builder()
            .Predicate(t => HasBoundNote && !string.IsNullOrEmpty(t))
            .Task(RemoveTag)
            .Build();
    }

    private static readonly NoteModel Empty = new(
        "", "", "", Array.Empty<string>(), "", false,
        DateTimeOffset.MinValue, DateTimeOffset.MinValue);

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _form?.Dispose();
        (ApproveCommand as IDisposable)?.Dispose();
        (AddTagCommand as IDisposable)?.Dispose();
        (RemoveTagCommand as IDisposable)?.Dispose();
        base.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static NoteFormVMBuilder Builder() => NoteFormVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class NoteFormVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly INoteRepository? _repo;
        private readonly INotificationHub? _notificationHub;

        internal static readonly NoteFormVMBuilder Empty = new();
        private NoteFormVMBuilder() { _hint = ""; }
        private NoteFormVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher,
            INoteRepository? repo, INotificationHub? notificationHub)
        {
            _name = name; _hint = hint; _hub = hub; _dispatcher = dispatcher;
            _repo = repo; _notificationHub = notificationHub;
        }

        /// <summary>Sets the required Name.</summary>
        public NoteFormVMBuilder Name(string name) => new(name, _hint, _hub, _dispatcher, _repo, _notificationHub);
        /// <summary>Sets the optional Hint.</summary>
        public NoteFormVMBuilder Hint(string hint) => new(_name, hint, _hub, _dispatcher, _repo, _notificationHub);
        /// <summary>Sets the required Services.</summary>
        public NoteFormVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, hub, dispatcher, _repo, _notificationHub);
        /// <summary>Sets the required Repository.</summary>
        public NoteFormVMBuilder Repository(INoteRepository repo) => new(_name, _hint, _hub, _dispatcher, repo, _notificationHub);
        /// <summary>Sets the optional NotificationHub (default: silent).</summary>
        public NoteFormVMBuilder NotificationHub(INotificationHub hub) => new(_name, _hint, _hub, _dispatcher, _repo, hub);

        /// <summary>Builds the VM after validation.</summary>
        public NoteFormVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_repo, "Repository");
            return new NoteFormVM(_name!, _hint, _hub!, _dispatcher!, _repo!, _notificationHub);
        }
    }
}
