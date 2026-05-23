using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Tests.Lifecycle;

public class ConstructionStatusTests
{
    [Fact]
    public void Has_Five_States()
    {
        Enum.GetValues<ConstructionStatus>().Should().HaveCount(5)
            .And.Contain([
                ConstructionStatus.Disposed,
                ConstructionStatus.Destructing,
                ConstructionStatus.Destructed,
                ConstructionStatus.Constructing,
                ConstructionStatus.Constructed,
            ]);
    }

    [Fact]
    public void Disposed_Is_Terminal_Numeric_Zero()
    {
        ((int)ConstructionStatus.Disposed).Should().Be(0,
            "spec/02-lifecycle.md treats Disposed as the terminal state");
    }
}
