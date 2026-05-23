#pragma warning disable CA1715 // Spec uses 'M' for model type parameter per ADR-0006
using VMx.Services;

namespace VMx.Components;

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
#pragma warning disable CA1000 // Generic static member on generic type: intentional per spec
    /// <summary>Returns a new empty builder for <see cref="ComponentVM{M}"/>.</summary>
    public static ComponentVMBuilder<M> Builder() => ComponentVMBuilder<M>.Empty;
#pragma warning restore CA1000

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
#pragma warning restore CA1715
