using FluentAssertions;
using VMx.Builders;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for <see cref="HierarchicalVMBuilder{TModel, TVM}"/>:
/// HIER-015..HIER-017. See spec/12-conformance.md §HierarchicalVM-Builder and
/// ADR-0035 §2 H1 / H2.
/// </summary>
public class HierarchicalVMBuilderConformanceTests
{
    // ── Test double ──────────────────────────────────────────────────────────

    /// <summary>
    /// Concrete subclass with a public constructor mirroring the abstract
    /// <c>protected</c> one — required because the builder must be told which
    /// concrete subclass to instantiate via <c>VmFactory</c>.
    /// </summary>
    private sealed class TestNode : HierarchicalVM<string, TestNode>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public TestNode(
            string model,
            Func<TestNode, IEnumerable<TestNode>> childrenFactory,
            IMessageHub hub,
            IDispatcher dispatcher,
            string? name = null,
            string hint = "",
            bool eagerChildren = false)
            : base(model, childrenFactory, hub, dispatcher, name, hint, eagerChildren)
        { }
    }

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    private static Func<HierarchicalVMConstructionContext<string, TestNode>, TestNode> TestNodeFactory
        => ctx => new TestNode(
            ctx.Model, ctx.ChildrenFactory, ctx.Hub, ctx.Dispatcher,
            ctx.Name, ctx.Hint, ctx.EagerChildren);

    private static HierarchicalVMBuilder<string, TestNode> FullyConfigured()
    {
        var (hub, dispatcher) = MakeServices();
        return HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root")
            .ChildrenFactory(_ => Array.Empty<TestNode>())
            .Services(hub, dispatcher)
            .VmFactory(TestNodeFactory);
    }

    // ── HIER-015 — Build() validates required fields ─────────────────────────

    /// <summary>
    /// HIER-015 (a): Build() with missing Model raises BuilderValidationException
    /// identifying "Model".
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-015")]
    public void HIER_015_Build_Missing_Model_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => HierarchicalVMBuilder<string, TestNode>.Empty
            // deliberately omitting .Model(...)
            .ChildrenFactory(_ => Array.Empty<TestNode>())
            .Services(hub, dispatcher)
            .VmFactory(TestNodeFactory)
            .Build();

        act.Should().Throw<BuilderValidationException>(
                "Build() must raise when Model is missing")
            .Which.MissingField.Should().Be("Model");
    }

    /// <summary>
    /// HIER-015 (b): Build() with missing ChildrenFactory raises
    /// BuilderValidationException identifying "ChildrenFactory".
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-015")]
    public void HIER_015_Build_Missing_ChildrenFactory_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root")
            // deliberately omitting .ChildrenFactory(...)
            .Services(hub, dispatcher)
            .VmFactory(TestNodeFactory)
            .Build();

        act.Should().Throw<BuilderValidationException>(
                "Build() must raise when ChildrenFactory is missing")
            .Which.MissingField.Should().Be("ChildrenFactory");
    }

    /// <summary>
    /// HIER-015 (c): Build() with missing Services raises BuilderValidationException
    /// identifying the missing hub/dispatcher field.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-015")]
    public void HIER_015_Build_Missing_Services_Raises_BuilderValidationException()
    {
        var act = () => HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root")
            .ChildrenFactory(_ => Array.Empty<TestNode>())
            // deliberately omitting .Services(...)
            .VmFactory(TestNodeFactory)
            .Build();

        act.Should().Throw<BuilderValidationException>(
                "Build() must raise when Services is missing")
            .Which.MissingField.Should().BeOneOf("Hub", "Dispatcher",
                "validation reports the first missing services field by name");
    }

    /// <summary>
    /// HIER-015 (d): Build() with missing VmFactory raises BuilderValidationException
    /// identifying "VmFactory" — required because HierarchicalVM is abstract.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-015")]
    public void HIER_015_Build_Missing_VmFactory_Raises_BuilderValidationException()
    {
        var (hub, dispatcher) = MakeServices();
        var act = () => HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root")
            .ChildrenFactory(_ => Array.Empty<TestNode>())
            .Services(hub, dispatcher)
            // deliberately omitting .VmFactory(...)
            .Build();

        act.Should().Throw<BuilderValidationException>(
                "Build() must raise when VmFactory is missing")
            .Which.MissingField.Should().Be("VmFactory");
    }

    // ── HIER-016 — Repeated Build() produces distinct-but-equivalent nodes ───

    /// <summary>
    /// HIER-016: Repeated Build() calls produce distinct-but-equivalent nodes
    /// (same Model, same Hint).
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-016")]
    public void HIER_016_Repeated_Build_Calls_Produce_Equivalent_But_Distinct_Nodes()
    {
        var (hub, dispatcher) = MakeServices();
        var builder = HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root-model")
            .Hint("the-hint")
            .ChildrenFactory(_ => Array.Empty<TestNode>())
            .Services(hub, dispatcher)
            .VmFactory(TestNodeFactory);

        var nodeA = builder.Build();
        var nodeB = builder.Build();

        object.ReferenceEquals(nodeA, nodeB).Should().BeFalse(
            "each Build() call must produce a new node instance");
        nodeA.Model.Should().Be("root-model");
        nodeB.Model.Should().Be("root-model");
        nodeA.Model.Should().Be(nodeB.Model, "Model must be equal across builds");
        nodeA.Hint.Should().Be("the-hint");
        nodeB.Hint.Should().Be("the-hint");
        nodeA.Hint.Should().Be(nodeB.Hint, "Hint must be equal across builds");
    }

    // ── HIER-017 — Field defaults applied when not set ───────────────────────

    /// <summary>
    /// HIER-017: Field defaults applied when not set — Hint defaults to empty
    /// string, Name defaults to <c>typeof(TVM).Name</c>, EagerChildren defaults
    /// to false (children materialized lazily — the factory is not invoked
    /// until Children is first accessed).
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-017")]
    public void HIER_017_Field_Defaults_Applied_When_Not_Set()
    {
        var (hub, dispatcher) = MakeServices();
        var factoryCalls = 0;

        var node = HierarchicalVMBuilder<string, TestNode>.Empty
            .Model("root")
            .ChildrenFactory(_ =>
            {
                factoryCalls++;
                return Array.Empty<TestNode>();
            })
            .Services(hub, dispatcher)
            .VmFactory(TestNodeFactory)
            .Build();

        // Hint default: empty string.
        node.Hint.Should().BeEmpty(
            "Hint must default to empty string per spec/10-builders.md");

        // Name default: typeof(TVM).Name.
        node.Name.Should().Be(
            nameof(TestNode),
            "Name must default to typeof(TVM).Name when not set");

        // EagerChildren default: false ⇒ children factory is NOT invoked until
        // Children is first accessed. Construct() should leave it unmaterialized.
        node.Construct();
        factoryCalls.Should().Be(0,
            "EagerChildren defaults to false — children factory must not run at construct");

        // Touching Children materializes lazily.
        _ = node.Children;
        factoryCalls.Should().Be(1,
            "Children materializes on first access when EagerChildren is false");
    }
}
