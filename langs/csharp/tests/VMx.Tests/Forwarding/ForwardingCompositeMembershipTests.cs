using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Forwarding;

/// <summary>
/// spec/09 §1-2 (FWD-002/FWD-004): a <see cref="ForwardingCompositeVM{VM}"/> held
/// by a parent composite shares one ownership identity with the composite it
/// wraps, so parent links, IsCurrent, and single-parent transfer reach it.
/// </summary>
public class ForwardingCompositeMembershipTests
{
    private sealed class Decorator(ICompositeVM<IComponentVM> wrapped)
        : ForwardingCompositeVM<IComponentVM>(wrapped);

    private static CompositeVM<IComponentVM> Composite(string name) =>
        CompositeVM<IComponentVM>.Builder()
            .Name(name)
            .Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();

    [Fact]
    public void Selecting_Decorator_MarksItCurrent()
    {
        var parent = Composite("parent");
        var decorator = new Decorator(Composite("inner"));
        parent.Construct();
        parent.Add(decorator);
        decorator.Construct();

        parent.Current = decorator;

        parent.Current.Should().BeSameAs(decorator);
        decorator.IsCurrent.Should().BeTrue();
        decorator.CanDeselect().Should().BeTrue();

        parent.Current = null;
        decorator.IsCurrent.Should().BeFalse();
        decorator.CanSelect().Should().BeTrue();
    }

    [Fact]
    public void Adding_Decorator_ToSecondParent_MovesIt()
    {
        var first = Composite("first");
        var second = Composite("second");
        var decorator = new Decorator(Composite("inner"));

        first.Add(decorator);
        second.Add(decorator);

        first.Count.Should().Be(0);
        second.Count.Should().Be(1);
    }

    [Fact]
    public void Decorator_And_WrappedComposite_AreOneOwnershipIdentity()
    {
        var first = Composite("first");
        var second = Composite("second");
        var inner = Composite("inner");
        var decorator = new Decorator(inner);

        first.Add(decorator);
        second.Add(inner);

        first.Count.Should().Be(0);
        second.Count.Should().Be(1);
    }
}
