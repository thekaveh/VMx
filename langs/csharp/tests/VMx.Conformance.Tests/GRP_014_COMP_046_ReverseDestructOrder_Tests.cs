using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Opt-in reverse child destruct order (spec/02 §6, spec/06 §5, spec/07 §2,
/// ADR-0161): GRP-014 and COMP-046. With <see cref="ChildOrder.Reverse"/>,
/// destruct (including the destruct phase of reconstruct) and dispose walk the
/// children last-first, construct stays in child order, and every child is
/// disposed before the parent publishes Disposed (LIFE-013). The default keeps
/// child order.
/// </summary>
public class GRP_014_COMP_046_ReverseDestructOrder_Tests
{
    private static readonly TestDispatcher Dispatcher = new();
    private static readonly string[] Names = ["a", "b", "c"];

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    /// <summary>Records each settled status message as "status:name".</summary>
    private static List<string> Record(MessageHub hub)
    {
        var log = new List<string>();
        hub.Messages.OfType<ConstructionStatusChangedMessage>()
            .Where(m => m.Status is ConstructionStatus.Constructed
                or ConstructionStatus.Destructed or ConstructionStatus.Disposed)
            .Subscribe(m => log.Add($"{m.Status}:{m.SenderName}"));
        return log;
    }

    private static string[] Expect(ConstructionStatus status, string[] children, string parent)
        => children.Append(parent).Select(name => $"{status}:{name}").ToArray();

    /// <summary>
    /// Drives construct, destruct, reconstruct and dispose on <paramref name="parent"/>
    /// and checks the child order of each phase against <paramref name="order"/>.
    /// </summary>
    private static void AssertOrder(
        MessageHub hub, IComponentVM parent, List<string> log, ChildOrder order)
    {
        var forward = Names;
        var teardown = order == ChildOrder.Reverse ? Enumerable.Reverse(Names).ToArray() : Names;

        parent.Construct();
        log.Should().Equal(Expect(ConstructionStatus.Constructed, forward, parent.Name));

        log.Clear();
        parent.Destruct();
        log.Should().Equal(Expect(ConstructionStatus.Destructed, teardown, parent.Name));

        parent.Construct();
        log.Clear();
        parent.Reconstruct();
        log.Should().Equal(
            Expect(ConstructionStatus.Destructed, teardown, parent.Name)
                .Concat(Expect(ConstructionStatus.Constructed, forward, parent.Name)));

        log.Clear();
        parent.Dispose();
        // Depth-first (LIFE-013): every child is Disposed before the parent.
        log.Should().Equal(Expect(ConstructionStatus.Disposed, teardown, parent.Name));
        hub.Dispose();
    }

    // ── GRP-014 — GroupVM destructs and disposes children in reverse order ──

    [Theory, Trait("Conformance", "GRP-014")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void GRP_014_Group_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(hub, Dispatcher)
            .Children(() => Names.Select(name => Child(hub, name)).ToArray());
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }

    [Fact, Trait("Conformance", "GRP-014")]
    public void GRP_014_Group_DestructOrder_Options()
    {
        var hub = new MessageHub();
        var group = GroupVM<ComponentVM<string>>.Create(new GroupVMOptions<ComponentVM<string>>
        {
            Name = "group",
            Hub = hub,
            Dispatcher = Dispatcher,
            Children = () => Names.Select(name => Child(hub, name)).ToArray(),
            DestructOrder = ChildOrder.Reverse,
        });
        var log = Record(hub);

        AssertOrder(hub, group, log, ChildOrder.Reverse);
    }

    // ── COMP-046 — CompositeVM destructs and disposes children in reverse order ──

    [Theory, Trait("Conformance", "COMP-046")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void COMP_046_Composite_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, Dispatcher)
            .Children(() => Names.Select(name => Child(hub, name)).ToArray())
            // A current child is cleared before the children are destructed.
            .Current(children => children.Last());
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }

    [Fact, Trait("Conformance", "COMP-046")]
    public void COMP_046_Composite_DestructOrder_Options()
    {
        var hub = new MessageHub();
        var composite = CompositeVM<ComponentVM<string>>.Create(
            new CompositeVMOptions<ComponentVM<string>>
            {
                Name = "composite",
                Hub = hub,
                Dispatcher = Dispatcher,
                Children = () => Names.Select(name => Child(hub, name)).ToArray(),
                DestructOrder = ChildOrder.Reverse,
            });
        var log = Record(hub);

        AssertOrder(hub, composite, log, ChildOrder.Reverse);
    }

    [Theory, Trait("Conformance", "COMP-046")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void COMP_046_ModeledComposite_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = CompositeVMOfM<string, ComponentVM<string>>.Builder()
            .Name("modeled").Services(hub, Dispatcher)
            .ChildrenModels(() => Names)
            .ChildModelToChildViewModel(name => Child(hub, name));
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }
}
