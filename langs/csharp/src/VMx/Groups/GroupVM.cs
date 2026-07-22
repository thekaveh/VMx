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

    // ── Options factory (additive; ADR-0055 / VMX-020) ──────────────────────
    /// <summary>
    /// Constructs a <see cref="GroupVM{VM}"/> from a <see cref="GroupVMOptions{VM}"/>
    /// record in a single call — an additive alternative to the fluent
    /// <see cref="GroupVMBuilder{VM}"/>. Delegates to that builder, so the
    /// required-field validation (<see cref="VMx.Builders.BuilderValidationException"/>
    /// on a missing Name/Hub/Dispatcher/Children) and the resulting VM are identical
    /// to the fluent path.
    /// </summary>
    public static GroupVM<VM> Create(GroupVMOptions<VM> options)
    {
        var b = GroupVMBuilder<VM>.Empty
            .Hint(options.Hint)
            .AutoConstructOnAdd(options.AutoConstructOnAdd);
        if (options.Name is not null) b = b.Name(options.Name);
        if (options.Hub is not null) b = b.OptionHub(options.Hub);
        if (options.Dispatcher is not null) b = b.OptionDispatcher(options.Dispatcher);
        if (options.Children is not null) b = b.Children(options.Children);
        if (options.OnConstruct is not null) b = b.OnConstruct(options.OnConstruct);
        if (options.OnDestruct is not null) b = b.OnDestruct(options.OnDestruct);
        return b.Build();
    }

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
        AttachPopulation(_childrenFactory(), () => _populated = true);
    }
}
