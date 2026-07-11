using System.ComponentModel;
using System.Windows.Input;
using VMx.Capabilities;
using VMx.Lifecycle;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Baseline interface for every ComponentVM variant.
/// See spec/05-component-vm.md §Members and spec/01-concepts.md §IComponentVM.
///
/// Implements the three lifecycle capabilities per spec/14-capabilities.md rule 2.
/// </summary>
public interface IComponentVM
    : INotifyPropertyChanged, IDisposable,
      IConstructable, IDestructable, IReconstructable
{
    /// <summary>Human-readable identifier; immutable post-construction.</summary>
    string Name { get; }

    /// <summary>Optional descriptive hint; immutable post-construction.</summary>
    string Hint { get; }

    /// <summary>Role discriminator; immutable.</summary>
    ViewModelType Type { get; }

    /// <summary>True when this VM is the current selection of its parent composite.</summary>
    bool IsCurrent { get; }

    /// <summary>True when Status == Constructed.</summary>
    bool IsConstructed { get; }

    /// <summary>Current lifecycle state.</summary>
    ConstructionStatus Status { get; }

    /// <summary>Injected shared message hub; the VM does not own its lifetime.</summary>
    IMessageHub Hub { get; }

    // ── Built-in commands ───────────────────────────────────────────────────

    /// <summary>Selects this VM in its parent composite.</summary>
    ICommand SelectCommand { get; }

    /// <summary>Deselects this VM in its parent composite.</summary>
    ICommand DeselectCommand { get; }

    /// <summary>Moves the parent's current selection to the next sibling.</summary>
    ICommand SelectNextCommand { get; }

    /// <summary>Moves the parent's current selection to the previous sibling.</summary>
    ICommand SelectPreviousCommand { get; }

    /// <summary>Destructs then re-constructs this VM.</summary>
    ICommand ReconstructCommand { get; }

    // ── Lifecycle operations are inherited from IConstructable, IDestructable,
    //    IReconstructable (capability micro-interfaces per spec ch. 14 rule 2).

    // ── Selection operations ────────────────────────────────────────────────

    /// <summary>Returns true when this VM can be selected.</summary>
    bool CanSelect();

    /// <summary>Selects this VM in its parent composite (spec: select()).</summary>
    void Select();

    /// <summary>Returns true when this VM can be deselected.</summary>
    bool CanDeselect();

    /// <summary>Deselects this VM in its parent composite.</summary>
    void Deselect();
}
