using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class PropertyChangeConformanceTests
{

    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildVm(
        string name = "vm1", string model = "initial")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        return (vm, hub, dispatcher);
    }

    // ── PROP-001 — Setter publishes PropertyChangedMessage ───────────────────

    /// <summary>
    /// PROP-001: setting Model to a different value publishes exactly one PropertyChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-001")]
    public void PROP_001_Setter_Publishes()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        var messages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                messages.Add(m);
        });

        vm.Model = "m2";

        messages.Should().HaveCount(1);
    }

    // ── PROP-002 — Setter same value is silent ────────────────────────────────

    /// <summary>
    /// PROP-002: setting Model to the same value emits no messages.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-002")]
    public void PROP_002_Setter_Same_Value_Silent()
    {
        var (vm, hub, _) = BuildVm(model: "m1");
        var count = 0;
        hub.Messages.Subscribe(_ => count++);

        vm.Model = "m1"; // same value

        count.Should().Be(0);
    }

    // ── PROP-003 — Sender identity ────────────────────────────────────────────

    /// <summary>
    /// PROP-003: the Sender in the PropertyChangedMessage is the VM instance.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-003")]
    public void PROP_003_Sender_Identity()
    {
        var (vm, hub, _) = BuildVm(name: "vm1", model: "m1");
        IMessage? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                observed = m;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.SenderObject.Should().BeSameAs(vm);
    }

    // ── PROP-004 — PropertyName and SenderName ────────────────────────────────

    /// <summary>
    /// PROP-004: PropertyName is "Model" and SenderName is the VM's Name.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-004")]
    public void PROP_004_PropertyName_SenderName()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        IPropertyChangedMessage<IComponentVM>? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "Model")
                observed = pcm;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.PropertyName.Should().Be("Model");
        observed.SenderName.Should().Be("n1");
    }
}
