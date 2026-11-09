using System.Collections.Specialized;
using System.ComponentModel;
using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// A throwing handler does not skip the later notification steps of a
/// committed change (spec/21 §3.3, #1367, #1430). The first failure
/// reaches the caller after the last step.
/// </summary>
public class CollectionNotificationFailureTests
{
    private sealed class HandlerFailure() : Exception("handler failed");

    // ── ObservableList (#1367) ──────────────────────────────────────────────

    public static TheoryData<string, string> ListCases() => new()
    {
        { "add", "ItemAdded" },
        { "insert", "ItemAdded" },
        { "remove", "ItemRemoved" },
        { "removeAt", "ItemRemoved" },
        { "clear", "Reset" },
        { "replaceAll", "Reset" },
        { "batch", "Reset" },
    };

    [Theory]
    [MemberData(nameof(ListCases))]
    public void ObservableList_Throwing_Granular_Handler_Skips_Neither_CollectionChanged_Nor_Count(
        string operation, string failingEvent)
    {
        var list = new ObservableList<int>();
        if (operation is "remove" or "removeAt" or "clear" or "replaceAll") list.Add(1);
        var collectionChanged = 0;
        var counts = 0;
        var later = 0;
        list.CollectionChanged += (_, _) => collectionChanged++;
        list.PropertyChanged += (_, e) => { if (e.PropertyName == "Count") counts++; };
        switch (failingEvent)
        {
            case "ItemAdded":
                list.ItemAdded += (_, _) => throw new HandlerFailure();
                list.ItemAdded += (_, _) => later++;
                break;
            case "ItemRemoved":
                list.ItemRemoved += (_, _) => throw new HandlerFailure();
                list.ItemRemoved += (_, _) => later++;
                break;
            default:
                list.Reset += (_, _) => throw new HandlerFailure();
                list.Reset += (_, _) => later++;
                break;
        }

        void AddInBatch()
        {
            using (list.BatchUpdate()) list.Add(1);
        }

        Action act = operation switch
        {
            "add" => () => list.Add(1),
            "insert" => () => list.Insert(0, 1),
            "remove" => () => list.Remove(1),
            "removeAt" => () => list.RemoveAt(0),
            "clear" => list.Clear,
            "replaceAll" => () => list.ReplaceAll([1, 2]),
            _ => AddInBatch,
        };

        act.Should().Throw<HandlerFailure>();
        collectionChanged.Should().Be(1);
        counts.Should().Be(1);
        later.Should().Be(1);
        list.Count.Should().Be(operation switch
        {
            "remove" or "removeAt" or "clear" => 0,
            "replaceAll" => 2,
            _ => 1,
        });
    }

    [Fact]
    public void ObservableList_Throwing_ItemReplaced_Handler_Does_Not_Skip_CollectionChanged()
    {
        var list = new ObservableList<int> { 1 };
        var collectionChanged = 0;
        list.CollectionChanged += (_, _) => collectionChanged++;
        list.ItemReplaced += (_, _) => throw new HandlerFailure();

        list.Invoking(l => l.Replace(0, 2)).Should().Throw<HandlerFailure>();

        collectionChanged.Should().Be(1);
        list.Should().Equal(2);
    }

    [Fact]
    public void ReadOnlyObservableList_Throwing_Handler_Reaches_Later_Facade_Handlers()
    {
        var dict = new ObservableDictionary<string, int, string>();
        var later = 0;
        dict.Keys1.ItemAdded += (_, _) => throw new HandlerFailure();
        dict.Keys1.ItemAdded += (_, _) => later++;

        dict.Invoking(d => d.Add("a", 1, "v")).Should().Throw<HandlerFailure>();

        later.Should().Be(1);
    }

    // ── Serviced collections: PropertyChanged handlers (#1430) ─────────────

    private static ServicedObservableCollection<string> Collection(string kind, TestHub hub)
        => kind == "keyed"
            ? new KeyedServicedObservableCollection<string, string>(item => item, hub)
            : new ServicedObservableCollection<string>(hub);

    public static TheoryData<string, string, string> PropertyCases()
    {
        var data = new TheoryData<string, string, string>();
        foreach (var kind in new[] { "plain", "keyed" })
        {
            foreach (var property in new[] { "Count", "Item[]" })
            {
                foreach (var operation in new[] { "add", "remove", "clear", "replaceAll" })
                    data.Add(kind, property, operation);
            }
            data.Add(kind, "Item[]", "replace");
            data.Add(kind, "Item[]", "move");
        }
        return data;
    }

