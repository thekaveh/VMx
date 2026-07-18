#pragma warning disable CA1051 // Protected field _wrapped is intentional: subclasses use it to override individual members
using System.ComponentModel;
using System.Windows.Input;
using VMx.Components;
using VMx.Services;

namespace VMx.Forwarding;

/// <summary>
/// Abstract forwarding decorator for <see cref="IComponentVM{M}"/>.
/// Every public member delegates to <see cref="_wrapped"/> by default.
/// Subclasses override individual members to customize behaviour.
///
/// See spec/09-forwarding.md §ForwardingComponentVM and FWD-001/FWD-002 in spec/12-conformance.md.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public abstract class ForwardingComponentVM<M> : IComponentVM<M>, IComponentVMInternals, IDisposable
{
    /// <summary>The wrapped instance that all members delegate to by default.</summary>
    protected readonly IComponentVM<M> _wrapped;
    private IParentCompositeVM? _parent;

    private sealed class ParentAdapter(
        IParentCompositeVM parent,
        ForwardingComponentVM<M> wrapper) : IParentCompositeVM
    {
        internal ForwardingComponentVM<M> RetainedWrapper => wrapper;
        public IComponentVM? Owner => parent.Owner;
        public IParentCompositeVM? OwnerParent => parent.OwnerParent;
        public bool SupportsChildSelection => parent.SupportsChildSelection;
        public IComponentVM? CurrentChild =>
            ReferenceEquals(parent.CurrentChild, wrapper) ? wrapper._wrapped : parent.CurrentChild;
        public void SelectChild(IComponentVM vm) => parent.SelectChild(wrapper);
        public void DeselectChild(IComponentVM vm) => parent.DeselectChild(wrapper);
        public bool ContainsChild(IComponentVM vm) => parent.ContainsChild(wrapper);
        public ParentTransferToken DetachForTransfer(IComponentVM vm) =>
            parent.DetachForTransfer(wrapper);
    }

    private sealed class WrappedParentAdapter(
        IParentCompositeVM parent,
        ForwardingComponentVM<M> wrapper,
        IComponentVM wrapped) : IParentCompositeVM
    {
        public IComponentVM? Owner => parent.Owner;
        public IParentCompositeVM? OwnerParent => parent.OwnerParent;
        public bool SupportsChildSelection => parent.SupportsChildSelection;
        public IComponentVM? CurrentChild =>
            ReferenceEquals(parent.CurrentChild, wrapped) ? wrapper : parent.CurrentChild;
        public void SelectChild(IComponentVM vm) => parent.SelectChild(wrapped);
        public void DeselectChild(IComponentVM vm) => parent.DeselectChild(wrapped);
        public bool ContainsChild(IComponentVM vm) => parent.ContainsChild(wrapped);
        public ParentTransferToken DetachForTransfer(IComponentVM vm)
        {
            var retainedWrapper = (parent as ParentAdapter)?.RetainedWrapper;
            var staged = parent.DetachForTransfer(wrapped);
            return new ParentTransferToken(
                commit: () =>
                {
                    try { staged.Commit(); }
                    finally
                    {
                        if (retainedWrapper is not null &&
                            !ReferenceEquals(retainedWrapper, wrapper))
                            retainedWrapper.ClearDirectParent();
                    }
                },
                rollback: staged.Rollback);
        }
    }

    /// <summary>Initialises the decorator with the instance to wrap.</summary>
    protected ForwardingComponentVM(IComponentVM<M> wrapped)
        => _wrapped = wrapped ?? throw new ArgumentNullException(nameof(wrapped));

    private void ClearDirectParent() => _parent = null;

    // ── IComponentVM: identity ─────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual string Name => _wrapped.Name;

    /// <inheritdoc/>
    public virtual string Hint => _wrapped.Hint;

    /// <inheritdoc/>
    public virtual ViewModelType Type => _wrapped.Type;

    // ── IComponentVM: state ────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool IsCurrent => _wrapped.IsCurrent;

    /// <inheritdoc/>
    public virtual bool IsConstructed => _wrapped.IsConstructed;

    /// <inheritdoc/>
    public virtual Lifecycle.ConstructionStatus Status => _wrapped.Status;

    /// <inheritdoc/>
    public virtual IMessageHub Hub => _wrapped.Hub;

    // ── IComponentVM<M>: model ─────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual M Model
    {
        get => _wrapped.Model;
        set => _wrapped.Model = value;
    }

    /// <inheritdoc/>
    public virtual string ModeledHint => _wrapped.ModeledHint;

    /// <inheritdoc/>
    public virtual void RepublishModel() => _wrapped.RepublishModel();

    // ── IComponentVM: commands ─────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual ICommand SelectCommand => _wrapped.SelectCommand;

    /// <inheritdoc/>
    public virtual ICommand DeselectCommand => _wrapped.DeselectCommand;

    /// <inheritdoc/>
    public virtual ICommand SelectNextCommand => _wrapped.SelectNextCommand;

    /// <inheritdoc/>
    public virtual ICommand SelectPreviousCommand => _wrapped.SelectPreviousCommand;

    /// <inheritdoc/>
    public virtual ICommand ReconstructCommand => _wrapped.ReconstructCommand;

    // ── IComponentVM: lifecycle ────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool CanConstruct() => _wrapped.CanConstruct();

    /// <inheritdoc/>
    public virtual void Construct() => _wrapped.Construct();

    /// <inheritdoc/>
    public virtual Task ConstructAsync() => _wrapped.ConstructAsync();

    /// <inheritdoc/>
    public virtual bool CanDestruct() => _wrapped.CanDestruct();

    /// <inheritdoc/>
    public virtual void Destruct() => _wrapped.Destruct();

    /// <inheritdoc/>
    public virtual Task DestructAsync() => _wrapped.DestructAsync();

    /// <inheritdoc/>
    public virtual bool CanReconstruct() => _wrapped.CanReconstruct();

    /// <inheritdoc/>
    public virtual void Reconstruct() => _wrapped.Reconstruct();

    /// <inheritdoc/>
    public virtual Task ReconstructAsync() => _wrapped.ReconstructAsync();

    // ── IComponentVM: selection ────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool CanSelect() => _wrapped.CanSelect();

    /// <inheritdoc/>
    public virtual void Select() => _wrapped.Select();

    /// <inheritdoc/>
    public virtual bool CanDeselect() => _wrapped.CanDeselect();

    /// <inheritdoc/>
    public virtual void Deselect() => _wrapped.Deselect();

    // ── INotifyPropertyChanged ─────────────────────────────────────────────

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged
    {
        add => _wrapped.PropertyChanged += value;
        remove => _wrapped.PropertyChanged -= value;
    }

    // ── IDisposable ────────────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual void Dispose()
    {
        _wrapped.Dispose();
    }

    IParentCompositeVM? IComponentVMInternals.Parent
    {
        get
        {
            if (_parent is not null) return _parent;
            var wrappedParent = _wrapped.GetParent();
            return wrappedParent is null
                ? null
                : new WrappedParentAdapter(wrappedParent, this, _wrapped);
        }
    }

    void IComponentVMInternals.SetParent(IParentCompositeVM? parent)
    {
        _parent = parent;
        _wrapped.SetParent(parent is null ? null : new ParentAdapter(parent, this));
    }

    void IComponentVMInternals.SetIsCurrent(bool value) => _wrapped.SetIsCurrent(value);

    bool IComponentVMInternals.CommitIsCurrent(bool value) => _wrapped.CommitIsCurrent(value);

    void IComponentVMInternals.PublishIsCurrent() => _wrapped.PublishIsCurrent();

    Task IComponentVMInternals.ConstructOrJoinAsync() => _wrapped.ConstructOrJoinAsync();
}
#pragma warning restore CA1051
