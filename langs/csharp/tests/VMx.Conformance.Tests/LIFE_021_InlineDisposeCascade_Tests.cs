using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-021 — a lifecycle call during the inline dispose cascade fails.
/// PLACEHOLDER: spec/02 §7.2 and ADR-0175 define the rule. A
/// <c>Construct()</c>, <c>Destruct()</c>, or <c>Reconstruct()</c> call that
/// starts during the cascade throws <c>StatusTransitionException</c> for
/// <c>Disposed</c> and publishes nothing, and no status other than
/// <c>Disposed</c> commits once the cascade has started. The implementation PR
/// replaces this skipped placeholder with the full LIFE-021 scenarios.
/// </summary>
public class LIFE_021_InlineDisposeCascade_Tests
{
    [Fact(Skip = "LIFE-021 placeholder: replaced by the ADR-0175 implementation")]
    [Trait("Conformance", "LIFE-021")]
    public void LIFE_021_Placeholder()
    {
    }
}
