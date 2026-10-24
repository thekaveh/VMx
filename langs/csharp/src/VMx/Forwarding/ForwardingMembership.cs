using VMx.Components;

namespace VMx.Forwarding;

/// <summary>
/// Parent/selection membership shared by every forwarding decorator. A decorator
/// and its wrapped VM are one ownership identity: the wrapped VM records the
/// decorator's parent through an adapter, so single-parent ownership, IsCurrent,
/// and transfer all act on the decorator the parent actually holds.
/// </summary>
internal sealed class ForwardingMembership(IComponentVM wrapper, IComponentVM wrapped)
{
    private IParentCompositeVM? _parent;

    private sealed class ParentAdapter(
        IParentCompositeVM parent,
        ForwardingMembership membership) : IParentCompositeVM
    {
        internal IParentCompositeVM Parent => parent;
        internal ForwardingMembership RetainedMembership => membership;
        public IComponentVM? Owner => parent.Owner;
        public IParentCompositeVM? OwnerParent => parent.OwnerParent;
        public bool SupportsChildSelection => parent.SupportsChildSelection;
        public IComponentVM? CurrentChild =>
            ReferenceEquals(parent.CurrentChild, membership._wrapper)
                ? membership._wrapped
                : parent.CurrentChild;
        public void SelectChild(IComponentVM vm) => parent.SelectChild(membership._wrapper);
        public void DeselectChild(IComponentVM vm) => parent.DeselectChild(membership._wrapper);
        public bool ContainsChild(IComponentVM vm) => parent.ContainsChild(membership._wrapper);
        public ParentTransferToken DetachForTransfer(IComponentVM vm)
        {
            var staged = parent.DetachForTransfer(membership._wrapper);
            return new ParentTransferToken(
                commit: () =>
                {
                    try { staged.Commit(); }
                    finally { membership.ClearDirectParent(); }
                },
                rollback: staged.Rollback);
        }
    }

    private sealed class WrappedParentAdapter(
        IParentCompositeVM parent,
        ForwardingMembership membership) : IParentCompositeVM
    {
        public IComponentVM? Owner => parent.Owner;
        public IParentCompositeVM? OwnerParent => parent.OwnerParent;
        public bool SupportsChildSelection => parent.SupportsChildSelection;
        public IComponentVM? CurrentChild =>
            ReferenceEquals(parent.CurrentChild, membership._wrapped)
                ? membership._wrapper
                : parent.CurrentChild;
        public void SelectChild(IComponentVM vm) => parent.SelectChild(membership._wrapped);
        public void DeselectChild(IComponentVM vm) => parent.DeselectChild(membership._wrapped);
        public bool ContainsChild(IComponentVM vm) => parent.ContainsChild(membership._wrapped);
        public ParentTransferToken DetachForTransfer(IComponentVM vm)
        {
            var retained = new List<ForwardingMembership>();
            for (var cursor = parent as ParentAdapter;
                 cursor is not null;
                 cursor = cursor.Parent as ParentAdapter)
                retained.Add(cursor.RetainedMembership);
            var staged = parent.DetachForTransfer(membership._wrapped);
            return new ParentTransferToken(
                commit: () =>
                {
                    try { staged.Commit(); }
                    finally
                    {
                        foreach (var other in retained)
                            if (!ReferenceEquals(other, membership))
                                other.ClearDirectParent();
                    }
                },
                rollback: staged.Rollback);
        }
    }

    private readonly IComponentVM _wrapper = wrapper;
    private readonly IComponentVM _wrapped = wrapped;

    private void ClearDirectParent() => _parent = null;

    internal IParentCompositeVM? Parent
    {
        get
        {
            if (_parent is not null) return _parent;
            var wrappedParent = _wrapped.GetParent();
            return wrappedParent is null
                ? null
                : new WrappedParentAdapter(wrappedParent, this);
        }
    }

    internal IComponentVM OwnershipIdentity => _wrapped.GetOwnershipIdentity();

    /// <summary>Registers a resource on the canonical ownership identity (ADR-0151).</summary>
    internal T Own<T>(T resource) where T : IDisposable
        => OwnershipIdentity is ComponentVMBase owner
            ? owner.OwnForAlias(resource)
            : throw new InvalidOperationException(
                "A forwarding decorator must wrap a VMx ComponentVMBase to own resources.");

    internal void SetParent(IParentCompositeVM? parent)
    {
        _parent = parent;
        _wrapped.SetParent(parent is null ? null : new ParentAdapter(parent, this));
    }

    internal void SetIsCurrent(bool value) => _wrapped.SetIsCurrent(value);

    internal bool CommitIsCurrent(bool value) => _wrapped.CommitIsCurrent(value);

    internal void PublishIsCurrent() => _wrapped.PublishIsCurrent();

    internal Task ConstructOrJoinAsync() => _wrapped.ConstructOrJoinAsync();

    internal Task JoinConstructAsync() => _wrapped.JoinConstructAsync();
}
