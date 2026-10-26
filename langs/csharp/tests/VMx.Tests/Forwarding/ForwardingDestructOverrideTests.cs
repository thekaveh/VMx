using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Forwarding;

/// <summary>
/// spec/09: a forwarding decorator may override any subset of its members. A
/// container destructing a decorator child that is not already Destructing
/// goes through the decorator's own <c>DestructAsync()</c>, so the override
/// runs (#754 keeps the join for an in-flight destruct only).
/// </summary>
public class ForwardingDestructOverrideTests
{
    private sealed class CountingComponentDecorator(IComponentVM<string> wrapped)
        : ForwardingComponentVM<string>(wrapped)
    {
        private int _destructAsyncCalls;

        public int DestructAsyncCalls => Volatile.Read(ref _destructAsyncCalls);

        public override Task DestructAsync()
        {
            Interlocked.Increment(ref _destructAsyncCalls);
            return base.DestructAsync();
        }
    }

    private sealed class CountingCompositeDecorator(ICompositeVM<IComponentVM> wrapped)
        : ForwardingCompositeVM<IComponentVM>(wrapped)
    {
        private int _destructAsyncCalls;

        public int DestructAsyncCalls => Volatile.Read(ref _destructAsyncCalls);

        public override Task DestructAsync()
        {
            Interlocked.Increment(ref _destructAsyncCalls);
            return base.DestructAsync();
        }
    }

    private static CompositeVM<IComponentVM> Parent(IComponentVM child) =>
        CompositeVM<IComponentVM>.Builder()
            .Name("parent")
            .Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [child])
            .Build();

    [Fact]
    public void Composite_Destruct_Runs_A_Component_Decorator_DestructAsync_Override_Once()
    {
        var inner = ComponentVM<string>.Builder()
            .Name("inner")
            .Services(new TestHub(), NullDispatcher.Instance)
            .Model("m")
            .Build();
        var decorator = new CountingComponentDecorator(inner);
        var parent = Parent(decorator);
        parent.Construct();

        parent.Destruct();

        decorator.DestructAsyncCalls.Should().Be(1);
        inner.Status.Should().Be(ConstructionStatus.Destructed);
        parent.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Composite_Destruct_Runs_A_Composite_Decorator_DestructAsync_Override_Once()
    {
        var leaf = ComponentVM<string>.Builder()
            .Name("leaf")
            .Services(new TestHub(), NullDispatcher.Instance)
            .Model("m")
            .Build();
        var inner = CompositeVM<IComponentVM>.Builder()
            .Name("inner")
            .Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [leaf])
            .Build();
        var decorator = new CountingCompositeDecorator(inner);
        var parent = Parent(decorator);
        parent.Construct();

        parent.Destruct();

        decorator.DestructAsyncCalls.Should().Be(1);
        inner.Status.Should().Be(ConstructionStatus.Destructed);
        leaf.Status.Should().Be(ConstructionStatus.Destructed);
        parent.Status.Should().Be(ConstructionStatus.Destructed);
    }
}
