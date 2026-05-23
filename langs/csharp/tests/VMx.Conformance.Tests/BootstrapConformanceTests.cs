using FluentAssertions;
using Xunit;

namespace VMx.Conformance.Tests;

public class BootstrapConformanceTests
{
    [Fact]
    public void FixturesAreAvailable()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "lifecycle-transitions.json");
        File.Exists(path).Should().BeTrue($"fixture should be copied to {path}");
    }
}
