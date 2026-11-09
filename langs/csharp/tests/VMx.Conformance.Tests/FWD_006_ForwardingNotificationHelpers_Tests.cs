using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// FWD-006: a forwarding decorator's notification helpers act on the wrapped
/// VM (spec/09-forwarding.md §1, ADR-0221, #1352). The dual-channel helper
/// sends one hub message whose sender is the wrapped VM, and the decorator's
/// PropertyChanged event fires once. The local-only helper fires the event and
/// sends no message. After the wrapped VM is disposed, the dual-channel helper
/// notifies on neither channel.
/// </summary>
public class FWD_006_ForwardingNotificationHelpers_Tests
{
    private sealed class NotifyingComponent<M>(IComponentVM<M> wrapped) : ForwardingComponentVM<M>(wrapped)
    {
        public void Notify(string name) => NotifyPropertyChanged(name);

        public void RaiseLocal(string name) => RaisePropertyChanged(name);
    }

    private sealed class NotifyingComposite<VM>(ICompositeVM<VM> wrapped) : ForwardingCompositeVM<VM>(wrapped)
        where VM : class, IComponentVM
    {
        public void Notify(string name) => NotifyPropertyChanged(name);

        public void RaiseLocal(string name) => RaisePropertyChanged(name);
    }

    public static TheoryData<string> Kinds() => new() { "component", "composite" };

    [Theory, Trait("Conformance", "FWD-006")]
    [MemberData(nameof(Kinds))]
    public void FWD_006_Decorator_Notification_Helpers_Act_On_The_Wrapped_VM(string kind)
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        IComponentVM inner;
        IComponentVM decorator;
        Action<string> notify;
        Action<string> raiseLocal;
        if (kind == "component")
        {
            var vm = ComponentVM<string>.Builder().Name("inner").Services(hub, dispatcher).Model("m").Build();
            var fwd = new NotifyingComponent<string>(vm);
            (inner, decorator, notify, raiseLocal) = (vm, fwd, fwd.Notify, fwd.RaiseLocal);
        }
        else
        {
            var composite = CompositeVM<ComponentVM<string>>.Builder()
                .Name("inner")
                .Services(hub, dispatcher)
                .Children(() => Array.Empty<ComponentVM<string>>())
                .Build();
            var fwd = new NotifyingComposite<ComponentVM<string>>(composite);
            (inner, decorator, notify, raiseLocal) = (composite, fwd, fwd.Notify, fwd.RaiseLocal);
        }
        var messages = new List<IPropertyChangedMessage<IComponentVM>>();
        using var subscription = hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> changed) messages.Add(changed);
        });
        var names = new List<string?>();
        decorator.PropertyChanged += (_, e) => names.Add(e.PropertyName);

        notify("Custom");

        names.Should().Equal("Custom");
        messages.Should().ContainSingle();
        messages[0].Sender.Should().BeSameAs(inner);
        messages[0].PropertyName.Should().Be("Custom");

        raiseLocal("Local");

        names.Should().Equal("Custom", "Local");
        messages.Should().ContainSingle();

        inner.Dispose();
        names.Clear();
        messages.Clear();
        notify("After");

        names.Should().BeEmpty();
        messages.Should().BeEmpty();
    }
}
