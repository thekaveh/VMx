using System.Reactive.Disposables;
using System.Reflection;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Forwarding;

/// <summary>
/// Owned resources registered through a forwarding decorator (spec/09 §1,
/// ADR-0151). FWD-005 covers the catalog scenario; these tests cover the
/// composite decorator, both overloads, and a non-VMx wrapped component.
/// </summary>
public class ForwardingOwnTests
{
    private sealed class OwningForwardingVM<M>(IComponentVM<M> wrapped)
        : ForwardingComponentVM<M>(wrapped)
    {
        public T Register<T>(T resource) where T : IDisposable => Own(resource);

        public IDisposable Register(Action cleanup) => Own(cleanup);
    }

    private sealed class OwningForwardingCompositeVM<VM>(ICompositeVM<VM> wrapped)
        : ForwardingCompositeVM<VM>(wrapped)
        where VM : class, IComponentVM
    {
        public IDisposable Register(Action cleanup) => Own(cleanup);
    }

    /// <summary>Implements the component interface without deriving from <see cref="ComponentVMBase"/>.</summary>
    public class ForeignComponentProxy : DispatchProxy
    {
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args) => null;
    }

    private static ComponentVM<string> BuildInner() =>
        ComponentVM<string>.Builder()
            .Name("inner")
            .Services(new TestHub(), new TestDispatcher())
            .Model("m")
            .Build();

    [Fact]
    public void Own_Returns_The_Resource_And_Disposes_It_With_The_Wrapped_VM()
    {
        var inner = BuildInner();
        var decorator = new OwningForwardingVM<string>(inner);
        var disposed = 0;
        var resource = Disposable.Create(() => disposed++);

        decorator.Register(resource).Should().BeSameAs(resource);
        disposed.Should().Be(0);

        inner.Dispose();

        disposed.Should().Be(1);
    }

    [Fact]
    public void Registration_After_Decorator_Disposal_Is_Released_Once()
    {
        var decorator = new OwningForwardingVM<string>(BuildInner());
        var released = 0;
        decorator.Dispose();

        decorator.Register(() => released++);
        decorator.Dispose();

        released.Should().Be(1);
    }

    [Fact]
    public void Composite_Decorator_Registers_On_The_Wrapped_Composite()
    {
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(new TestHub(), new TestDispatcher())
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        var decorator = new OwningForwardingCompositeVM<ComponentVM<string>>(composite);
        var released = new List<string>();
        decorator.Register(() => released.Add("r1"));
        decorator.Register(() => released.Add("r2"));

        decorator.Dispose();

        composite.Status.Should().Be(ConstructionStatus.Disposed);
        released.Should().Equal("r2", "r1");
    }

    [Fact]
    public void Own_Throws_When_The_Wrapped_VM_Is_Not_A_ComponentVMBase()
    {
        var foreign = DispatchProxy.Create<IComponentVM<string>, ForeignComponentProxy>();
        var decorator = new OwningForwardingVM<string>(foreign);

        decorator.Invoking(d => d.Register(() => { }))
            .Should().Throw<InvalidOperationException>();
    }
}
