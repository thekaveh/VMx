using System.ComponentModel;
using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-005..COL-009 — ObservableList&lt;T&gt; granular events.
/// See spec/21-collections.md §3 and ADR-0026.
/// </summary>
public class COL_005_to_009_ObservableListTests
{
    // ── COL-005 ──────────────────────────────────────────────────────────────

    /// <summary>COL-005: ObservableList ItemAdded payload shape — item and index are correct.</summary>
    [Fact, Trait("Conformance", "COL-005")]
    public void COL_005_ItemAdded_PayloadShape()
    {
        var sut = new ObservableList<string>();
        sut.Add("a"); // pre-populate so index is predictable

        var received = new List<(string Item, int Index)>();
        sut.ItemAdded += (_, e) => received.Add((e.Item, e.Index));

        sut.Add("b");

        received.Should().ContainSingle();
        received[0].Item.Should().Be("b");
        received[0].Index.Should().Be(1);
    }

    // ── COL-006 ──────────────────────────────────────────────────────────────

    /// <summary>COL-006: ObservableList ItemRemoved payload shape — item and original index.</summary>
    [Fact, Trait("Conformance", "COL-006")]
    public void COL_006_ItemRemoved_PayloadShape()
    {
        var sut = new ObservableList<string>();
        sut.Add("x");
        sut.Add("y");
        sut.Add("z");

        var received = new List<(string Item, int Index)>();
        sut.ItemRemoved += (_, e) => received.Add((e.Item, e.Index));

        sut.RemoveAt(1); // remove "y" at index 1

        received.Should().ContainSingle();
        received[0].Item.Should().Be("y");
        received[0].Index.Should().Be(1); // index before removal
    }

    // ── COL-007 ──────────────────────────────────────────────────────────────

    /// <summary>COL-007: ObservableList ItemReplaced payload shape — newItem, oldItem, index.</summary>
    [Fact, Trait("Conformance", "COL-007")]
    public void COL_007_ItemReplaced_PayloadShape()
    {
        var sut = new ObservableList<string>();
        sut.Add("old");
        sut.Add("other");

        var received = new List<(string NewItem, string OldItem, int Index)>();
        sut.ItemReplaced += (_, e) => received.Add((e.NewItem, e.OldItem, e.Index));

        sut.Replace(0, "new");

        received.Should().ContainSingle();
        received[0].NewItem.Should().Be("new");
        received[0].OldItem.Should().Be("old");
        received[0].Index.Should().Be(0);
    }

    // ── COL-008 ──────────────────────────────────────────────────────────────

    /// <summary>COL-008: ObservableList Count/PropertyChanged ordering after add.</summary>
    [Fact, Trait("Conformance", "COL-008")]
    public void COL_008_CountPropertyChangedOrdering_AfterAdd()
    {
        var sut = new ObservableList<int>();
        var callOrder = new List<string>();

        sut.ItemAdded += (_, _) => callOrder.Add("item_added");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) =>
            callOrder.Add($"property_changed:{e.PropertyName}");

        sut.Add(42);

        // ItemAdded must fire before PropertyChanged("Count") — normative per spec §3.3
        callOrder.Should().Equal("item_added", "property_changed:Count");
    }

    // ── COL-009 ──────────────────────────────────────────────────────────────

    /// <summary>COL-009: ObservableList batch suppression — only Reset fires inside BatchUpdate.</summary>
    [Fact, Trait("Conformance", "COL-009")]
    public void COL_009_BatchSuppression_OnlyResetFires()
    {
        var sut = new ObservableList<int>();

        var granularEvents = new List<string>();
        int resetCount = 0;

        sut.ItemAdded += (_, _) => granularEvents.Add("added");
        sut.ItemRemoved += (_, _) => granularEvents.Add("removed");
        sut.ItemReplaced += (_, _) => granularEvents.Add("replaced");
        sut.Reset += (_, _) => resetCount++;

        using (sut.BatchUpdate())
        {
            sut.Add(1);
            sut.Add(2);
            sut.RemoveAt(0);
            sut.Replace(0, 99);
        }

        granularEvents.Should().BeEmpty();
        resetCount.Should().Be(1);
    }

    // ── COL-023 ──────────────────────────────────────────────────────────────

    /// <summary>COL-023: Batch with count-changing mutations emits Reset then PropertyChanged("Count").</summary>
    [Fact, Trait("Conformance", "COL-023")]
    public void COL_023_BatchEnd_CountNotification_WhenCountChanges()
    {
        var sut = new ObservableList<int>();
        sut.Add(10); // pre-populate: count = 1

        var callOrder = new List<string>();
        int countAtReset = -1;
        int countAtPropertyChanged = -1;

        sut.Reset += (_, _) =>
        {
            countAtReset = sut.Count;
            callOrder.Add("reset");
        };
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(sut.Count))
            {
                countAtPropertyChanged = sut.Count;
                callOrder.Add($"property_changed:{e.PropertyName}");
            }
        };

        // Add two items — count goes from 1 to 3
        using (sut.BatchUpdate())
        {
            sut.Add(20);
            sut.Add(30);
        }

        // Reset fires before PropertyChanged("Count") — ordering is normative
        callOrder.Should().Equal("reset", "property_changed:Count");
        // Count is already updated when both events fire
        countAtReset.Should().Be(3);
        countAtPropertyChanged.Should().Be(3);
    }

    /// <summary>COL-023: Empty batch emits neither Reset nor PropertyChanged("Count").</summary>
    [Fact, Trait("Conformance", "COL-023")]
    public void COL_023_EmptyBatch_EmitsNothing()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);

        var events = new List<string>();
        sut.Reset += (_, _) => events.Add("reset");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => events.Add($"pc:{e.PropertyName}");

        // Empty batch — no mutations
        using (sut.BatchUpdate()) { /* nothing */ }

        events.Should().BeEmpty();
    }

    /// <summary>COL-023: Count-preserving batch (replace only) emits Reset but NOT PropertyChanged("Count").</summary>
    [Fact, Trait("Conformance", "COL-023")]
    public void COL_023_CountPreservingBatch_EmitsResetButNotCountNotification()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);

        var events = new List<string>();
        sut.Reset += (_, _) => events.Add("reset");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => events.Add($"pc:{e.PropertyName}");

        // Only a replace — count stays at 2
        using (sut.BatchUpdate())
        {
            sut.Replace(0, 99);
        }

        // Reset fires because there was a mutation, but no Count notification
        events.Should().Equal("reset");
    }
}
