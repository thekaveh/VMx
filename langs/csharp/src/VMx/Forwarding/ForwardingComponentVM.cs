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
/// See spec/09-forwarding.md §ForwardingComponentVM and FWD-001 through FWD-005 in spec/12-conformance.md.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public abstract class ForwardingComponentVM<M> : IComponentVM<M>, IComponentVMInternals, IDisposable
{
    /// <summary>The wrapped instance that all members delegate to by default.</summary>
    protected readonly IComponentVM<M> _wrapped;
    private readonly ForwardingMembership _membership;

    /// <summary>Initialises the decorator with the instance to wrap.</summary>
    protected ForwardingComponentVM(IComponentVM<M> wrapped)
    {
        _wrapped = wrapped ?? throw new ArgumentNullException(nameof(wrapped));
        _membership = new ForwardingMembership(this, wrapped);
    }

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

    /// <summary>
    /// Registers a disposable on the wrapped VM's terminal cleanup and returns it.
    /// It is disposed when the wrapped VM is disposed, through any decorator or
    /// directly, or at once if the wrapped VM is already disposed (ADR-0151).
    /// </summary>
    protected T Own<T>(T resource) where T : IDisposable => _membership.Own(resource);

    /// <summary>Registers a cleanup action on the wrapped VM's terminal cleanup (ADR-0151).</summary>
    protected IDisposable Own(Action cleanup)
        => Own(System.Reactive.Disposables.Disposable.Create(cleanup));

    IParentCompositeVM? IComponentVMInternals.Parent => _membership.Parent;

    IComponentVM IComponentVMInternals.OwnershipIdentity => _membership.OwnershipIdentity;

    void IComponentVMInternals.SetParent(IParentCompositeVM? parent) => _membership.SetParent(parent);

    void IComponentVMInternals.SetIsCurrent(bool value) => _membership.SetIsCurrent(value);

    bool IComponentVMInternals.CommitIsCurrent(bool value) => _membership.CommitIsCurrent(value);

    void IComponentVMInternals.PublishIsCurrent() => _membership.PublishIsCurrent();

    Task IComponentVMInternals.ConstructOrJoinAsync() => _membership.ConstructOrJoinAsync();

    Task IComponentVMInternals.JoinConstructAsync() => _membership.JoinConstructAsync();
}
#pragma warning restore CA1051
