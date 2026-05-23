using System.ComponentModel;
using System.Windows.Input;
using VMx.Lifecycle;

namespace VMx.Components;

/// <summary>
/// Baseline interface for every ComponentVM variant.
/// See spec/05-component-vm.md §Members and spec/01-concepts.md §IComponentVM.
/// </summary>
public interface IComponentVM : INotifyPropertyChanged, IDisposable
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

    // ── Lifecycle operations ────────────────────────────────────────────────

    /// <summary>Returns true when Construct() is safe to call.</summary>
    bool CanConstruct();

    /// <summary>Transitions Destructed → Constructing → Constructed.</summary>
    void Construct();

    /// <summary>Transitions Destructed → Constructing → Constructed asynchronously.</summary>
    Task ConstructAsync();

    /// <summary>Returns true when Destruct() is safe to call.</summary>
    bool CanDestruct();

    /// <summary>Transitions Constructed → Destructing → Destructed.</summary>
    void Destruct();

    /// <summary>Transitions Constructed → Destructing → Destructed asynchronously.</summary>
    Task DestructAsync();

    /// <summary>Returns true when Reconstruct() is safe to call.</summary>
    bool CanReconstruct();

    /// <summary>Destructs then re-constructs this VM.</summary>
    void Reconstruct();

    /// <summary>Destructs then re-constructs this VM asynchronously.</summary>
    Task ReconstructAsync();

    // ── Selection operations ────────────────────────────────────────────────

    /// <summary>Returns true when this VM can be selected.</summary>
    bool CanSelect();

    /// <summary>Selects this VM in its parent composite (spec: select()).</summary>
#pragma warning disable CA1716 // 'Select' is the spec-mandated name per spec/05-component-vm.md
    void Select();
#pragma warning restore CA1716

    /// <summary>Returns true when this VM can be deselected.</summary>
    bool CanDeselect();

    /// <summary>Deselects this VM in its parent composite.</summary>
    void Deselect();
}
