using VMx.Components;
using VMx.Services;

namespace VMx.Composites;

/// <summary>
/// Sealed modeled composite VM.  Children are produced by evaluating a
/// <c>ChildrenModels</c> factory and mapping each model <typeparamref name="M"/>
/// to a child VM via <c>ChildModelToChildViewModel</c>, lazily on first Construct.
///
/// Use <c>CompositeVMOfM&lt;M, VM&gt;.Builder()</c> to create instances.
/// See spec/06-composite-vm.md §Modeled variant.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class CompositeVMOfM<M, VM> : CompositeVMBase<VM>, ICompositeVM<M, VM>
    where VM : class, IComponentVM
{
    private readonly Func<IEnumerable<M>> _childrenModels;
    private readonly Func<M, VM> _childModelToChildViewModel;
    private bool _populated;

    private CompositeVMOfM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<M>> childrenModels,
        Func<M, VM> childModelToChildViewModel,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged)
        : base(name, hint, hub, dispatcher, asyncSelection, autoConstructOnAdd, onConstruct, onDestruct, currentSelector, onCurrentChanged)
    {
        _childrenModels = childrenModels;
        _childModelToChildViewModel = childModelToChildViewModel;
    }

    /// <summary>Returns a new empty builder for <see cref="CompositeVMOfM{M,VM}"/>.</summary>
    public static CompositeVMOfMBuilder<M, VM> Builder() => CompositeVMOfMBuilder<M, VM>.Empty;

    /// <summary>Internal factory called by the builder.</summary>
    internal static CompositeVMOfM<M, VM> Create(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<M>> childrenModels,
        Func<M, VM> childModelToChildViewModel,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged)
        => new(name, hint, hub, dispatcher, asyncSelection, autoConstructOnAdd,
               childrenModels, childModelToChildViewModel,
               onConstruct, onDestruct, currentSelector, onCurrentChanged);

    /// <inheritdoc/>
    protected override void PopulateChildren()
    {
        if (_populated) return;
        var children = _childrenModels().Select(_childModelToChildViewModel).ToArray();
        AttachPopulation(children, () => _populated = true);
    }
}
