using System.Collections.Specialized;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using FluentAssertions;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Messages;
using VMx.Properties;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests;

/// <summary>
/// Regression tests for the subscriber-failure delivery rules of spec/03 §3.6
/// (ADR-0191, #1304, #1311) on the channels that the conformance tests do not
/// reach: the hub helpers, the container local events, the forwarding
/// commands, and completion on disposal.
/// </summary>
public class SubscriberFailureDeliveryTests
{
    private sealed class SubscriberFailure() : Exception("subscriber failed");

    private static readonly TestDispatcher Dispatcher = new();

    private sealed class Source
    {
        public int Count { get; set; }
    }

    private static void SendCount(MessageHub hub, Source source, int value)
    {
        source.Count = value;
        hub.Send(PropertyChangedMessage<Source>.Create(source, "source", nameof(Source.Count)));
    }

    public static TheoryData<string> Helpers() => new() { "values", "one-name", "many-names" };

    private static IDisposable SubscribeHelper(string kind, MessageHub hub, Source source, Action onNext) => kind switch
    {
        "values" => hub.PropertyValueChangedMessagesFor(source, s => s.Count).Subscribe(_ => onNext()),
        "one-name" => hub.WhenPropertyChanged(source, nameof(Source.Count)).Subscribe(_ => onNext()),
        _ => hub.WhenPropertyChanged(source, nameof(Source.Count), "Other").Subscribe(_ => onNext()),
    };

    [Theory]
    [MemberData(nameof(Helpers))]
    public void Hub_Helper_Subscriber_That_Throws_Stays_Attached(string kind)
    {
        using var hub = new MessageHub();
        var source = new Source();
        var a = 0;
        var b = 0;
        using var failing = SubscribeHelper(kind, hub, source, () =>
        {
            a++;
            throw new SubscriberFailure();
        });
        using var recording = SubscribeHelper(kind, hub, source, () => b++);

        hub.Invoking(_ => SendCount(hub, source, 1)).Should().NotThrow();
        hub.Invoking(_ => SendCount(hub, source, 2)).Should().NotThrow();

        a.Should().Be(2);
        b.Should().Be(2);
    }

    public static TheoryData<string> Containers() => new() { "composite", "group" };

