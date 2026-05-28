using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-010..COL-015 — ObservableDictionary (multi-key).
/// See spec/21-collections.md §4 and ADR-0025.
/// </summary>
public class COL_010_to_015_ObservableDictionaryTests
{
    // ── COL-010 ──────────────────────────────────────────────────────────────

    /// <summary>COL-010: ObservableDictionary insert and retrieve.</summary>
    [Fact, Trait("Conformance", "COL-010")]
    public void COL_010_Insert_And_Retrieve()
    {
        var sut = new ObservableDictionary<string, int, double>();
        var addedEvents = new List<(string K1, int K2, double V)>();
        sut.ItemAdded += (_, e) => addedEvents.Add((e.Key1, e.Key2, e.Value));

        sut.Add("alpha", 1, 3.14);

        // ContainsKey is true after insert
        sut.ContainsKey("alpha", 1).Should().BeTrue();

        // Indexer returns correct value
        sut["alpha", 1].Should().Be(3.14);

        // Count incremented
        sut.Count.Should().Be(1);

        // ItemAdded event fired with correct payload
        addedEvents.Should().ContainSingle();
        addedEvents[0].K1.Should().Be("alpha");
        addedEvents[0].K2.Should().Be(1);
        addedEvents[0].V.Should().Be(3.14);

        // Keys1 contains the new Key1
        sut.Keys1.Should().Contain("alpha");

        // Keys2 contains the new Key2
        sut.Keys2.Should().Contain(1);
    }

    // ── COL-011 ──────────────────────────────────────────────────────────────

    /// <summary>COL-011: ObservableDictionary remove.</summary>
    [Fact, Trait("Conformance", "COL-011")]
    public void COL_011_Remove()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("alpha", 1, 3.14);
        sut.Add("alpha", 2, 2.72);  // same key1, different key2
        sut.Add("beta", 1, 1.41);  // different key1, same key2

        var removedEvents = new List<(string K1, int K2, double V)>();
        sut.ItemRemoved += (_, e) => removedEvents.Add((e.Key1, e.Key2, e.Value));

        bool result = sut.Remove("alpha", 1);

        // Return value is true
        result.Should().BeTrue();

        // Entry is no longer present
        sut.ContainsKey("alpha", 1).Should().BeFalse();
        sut.Count.Should().Be(2);

        // ItemRemoved fired with correct payload
        removedEvents.Should().ContainSingle();
        removedEvents[0].K1.Should().Be("alpha");
        removedEvents[0].K2.Should().Be(1);
        removedEvents[0].V.Should().Be(3.14);

        // "alpha" still in Keys1 because ("alpha", 2) remains
        sut.Keys1.Should().Contain("alpha");

        // Key2=1 still in Keys2 because ("beta", 1) remains
        sut.Keys2.Should().Contain(1);

        // Now remove the last entry that uses Key2=2
        sut.Remove("alpha", 2);
        sut.Keys2.Should().NotContain(2);

