using VMx.Builders;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Sealed, non-modeled leaf viewmodel.
///
/// See spec/05-component-vm.md §Variants (ComponentVM, type=Component). Use
/// <c>ComponentVM.Builder()</c> to construct instances. Pair with
/// <see cref="ComponentVM{M}"/> when a typed model is required.
/// </summary>
public sealed class ComponentVM : ComponentVMBase, IComponentVM
{
    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    private ComponentVM(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct,
        bool background)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct, background)
    {
    }

    // ── Builder factory ──────────────────────────────────────────────────────
    /// <summary>Returns a new empty builder for <see cref="ComponentVM"/>.</summary>
    public static ComponentVMBuilder Builder() => ComponentVMBuilder.Empty;

    // ── Options factory (additive; ADR-0055 / VMX-020) ──────────────────────
    /// <summary>
    /// Constructs a <see cref="ComponentVM"/> from a <see cref="ComponentVMOptions"/>
    /// record in a single call — an additive alternative to the fluent
    /// <see cref="ComponentVMBuilder"/>. Delegates to that builder, so the required-field
    /// validation (<see cref="BuilderValidationException"/> on a missing Name/Hub/Dispatcher)
    /// and the resulting VM are identical to the fluent path.
    /// </summary>
    public static ComponentVM Create(ComponentVMOptions options)
    {
        var b = ComponentVMBuilder.Empty
            .Hint(options.Hint)
            .Background(options.Background);
        if (options.Name is not null) b = b.Name(options.Name);
        if (options.Hub is not null) b = b.OptionHub(options.Hub);
        if (options.Dispatcher is not null) b = b.OptionDispatcher(options.Dispatcher);
        if (options.OnConstruct is not null) b = b.OnConstruct(options.OnConstruct);
        if (options.OnDestruct is not null) b = b.OnDestruct(options.OnDestruct);
        return b.Build();
    }

    // ── Internal factory used by builder ────────────────────────────────────
    internal static ComponentVM Create(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct,
        bool background)
        => new(name, hint, hub, dispatcher, onConstruct, onDestruct, background);
}

/// <summary>
/// Sealed, modeled leaf viewmodel. Model is settable after construction.
///
/// See spec/05-component-vm.md §Variants (ComponentVM&lt;M&gt;, type=Component).
/// Use <c>ComponentVM&lt;M&gt;.Builder()</c> to construct instances.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public sealed class ComponentVM<M> : ComponentVMBaseOfM<M>, IComponentVM<M>
{
    private readonly ViewModelType _type;

    /// <inheritdoc/>
    public override ViewModelType Type => _type;

    /// <inheritdoc/>
    public M Model
    {
        get => ModelValue;
        set => ModelValue = value;
    }

    private ComponentVM(
        string name,
        string hint,
        ViewModelType type,
        M model,
        Func<M, string> modeledHinter,
        Action<M>? onModelChanged,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct,
        bool background = false)
        : base(name, hint, model, modeledHinter, onModelChanged, hub, dispatcher, onConstruct, onDestruct, background)
    {
        _type = type;
    }

    // ── Builder factory ──────────────────────────────────────────────────────
    /// <summary>Returns a new empty builder for <see cref="ComponentVM{M}"/>.</summary>
    public static ComponentVMBuilder<M> Builder() => ComponentVMBuilder<M>.Empty;

    // ── Options factory (additive; ADR-0055 / VMX-020) ──────────────────────
    /// <summary>
    /// Constructs a <see cref="ComponentVM{M}"/> from a <see cref="ComponentVMOptions{M}"/>
    /// record in a single call — an additive alternative to the fluent
    /// <see cref="ComponentVMBuilder{M}"/>. Delegates to that builder, so the required-field
    /// validation (<see cref="BuilderValidationException"/> on a missing Name/Hub/Dispatcher)
    /// and the resulting VM are identical to the fluent path.
    /// </summary>
    public static ComponentVM<M> Create(ComponentVMOptions<M> options)
    {
        var b = ComponentVMBuilder<M>.Empty
            .Hint(options.Hint)
            .Type(options.Type)
            .Model(options.Model)
            .Background(options.Background);
        if (options.Name is not null) b = b.Name(options.Name);
        if (options.Hub is not null) b = b.OptionHub(options.Hub);
        if (options.Dispatcher is not null) b = b.OptionDispatcher(options.Dispatcher);
        if (options.ModeledHinter is not null) b = b.ModeledHinter(options.ModeledHinter);
        if (options.OnModelChanged is not null) b = b.OnModelChanged(options.OnModelChanged);
        if (options.OnConstruct is not null) b = b.OnConstruct(options.OnConstruct);
        if (options.OnDestruct is not null) b = b.OnDestruct(options.OnDestruct);
        return b.Build();
    }

    // ── Internal factory used by builder ────────────────────────────────────
    internal static ComponentVM<M> Create(
        string name,
        string hint,
        ViewModelType type,
        M model,
        Func<M, string> modeledHinter,
        Action<M>? onModelChanged,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct,
        bool background = false)
        => new(name, hint, type, model, modeledHinter, onModelChanged, hub, dispatcher, onConstruct, onDestruct, background);
}
