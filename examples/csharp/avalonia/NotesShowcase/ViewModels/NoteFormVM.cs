using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Reactive.Subjects;
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
    private const string TitleRequired = "Title is required.";
    private readonly INoteRepository _repo;
    private readonly INotificationHub? _notificationHub;
    private FormVM<NoteModel>? _form;
    private NoteModel? _bound;
    private string _tagDraft = string.Empty;
    private bool _ownDisposed;
    private readonly Subject<System.Reactive.Unit> _canExecuteTrigger = new();
    private readonly Subject<NoteModel> _onSaved = new();
    private readonly IDispatcher _dispatcher;
    private IDisposable? _approvedSub;

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

    // Phase 5.a binding gap #1 (parity with Phase 5.b / 5.c): NoteModel is an
    // immutable record, so Avalonia widgets cannot two-way bind through
    // ``Draft.Title``/``Draft.Body``/``Draft.Starred`` directly. Expose mutable
    // scalar accessors that rebuild the draft via ``with`` expressions so
    // ``TextBox`` / ``CheckBox`` two-way bindings round-trip into the form and
    // ``IsDirty`` / ``IsValid`` / ``ApproveCommand.CanExecute`` flip reactively.

    /// <summary>Two-way bindable title (proxies <see cref="Draft"/>.Title).</summary>
    public string Title
    {
        get => Draft.Title;
        set
        {
            if (_form is null || string.Equals(Draft.Title, value, StringComparison.Ordinal)) return;
            Draft = Draft with { Title = value };
        }
    }

    /// <summary>Two-way bindable body (proxies <see cref="Draft"/>.Body).</summary>
    public string Body
    {
        get => Draft.Body;
        set
        {
            if (_form is null || string.Equals(Draft.Body, value, StringComparison.Ordinal)) return;
            Draft = Draft with { Body = value };
        }
    }

    /// <summary>Two-way bindable starred flag (proxies <see cref="Draft"/>.Starred).</summary>
    public bool Starred
    {
        get => Draft.Starred;
        set
        {
            if (_form is null || Draft.Starred == value) return;
            Draft = Draft with { Starred = value };
        }
    }

    /// <summary>Read-only view of the draft tag list (mutate via tag commands).</summary>
    public IReadOnlyList<string> Tags => Draft.Tags;

    /// <summary>
    /// Comma-joined tag list — bind UI text labels to this so the rendered
    /// string is "alpha, beta" instead of an enumerable repr. Mirrors Py
    /// <c>tags_text</c> (Round-3 Important C-I1) and TS <c>tagsText</c>.
    /// </summary>
    public string TagsText => string.Join(", ", Draft.Tags);

    /// <summary>True when the draft differs from the snapshot.</summary>
    public bool IsDirty => _form?.IsDirty ?? false;

    /// <summary>True when the draft passes FormVM validation.</summary>
    public bool IsValid => _form?.IsValid ?? false;

    /// <summary>Field-level validation error for <see cref="Title"/>, if any.</summary>
    public string? TitleError => _form?.FieldError(nameof(Title));

    /// <summary>Approve = persist via repo + publish "Saved" notification.</summary>
    public ICommand ApproveCommand { get; }

    /// <summary>Deny = revert draft to snapshot.</summary>
    /// <summary>
    /// Stable command that reverts the currently-bound form (no-op when
    /// unbound). One object for the VM's lifetime — and it re-emits this
    /// VM's own draft channels: the inner FormVM's Deny publishes with
    /// sender = FormVM, which the XAML bindings (keyed on this VM) never
    /// observe, so the editor kept the edited text on screen (real-wiring
    /// audit, pass 6).
    /// </summary>
    public ICommand DenyCommand { get; }

    /// <summary>
    /// Emits the persisted note after each successful save — the workspace
    /// refreshes the matching list row (Title/Starred were
    /// construction-time snapshots otherwise).
    /// </summary>
    public IObservable<NoteModel> OnSaved => _onSaved.AsObservable();

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
            _canExecuteTrigger.OnNext(System.Reactive.Unit.Default);
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
        _approvedSub?.Dispose();
        _bound = note;
        _form = new FormVM<NoteModel>(
            initial: note,
            persister: PersistAsync,
            hub: Hub,
            strict: true,
            validators: new Dictionary<string, Func<NoteModel, string?>>
            {
                [nameof(Title)] = note => string.IsNullOrWhiteSpace(note.Title) ? TitleRequired : null
            });
        _approvedSub = _form.OnApproved.Subscribe(m => _onSaved.OnNext(m));
        EmitDraftChanges();
    }

    /// <summary>
    /// Clears the form back to its initial empty state — disposes the inner
    /// <see cref="FormVM{TM}"/>, resets <see cref="HasBoundNote"/> to
    /// <c>false</c>, and emits PropertyChanged for the bound surface so
    /// widgets re-read (Title / Body / Starred / Tags / TagsText all flip
    /// to the empty model). Round-4 Important-1: called by
    /// <see cref="WorkspaceVM"/> when <see cref="NotesViewVM.Current"/>
    /// transitions to <c>null</c> (e.g. the selected note is deleted) so
    /// the editor does not display ghost data from the just-removed note.
    ///
    /// Round-5 Minor: also reset <see cref="TagDraft"/>. The user-typed
    /// tag input buffer is part of the editor state, so a binding
    /// transition must clear it too — otherwise the chip input still shows
    /// the orphan text after the note disappears. Cross-flavor parity with
    /// Python <c>self._tag_draft = ""</c> and TS <c>this.tagDraft = ""</c>.
    /// </summary>
    public void Unbind()
    {
        var hadTagDraft = _tagDraft.Length > 0;
        if (_form is null && _bound is null && !hadTagDraft) return;
        _form?.Dispose();
        _form = null;
        _bound = null;
        if (hadTagDraft)
        {
            _tagDraft = string.Empty;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(TagDraft)));
            RaisePropertyChanged(nameof(TagDraft));
        }
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
        // This continuation runs off the UI thread (ConfigureAwait(false));
        // EmitDraftChanges raises INPC into live XAML bindings, so marshal
        // (real-wiring audit, pass 6).
        _dispatcher.Foreground.Schedule(() =>
        {
            if (_ownDisposed) return; // queued tail may outlive the VM
            EmitDraftChanges();
            if (_notificationHub is not null)
            {
                _ = _notificationHub.Post(new Notification(
                    NotificationType.Notification,
                    $"Saved “{Snapshot.Title}”"));
            }
        });
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
        // Includes the per-field scalar accessors (Title/Body/Starred/Tags) so
        // two-way bound widgets receive PropertyChanged and re-read after every
        // draft mutation. See Phase 5.a binding gap #1.
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Draft)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Snapshot)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsDirty)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsValid)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(TitleError)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Title)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Body)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Starred)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Tags)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(TagsText)));
        // Round-3 Important B-I2: both commands are stable objects now, but
        // consumers that re-resolve on change notifications still expect the
        // signal on rebinds (cross-flavor parity).
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(ApproveCommand)));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(DenyCommand)));
        RaisePropertyChanged(nameof(Draft));
        RaisePropertyChanged(nameof(Snapshot));
        RaisePropertyChanged(nameof(IsDirty));
        RaisePropertyChanged(nameof(IsValid));
        RaisePropertyChanged(nameof(TitleError));
        RaisePropertyChanged(nameof(Title));
        RaisePropertyChanged(nameof(Body));
        RaisePropertyChanged(nameof(Starred));
        RaisePropertyChanged(nameof(Tags));
        RaisePropertyChanged(nameof(TagsText));
        RaisePropertyChanged(nameof(ApproveCommand));
        RaisePropertyChanged(nameof(DenyCommand));
        _canExecuteTrigger.OnNext(System.Reactive.Unit.Default);
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
        _dispatcher = dispatcher;
        // Phase 5.a binding gap #1: draft mutation must flip
        // ApproveCommand.CanExecute reactively for Avalonia buttons. Wire the
        // ``_canExecuteTrigger`` subject through .Triggers(...) so each
        // EmitDraftChanges call fires CanExecuteChanged.
        ApproveCommand = RelayCommand.Builder()
            .Predicate(() => IsDirty && IsValid)
            .Task(() => _ = ApproveAsync())
            .Triggers(_canExecuteTrigger)
            .Build();
        DenyCommand = RelayCommand.Builder()
            .Task(() =>
            {
                _form?.DenyCommand.Execute(null);
                EmitDraftChanges();
            })
            .Build();
        AddTagCommand = RelayCommand.Builder()
            .Predicate(() => HasBoundNote && !string.IsNullOrWhiteSpace(_tagDraft))
            .Task(AddTag)
            .Triggers(_canExecuteTrigger)
            .Build();
        RemoveTagCommand = RelayCommand<string?>.Builder()
            .Predicate(t => HasBoundNote && !string.IsNullOrEmpty(t))
            .Task(RemoveTag)
            .Build();
    }

    private static readonly NoteModel Empty = new(
        Id: "",
        NotebookId: "",
        Title: "",
        Tags: Array.Empty<string>(),
        Body: "",
        Starred: false,
        CreatedAt: DateTimeOffset.MinValue,
        UpdatedAt: DateTimeOffset.MinValue);

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        _form?.Dispose();
        _approvedSub?.Dispose();
        (ApproveCommand as IDisposable)?.Dispose();
        (DenyCommand as IDisposable)?.Dispose();
        (AddTagCommand as IDisposable)?.Dispose();
        (RemoveTagCommand as IDisposable)?.Dispose();
        _canExecuteTrigger.OnCompleted();
        _canExecuteTrigger.Dispose();
        _onSaved.OnCompleted();
        _onSaved.Dispose();
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