        // Now remove the last entry that uses Key1="beta"
        sut.Remove("beta", 1);
        sut.Keys1.Should().NotContain("beta");
        sut.Keys2.Should().NotContain(1);
    }

    // ── COL-012 ──────────────────────────────────────────────────────────────

    /// <summary>COL-012: ObservableDictionary replace.</summary>
    [Fact, Trait("Conformance", "COL-012")]
    public void COL_012_Replace()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("alpha", 1, 3.14);

        var addedEvents = new List<string>();
        var removedEvents = new List<string>();
        var replacedEvents = new List<(string K1, int K2, double NewV, double OldV)>();

        sut.ItemAdded += (_, _) => addedEvents.Add("added");
        sut.ItemRemoved += (_, _) => removedEvents.Add("removed");
        sut.ItemReplaced += (_, e) => replacedEvents.Add((e.Key1, e.Key2, e.NewValue, e.OldValue));

        // Setting via indexer on an existing key pair triggers Replace
        sut["alpha", 1] = 9.99;

        // New value is accessible
        sut["alpha", 1].Should().Be(9.99);

        // Count unchanged
        sut.Count.Should().Be(1);

        // ItemReplaced fired, NOT Added or Removed
        addedEvents.Should().BeEmpty("Replace must NOT fire ItemAdded");
        removedEvents.Should().BeEmpty("Replace must NOT fire ItemRemoved");
        replacedEvents.Should().ContainSingle();
        replacedEvents[0].K1.Should().Be("alpha");
        replacedEvents[0].K2.Should().Be(1);
        replacedEvents[0].NewV.Should().Be(9.99);
        replacedEvents[0].OldV.Should().Be(3.14);
    }

    // ── COL-013 ──────────────────────────────────────────────────────────────

    /// <summary>COL-013: ObservableDictionary distinct-key observable views stay in sync.</summary>
    [Fact, Trait("Conformance", "COL-013")]
    public void COL_013_DistinctKeyViews_StayInSync()
    {
        var sut = new ObservableDictionary<string, int, double>();

        // Track Keys1 ItemAdded / ItemRemoved events
        var keys1Added = new List<string>();
        var keys1Removed = new List<string>();
        sut.Keys1.ItemAdded += (_, e) => keys1Added.Add(e.Item);
        sut.Keys1.ItemRemoved += (_, e) => keys1Removed.Add(e.Item);

        var keys2Added = new List<int>();
        var keys2Removed = new List<int>();
        sut.Keys2.ItemAdded += (_, e) => keys2Added.Add(e.Item);
        sut.Keys2.ItemRemoved += (_, e) => keys2Removed.Add(e.Item);

        // Insert first entry — both key axes get a new value
        sut.Add("alpha", 1, 1.0);
        keys1Added.Should().Equal("alpha");
        keys2Added.Should().Equal(1);

        // Insert second entry with same Key1 — Keys1 does NOT get another event
        sut.Add("alpha", 2, 2.0);
        keys1Added.Should().HaveCount(1, "Key1='alpha' already present; no new Keys1 event");
        keys2Added.Should().HaveCount(2).And.Contain(2);

        // Insert entry with new Key1
        sut.Add("beta", 1, 3.0);
        keys1Added.Should().Contain("beta");
        keys2Added.Should().HaveCount(2, "Key2=1 already present; no new Keys2 event");

        // Remove ("alpha", 1) — "alpha" still present via ("alpha", 2), no Keys1 removal
        sut.Remove("alpha", 1);
        keys1Removed.Should().BeEmpty("alpha still has entry (alpha,2)");

        // Remove ("alpha", 2) — "alpha" now gone, Keys1 should fire ItemRemoved
        sut.Remove("alpha", 2);
        keys1Removed.Should().Contain("alpha");

        // Key2=2 disappeared when ("alpha",2) was removed
        keys2Removed.Should().Contain(2);
    }

    // ── COL-014 ──────────────────────────────────────────────────────────────

    /// <summary>COL-014: ObservableDictionary enumeration order is insertion order.</summary>
    [Fact, Trait("Conformance", "COL-014")]
    public void COL_014_EnumerationOrder_IsInsertionOrder()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("alpha", 1, 1.1);
        sut.Add("beta", 2, 2.2);
        sut.Add("gamma", 1, 3.3);
        sut.Add("alpha", 2, 4.4);

        var entries = sut.ToList();

        entries.Should().HaveCount(4);
        entries[0].Key.Should().Be(("alpha", 1));
        entries[0].Value.Should().Be(1.1);
        entries[1].Key.Should().Be(("beta", 2));
        entries[1].Value.Should().Be(2.2);
        entries[2].Key.Should().Be(("gamma", 1));
        entries[2].Value.Should().Be(3.3);
        entries[3].Key.Should().Be(("alpha", 2));
        entries[3].Value.Should().Be(4.4);
    }

    // ── COL-015 ──────────────────────────────────────────────────────────────

    /// <summary>COL-015: ObservableDictionary clear empties key views.</summary>
    [Fact, Trait("Conformance", "COL-015")]
    public void COL_015_Clear_EmptiesKeyViews()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("alpha", 1, 1.0);
        sut.Add("beta", 2, 2.0);

        var granularEvents = new List<string>();
        int resetCount = 0;
        sut.ItemAdded += (_, _) => granularEvents.Add("added");
        sut.ItemRemoved += (_, _) => granularEvents.Add("removed");
        sut.Reset += (_, _) => resetCount++;

        sut.Clear();

        // Count drops to zero
        sut.Count.Should().Be(0);

        // Keys1 and Keys2 are empty
        sut.Keys1.Count.Should().Be(0);
        sut.Keys2.Count.Should().Be(0);

        // Reset fired exactly once
        resetCount.Should().Be(1);

        // No individual ItemAdded/ItemRemoved events fired during Clear
        granularEvents.Should().BeEmpty("Clear must NOT fire per-entry ItemRemoved events");
    }

    // ── COL-022 ──────────────────────────────────────────────────────────────

    /// <summary>COL-022: ObservableDictionary hub publication — mutations publish CollectionChangedMessage to the hub.</summary>
    [Fact, Trait("Conformance", "COL-022")]
    public void COL_022_Hub_Publication()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);

        var received = new List<IMessage>();
        hub.Messages.Subscribe(m => received.Add(m));

        // Add — publishes an Add message
        sut.Add("alpha", 1, 3.14);
        received.Should().HaveCount(1);
        var addMsg = received[0]
            .Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Subject;
        addMsg.Action.Should().Be(System.Collections.Specialized.NotifyCollectionChangedAction.Add);
        addMsg.SenderObject.Should().BeSameAs(sut);
        addMsg.NewItems.Should().ContainSingle()
            .Which.Should().Be(new KeyValuePair<(string, int), double>(("alpha", 1), 3.14));

        received.Clear();

        // Replace (indexer set) — publishes a Replace message
        sut["alpha", 1] = 9.99;
        received.Should().HaveCount(1);
        received[0]
            .Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(System.Collections.Specialized.NotifyCollectionChangedAction.Replace);

        received.Clear();

        // Remove — publishes a Remove message
        sut.Remove("alpha", 1);
        received.Should().HaveCount(1);
        received[0]
            .Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(System.Collections.Specialized.NotifyCollectionChangedAction.Remove);

        received.Clear();

        // Clear — publishes a Reset message
        sut.Add("beta", 2, 2.72);
        received.Clear(); // discard the Add from above
        sut.Clear();
        received.Should().HaveCount(1);
        received[0]
            .Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(System.Collections.Specialized.NotifyCollectionChangedAction.Reset);
    }

    /// <summary>COL-022 (no-hub path): ObservableDictionary with null hub does not throw and does not publish.</summary>
    [Fact, Trait("Conformance", "COL-022")]
    public void COL_022_NoHub_NoPublicationNoErrors()
    {
        // Construct without hub — must not throw on any mutation.
        var sut = new ObservableDictionary<string, int, double>();

        var act = () =>
        {
            sut.Add("x", 1, 1.0);
            sut["x", 1] = 2.0;
            sut.Remove("x", 1);
            sut.Add("y", 2, 3.0);
            sut.Clear();
        };

        act.Should().NotThrow();
    }
}
