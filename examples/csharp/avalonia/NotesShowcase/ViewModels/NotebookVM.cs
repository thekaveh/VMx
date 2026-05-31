using VMx.Builders;
using VMx.Capabilities;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using NotesShowcase.Models;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Leaf VM for a notebook tree node.
///
/// Capabilities (plan §3.a.6, scenario §6.2):
///   <see cref="ISelectable"/>, <see cref="IExpandable"/>, <see cref="ICollapsible"/>,
///   <see cref="IExpansionTogglable"/>, <see cref="IReconstructable"/>.
///
/// Implemented as a direct subclass of <see cref="ComponentVMBase"/> rather than
/// <see cref="ComponentVM{M}"/> because the latter is sealed and we need to
/// layer the capability mix-ins. The model is held as a read-only field
/// (notebooks are renamed via repo + re-populate, not mutated in-place).
/// </summary>
public sealed class NotebookVM
    : ComponentVMBase,
      ISelectable,
      IExpandable,
      ICollapsible,
      IExpansionTogglable,
      IReconstructable
{
    private readonly ExpandableState _expansion;
    private NotebookModel _model;
    private Func<NotebookVM, IReadOnlyList<NotebookVM>>? _childrenGetter;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>
    /// Public accessor for the underlying <see cref="IMessageHub"/> — exposed
    /// on the example VMs (not the library) so views and tests can subscribe
    /// without reflection. The view layer uses this to drive its
    /// <c>BindableVm</c> adapter (see Phase 4.a).
    /// </summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>Current notebook model.</summary>
    public NotebookModel Model
    {
        get => _model;
        set
        {
            if (EqualityComparer<NotebookModel>.Default.Equals(_model, value)) return;
            _model = value;
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Model)));
            RaisePropertyChanged(nameof(Model));
            RaisePropertyChanged(nameof(NotebookName));
            Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(NotebookName)));
        }
    }

    /// <summary>Notebook display name (derived from <see cref="Model"/>).</summary>
    public string NotebookName => _model.Name;

    /// <summary>
    /// Child notebook VMs (parent_id walk via the owner-supplied getter).
    /// Returns an empty list when no getter has been wired (standalone VMs do
    /// not know about siblings). Phase 5.a binding gap #2 (parity with
    /// Phase 5.b ``children_getter``): the Avalonia <c>TreeView</c>'s
    /// <c>TreeDataTemplate</c> binds <c>ItemsSource="{Binding Children}"</c>
    /// so nested notebooks (Specs under Work) appear under their parent.
    /// </summary>
    public IReadOnlyList<NotebookVM> Children
        => _childrenGetter is null ? Array.Empty<NotebookVM>() : _childrenGetter(this);

    /// <summary>
    /// Late-binds the children resolver (used by <see cref="NotebooksRootVM"/>
    /// after each <c>PopulateAsync</c> / <c>AddNotebookAsync</c>). Emits
    /// <see cref="PropertyChangedMessage{TSender}"/> for <c>Children</c> so
    /// already-bound tree views refresh.
    /// </summary>
    public void SetChildrenGetter(Func<NotebookVM, IReadOnlyList<NotebookVM>>? getter)
    {
        _childrenGetter = getter;
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Children)));
        RaisePropertyChanged(nameof(Children));
    }

    /// <summary>
    /// Re-emits a <c>Children</c> change notification (called by
    /// <see cref="NotebooksRootVM"/> whenever the flat collection mutates so
    /// already-bound parents refresh their child list).
    /// </summary>
    internal void NotifyChildrenChanged()
    {
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Children)));
        RaisePropertyChanged(nameof(Children));
    }

    // ── ISelectable / IExpandable / ICollapsible / IExpansionTogglable ──────

    /// <inheritdoc cref="IExpandable.IsExpanded"/>
    public bool IsExpanded => _expansion.IsExpanded;

    /// <inheritdoc cref="IExpandable.CanExpand"/>
    public bool CanExpand() => _expansion.CanExpand();

    /// <inheritdoc cref="IExpandable.Expand"/>
    public void Expand()
    {
        if (!_expansion.CanExpand()) return;
        _expansion.Expand();
        EmitExpansionChange();
    }

    /// <inheritdoc cref="ICollapsible.CanCollapse"/>
    public bool CanCollapse() => _expansion.CanCollapse();

    /// <inheritdoc cref="ICollapsible.Collapse"/>
    public void Collapse()
    {
        if (!_expansion.CanCollapse()) return;
        _expansion.Collapse();
        EmitExpansionChange();
    }

    /// <inheritdoc cref="IExpansionTogglable.CanToggleExpansion"/>
    public bool CanToggleExpansion() => _expansion.CanToggleExpansion();

    /// <inheritdoc cref="IExpansionTogglable.ToggleExpansion"/>
    public void ToggleExpansion()
    {
        if (_expansion.IsExpanded) Collapse(); else Expand();
    }

    private void EmitExpansionChange()
    {
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(IsExpanded)));
        RaisePropertyChanged(nameof(IsExpanded));
    }

    // Selection delegates to base ComponentVMBase Select/Deselect plumbing.

    private NotebookVM(
        string name,
        string hint,
        NotebookModel model,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool initiallyExpanded,
        Func<NotebookVM, IReadOnlyList<NotebookVM>>? childrenGetter)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _model = model;
        _expansion = new ExpandableState(initiallyExpanded);
        _childrenGetter = childrenGetter;
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        _expansion.Dispose();
        base.OnDispose();
    }

    /// <summary>Returns a new empty builder for <see cref="NotebookVM"/>.</summary>
    public static NotebookVMBuilder Builder() => NotebookVMBuilder.Empty;

    /// <summary>Immutable fluent builder for <see cref="NotebookVM"/> (spec ch. 10).</summary>
    public sealed class NotebookVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly NotebookModel? _model;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly bool _initiallyExpanded;
        private readonly Func<NotebookVM, IReadOnlyList<NotebookVM>>? _childrenGetter;

        internal static readonly NotebookVMBuilder Empty = new();

        private NotebookVMBuilder() { _hint = ""; }

        private NotebookVMBuilder(
            string? name,
            string hint,
            NotebookModel? model,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            bool initiallyExpanded,
            Func<NotebookVM, IReadOnlyList<NotebookVM>>? childrenGetter)
        {
            _name = name;
            _hint = hint;
            _model = model;
            _hub = hub;
            _dispatcher = dispatcher;
            _initiallyExpanded = initiallyExpanded;
            _childrenGetter = childrenGetter;
        }

        /// <summary>Sets the required VM Name.</summary>
        public NotebookVMBuilder Name(string name)
            => new(name, _hint, _model, _hub, _dispatcher, _initiallyExpanded, _childrenGetter);

        /// <summary>Sets the optional Hint.</summary>
        public NotebookVMBuilder Hint(string hint)
            => new(_name, hint, _model, _hub, _dispatcher, _initiallyExpanded, _childrenGetter);

        /// <summary>Sets the required notebook model.</summary>
        public NotebookVMBuilder Model(NotebookModel model)
            => new(_name, _hint, model, _hub, _dispatcher, _initiallyExpanded, _childrenGetter);

        /// <summary>Sets the required Services (hub + dispatcher).</summary>
        public NotebookVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, _model, hub, dispatcher, _initiallyExpanded, _childrenGetter);

        /// <summary>Sets the optional initial expansion state (default false).</summary>
        public NotebookVMBuilder InitiallyExpanded(bool initiallyExpanded)
            => new(_name, _hint, _model, _hub, _dispatcher, initiallyExpanded, _childrenGetter);

        /// <summary>
        /// Sets the optional children-getter callback. Phase 5.a binding gap #2:
        /// the owning <see cref="NotebooksRootVM"/> wires this so each notebook
        /// can resolve its children from the flat collection.
        /// </summary>
        public NotebookVMBuilder ChildrenGetter(Func<NotebookVM, IReadOnlyList<NotebookVM>> getter)
            => new(_name, _hint, _model, _hub, _dispatcher, _initiallyExpanded, getter);

        /// <summary>Builds the VM after validating required fields.</summary>
        public NotebookVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_model, "Model");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            return new NotebookVM(_name!, _hint, _model!, _hub!, _dispatcher!, _initiallyExpanded, _childrenGetter);
        }
    }
}