    private static IList<IComponentVM> Container(string kind, MessageHub hub) => kind == "composite"
        ? CompositeVM<IComponentVM>.Builder().Name("c").Services(hub, Dispatcher).Children(() => []).Build()
        : GroupVM<IComponentVM>.Builder().Name("g").Services(hub, Dispatcher).Children(() => []).Build();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    [Theory]
    [MemberData(nameof(Containers))]
    public void Container_Local_Handlers_Each_Receive_The_Change_Once(string kind)
    {
        using var hub = new MessageHub();
        var container = Container(kind, hub);
        var order = new List<string>();
        using var hubSubscription = hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.Sender, container))
            .Subscribe(_ => order.Add("hub"));
        var notifier = (INotifyCollectionChanged)container;
        notifier.CollectionChanged += (_, args) =>
        {
            order.Add($"A:{args.Action}");
            throw new SubscriberFailure();
        };
        notifier.CollectionChanged += (_, args) => order.Add($"B:{args.Action}");

        container.Invoking(c => c.Add(Child(hub, "a"))).Should().Throw<SubscriberFailure>();
        container.Invoking(c => c.RemoveAt(0)).Should().Throw<SubscriberFailure>();

        order.Should().Equal("A:Add", "B:Add", "hub", "A:Remove", "B:Remove", "hub");
        ((IDisposable)container).Dispose();
    }

    [Fact]
    public void Serviced_Collection_Multicast_Handler_Reaches_Every_Entry()
    {
        var collection = new VMx.Collections.ServicedObservableCollection<string>();
        var order = new List<string>();
        NotifyCollectionChangedEventHandler a = (_, _) =>
        {
            order.Add("A");
            throw new SubscriberFailure();
        };
        NotifyCollectionChangedEventHandler b = (_, _) => order.Add("B");
        collection.CollectionChanged += a + b;

        collection.Invoking(c => c.Add("one")).Should().Throw<SubscriberFailure>();
        order.Should().Equal("A", "B");

        // Standard event semantics: removing one entry of a multicast
        // subscription keeps the other entry attached.
        collection.CollectionChanged -= a;
        collection.Add("two");
        order.Should().Equal("A", "B", "B");

        collection.CollectionChanged += a;
        collection.CollectionChanged -= b + a;
        collection.Add("three");
        order.Should().Equal("A", "B", "B");
    }

    public static TheoryData<string> Wrappers() => new() { "decorator", "confirmation", "composite" };

    private static ICommand Wrapper(string kind, ICommand inner) => kind switch
    {
        "decorator" => new DecoratorCommand(inner),
        "confirmation" => new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true)),
        _ => new CompositeCommand(inner),
    };

    [Theory]
    [MemberData(nameof(Wrappers))]
    public void Forwarding_Command_Handlers_Each_Receive_The_Notification(string kind)
    {
        using var trigger = new Subject<System.Reactive.Unit>();
        using var inner = RelayCommand.Builder().Triggers(trigger.Select(u => u)).Build();
        var wrapper = Wrapper(kind, inner);
        var a = 0;
        var b = 0;
        wrapper.CanExecuteChanged += (_, _) =>
        {
            a++;
            throw new SubscriberFailure();
        };
        wrapper.CanExecuteChanged += (_, _) => b++;

        trigger.Invoking(t => t.OnNext(System.Reactive.Unit.Default)).Should().NotThrow();
        trigger.Invoking(t => t.OnNext(System.Reactive.Unit.Default)).Should().NotThrow();
        inner.Invoking(c => c.RaiseCanExecuteChanged()).Should().Throw<SubscriberFailure>();

        a.Should().Be(3);
        b.Should().Be(3);

        // Disposal notifies every handler once, then rethrows the failure
        // (spec/04 §8.4).
        wrapper.Invoking(w => ((IDisposable)w).Dispose()).Should().Throw<SubscriberFailure>();
        a.Should().Be(4);
        b.Should().Be(4);
    }

    [Fact]
    public void Derived_Property_Dispose_Completes_Every_Subscriber_Then_Rethrows()
    {
        var property = DerivedProperty.From(new BehaviorSubject<int>(1), x => x);
        var completed = new List<string>();
        property.ValueChanged.Subscribe(_ => { }, () =>
        {
            completed.Add("A");
            throw new SubscriberFailure();
        });
        property.ValueChanged.Subscribe(_ => { }, () => completed.Add("B"));

        property.Invoking(p => p.Dispose()).Should().Throw<SubscriberFailure>();

        completed.Should().Equal("A", "B");
    }

    [Fact]
    public void Searchable_State_Dispose_Completes_Every_Subscriber_Then_Rethrows()
    {
        var state = new SearchableState<string>(
            () => ["a"], (_, _) => true, TimeSpan.Zero, ImmediateScheduler.Instance);
        var completed = new List<string>();
        state.Filtered.Subscribe(_ => { }, () =>
        {
            completed.Add("A");
            throw new SubscriberFailure();
        });
        state.Filtered.Subscribe(_ => { }, () => completed.Add("B"));

        state.Invoking(s => s.Dispose()).Should().Throw<SubscriberFailure>();

        completed.Should().Equal("A", "B");
    }

    [Fact]
    public void Searchable_State_Failing_Items_Supplier_Keeps_Last_Snapshot()
    {
        var fail = false;
        using var state = new SearchableState<string>(
            () => fail ? throw new SubscriberFailure() : ["apple", "banana"],
            (item, term) => item.Contains(term, StringComparison.Ordinal),
            TimeSpan.Zero,
            ImmediateScheduler.Instance);
        var snapshots = new List<IReadOnlyList<string>>();
        using var subscription = state.Filtered.Subscribe(snapshots.Add);

        fail = true;
        state.Invoking(s => s.SearchTerm = "an").Should().NotThrow();
        fail = false;
        state.Search();

        snapshots.Should().HaveCount(2);
        snapshots[1].Should().Equal("banana");
    }
}
