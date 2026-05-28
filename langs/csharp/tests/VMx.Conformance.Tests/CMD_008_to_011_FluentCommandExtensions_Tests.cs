using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance stubs for CMD-008..CMD-011 — fluent command extension methods.
/// See spec/04-commands.md §9 and ADR-0027.
/// Implementation deferred to Substage 1D execution phase.
/// </summary>
public class CMD_008_to_011_FluentCommandExtensions_Tests
{
    // ── CMD-008 ────────────────────────────────────────────────────────────

    /// <summary>CMD-008: Confirm(delegate) is equivalent to explicit ConfirmationDecoratorCommand.</summary>
    [Fact, Trait("Conformance", "CMD-008")]
    public void CMD_008_Confirm_Equivalent_To_Explicit_Constructor()
    {
        // TODO(Substage-1D-exec): implement using ICommandExtensions.Confirm once added.
        throw new NotImplementedException("CMD-008 stub — pending Substage 1D implementation.");
    }

    // ── CMD-009 ────────────────────────────────────────────────────────────

    /// <summary>CMD-009: PrecedeWith(other) is equivalent to CompositeCommand(other, receiver).</summary>
    [Fact, Trait("Conformance", "CMD-009")]
    public void CMD_009_PrecedeWith_Equivalent_To_Explicit_Constructor()
    {
        // TODO(Substage-1D-exec): implement using ICommandExtensions.PrecedeWith once added.
        throw new NotImplementedException("CMD-009 stub — pending Substage 1D implementation.");
    }

    // ── CMD-010 ────────────────────────────────────────────────────────────

    /// <summary>CMD-010: SucceedWith(other) is equivalent to CompositeCommand(receiver, other).</summary>
    [Fact, Trait("Conformance", "CMD-010")]
    public void CMD_010_SucceedWith_Equivalent_To_Explicit_Constructor()
    {
        // TODO(Substage-1D-exec): implement using ICommandExtensions.SucceedWith once added.
        throw new NotImplementedException("CMD-010 stub — pending Substage 1D implementation.");
    }

    // ── CMD-011 ────────────────────────────────────────────────────────────

    /// <summary>CMD-011: WrapWith(predicate?, pre?, post?) is equivalent to explicit DecoratorCommand.</summary>
    [Fact, Trait("Conformance", "CMD-011")]
    public void CMD_011_WrapWith_Equivalent_To_Explicit_Constructor()
    {
        // TODO(Substage-1D-exec): implement using ICommandExtensions.WrapWith once added.
        throw new NotImplementedException("CMD-011 stub — pending Substage 1D implementation.");
    }
}
