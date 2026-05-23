namespace VMx.Components;

/// <summary>
/// Discriminator that identifies what role a viewmodel plays in the hierarchy.
/// See spec/05-component-vm.md §Variants and spec/01-concepts.md.
/// </summary>
public enum ViewModelType
{
    /// <summary>A modeled or non-modeled leaf component VM.</summary>
    Component = 0,

    /// <summary>A read-only modeled leaf component VM (model is immutable post-construction).</summary>
    ReadOnlyComponent = 1,

    /// <summary>A VM that aggregates multiple heterogeneous child VMs.</summary>
    Aggregate = 2,

    /// <summary>A VM that groups homogeneous child VMs.</summary>
    Group = 3,

    /// <summary>A VM that contains an ordered collection of child VMs with selection.</summary>
    Composite = 4,
}
