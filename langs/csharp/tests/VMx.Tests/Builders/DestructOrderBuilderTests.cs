using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Builders;

/// <summary>
/// The <c>DestructOrder</c> builder setter and options field (ADR-0161,
/// BLD-001/BLD-004/BLD-006): the setter returns a new builder and leaves the
/// original at the default, the default is <see cref="ChildOrder.Insertion"/>,
/// and <c>Create(options)</c> carries the field to the VM.
/// </summary>
public class DestructOrderBuilderTests
{
    private static readonly TestDispatcher Dispatcher = new();
    private static readonly string[] Names = ["a", "b", "c"];

    private static ComponentVM<string> Child(TestHub hub, string name, List<string> log)
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, Dispatcher).Model(name)
            .OnDestruct(() => log.Add(name))
            .Build();

    private static Func<IEnumerable<ComponentVM<string>>> Children(TestHub hub, List<string> log)
        => () => Names.Select(name => Child(hub, name, log)).ToArray();

    /// <summary>Constructs, destructs and returns the child destruct order.</summary>
    private static List<string> DestructOrderOf(IComponentVM vm, List<string> log)
    {
        vm.Construct();
        vm.Destruct();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
        return log;
    }

    [Fact]
    public void Default_ChildOrder_Is_Insertion()
    {
        default(ChildOrder).Should().Be(ChildOrder.Insertion);
        new GroupVMOptions<ComponentVM<string>>().DestructOrder.Should().Be(ChildOrder.Insertion);
        new CompositeVMOptions<ComponentVM<string>>().DestructOrder.Should().Be(ChildOrder.Insertion);
    }

    [Fact]
    public void Group_Setter_Returns_New_Builder_And_Leaves_Original_At_Default()
    {
        var hub = new TestHub();
        var log = new List<string>();
        var original = GroupVM<ComponentVM<string>>.Builder()
            .Name("g").Services(hub, Dispatcher).Children(Children(hub, log));
        var reversed = original.DestructOrder(ChildOrder.Reverse);

        ReferenceEquals(original, reversed).Should().BeFalse();
        DestructOrderOf(original.Build(), log).Should().Equal("a", "b", "c");
        log.Clear();
        DestructOrderOf(reversed.Build(), log).Should().Equal("c", "b", "a");
        log.Clear();
        DestructOrderOf(reversed.DestructOrder(ChildOrder.Insertion).Build(), log)
            .Should().Equal("a", "b", "c");
    }

    [Fact]
    public void Composite_Setter_Returns_New_Builder_And_Leaves_Original_At_Default()
    {
        var hub = new TestHub();
        var log = new List<string>();
        var original = CompositeVM<ComponentVM<string>>.Builder()
            .Name("c").Services(hub, Dispatcher).Children(Children(hub, log));
        var reversed = original.DestructOrder(ChildOrder.Reverse);

        ReferenceEquals(original, reversed).Should().BeFalse();
        DestructOrderOf(original.Build(), log).Should().Equal("a", "b", "c");
        log.Clear();
        DestructOrderOf(reversed.Build(), log).Should().Equal("c", "b", "a");
    }

    [Fact]
    public void Modeled_Composite_Setter_Returns_New_Builder_And_Leaves_Original_At_Default()
    {
        var hub = new TestHub();
        var log = new List<string>();
        var original = CompositeVMOfM<string, ComponentVM<string>>.Builder()
            .Name("m").Services(hub, Dispatcher)
            .ChildrenModels(() => Names)
            .ChildModelToChildViewModel(name => Child(hub, name, log));
        var reversed = original.DestructOrder(ChildOrder.Reverse);

        ReferenceEquals(original, reversed).Should().BeFalse();
        DestructOrderOf(original.Build(), log).Should().Equal("a", "b", "c");
        log.Clear();
        DestructOrderOf(reversed.Build(), log).Should().Equal("c", "b", "a");
    }

    [Theory]
    [InlineData(ChildOrder.Insertion, new[] { "a", "b", "c" })]
    [InlineData(ChildOrder.Reverse, new[] { "c", "b", "a" })]
    public void Group_Create_Honors_DestructOrder(ChildOrder order, string[] expected)
    {
        var hub = new TestHub();
        var log = new List<string>();
        var group = GroupVM<ComponentVM<string>>.Create(new GroupVMOptions<ComponentVM<string>>
        {
            Name = "g",
            Hub = hub,
            Dispatcher = Dispatcher,
            Children = Children(hub, log),
            DestructOrder = order,
        });

        DestructOrderOf(group, log).Should().Equal(expected);
    }

    [Theory]
    [InlineData(ChildOrder.Insertion, new[] { "a", "b", "c" })]
    [InlineData(ChildOrder.Reverse, new[] { "c", "b", "a" })]
    public void Composite_Create_Honors_DestructOrder(ChildOrder order, string[] expected)
    {
        var hub = new TestHub();
        var log = new List<string>();
        var composite = CompositeVM<ComponentVM<string>>.Create(
            new CompositeVMOptions<ComponentVM<string>>
            {
                Name = "c",
                Hub = hub,
                Dispatcher = Dispatcher,
                Children = Children(hub, log),
                DestructOrder = order,
            });

        DestructOrderOf(composite, log).Should().Equal(expected);
    }

    [Fact]
    public void Reverse_Dispose_Keeps_Disposing_After_A_Failure_And_Rethrows_The_First()
    {
        var hub = new TestHub();
        var disposed = new List<string>();
        var children = Names.Select(name => new ThrowingDisposeVM(name, hub, disposed)).ToArray();
        var group = GroupVM<ThrowingDisposeVM>.Builder()
            .Name("g").Services(hub, Dispatcher).Children(() => children)
            .DestructOrder(ChildOrder.Reverse).Build();
        group.Construct();

        var act = group.Dispose;

        // Best effort in reverse order: c and b both throw; c's failure is first.
        act.Should().Throw<InvalidOperationException>().WithMessage("c");
        disposed.Should().Equal("c", "b", "a");
        group.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>A child whose dispose records its name and throws for b and c.</summary>
    public sealed class ThrowingDisposeVM(string name, TestHub hub, List<string> disposed)
        : ComponentVMBase(name, hub, Dispatcher)
    {
        /// <inheritdoc/>
        public override ViewModelType Type => ViewModelType.Component;

        /// <inheritdoc/>
        protected override void OnDispose()
        {
            disposed.Add(Name);
            if (Name != "a") throw new InvalidOperationException(Name);
        }
    }
}
