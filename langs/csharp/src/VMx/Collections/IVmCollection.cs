using System.Collections.Specialized;
using VMx.Components;

namespace VMx.Collections;

/// <summary>
/// Shared ordered, observable, lifecycle-aware child-collection capability.
/// Selection is intentionally excluded; use <see cref="ISelectableVmCollection{VM}"/>
/// when a collection owns a current-child slot.
/// </summary>
public interface IVmCollection<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged
    where VM : class, IComponentVM
{
    /// <summary>Moves the existing child at <paramref name="fromIndex"/> to <paramref name="toIndex"/>.</summary>
    /// <remarks>Both indices address the pre-move collection and must be in <c>[0, Count)</c>.</remarks>
    void Move(int fromIndex, int toIndex);

    /// <summary>Opens a ref-counted collection mutation batch.</summary>
    IDisposable BatchUpdate();
}

/// <summary>A VM collection that additionally owns a current-child selection slot.</summary>
public interface ISelectableVmCollection<VM> : IVmCollection<VM>
    where VM : class, IComponentVM
{
    /// <summary>The currently selected child, or <c>null</c>.</summary>
    VM? Current { get; set; }

    /// <summary>Selects a constructed child member.</summary>
    void SelectComponent(VM vm);

    /// <summary>Deselects the current child.</summary>
    void DeselectComponent(VM vm);

    /// <summary>Returns whether <paramref name="vm"/> can become current.</summary>
    bool CanSelectComponent(VM vm);
}
