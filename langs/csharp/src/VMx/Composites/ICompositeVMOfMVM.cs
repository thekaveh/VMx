using VMx.Components;

namespace VMx.Composites;

/// <summary>
/// Modeled composite: children are derived from a model factory and a model→VM mapper.
/// The model values are NOT exposed on the composite itself; children hold their own models.
///
/// See spec/06-composite-vm.md §Modeled variant.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public interface ICompositeVM<M, VM> : ICompositeVM<VM>
    where VM : class, IComponentVM
{
}
