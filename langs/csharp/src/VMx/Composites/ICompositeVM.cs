#pragma warning disable CA1715 // Spec uses 'VM' for child VM type parameter per ADR-0006
using System.Collections.Specialized;
using VMx.Components;

namespace VMx.Composites;

/// <summary>
/// A container viewmodel with an ordered list of children and a <see cref="Current"/>
/// selection slot. Inherits lifecycle and selection from <see cref="IComponentVM"/>.
///
/// See spec/06-composite-vm.md §Members and §Current contract.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public interface ICompositeVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged
    where VM : class, IComponentVM
{
    /// <summary>
    /// The currently selected child, or <c>null</c> if none is selected.
    /// Setting to a value not in the children collection raises <see cref="InvalidOperationException"/>.
    /// Setting to <c>null</c> is always legal.
    /// </summary>
    VM? Current { get; set; }

    /// <summary>
    /// Selects <paramref name="vm"/> as the current child.
    /// Raises if <see cref="CanSelectComponent(VM)"/> returns false.
    /// </summary>
    void SelectComponent(VM vm);

    /// <summary>
    /// Deselects <paramref name="vm"/>.
    /// Raises if <paramref name="vm"/> is not the current selection.
    /// </summary>
    void DeselectComponent(VM vm);

    /// <summary>
    /// Returns <c>true</c> iff <paramref name="vm"/> is in the children collection
    /// and has <see cref="IComponentVM.Status"/> == <see cref="Lifecycle.ConstructionStatus.Constructed"/>.
    /// </summary>
    bool CanSelectComponent(VM vm);
}
#pragma warning restore CA1715
