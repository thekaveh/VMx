#pragma warning disable CA1715 // Spec uses 'M' for model type parameter per ADR-0006
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Convenience extensions for the three <c>ComponentVM</c>-family builders.
///
/// <para>
/// <see cref="WithNullServices(ComponentVMBuilder)"/> and its overloads wire
/// <see cref="NullMessageHub.Instance"/> + <see cref="NullDispatcher.Instance"/>
/// into the builder in a single call, removing the boilerplate of constructing
/// or referencing the null services explicitly. Intended for tests, samples,
/// and exploration code. Production VMs should call the builder's
/// <c>Services(hub, dispatcher)</c> method with real services instead.
/// </para>
/// </summary>
public static class ComponentVMBuilderExtensions
{
    /// <summary>
    /// Wires <see cref="NullMessageHub.Instance"/> and
    /// <see cref="NullDispatcher.Instance"/> into the builder.
    /// </summary>
    public static ComponentVMBuilder<M> WithNullServices<M>(this ComponentVMBuilder<M> builder)
        => builder.Services(NullMessageHub.Instance, NullDispatcher.Instance);

    /// <summary>
    /// Wires <see cref="NullMessageHub.Instance"/> and
    /// <see cref="NullDispatcher.Instance"/> into the builder.
    /// </summary>
    public static ComponentVMBuilder WithNullServices(this ComponentVMBuilder builder)
        => builder.Services(NullMessageHub.Instance, NullDispatcher.Instance);

    /// <summary>
    /// Wires <see cref="NullMessageHub.Instance"/> and
    /// <see cref="NullDispatcher.Instance"/> into the builder.
    /// </summary>
    public static ReadonlyComponentVMBuilder<M> WithNullServices<M>(this ReadonlyComponentVMBuilder<M> builder)
        => builder.Services(NullMessageHub.Instance, NullDispatcher.Instance);
}
#pragma warning restore CA1715
