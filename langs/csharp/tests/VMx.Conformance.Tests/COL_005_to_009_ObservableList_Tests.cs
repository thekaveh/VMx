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
}
