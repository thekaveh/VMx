using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-066: a failing local subscriber does not suppress the hub message.
/// The change is committed, exactly one hub <c>CollectionChangedMessage</c>
/// is sent, and C# rethrows the first failure after publication
/// (spec/01-concepts.md §1.4, spec/21-collections.md §2.5, ADR-0171, #1051).
/// </summary>
public class COL_066_FailingLocalSubscriber_Tests
{
    private sealed class LocalFailure() : Exception("local handler failed");

    public static TheoryData<string> ListMutations() => new()
    {
        "add", "remove", "replace", "move", "clear", "replaceAll",
    };

    private static (List<CollectionChangedMessage<string>> Messages, List<string> Order) Observe(TestHub hub)
    {
        var messages = new List<CollectionChangedMessage<string>>();
        var order = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            messages.Add((CollectionChangedMessage<string>)message);
            order.Add("hub");
        });
        return (messages, order);
    }

    private static (NotifyCollectionChangedAction Action, string[] Expected) MutateList(
        ServicedObservableCollection<string> list, string mutation)
    {
        Action act = mutation switch
        {
            "add" => () => list.Add("c"),
            "remove" => () => list.RemoveAt(0),
            "replace" => () => list.Replace(0, "z"),
            "move" => () => list.Move(0, 1),
            "clear" => list.Clear,
            "replaceAll" => () => list.ReplaceAll(["x", "y"]),
            _ => throw new ArgumentOutOfRangeException(nameof(mutation)),
        };
        act.Should().Throw<LocalFailure>();
        return mutation switch
        {
            "add" => (NotifyCollectionChangedAction.Add, ["a", "b", "c"]),
            "remove" => (NotifyCollectionChangedAction.Remove, ["b"]),
            "replace" => (NotifyCollectionChangedAction.Replace, ["z", "b"]),
            "move" => (NotifyCollectionChangedAction.Move, ["b", "a"]),
            "clear" => (NotifyCollectionChangedAction.Reset, []),
            _ => (NotifyCollectionChangedAction.Reset, ["x", "y"]),
        };
    }

    [Theory, Trait("Conformance", "COL-066")]
    [MemberData(nameof(ListMutations))]
    public void COL_066_ServicedCollectionSendsOneHubMessageDespiteFailingLocalHandler(string mutation)
    {
        var hub = new TestHub();
        var list = new ServicedObservableCollection<string>(hub) { "a", "b" };
        var (messages, order) = Observe(hub);
        list.CollectionChanged += (_, _) =>
        {
            order.Add("local");
            throw new LocalFailure();
        };

        var (action, expected) = MutateList(list, mutation);

        list.Should().Equal(expected);
        messages.Should().ContainSingle().Which.Action.Should().Be(action);
        order.Should().Equal("local", "hub");
    }

    [Theory, Trait("Conformance", "COL-066")]
    [MemberData(nameof(ListMutations))]
    public void COL_066_KeyedCollectionSendsOneHubMessageDespiteFailingLocalHandler(string mutation)
    {
        var hub = new TestHub();
        var list = new KeyedServicedObservableCollection<string, string>(item => item, hub) { "a", "b" };
        var (messages, order) = Observe(hub);
        list.CollectionChanged += (_, _) =>
        {
            order.Add("local");
            throw new LocalFailure();
        };

        var (action, expected) = MutateList(list, mutation);

        list.Should().Equal(expected);
        foreach (var item in expected)
            list.TryGetValue(item, out var found).Should().BeTrue();
        messages.Should().ContainSingle().Which.Action.Should().Be(action);
        order.Should().Equal("local", "hub");
    }

    public static TheoryData<string, string> DictionaryMutations() => new()
    {
        { "add", "granular" }, { "add", "collection" },
        { "remove", "granular" }, { "remove", "collection" },
        { "replace", "granular" }, { "replace", "collection" },
        { "clear", "granular" }, { "clear", "collection" },
    };

    [Theory, Trait("Conformance", "COL-066")]
    [MemberData(nameof(DictionaryMutations))]
    public void COL_066_DictionarySendsOneHubMessageDespiteFailingLocalHandler(string mutation, string failing)
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.Add("a", 1, "one");
        var messages = new List<IMessage>();
        var order = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            messages.Add(message);
            order.Add("hub");
        });
        void Fail(string channel)
        {
            order.Add(channel);
            if (channel == failing) throw new LocalFailure();
        }
        dict.ItemAdded += (_, _) => Fail("granular");
        dict.ItemRemoved += (_, _) => Fail("granular");
        dict.ItemReplaced += (_, _) => Fail("granular");
        dict.Reset += (_, _) => Fail("granular");
        dict.CollectionChanged += (_, _) => Fail("collection");

        Action act = mutation switch
        {
            "add" => () => dict.Add("b", 2, "two"),
            "remove" => () => dict.Remove("a", 1),
            "replace" => () => dict["a", 1] = "uno",
            _ => dict.Clear,
        };
        act.Should().Throw<LocalFailure>();

        var expected = mutation switch
        {
            "add" => new[] { ("a", 1, "one"), ("b", 2, "two") },
            "replace" => [("a", 1, "uno")],
            _ => [],
        };
        dict.Select(entry => (entry.Key.Item1, entry.Key.Item2, entry.Value)).Should().Equal(expected);
        messages.Should().ContainSingle()
            .Which.Should().BeOfType<CollectionChangedMessage<KeyValuePair<(string, int), string>>>();
        order.Should().Equal("granular", "collection", "hub");
    }
}
