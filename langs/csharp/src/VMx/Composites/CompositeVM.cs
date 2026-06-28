using VMx.Components;
using VMx.Services;

namespace VMx.Composites;

/// <summary>
/// Sealed non-modeled composite VM.  Children are supplied by a builder factory
/// <c>() =&gt; IEnumerable&lt;VM&gt;</c> evaluated lazily on the first <see cref="ComponentVMBase.Construct"/>.
///
/// Use <c>CompositeVM&lt;VM&gt;.Builder()</c> to create instances.
/// See spec/06-composite-vm.md §Variants (non-modeled).
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class CompositeVM<VM> : CompositeVMBase<VM>, ICompositeVM<VM>
    where VM : class, IComponentVM
{
    private readonly Func<IEnumerable<VM>>? _childrenFactory;
    private bool _populated;

    private CompositeVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged)
        : base(name, hint, hub, dispatcher, asyncSelection, autoConstructOnAdd, onConstruct, onDestruct, currentSelector, onCurrentChanged)
    {
        _childrenFactory = childrenFactory;
    }

    /// <summary>Returns a new empty builder for <see cref="CompositeVM{VM}"/>.</summary>
    public static CompositeVMBuilder<VM> Builder() => CompositeVMBuilder<VM>.Empty;

    /// <summary>Internal factory called by the builder.</summary>
    internal static CompositeVM<VM> Create(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector,
        Action<VM?>? onCurrentChanged)
        => new(name, hint, hub, dispatcher, asyncSelection, autoConstructOnAdd, childrenFactory, onConstruct, onDestruct, currentSelector, onCurrentChanged);

    /// <inheritdoc/>
    protected override void PopulateChildren()
    {
        if (_populated || _childrenFactory is null) return;
        _populated = true;
        foreach (var child in _childrenFactory())
            Add(child);
    }
}