    [Theory]
    [MemberData(nameof(PropertyCases))]
    public void Serviced_Throwing_PropertyChanged_Handler_Skips_Neither_CollectionChanged_Nor_Hub(
        string kind, string property, string operation)
    {
        using var hub = new TestHub();
        var messages = 0;
        using var subscription = hub.Messages.Subscribe(_ => messages++);
        var collection = Collection(kind, hub);
        collection.Add("a");
        collection.Add("b");
        messages = 0;
        var collectionChanged = 0;
        var later = 0;
        collection.CollectionChanged += (_, _) => collectionChanged++;
        INotifyPropertyChanged notifier = collection;
        notifier.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == property) throw new HandlerFailure();
        };
        notifier.PropertyChanged += (_, e) => { if (e.PropertyName == property) later++; };

        Action act = operation switch
        {
            "add" => () => collection.Add("c"),
            "remove" => () => collection.RemoveAt(0),
            "clear" => collection.Clear,
            "replaceAll" => () => collection.ReplaceAll(["x", "y", "z"]),
            "replace" => () => collection.Replace(0, "x"),
            _ => () => collection.Move(0, 1),
        };

        act.Should().Throw<HandlerFailure>();
        collectionChanged.Should().Be(1);
        messages.Should().Be(1);
        later.Should().Be(1);

        // The pending failure belongs to that mutation only.
        collectionChanged = 0;
        messages = 0;
        Action next = () => collection.Move(0, collection.Count - 1);
        if (property == "Item[]" && collection.Count > 1)
            next.Should().Throw<HandlerFailure>();
        else if (collection.Count > 1)
            next.Should().NotThrow();
    }

    [Fact]
    public void Serviced_PropertyChanged_Handler_Can_Be_Removed()
    {
        var collection = new ServicedObservableCollection<string>();
        var seen = 0;
        PropertyChangedEventHandler handler = (_, _) => seen++;
        INotifyPropertyChanged notifier = collection;
        notifier.PropertyChanged += handler;
        collection.Add("a");
        notifier.PropertyChanged -= handler;
        collection.Add("b");

        seen.Should().Be(2, "Add raises Count and Item[] once, before the handler is removed");
    }

    // ── ObservableDictionary key views (#1430) ─────────────────────────────

    public static TheoryData<string, string> KeyViewCases()
    {
        var data = new TheoryData<string, string>();
        foreach (var view in new[] { "Keys1", "Keys2" })
            foreach (var operation in new[] { "add", "indexer", "remove", "clear" })
                data.Add(view, operation);
        return data;
    }

    [Theory]
    [MemberData(nameof(KeyViewCases))]
    public void Dictionary_Throwing_KeyView_Subscriber_Skips_No_Notification(string view, string operation)
    {
        using var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub) { };
        dict.Add("a", 1, "v");
        var messages = 0;
        using var subscription = hub.Messages.Subscribe(_ => messages++);
        var granular = 0;
        var collectionChanged = 0;
        dict.ItemAdded += (_, _) => granular++;
        dict.ItemRemoved += (_, _) => granular++;
        dict.Reset += (_, _) => granular++;
        dict.CollectionChanged += (_, _) => collectionChanged++;
        ReadOnlyObservableList<string>? keys1 = view == "Keys1" ? dict.Keys1 : null;
        ReadOnlyObservableList<int>? keys2 = view == "Keys2" ? dict.Keys2 : null;
        if (keys1 is not null) keys1.CollectionChanged += (_, _) => throw new HandlerFailure();
        if (keys2 is not null) keys2.CollectionChanged += (_, _) => throw new HandlerFailure();

        Action act = operation switch
        {
            "add" => () => dict.Add("b", 2, "x"),
            "indexer" => () => dict["b", 2] = "x",
            "remove" => () => dict.Remove("a", 1),
            _ => dict.Clear,
        };

        act.Should().Throw<HandlerFailure>();
        granular.Should().Be(1);
        collectionChanged.Should().Be(1);
        messages.Should().Be(1);
        AssertViewsMatch(dict);
    }

    [Fact]
    public void Dictionary_Failed_Keys2_Add_Still_Lists_The_New_Key1()
    {
        var dict = new ObservableDictionary<string, int, string>();
        NotifyCollectionChangedEventHandler failing = (_, _) => throw new HandlerFailure();
        dict.Keys2.CollectionChanged += failing;

        dict.Invoking(d => d.Add("a", 1, "v")).Should().Throw<HandlerFailure>();

        dict.Keys1.Should().Equal("a");
        dict.Keys2.Should().Equal(1);
        dict.Keys2.CollectionChanged -= failing;
        dict.Add("a", 2, "z");
        dict.Keys1.Should().Equal("a");
        dict.Keys2.Should().Equal(1, 2);
        dict.Count.Should().Be(2);
    }

    private static void AssertViewsMatch(ObservableDictionary<string, int, string> dict)
    {
        var keys1 = new List<string>();
        var keys2 = new List<int>();
        foreach (var entry in dict)
        {
            if (!keys1.Contains(entry.Key.Item1)) keys1.Add(entry.Key.Item1);
            if (!keys2.Contains(entry.Key.Item2)) keys2.Add(entry.Key.Item2);
        }
        dict.Keys1.Should().Equal(keys1);
        dict.Keys2.Should().Equal(keys2);
    }
}
