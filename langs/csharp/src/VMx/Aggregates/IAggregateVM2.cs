using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Arity-2 aggregate viewmodel interface.
/// Exposes two typed component slots populated on construct().
/// See spec/08-aggregate-vm.md.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
/// <typeparam name="VM2">Type of the second component.</typeparam>
public interface IAggregateVM2<out VM1, out VM2> : IComponentVM
    where VM1 : class, IComponentVM
    where VM2 : class, IComponentVM
{
    /// <summary>The first component VM. Populated after construct(); null before.</summary>
    VM1? Component1 { get; }

    /// <summary>The second component VM. Populated after construct(); null before.</summary>
    VM2? Component2 { get; }
}
