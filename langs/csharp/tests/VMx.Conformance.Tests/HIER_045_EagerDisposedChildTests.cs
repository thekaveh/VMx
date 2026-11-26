using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// HIER-045: eager construction skips a disposed child (spec/18-hierarchical-vm.md §3,
/// ADR-0258).
/// </summary>
public class HIER_045_EagerDisposedChildTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private sealed class Node(string key, IMessageHub hub, Func<Node, IEnumerable<Node>>? factory = null, bool eager = false)
        : HierarchicalVM<string, Node>(
            key, factory ?? (_ => []), hub, HIER_045_EagerDisposedChildTests.Dispatcher, key, eagerChildren: eager)
    {
        public override ViewModelType Type => ViewModelType.Component;
    }

    [Fact, Trait("Conformance", "HIER-045")]
    public void HIER_045_Eager_Construction_Skips_A_Disposed_Child()
    {
        using var hub = new MessageHub();
        var a = new Node("a", hub);
        var b = new Node("b", hub);
        var root = new Node("root", hub, _ => [a, b], eager: true);

        var changes = new List<(string Sender, VMx.Lifecycle.ConstructionStatus Status)>();
        hub.Messages
            .OfType<ConstructionStatusChangedMessage>()
            .Subscribe(message => changes.Add((message.SenderName, message.Status)));

        root.Construct();
        a.Dispose();
        root.Destruct();
        b.Destruct();
        changes.Clear();

        // Neither call throws; the walk skips the disposed child a.
        root.Construct();
        root.Reconstruct();

        root.Status.Should().Be(VMx.Lifecycle.ConstructionStatus.Constructed);
        b.Status.Should().Be(VMx.Lifecycle.ConstructionStatus.Constructed);
        a.Status.Should().Be(VMx.Lifecycle.ConstructionStatus.Disposed);
        changes.Where(change => change.Sender == "a").Should().BeEmpty();
    }
}
