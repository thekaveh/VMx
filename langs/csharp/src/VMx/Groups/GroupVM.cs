using VMx.Components;
using VMx.Services;

namespace VMx.Groups;

/// <summary>
/// Sealed non-modeled group VM. Children are supplied by a builder factory
/// <c>() =&gt; IEnumerable&lt;VM&gt;</c> evaluated lazily on the first <see cref="ComponentVMBase.Construct"/>.
///
/// Use <c>GroupVM&lt;VM&gt;.Builder()</c> to create instances.
/// See spec/07-group-vm.md §Builder (non-modeled variant).
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class GroupVM<VM> : GroupVMBase<VM>, IGroupVM<VM>
    where VM : class, IComponentVM
{
    private readonly Func<IEnumerable<VM>>? _childrenFactory;
    private bool _populated;

    private GroupVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct)
        : base(name, hint, hub, dispatcher, autoConstructOnAdd, onConstruct, onDestruct)
    {
        _childrenFactory = childrenFactory;
    }

    /// <summary>Returns a new empty builder for <see cref="GroupVM{VM}"/>.</summary>
    public static GroupVMBuilder<VM> Builder() => GroupVMBuilder<VM>.Empty;

    /// <summary>Internal factory called by the builder.</summary>
    internal static GroupVM<VM> Create(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct)
        => new(name, hint, hub, dispatcher, autoConstructOnAdd, childrenFactory, onConstruct, onDestruct);

    /// <inheritdoc/>
    protected override void PopulateChildren()
    {
        if (_populated || _childrenFactory is null) return;
        _populated = true;
        foreach (var child in _childrenFactory())
            Add(child);
    }
}
