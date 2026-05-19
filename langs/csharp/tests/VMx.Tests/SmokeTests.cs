using System.Reflection;
using FluentAssertions;
using Xunit;

namespace VMx.Tests;

public class SmokeTests
{
    [Fact]
    public void Placeholder_Has_MinSpecVersion()
    {
        Placeholder.MinSpecVersion.Should().Be("0.0.0");
    }

    [Fact]
    public void Assembly_Has_MinSpecVersion_Metadata()
    {
        var assembly = typeof(Placeholder).Assembly;
        var minSpec = assembly
            .GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "MinSpecVersion");

        minSpec.Should().NotBeNull();
        minSpec!.Value.Should().Be("0.0.0");
    }
}
