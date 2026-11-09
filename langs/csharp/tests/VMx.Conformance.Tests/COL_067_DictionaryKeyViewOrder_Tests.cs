using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-067: an <c>ObservableDictionary</c> mutation changes the entries and
/// <c>Count</c>, then both key views, then raises the dictionary events and
/// sends the hub message. The order of the two key-view notifications is not
/// checked (spec/21-collections.md §4.2, ADR-0177, #1176).
/// </summary>
public class COL_067_DictionaryKeyViewOrder_Tests
{
    private sealed record Snapshot(string Entries, int Count, string Keys1, string Keys2);

    public static TheoryData<string> Mutations() => new() { "add", "insert", "remove", "clear" };

    private static Snapshot Read(ObservableDictionary<string, int, string> dict) => new(
        string.Join(",", dict.Select(entry => $"{entry.Key.Item1}{entry.Key.Item2}{entry.Value}")),
        dict.Count,
        string.Join(",", dict.Keys1),
        string.Join(",", dict.Keys2));

    [Theory, Trait("Conformance", "COL-067")]
    [MemberData(nameof(Mutations))]
    public void COL_067_DictionaryEventsAndHubMessageFollowBothKeyViews(string mutation)
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.Add("a", 1, "one");
        dict.Add("b", 2, "two");
        var seen = new List<(string Channel, Snapshot State)>();
        void Record(string channel) => seen.Add((channel, Read(dict)));

        hub.Messages.Subscribe(_ => Record("hub"));
        dict.ItemAdded += (_, _) => Record("dictionary");
        dict.ItemRemoved += (_, _) => Record("dictionary");
        dict.Reset += (_, _) => Record("dictionary");
        dict.CollectionChanged += (_, _) => Record("collection");
        dict.Keys1.ItemAdded += (_, _) => Record("keys1");
        dict.Keys1.ItemRemoved += (_, _) => Record("keys1");
        dict.Keys1.Reset += (_, _) => Record("keys1");
        dict.Keys2.ItemAdded += (_, _) => Record("keys2");
        dict.Keys2.ItemRemoved += (_, _) => Record("keys2");
        dict.Keys2.Reset += (_, _) => Record("keys2");

        switch (mutation)
        {
            case "add": dict.Add("c", 3, "three"); break;
            case "insert": dict["c", 3] = "three"; break;
            case "remove": dict.Remove("a", 1).Should().BeTrue(); break;
            default: dict.Clear(); break;
        }

        var final = Read(dict);
        final.Should().Be(mutation switch
        {
            "add" or "insert" => new Snapshot("a1one,b2two,c3three", 3, "a,b,c", "1,2,3"),
            "remove" => new Snapshot("b2two", 1, "b", "2"),
            _ => new Snapshot("", 0, "", ""),
        });

        // Both key views notify first, in an unspecified order; then the
        // dictionary events, then the hub message.
        seen.Select(s => s.Channel).Take(2).Should().BeEquivalentTo("keys1", "keys2");
        seen.Select(s => s.Channel).Skip(2).Should().Equal("dictionary", "collection", "hub");

        // A key-view handler sees the updated entries, Count and own view.
        foreach (var (channel, state) in seen.Take(2))
        {
            state.Entries.Should().Be(final.Entries);
            state.Count.Should().Be(final.Count);
            (channel == "keys1" ? state.Keys1 : state.Keys2)
                .Should().Be(channel == "keys1" ? final.Keys1 : final.Keys2);
        }

        // The dictionary events and the hub message see both views updated.
        foreach (var (_, state) in seen.Skip(2))
            state.Should().Be(final);
    }
}
