using VMx.Collections;
using VMx.Components;

namespace VMx.Composites;

/// <summary>
/// A container viewmodel with an ordered list of children and a <see cref="ISelectableVmCollection{VM}.Current"/>
/// selection slot. Inherits lifecycle and selection from <see cref="IComponentVM"/>.
///
/// See spec/06-composite-vm.md §Members and §Current contract.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public interface ICompositeVM<VM> : ISelectableVmCollection<VM>
    where VM : class, IComponentVM
{
}
