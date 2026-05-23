#pragma warning disable CA1715 // Spec uses 'VM' for child VM type parameter per ADR-0006
namespace VMx.Components;

/// <summary>
/// Minimal forward-declaration of <see cref="ICompositeVM{VM}"/> needed by
/// <see cref="ComponentVMBase"/> so it can expose a typed <c>Parent</c>.
/// The full implementation lives in the Composites module (Task 7).
/// See spec/06-composite-vm.md.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public interface ICompositeVM<VM> : IComponentVM where VM : IComponentVM
{
    /// <summary>The currently selected child, or null if none.</summary>
    VM? Current { get; }

    /// <summary>Selects <paramref name="vm"/> as the current child.</summary>
    void SelectComponent(VM vm);

    /// <summary>Deselects <paramref name="vm"/>.</summary>
    void DeselectComponent(VM vm);

    /// <summary>Returns true when <paramref name="vm"/> can be selected.</summary>
    bool CanSelectComponent(VM vm);
}
#pragma warning restore CA1715
