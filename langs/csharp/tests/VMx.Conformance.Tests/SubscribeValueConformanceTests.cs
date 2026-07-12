using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class SubscribeValueConformanceTests
{
    [Fact, Trait("Conformance", "SUBV-001")]
    public void SUBV_001_Filters_By_Fixed_Source_And_Uses_Default_Equality()
    {
        using var hub = new MessageHub();
        var dispatcher = new TestDispatcher();
        var source = BuildVm(hub, dispatcher, "source", 0);
        var other = BuildVm(hub, dispatcher, "other", 0);
        var selected = new List<(int Current, int Previous)>();
        var selectorCalls = 0;

        using var subscription = source.SubscribeValue(
            vm =>
            {
                selectorCalls++;
                return vm.Model.Value;
            },
            (current, previous) => selected.Add((current, previous)),
            fireImmediately: true);

        other.Model = new Model(1);
        hub.Send(new StubMessage(source));
        source.Model = new Model(1);
        source.Model = new Model(1);
        source.Model = new Model(2);

        selected.Should().Equal((0, 0), (1, 0), (2, 1));
        selectorCalls.Should().Be(4,
            "the initial snapshot and each of the three source property messages are selected once");
    }

    [Fact, Trait("Conformance", "SUBV-002")]
    public void SUBV_002_Uses_Custom_Equality_Exactly_Once_Per_Matching_Message()
    {
        using var hub = new MessageHub();
        var dispatcher = new TestDispatcher();
        var source = BuildVm(hub, dispatcher, "source", 0);
        var other = BuildVm(hub, dispatcher, "other", 0);
        var comparer = new CountingParityComparer();
        var selected = new List<(int Current, int Previous)>();
        var selectorCalls = 0;

        using var subscription = source.SubscribeValue(
            vm =>
            {
                selectorCalls++;
                return vm.Model.Value;
            },
            (current, previous) => selected.Add((current, previous)),
            comparer);

        selectorCalls.Should().Be(1);
        comparer.Calls.Should().Be(0);

        source.Model = new Model(1);
        selectorCalls.Should().Be(2);
        comparer.Calls.Should().Be(1);

        source.Model = new Model(3);
        selectorCalls.Should().Be(3);
        comparer.Calls.Should().Be(2);

        other.Model = new Model(2);
        hub.Send(new StubMessage(source));

        selectorCalls.Should().Be(3);
        comparer.Calls.Should().Be(2);
        selected.Should().Equal((1, 0));
    }

    [Fact, Trait("Conformance", "SUBV-003")]
    public void SUBV_003_Preserves_Reentrant_And_Batch_Order_Until_Disposed()
    {
        using var hub = new MessageHub();
        var dispatcher = new TestDispatcher();

        var reentrant = BuildVm(hub, dispatcher, "reentrant", 0);
        var reentrantValues = new List<(int Current, int Previous)>();
        using (reentrant.SubscribeValue(
            vm => vm.Model.Value,
            (current, previous) =>
            {
                reentrantValues.Add((current, previous));
                if (current == 1) reentrant.Model = new Model(2);
            }))
        {
            reentrant.Model = new Model(1);
        }

        reentrantValues.Should().Equal((1, 0), (2, 1));

        var batched = BuildVm(hub, dispatcher, "batched", 0);
        var batchedValues = new List<(int Current, int Previous)>();
        using (batched.SubscribeValue(
            vm => vm.Model.Value,
            (current, previous) => batchedValues.Add((current, previous))))
        {
            hub.Batch(() =>
            {
                batched.Model = new Model(1);
                batched.Model = new Model(2);
            });
        }

        batchedValues.Should().Equal((2, 0));

        var disposing = BuildVm(hub, dispatcher, "disposing", 0);
        var disposingValues = new List<(int Current, int Previous)>();
        var disposingSelectorCalls = 0;
        IDisposable? disposingSubscription = null;
        disposingSubscription = disposing.SubscribeValue(
            vm =>
            {
                disposingSelectorCalls++;
                return vm.Model.Value;
            },
            (current, previous) =>
            {
                disposingValues.Add((current, previous));
                disposingSubscription!.Dispose();
                disposing.Model = new Model(2);
            });

        disposing.Model = new Model(1);
        disposing.Model = new Model(3);
        disposingSubscription.Dispose();

        disposingValues.Should().Equal((1, 0));
        disposingSelectorCalls.Should().Be(2,
            "disposal during the first callback prevents its queued and later messages");
    }

    [Fact, Trait("Conformance", "SUBV-004")]
    public void SUBV_004_Propagates_Setup_Failures_And_Isolates_Delivery_Failures()
    {
        using var hub = new MessageHub();
        var dispatcher = new TestDispatcher();
        var source = BuildVm(hub, dispatcher, "source", 0);

        Action nullSource = () => SubscribeValueExtensions.SubscribeValue<ComponentVM<Model>, int>(
            null!, vm => vm.Model.Value, (_, _) => { });
        Action nullSelector = () => SubscribeValueExtensions.SubscribeValue<ComponentVM<Model>, int>(
            source, null!, (_, _) => { });
        Action nullCallback = () => source.SubscribeValue(vm => vm.Model.Value, null!);

        nullSource.Should().Throw<ArgumentNullException>().WithParameterName("source");
        nullSelector.Should().Throw<ArgumentNullException>().WithParameterName("selector");
        nullCallback.Should().Throw<ArgumentNullException>().WithParameterName("callback");

        var initialFailure = new InvalidOperationException("initial selector");
        var initialSelectorCalls = 0;
        Action subscribeWithFailingSelector = () => source.SubscribeValue(
            _ =>
            {
                initialSelectorCalls++;
                throw initialFailure;
            },
            (int _, int _) => { });

        subscribeWithFailingSelector.Should().Throw<InvalidOperationException>()
            .Which.Should().BeSameAs(initialFailure);
        source.Model = new Model(1);
        initialSelectorCalls.Should().Be(1, "a failed initial selector attaches no subscription");

        var immediateSource = BuildVm(hub, dispatcher, "immediate", 0);
        var immediateFailure = new InvalidOperationException("immediate callback");
        var immediateSelectorCalls = 0;
        var immediateCallbackCalls = 0;
        Action subscribeWithFailingImmediateCallback = () => immediateSource.SubscribeValue(
            vm =>
            {
                immediateSelectorCalls++;
                return vm.Model.Value;
            },
            (_, _) =>
            {
                immediateCallbackCalls++;
                throw immediateFailure;
            },
            fireImmediately: true);

        subscribeWithFailingImmediateCallback.Should().Throw<InvalidOperationException>()
            .Which.Should().BeSameAs(immediateFailure);
        immediateSource.Model = new Model(1);
        immediateSelectorCalls.Should().Be(1);
        immediateCallbackCalls.Should().Be(1, "a failed immediate callback attaches no subscription");

        var deliverySource = BuildVm(hub, dispatcher, "delivery", 0);
        var deliveryFailure = new InvalidOperationException("delivery callback");
        var delivered = new List<(int Current, int Previous)>();
        var observedMessages = 0;
        using var failingSubscription = deliverySource.SubscribeValue(
            vm => vm.Model.Value,
            (current, previous) =>
            {
                delivered.Add((current, previous));
                if (current == 1) throw deliveryFailure;
            });
        using var observingSubscription = hub.Messages
            .OfType<IPropertyChangedMessage<object>>()
            .Where(message => ReferenceEquals(message.SenderObject, deliverySource))
            .Subscribe(_ => observedMessages++);

        Action firstDelivery = () => deliverySource.Model = new Model(1);
        firstDelivery.Should().NotThrow();
        deliverySource.Model = new Model(2);

        observedMessages.Should().Be(2,
            "a failing bridge callback must not block another hub subscriber");
        delivered.Should().Equal((1, 0), (2, 1));
    }

    private static ComponentVM<Model> BuildVm(
        MessageHub hub,
        TestDispatcher dispatcher,
        string name,
        int value)
        => ComponentVM<Model>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(new Model(value))
            .Build();

    private sealed class Model(int value)
    {
        public int Value { get; } = value;
    }

    private sealed record StubMessage(object SenderObject) : IMessage
    {
        public string SenderName => "stub";
    }

    private sealed class CountingParityComparer : IEqualityComparer<int>
    {
        public int Calls { get; private set; }

        public bool Equals(int x, int y)
        {
            Calls++;
            return x % 2 == y % 2;
        }

        public int GetHashCode(int obj) => obj.GetHashCode();
    }
}
