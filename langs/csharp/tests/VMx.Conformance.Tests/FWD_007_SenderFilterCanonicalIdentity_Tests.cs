using FluentAssertions;
using VMx.Components;
using VMx.Forwarding;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// FWD-007: the hub subscription helpers (spec/03-messages.md §7.1, §7.2 and §7.4)
/// match a forwarding decorator by its canonical ownership identity, through nested
/// decorators. The wrapped VM sends each message that a decorator causes (ADR-0221),
/// so a helper given the outer decorator sees the wrapped VM's writes, and no other
/// VM's (spec/09-forwarding.md §1, ADR-0124, ADR-0233).
/// </summary>
public class FWD_007_SenderFilterCanonicalIdentity_Tests
{
    private sealed class Decorator<M>(IComponentVM<M> wrapped) : ForwardingComponentVM<M>(wrapped);

    [Fact, Trait("Conformance", "FWD-007")]
    public void FWD_007_Helpers_Given_A_Two_Layer_Decorator_Match_The_Wrapped_VM_Writes()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var inner = ComponentVM<string>.Builder().Name("inner").Services(hub, dispatcher).Model("m").Build();
        var outer = new Decorator<string>(new Decorator<string>(inner));

        var messages = new List<IPropertyChangedMessage<object>>();
        using var whenSubscription = hub.WhenPropertyChanged(outer, "Model").Subscribe(messages.Add);
        var values = new List<string>();
        using var valueSubscription = hub.PropertyValueChangedMessagesFor(outer, vm => vm.Model).Subscribe(values.Add);
        var selected = new List<(string Current, string Previous)>();
        using var selectSubscription = outer.SubscribeValue(vm => vm.Model, (current, previous) => selected.Add((current, previous)));

        outer.Model = "updated";

        messages.Should().ContainSingle();
        messages[0].SenderObject.Should().BeSameAs(inner);
        values.Should().Equal("updated");
        selected.Should().Equal(("updated", "m"));
    }

    [Fact, Trait("Conformance", "FWD-007")]
    public void FWD_007_Helpers_Given_A_Two_Layer_Decorator_Ignore_Other_VMs_On_The_Hub()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var inner = ComponentVM<string>.Builder().Name("inner").Services(hub, dispatcher).Model("m").Build();
        var other = ComponentVM<string>.Builder().Name("other").Services(hub, dispatcher).Model("m").Build();
        var outer = new Decorator<string>(new Decorator<string>(inner));

        var messages = new List<IPropertyChangedMessage<object>>();
        using var whenSubscription = hub.WhenPropertyChanged(outer, "Model").Subscribe(messages.Add);
        var values = new List<string>();
        using var valueSubscription = hub.PropertyValueChangedMessagesFor(outer, vm => vm.Model).Subscribe(values.Add);
        var selected = new List<(string Current, string Previous)>();
        using var selectSubscription = outer.SubscribeValue(vm => vm.Model, (current, previous) => selected.Add((current, previous)));

        other.Model = "other-updated";

        messages.Should().BeEmpty();
        values.Should().BeEmpty();
        selected.Should().BeEmpty();
    }
}
