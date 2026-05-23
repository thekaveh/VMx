#pragma warning disable CA1715 // Spec uses 'M' for model type parameter per ADR-0006
namespace VMx.Components;

/// <summary>
/// Read-only modeled ComponentVM: exposes <see cref="Model"/> as a get-only property
/// (model is provided at build time and never changes).
/// See spec/05-component-vm.md §Readonly variant.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public interface IReadonlyComponentVM<M> : IComponentVM
{
    /// <summary>The model value fixed at build time.</summary>
    M Model { get; }

    /// <summary>Derived hint, computed from the fixed model at construction time.</summary>
    string ModeledHint { get; }
}
#pragma warning restore CA1715
