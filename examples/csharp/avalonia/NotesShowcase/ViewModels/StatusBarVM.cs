using System.Reactive.Linq;
using System.Reactive.Subjects;
using VMx.Builders;
using VMx.Components;
using VMx.Messages;
using VMx.Properties;
using VMx.Services;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Read-only VM driving the three status-bar slots: note count, starred count,
/// and editing state. Each slot is a <see cref="DerivedProperty{TValue}"/>
/// composed from hub-published <see cref="PropertyChangedMessage{TSender}"/>
/// streams.
/// </summary>
public sealed class StatusBarVM : ComponentVMBase
{
    private readonly NotesViewVM _notesView;
    private readonly NotebooksRootVM _notebooks;
    private readonly NoteFormVM _noteForm;
    private readonly BehaviorSubject<NotesViewVM> _notesViewSubject;
    private readonly BehaviorSubject<NotebooksRootVM> _notebooksSubject;
    private readonly BehaviorSubject<NoteFormVM> _noteFormSubject;
    private readonly IDisposable _notesViewSub;
    private readonly IDisposable _notebooksSub;
    private readonly IDisposable _noteFormSub;
    private bool _ownDisposed;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>"N notes" — total count across all visible items in <see cref="NotesViewVM"/>.</summary>
    public DerivedProperty<string> NoteCountText { get; }

    /// <summary>"K starred" — count of starred items.</summary>
    public DerivedProperty<string> StarredText { get; }

    /// <summary>"Editing: TITLE" / "No selection" — reflects the form's draft state.</summary>
    public DerivedProperty<string> EditingText { get; }

    private NotesViewVM NotesViewRef => _notesView;
    private NotebooksRootVM NotebooksRef => _notebooks;
    private NoteFormVM NoteFormRef => _noteForm;

    private StatusBarVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        NotesViewVM notesView,
        NotebooksRootVM notebooks,
        NoteFormVM noteForm)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _notesView = notesView;
        _notebooks = notebooks;
        _noteForm = noteForm;

        _notesViewSubject = new BehaviorSubject<NotesViewVM>(notesView);
        _notebooksSubject = new BehaviorSubject<NotebooksRootVM>(notebooks);
        _noteFormSubject = new BehaviorSubject<NoteFormVM>(noteForm);

        // Re-emit each source whenever its hub publishes a relevant PropertyChanged.
        _notesViewSub = notesView.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, notesView))
            .Subscribe(_ => _notesViewSubject.OnNext(notesView));
        _notebooksSub = notebooks.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, notebooks))
            .Subscribe(_ => _notebooksSubject.OnNext(notebooks));
        _noteFormSub = noteForm.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, noteForm))
            .Subscribe(_ => _noteFormSubject.OnNext(noteForm));

        NoteCountText = DerivedProperty.From(
            _notesViewSubject,
            nv => $"{nv.FilteredItems.Count} note{(nv.FilteredItems.Count == 1 ? string.Empty : "s")}");

        StarredText = DerivedProperty.From(
            _notesViewSubject,
            nv =>
            {
                var k = nv.FilteredItems.Count(n => n.Starred);
                return $"{k} starred";
            });

        EditingText = DerivedProperty.From(
            _noteFormSubject,
            nf => nf.HasBoundNote
                ? $"Editing: {nf.Draft.Title}{(nf.IsDirty ? " *" : string.Empty)}"
                : "No selection");
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        NoteCountText.Dispose();
        StarredText.Dispose();
        EditingText.Dispose();
        _notesViewSub.Dispose();
        _notebooksSub.Dispose();
        _noteFormSub.Dispose();
        _notesViewSubject.OnCompleted(); _notesViewSubject.Dispose();
        _notebooksSubject.OnCompleted(); _notebooksSubject.Dispose();
        _noteFormSubject.OnCompleted(); _noteFormSubject.Dispose();
        base.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static StatusBarVMBuilder Builder() => StatusBarVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class StatusBarVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly NotesViewVM? _notesView;
        private readonly NotebooksRootVM? _notebooks;
        private readonly NoteFormVM? _noteForm;

        internal static readonly StatusBarVMBuilder Empty = new();
        private StatusBarVMBuilder() { _hint = ""; }
        private StatusBarVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher,
            NotesViewVM? notesView, NotebooksRootVM? notebooks, NoteFormVM? noteForm)
        {
            _name = name; _hint = hint;
            _hub = hub; _dispatcher = dispatcher;
            _notesView = notesView; _notebooks = notebooks; _noteForm = noteForm;
        }
        /// <summary>Sets the required Name.</summary>
        public StatusBarVMBuilder Name(string name) => new(name, _hint, _hub, _dispatcher, _notesView, _notebooks, _noteForm);
        /// <summary>Sets the optional Hint.</summary>
        public StatusBarVMBuilder Hint(string hint) => new(_name, hint, _hub, _dispatcher, _notesView, _notebooks, _noteForm);
        /// <summary>Sets the required Services.</summary>
        public StatusBarVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, hub, dispatcher, _notesView, _notebooks, _noteForm);
        /// <summary>Sets the required NotesViewVM source.</summary>
        public StatusBarVMBuilder NotesView(NotesViewVM source) => new(_name, _hint, _hub, _dispatcher, source, _notebooks, _noteForm);
        /// <summary>Sets the required NotebooksRootVM source.</summary>
        public StatusBarVMBuilder Notebooks(NotebooksRootVM source) => new(_name, _hint, _hub, _dispatcher, _notesView, source, _noteForm);
        /// <summary>Sets the required NoteFormVM source.</summary>
        public StatusBarVMBuilder NoteForm(NoteFormVM source) => new(_name, _hint, _hub, _dispatcher, _notesView, _notebooks, source);

        /// <summary>Builds the VM after validation.</summary>
        public StatusBarVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_notesView, "NotesView");
            BuilderValidationException.Require(_notebooks, "Notebooks");
            BuilderValidationException.Require(_noteForm, "NoteForm");
            return new StatusBarVM(_name!, _hint, _hub!, _dispatcher!, _notesView!, _notebooks!, _noteForm!);
        }
    }
}
