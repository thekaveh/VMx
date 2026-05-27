using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

/// <summary>
/// Unit tests for <see cref="DecoratorCommand"/> behavior not covered by
/// CMDD-001..009 in the conformance catalog (e.g., exception handling
/// semantics on inner.Execute).
/// </summary>
public class DecoratorCommandTests
{
    private static System.Windows.Input.ICommand BuildThrowing()
    {
        return RelayCommand.Builder()
            .Task(() => throw new InvalidOperationException("boom"))
            .Predicate(() => true)
            .Build();
    }

    [Fact]
    public void PostExecute_Runs_Even_When_Inner_Throws()
    {
        var log = new List<string>();
        using var dec = new DecoratorCommand(
            BuildThrowing(),
            preExecute: () => log.Add("pre"),
            postExecute: () => log.Add("post"));

        Action act = () => dec.Execute(null);

        act.Should().Throw<InvalidOperationException>();
        log.Should().Equal("pre", "post");
    }
}
