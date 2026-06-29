using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Messages;

/// <summary>
/// VMX-017: <see cref="MessageHubExtensions.WhenPropertyChanged"/> — the typed
/// hub helper that replaces the hand-wired
/// <c>OfType(...).Where(ReferenceEquals + PropertyName)</c> filter repeated across
/// the flagship cross-VM bindings.
/// </summary>
public class WhenPropertyChangedTests
{
    [Fact]
    public void Filters_By_Sender_Identity_And_Property_Name()
    {
        using var hub = new MessageHub();
        var senderA = new object();
        var senderB = new object();

        var received = new List<string>();
        using var sub = hub.WhenPropertyChanged(senderA, "Foo")
            .Subscribe(m => received.Add(m.PropertyName));

        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Foo"));   // match
        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Bar"));   // wrong property
        hub.Send(PropertyChangedMessage<object>.Create(senderB, "B", "Foo"));   // wrong sender

        received.Should().Equal("Foo");
    }

    [Fact]
    public void Matches_Covariant_Sender_Generic_Argument()
    {
        // VMs publish PropertyChangedMessage<IComponentVM>; the helper keys on an
        // object sender and must still match via interface covariance.
        using var hub = new MessageHub();
        var vm = ComponentVM.Builder().Name("vm").WithNullServices().Build();

        var hits = 0;
        using var sub = hub.WhenPropertyChanged(vm, "IsCurrent").Subscribe(_ => hits++);

        hub.Send(PropertyChangedMessage<IComponentVM>.Create(vm, vm.Name, "IsCurrent"));

        hits.Should().Be(1, "the covariant IPropertyChangedMessage<object> match must capture the message");
    }

    [Fact]
    public void Null_Arguments_Throw()
    {
        using var hub = new MessageHub();
        var sender = new object();

        ((Action)(() => hub.WhenPropertyChanged(null!, "P"))).Should().Throw<ArgumentNullException>();
        ((Action)(() => hub.WhenPropertyChanged(sender, null!))).Should().Throw<ArgumentNullException>();
    }
}
