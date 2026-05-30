using System.Reactive.Subjects;
using VMx.Builders;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Properties;
using VMx.Services;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Projects a focused VM's implemented capability interfaces into a flat list
/// of <see cref="ActionVM"/>s for the action-bar (plan §3.a.10, spec §14.4).
///
/// The focused VM is injected via a delegate (<c>Func&lt;object?&gt;</c>) so
/// the host can choose how it tracks focus (e.g. "last selected" across the
/// notebooks tree, notes list, and form). Call <see cref="RecomputeActions"/>
/// after focus changes to refresh the projection.
/// </summary>
public sealed class CapabilityActionsVM : ComponentVMBase
{
    private readonly Func<object?> _focusedGetter;
    private readonly BehaviorSubject<object?> _focusSubject;
    private bool _ownDisposed;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>Snapshot of the currently focused VM.</summary>
    public object? FocusedVM => _focusedGetter();

    /// <summary>The projected action list. Recomputes on <see cref="RecomputeActions"/>.</summary>
    public DerivedProperty<IReadOnlyList<ActionVM>> Actions { get; }

    /// <summary>
    /// Inspects the focused VM and rebuilds the action list. The host calls
    /// this after focus changes (e.g. via a hub subscription on selection
    /// messages — kept out of the leaf VM for testability).
    /// </summary>
    public void RecomputeActions() => _focusSubject.OnNext(_focusedGetter());

    private static IReadOnlyList<ActionVM> Project(object? focused)
    {
        if (focused is null) return Array.Empty<ActionVM>();
        var actions = new List<ActionVM>();

        // Selection
        if (focused is ISelectable sel)
        {
            actions.Add(new ActionVM("Select", RelayCommand.Builder()
                .Predicate(sel.CanSelect).Task(sel.Select).Build()));
        }
        if (focused is IDeselectable des)
        {
            actions.Add(new ActionVM("Deselect", RelayCommand.Builder()
                .Predicate(des.CanDeselect).Task(des.Deselect).Build()));
        }
        if (focused is ISelectionTogglable sst)
        {
            actions.Add(new ActionVM("Toggle Selection", RelayCommand.Builder()
                .Predicate(sst.CanToggleSelection).Task(sst.ToggleSelection).Build()));
        }

        // Expansion
        if (focused is IExpandable exp)
        {
            actions.Add(new ActionVM("Expand", RelayCommand.Builder()
                .Predicate(exp.CanExpand).Task(exp.Expand).Build()));
        }
        if (focused is ICollapsible col)
        {
            actions.Add(new ActionVM("Collapse", RelayCommand.Builder()
                .Predicate(col.CanCollapse).Task(col.Collapse).Build()));
        }
        if (focused is IExpansionTogglable exTog)
        {
            actions.Add(new ActionVM("Toggle Expansion", RelayCommand.Builder()
                .Predicate(exTog.CanToggleExpansion).Task(exTog.ToggleExpansion).Build()));
        }

        // Dialog
        if (focused is IClosable cls)
        {
            actions.Add(new ActionVM("Close", RelayCommand.Builder()
                .Predicate(cls.CanClose).Task(cls.Close).Build()));
        }
        if (focused is IApprovable apr)
        {
            actions.Add(new ActionVM("Approve", RelayCommand.Builder()
                .Predicate(apr.CanApprove).Task(apr.Approve).Build()));
        }
        if (focused is ICancelable cnc)
        {
            actions.Add(new ActionVM("Cancel", RelayCommand.Builder()
                .Predicate(cnc.CanCancel).Task(cnc.Cancel).Build()));
        }

        // CRUD
        if (focused is INewCreatable nc)
        {
            actions.Add(new ActionVM("New", RelayCommand.Builder()
                .Predicate(nc.CanCreateNew).Task(nc.CreateNew).Build()));
        }
        // Save / Delete target NoteVM (the only example-defined VM implementing
        // ISavable<T> / IDeletable<T>). Scenario §6.2: each note saves /
        // deletes itself.
        if (focused is NoteVM noteSelf)
        {
            if (focused is ISavable<NoteVM> sav)
            {
                actions.Add(new ActionVM("Save", RelayCommand.Builder()
                    .Predicate(() => sav.CanSave(noteSelf))
                    .Task(() => sav.Save(noteSelf)).Build()));
            }
            if (focused is IDeletable<NoteVM> del)
            {
                actions.Add(new ActionVM("Delete", RelayCommand.Builder()
                    .Predicate(() => del.CanDelete(noteSelf))
                    .Task(() => del.Delete(noteSelf)).Build()));
            }
        }

        // Lifecycle
        if (focused is IReconstructable rec)
        {
            actions.Add(new ActionVM("Reconstruct", RelayCommand.Builder()
                .Predicate(rec.CanReconstruct).Task(rec.Reconstruct).Build()));
        }

        return actions;
    }

    private CapabilityActionsVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Func<object?> focusedGetter)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _focusedGetter = focusedGetter;
        _focusSubject = new BehaviorSubject<object?>(focusedGetter());
        Actions = DerivedProperty.From(_focusSubject, Project);
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        if (_ownDisposed) { base.Dispose(); return; }
        _ownDisposed = true;
        Actions.Dispose();
        _focusSubject.OnCompleted();
        _focusSubject.Dispose();
        base.Dispose();
    }

    /// <summary>Returns a new empty builder.</summary>
    public static CapabilityActionsVMBuilder Builder() => CapabilityActionsVMBuilder.Empty;

    /// <summary>Immutable fluent builder.</summary>
    public sealed class CapabilityActionsVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Func<object?>? _focusedGetter;

        internal static readonly CapabilityActionsVMBuilder Empty = new();
        private CapabilityActionsVMBuilder() { _hint = ""; }
        private CapabilityActionsVMBuilder(
            string? name, string hint,
            IMessageHub? hub, IDispatcher? dispatcher,
            Func<object?>? focusedGetter)
        {
            _name = name; _hint = hint;
            _hub = hub; _dispatcher = dispatcher;
            _focusedGetter = focusedGetter;
        }

        /// <summary>Sets the required Name.</summary>
        public CapabilityActionsVMBuilder Name(string name) => new(name, _hint, _hub, _dispatcher, _focusedGetter);
        /// <summary>Sets the optional Hint.</summary>
        public CapabilityActionsVMBuilder Hint(string hint) => new(_name, hint, _hub, _dispatcher, _focusedGetter);
        /// <summary>Sets the required Services.</summary>
        public CapabilityActionsVMBuilder Services(IMessageHub hub, IDispatcher dispatcher) => new(_name, _hint, hub, dispatcher, _focusedGetter);
        /// <summary>Sets the required focus-getter delegate.</summary>
        public CapabilityActionsVMBuilder FocusedGetter(Func<object?> getter) => new(_name, _hint, _hub, _dispatcher, getter);

        /// <summary>Builds the VM after validation.</summary>
        public CapabilityActionsVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_focusedGetter, "FocusedGetter");
            return new CapabilityActionsVM(_name!, _hint, _hub!, _dispatcher!, _focusedGetter!);
        }
    }
}
