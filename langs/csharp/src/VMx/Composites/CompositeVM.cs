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

    // ── Options factory (additive; ADR-0055 / VMX-020) ──────────────────────
    /// <summary>
    /// Constructs a <see cref="CompositeVM{VM}"/> from a <see cref="CompositeVMOptions{VM}"/>
    /// record in a single call — an additive alternative to the fluent
    /// <see cref="CompositeVMBuilder{VM}"/>. Delegates to that builder, so the
    /// required-field validation (<see cref="VMx.Builders.BuilderValidationException"/>
    /// on a missing Name/Hub/Dispatcher/Children) and the resulting VM are identical
    /// to the fluent path.
    /// </summary>
    public static CompositeVM<VM> Create(CompositeVMOptions<VM> options)
    {
        var b = CompositeVMBuilder<VM>.Empty
            .Hint(options.Hint)
            .AsyncSelection(options.AsyncSelection)
            .AutoConstructOnAdd(options.AutoConstructOnAdd);
        if (options.Name is not null) b = b.Name(options.Name);
        if (options.Hub is not null) b = b.OptionHub(options.Hub);
        if (options.Dispatcher is not null) b = b.OptionDispatcher(options.Dispatcher);
        if (options.Children is not null) b = b.Children(options.Children);
        if (options.Current is not null) b = b.Current(options.Current);
        if (options.OnCurrentChanged is not null) b = b.OnCurrentChanged(options.OnCurrentChanged);
        if (options.OnConstruct is not null) b = b.OnConstruct(options.OnConstruct);
        if (options.OnDestruct is not null) b = b.OnDestruct(options.OnDestruct);
        return b.Build();
    }

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
        AttachPopulation(_childrenFactory());
        _populated = true;
    }
}
