using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Arity-6 aggregate viewmodel interface.
/// Exposes six typed component slots populated on construct().
/// See spec/08-aggregate-vm.md and ADR-0034.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
/// <typeparam name="VM2">Type of the second component.</typeparam>
/// <typeparam name="VM3">Type of the third component.</typeparam>
/// <typeparam name="VM4">Type of the fourth component.</typeparam>
/// <typeparam name="VM5">Type of the fifth component.</typeparam>
/// <typeparam name="VM6">Type of the sixth component.</typeparam>
public interface IAggregateVM6<out VM1, out VM2, out VM3, out VM4, out VM5, out VM6> : IComponentVM
    where VM1 : class, IComponentVM
    where VM2 : class, IComponentVM
    where VM3 : class, IComponentVM
    where VM4 : class, IComponentVM
    where VM5 : class, IComponentVM
    where VM6 : class, IComponentVM
{
    /// <summary>The first component VM. Populated after construct(); null before.</summary>
    VM1? Component1 { get; }

    /// <summary>The second component VM. Populated after construct(); null before.</summary>
    VM2? Component2 { get; }

    /// <summary>The third component VM. Populated after construct(); null before.</summary>
    VM3? Component3 { get; }

    /// <summary>The fourth component VM. Populated after construct(); null before.</summary>
    VM4? Component4 { get; }

    /// <summary>The fifth component VM. Populated after construct(); null before.</summary>
    VM5? Component5 { get; }

    /// <summary>The sixth component VM. Populated after construct(); null before.</summary>
    VM6? Component6 { get; }
}
