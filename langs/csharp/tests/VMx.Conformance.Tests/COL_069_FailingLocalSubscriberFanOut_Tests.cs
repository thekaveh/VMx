using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-069: a failing local subscriber does not stop the later local
/// subscribers. Each change reaches every handler once, the failing handler
/// stays attached, one hub message is sent, and C# rethrows the first failure
/// after the hub send (spec/21 §2.5, spec/01 §1.4, spec/03 §3.6, ADR-0191).
/// </summary>
public class COL_069_FailingLocalSubscriberFanOut_Tests
{
    private sealed class LocalFailure() : Exception("local handler failed");

    private static List<string> ObserveHub(TestHub hub, List<string> order)
    {
        var messages = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            messages.Add(message.GetType().Name);
            order.Add("hub");
        });
        return messages;
    }

    private static void AssertList(ServicedObservableCollection<string> list, TestHub hub)
    {
        var order = new List<string>();
        var messages = ObserveHub(hub, order);
        list.CollectionChanged += (_, args) =>
        {
            order.Add($"A:{args.Action}");
            throw new LocalFailure();
        };
        list.CollectionChanged += (_, args) => order.Add($"B:{args.Action}");

        list.Invoking(l => l.Add("c")).Should().Throw<LocalFailure>();
        list.Invoking(l => l.RemoveAt(0)).Should().Throw<LocalFailure>();

        list.Should().Equal("b", "c");
        messages.Should().HaveCount(2);
        order.Should().Equal(
            "A:Add", "B:Add", "hub",
            "A:Remove", "B:Remove", "hub");
    }

    [Fact, Trait("Conformance", "COL-069")]
    public void COL_069_ServicedCollectionDeliversToEveryLocalHandler()
    {
        var hub = new TestHub();
        AssertList(new ServicedObservableCollection<string>(hub) { "a", "b" }, hub);
    }

    [Fact, Trait("Conformance", "COL-069")]
    public void COL_069_KeyedCollectionDeliversToEveryLocalHandler()
    {
        var hub = new TestHub();
        AssertList(new KeyedServicedObservableCollection<string, string>(item => item, hub) { "a", "b" }, hub);
    }

    public static TheoryData<string> DictionaryChannels() => new() { "granular", "collection" };

    [Theory, Trait("Conformance", "COL-069")]
    [MemberData(nameof(DictionaryChannels))]
    public void COL_069_DictionaryDeliversToEveryLocalHandler(string channel)
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        var order = new List<string>();
        var messages = ObserveHub(hub, order);
        void Handle(string name, string evt, string target)
        {
            order.Add($"{name}:{evt}");
            if (name == "A" && target == channel) throw new LocalFailure();
        }
        foreach (var name in new[] { "A", "B" })
        {
            dict.ItemAdded += (_, _) => Handle(name, "added", "granular");
            dict.ItemRemoved += (_, _) => Handle(name, "removed", "granular");
            dict.CollectionChanged += (_, args) => Handle(name, args.Action.ToString(), "collection");
        }

        dict.Invoking(d => d.Add("a", 1, "one")).Should().Throw<LocalFailure>();
        dict.Invoking(d => d.Remove("a", 1)).Should().Throw<LocalFailure>();

        dict.Should().BeEmpty();
        messages.Should().HaveCount(2);
        order.Should().Equal(
            "A:added", "B:added", "A:Add", "B:Add", "hub",
            "A:removed", "B:removed", "A:Remove", "B:Remove", "hub");
    }

    [Fact, Trait("Conformance", "COL-069")]
    public void COL_069_SingleHandlerReentrantMutationStillAllowed()
    {
        var hub = new TestHub();
        var list = new ServicedObservableCollection<string>(hub) { "a" };
        var nested = false;
        list.CollectionChanged += (_, args) =>
        {
            if (nested || args.Action != NotifyCollectionChangedAction.Add) return;
            nested = true;
            list.Add("nested");
        };

        list.Add("b");

        list.Should().Equal("a", "b", "nested");
    }

    [Fact, Trait("Conformance", "COL-069")]
    public void COL_069_RemovedHandlerNoLongerReceivesChanges()
    {
        var list = new ServicedObservableCollection<string>();
        var a = 0;
        var b = 0;
        NotifyCollectionChangedEventHandler first = (_, _) =>
        {
            a++;
            throw new LocalFailure();
        };
        list.CollectionChanged += first;
        list.CollectionChanged += (_, _) => b++;

        list.Invoking(l => l.Add("a")).Should().Throw<LocalFailure>();
        list.CollectionChanged -= first;
        list.Add("b");

        a.Should().Be(1);
        b.Should().Be(2);
    }
}
