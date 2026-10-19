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
    private static RelayCommand BuildThrowing()
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

    [Fact]
    public void CompositeCommand_copies_its_inner_list_and_rejects_null_entries()
    {
        var log = new List<string>();
        var a = RelayCommand.Builder().Task(() => log.Add("a")).Build();
        var b = RelayCommand.Builder().Task(() => log.Add("b")).Build();
        var inner = new System.Windows.Input.ICommand[] { a };
        var composite = new CompositeCommand(inner);

        inner[0] = b;
        composite.Execute(null);

        log.Should().Equal("a");
        var act = () => new CompositeCommand(a, null!);
        act.Should().Throw<ArgumentException>();
    }
}
