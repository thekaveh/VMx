using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Arity-1 aggregate viewmodel interface.
/// Exposes one typed component slot populated on construct().
/// See spec/08-aggregate-vm.md.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
public interface IAggregateVM1<out VM1> : IComponentVM
    where VM1 : class, IComponentVM
{
    /// <summary>The first component VM. Populated after construct(); null before.</summary>
    VM1? Component1 { get; }
}
