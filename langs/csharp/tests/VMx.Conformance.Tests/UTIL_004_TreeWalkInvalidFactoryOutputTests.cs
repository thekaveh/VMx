using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tree.Tree;

namespace VMx.Conformance.Tests;

/// <summary>
/// UTIL-004 — <c>Walk</c>, <c>WalkExpanded</c> and <c>Find</c> report invalid
/// children-factory output as a recoverable error (spec/13 §6.1, ADR-0170).
/// </summary>
public class UTIL_004_TreeWalkInvalidFactoryOutputTests
{
    private sealed class WalkNode(string name, Func<WalkNode, IEnumerable<WalkNode>>? factory = null)
        : HierarchicalVM<string, WalkNode>(
            name,
            factory ?? (_ => []),
            new TestHub(),
            new TestDispatcher(),
            name)
    {
        public override ViewModelType Type => ViewModelType.Component;
    }

    [Fact]
    [Trait("Conformance", "UTIL-004")]
    public void UTIL_004_Walks_Report_Invalid_Factory_Output_And_Stay_Retryable()
    {
        var a = new WalkNode("a");
        var c = new WalkNode("c");
        var d = new WalkNode("d");
        WalkNode[] snapshot = [c, c];
        var calls = 0;
        var b = new WalkNode("b", _ =>
        {
            calls++;
            return snapshot;
        });
        var root = new WalkNode("root", _ => [a, b]);
        root.Children.Should().Equal(a, b);

        FluentActions.Enumerating(() => Walk(root)).Should().Throw<InvalidOperationException>();
        FluentActions.Enumerating(() => WalkExpanded(root)).Should().Throw<InvalidOperationException>();
        FluentActions.Invoking(() => Find(root, _ => false)).Should().Throw<InvalidOperationException>();
        calls.Should().Be(3, "each walk retries the factory");
        c.HierarchicalParent.Should().BeNull("a rejected snapshot assigns no parent");
        FluentActions.Invoking(() => b.Children).Should().Throw<InvalidOperationException>();
        calls.Should().Be(4, "b keeps no children cache, so a direct read runs the factory again");

        Find(root, node => ReferenceEquals(node, a)).Should().BeSameAs(a);
        calls.Should().Be(4, "find returns a match before the failing node");

        snapshot = [c, d];
        Walk(root).Select(node => node.Name).Should().Equal("root", "a", "b", "c", "d");
    }
}
