using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Tests.Lifecycle;

public class LifecycleTransitionValidatorTests
{
    [Theory]
    [InlineData(ConstructionStatus.Destructed, "construct", true)]
    [InlineData(ConstructionStatus.Constructed, "destruct", true)]
    [InlineData(ConstructionStatus.Constructed, "reconstruct", true)]
    [InlineData(ConstructionStatus.Disposed, "construct", false)]
    [InlineData(ConstructionStatus.Disposed, "destruct", false)]
    [InlineData(ConstructionStatus.Disposed, "reconstruct", false)]
    [InlineData(ConstructionStatus.Constructing, "construct", false)]
    [InlineData(ConstructionStatus.Destructing, "destruct", false)]
    public void IsLegal_Matches_Fixture(ConstructionStatus from, string op, bool expected)
    {
        LifecycleTransitionValidator.IsLegal(from, op).Should().Be(expected);
    }

    [Fact]
    public void Require_Throws_With_State_And_Operation_In_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "construct"));
        ex.CurrentStatus.Should().Be(ConstructionStatus.Disposed);
        ex.AttemptedOperation.Should().Be("construct");
        ex.Message.Should().Contain("Disposed").And.Contain("construct");
    }

    [Fact]
    public void FinalState_Returns_Expected_Status_For_Legal_Transitions()
    {
        LifecycleTransitionValidator.FinalState(ConstructionStatus.Destructed, "construct")
            .Should().Be(ConstructionStatus.Constructed);
        LifecycleTransitionValidator.FinalState(ConstructionStatus.Constructed, "destruct")
            .Should().Be(ConstructionStatus.Destructed);
    }
}
