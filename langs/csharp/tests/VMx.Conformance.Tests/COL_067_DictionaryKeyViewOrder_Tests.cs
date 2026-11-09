using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-067: an <c>ObservableDictionary</c> mutation changes the entries and
/// <c>Count</c>, then each key view that changes, then raises the dictionary
/// events and sends the hub message. A key view changes only when a distinct
/// key first appears or last disappears, so a mutation can change both views,
/// one view, or none. The order of two key-view notifications is not checked
/// (spec/21-collections.md §4.2, ADR-0177, #1176, #1429).
/// </summary>
public class COL_067_DictionaryKeyViewOrder_Tests
{
    private sealed record Snapshot(string Entries, int Count, string Keys1, string Keys2);

    public static TheoryData<string> Mutations() => new()
    {
        "add", "insert", "remove", "clear", "add-keys2-only", "remove-keys2-only", "add-no-key-view",
    };

    private static Snapshot Read(ObservableDictionary<string, int, string> dict) => new(
        string.Join(",", dict.Select(entry => $"{entry.Key.Item1}{entry.Key.Item2}{entry.Value}")),
        dict.Count,
        string.Join(",", dict.Keys1),
        string.Join(",", dict.Keys2));

    [Theory, Trait("Conformance", "COL-067")]
    [MemberData(nameof(Mutations))]
    public void COL_067_DictionaryEventsAndHubMessageFollowTheKeyViews(string mutation)
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.Add("a", 1, "one");
        dict.Add("b", 2, "two");
        // ("a", 3) keeps "a" in Keys1 when ("a", 1) is removed.
        if (mutation == "remove-keys2-only") dict.Add("a", 3, "three");
        var start = Read(dict);
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
            case "clear": dict.Clear(); break;
            // Only a new Keys2 value appears; "a" is already in Keys1.
            case "add-keys2-only": dict.Add("a", 3, "three"); break;
            // Only the Keys2 value 1 disappears.
            case "remove-keys2-only": dict.Remove("a", 1).Should().BeTrue(); break;
            // Both keys already appear in other entries, so no key view changes.
            default: dict.Add("a", 2, "a-two"); break;
        }

        var final = Read(dict);
        final.Should().Be(mutation switch
        {
            "add" or "insert" => new Snapshot("a1one,b2two,c3three", 3, "a,b,c", "1,2,3"),
            "remove" => new Snapshot("b2two", 1, "b", "2"),
            "clear" => new Snapshot("", 0, "", ""),
            "add-keys2-only" => new Snapshot("a1one,b2two,a3three", 3, "a,b", "1,2,3"),
            "remove-keys2-only" => new Snapshot("b2two,a3three", 2, "a,b", "2,3"),
            _ => new Snapshot("a1one,b2two,a2a-two", 3, "a,b", "1,2"),
        });
        string[] changed = mutation switch
        {
            "add-keys2-only" or "remove-keys2-only" => ["keys2"],
            "add-no-key-view" => [],
            _ => ["keys1", "keys2"],
        };

        // A view that does not change keeps its start content.
        if (!changed.Contains("keys1")) final.Keys1.Should().Be(start.Keys1);
        if (!changed.Contains("keys2")) final.Keys2.Should().Be(start.Keys2);

        // Each changed key view notifies first, in an unspecified order; then
        // the dictionary events, then the hub message. An unchanged view stays
        // silent.
        seen.Select(s => s.Channel).Take(changed.Length).Should().BeEquivalentTo(changed);
        seen.Select(s => s.Channel).Skip(changed.Length).Should().Equal("dictionary", "collection", "hub");

        // A key-view handler sees the updated entries, Count and own view.
        foreach (var (channel, state) in seen.Take(changed.Length))
        {
            state.Entries.Should().Be(final.Entries);
            state.Count.Should().Be(final.Count);
            (channel == "keys1" ? state.Keys1 : state.Keys2)
                .Should().Be(channel == "keys1" ? final.Keys1 : final.Keys2);
        }

        // The dictionary events and the hub message see both views updated.
        foreach (var (_, state) in seen.Skip(changed.Length))
            state.Should().Be(final);
    }
}
