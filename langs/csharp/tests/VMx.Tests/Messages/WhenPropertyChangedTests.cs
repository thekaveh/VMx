using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Messages;

/// <summary>
/// VMX-017: <see cref="MessageHubExtensions.WhenPropertyChanged(IMessageHub, object, string)"/> — the typed
/// hub helper that replaces the hand-wired
/// <c>OfType(...).Where(ReferenceEquals + PropertyName)</c> filter repeated across
/// the flagship cross-VM bindings — and its several-name overload (ADR-0160).
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
        ((Action)(() => hub.WhenPropertyChanged(sender, (string)null!))).Should().Throw<ArgumentNullException>();
    }

    [Fact]
    public void Single_String_Argument_Binds_To_The_Single_Name_Overload()
    {
        // A one-name call keeps binding to the string overload, which rejects a
        // null name with ArgumentNullException; the params overload would throw
        // ArgumentException instead (ADR-0160).
        using var hub = new MessageHub();
        string? name = null;

        ((Action)(() => hub.WhenPropertyChanged(new object(), name!)))
            .Should().Throw<ArgumentNullException>().Which.ParamName.Should().Be("propertyName");
    }

    [Fact]
    public void Several_Names_Emit_Matching_Messages_In_Hub_Order()
    {
        using var hub = new MessageHub();
        var senderA = new object();
        var senderB = new object();

        var received = new List<string>();
        using var sub = hub.WhenPropertyChanged(senderA, "Foo", "Bar")
            .Subscribe(m => received.Add(m.PropertyName));

        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Bar"));   // match
        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Baz"));   // name not listed
        hub.Send(PropertyChangedMessage<object>.Create(senderB, "B", "Foo"));   // wrong sender
        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Foo"));   // match
        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "foo"));   // ordinal mismatch
        hub.Send(PropertyChangedMessage<object>.Create(senderA, "A", "Bar"));   // match

        received.Should().Equal("Bar", "Foo", "Bar");
    }

    [Fact]
    public void Several_Names_Accept_An_Array()
    {
        using var hub = new MessageHub();
        var sender = new object();
        var names = new[] { "Foo", "Bar" };

        var received = new List<string>();
        using var sub = hub.WhenPropertyChanged(sender, names).Subscribe(m => received.Add(m.PropertyName));
        names[1] = "Baz";   // the overload copies the names when it is called

        hub.Send(PropertyChangedMessage<object>.Create(sender, "S", "Bar"));
        hub.Send(PropertyChangedMessage<object>.Create(sender, "S", "Baz"));

        received.Should().Equal("Bar");
    }

    [Fact]
    public void Repeated_Name_Emits_Each_Message_Once()
    {
        using var hub = new MessageHub();
        var sender = new object();

        var hits = 0;
        using var sub = hub.WhenPropertyChanged(sender, "Foo", "Foo", "Bar").Subscribe(_ => hits++);

        hub.Send(PropertyChangedMessage<object>.Create(sender, "S", "Foo"));

        hits.Should().Be(1);
    }

    [Fact]
    public void Several_Names_Use_One_Hub_Subscription()
    {
        var hub = new CountingHub();
        var sender = new object();

        var received = new List<string>();
        var sub = hub.WhenPropertyChanged(sender, "Foo", "Bar").Subscribe(m => received.Add(m.PropertyName));
        hub.Subscriptions.Should().Be(1);

        hub.Send(PropertyChangedMessage<object>.Create(sender, "S", "Foo"));
        sub.Dispose();
        hub.Send(PropertyChangedMessage<object>.Create(sender, "S", "Bar"));

        received.Should().Equal("Foo");
        hub.Subject.HasObservers.Should().BeFalse("disposing the one subscription releases the hub");
    }

    [Fact]
    public void Several_Names_Reject_Invalid_Arguments()
    {
        using var hub = new MessageHub();
        var sender = new object();

        ((Action)(() => hub.WhenPropertyChanged(null!, "P", "Q"))).Should().Throw<ArgumentNullException>();
        ((Action)(() => hub.WhenPropertyChanged(sender, (string[])null!))).Should().Throw<ArgumentNullException>();
        ((Action)(() => hub.WhenPropertyChanged(sender))).Should().Throw<ArgumentException>()
            .Which.ParamName.Should().Be("propertyNames");
        ((Action)(() => hub.WhenPropertyChanged(sender, "P", null!))).Should().Throw<ArgumentException>()
            .Which.ParamName.Should().Be("propertyNames");
    }

    private sealed class CountingHub : IMessageHub
    {
        public Subject<IMessage> Subject { get; } = new();

        public int Subscriptions { get; private set; }

        public IObservable<IMessage> Messages => new CountingObservable(this);

        public void Send<TMessage>(TMessage message) where TMessage : IMessage => Subject.OnNext(message);

        private sealed class CountingObservable(CountingHub owner) : IObservable<IMessage>
        {
            public IDisposable Subscribe(IObserver<IMessage> observer)
            {
                owner.Subscriptions++;
                return owner.Subject.Subscribe(observer);
            }
        }
    }
}
