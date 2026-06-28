using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Arity-4 aggregate viewmodel interface.
/// Exposes four typed component slots populated on construct().
/// See spec/08-aggregate-vm.md.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
/// <typeparam name="VM2">Type of the second component.</typeparam>
/// <typeparam name="VM3">Type of the third component.</typeparam>
/// <typeparam name="VM4">Type of the fourth component.</typeparam>
public interface IAggregateVM4<out VM1, out VM2, out VM3, out VM4> : IComponentVM
    where VM1 : class, IComponentVM
    where VM2 : class, IComponentVM
    where VM3 : class, IComponentVM
    where VM4 : class, IComponentVM
{
    /// <summary>The first component VM. Populated after construct(); null before.</summary>
    VM1? Component1 { get; }

    /// <summary>The second component VM. Populated after construct(); null before.</summary>
    VM2? Component2 { get; }

    /// <summary>The third component VM. Populated after construct(); null before.</summary>
    VM3? Component3 { get; }

    /// <summary>The fourth component VM. Populated after construct(); null before.</summary>
    VM4? Component4 { get; }
}
