#pragma warning disable CA1715 // Spec uses 'M' for model type parameter per ADR-0006
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Sealed, read-only modeled leaf viewmodel. Model is fixed at build time.
///
/// See spec/05-component-vm.md §Readonly variant (type=ReadOnlyComponent).
/// Use <c>ReadonlyComponentVM&lt;M&gt;.Builder()</c> to construct instances.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public sealed class ReadonlyComponentVM<M> : ComponentVMBase, IReadonlyComponentVM<M>
{
    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.ReadOnlyComponent;

    /// <inheritdoc/>
    public M Model { get; }

    /// <inheritdoc/>
    public string ModeledHint { get; }

    private ReadonlyComponentVM(
        string name,
        string hint,
        M model,
        Func<M, string> modeledHinter,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct)
    {
        Model = model;
        ModeledHint = modeledHinter(model);
    }

    // ── Builder factory ──────────────────────────────────────────────────────
#pragma warning disable CA1000 // Generic static member on generic type: intentional per spec
    /// <summary>Returns a new empty builder for <see cref="ReadonlyComponentVM{M}"/>.</summary>
    public static ReadonlyComponentVMBuilder<M> Builder() => ReadonlyComponentVMBuilder<M>.Empty;
#pragma warning restore CA1000

    // ── Internal factory used by builder ────────────────────────────────────
    internal static ReadonlyComponentVM<M> Create(
        string name,
        string hint,
        M model,
        Func<M, string> modeledHinter,
        IMessageHub hub,
        IDispatcher dispatcher,
        Action? onConstruct,
        Action? onDestruct)
        => new(name, hint, model, modeledHinter, hub, dispatcher, onConstruct, onDestruct);
}
#pragma warning restore CA1715
