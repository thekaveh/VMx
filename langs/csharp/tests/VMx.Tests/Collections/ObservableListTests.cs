using System.Collections.Specialized;
using System.ComponentModel;
using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// Unit tests for <see cref="ObservableList{T}"/>.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class ObservableListTests
{
    // ── Basic mutations — no subscribers ─────────────────────────────────────

    [Fact]
    public void Add_IncrementsCount()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        sut.Count.Should().Be(2);
    }

    [Fact]
    public void Insert_PlacesItemAtCorrectPosition()
    {
        var sut = new ObservableList<int>();
        sut.Add(10);
        sut.Add(30);
        sut.Insert(1, 20);
        sut.Should().ContainInOrder(10, 20, 30);
    }

    [Fact]
    public void Remove_ReturnsTrueWhenFound()
    {
        var sut = new ObservableList<string>();
        sut.Add("a");
        sut.Remove("a").Should().BeTrue();
        sut.Count.Should().Be(0);
    }

    [Fact]
    public void Remove_ReturnsFalseWhenNotFound()
    {
        var sut = new ObservableList<string>();
        sut.Remove("nonexistent").Should().BeFalse();
    }

    [Fact]
    public void RemoveAt_RemovesCorrectItem()
    {
        var sut = new ObservableList<int>();
        sut.Add(10);
        sut.Add(20);
        sut.Add(30);
        sut.RemoveAt(1);
        sut.Should().ContainInOrder(10, 30);
    }

    [Fact]
    public void Replace_ChangesItemInPlace()
    {
        var sut = new ObservableList<string>();
        sut.Add("old");
        sut.Replace(0, "new");
        sut[0].Should().Be("new");
        sut.Count.Should().Be(1);
    }

    [Fact]
    public void Clear_EmptiesList()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        sut.Clear();
        sut.Count.Should().Be(0);
    }

    // ── ItemAdded ─────────────────────────────────────────────────────────────

    [Fact]
    public void ItemAdded_FiresOnAdd_WithCorrectPayload()
    {
        var sut = new ObservableList<string>();
        var received = new List<(string Item, int Index)>();
        sut.ItemAdded += (_, e) => received.Add((e.Item, e.Index));

        sut.Add("hello");

        received.Should().ContainSingle().Which.Should().Be(("hello", 0));
    }

    [Fact]
    public void ItemAdded_FiresOnInsert_WithCorrectIndex()
    {
        var sut = new ObservableList<int>();
        sut.Add(10);
        sut.Add(30);
        var received = new List<(int Item, int Index)>();
        sut.ItemAdded += (_, e) => received.Add((e.Item, e.Index));

        sut.Insert(1, 20);

        received.Should().ContainSingle().Which.Should().Be((20, 1));
    }

    [Fact]
    public void ItemAdded_IndexIncrementsCorrectly()
    {
        var sut = new ObservableList<int>();
        var received = new List<(int Item, int Index)>();
        sut.ItemAdded += (_, e) => received.Add((e.Item, e.Index));

        sut.Add(1);
        sut.Add(2);
        sut.Add(3);

        received.Should().HaveCount(3);
        received[0].Should().Be((1, 0));
        received[1].Should().Be((2, 1));
        received[2].Should().Be((3, 2));
    }

    // ── ItemRemoved ───────────────────────────────────────────────────────────

    [Fact]
    public void ItemRemoved_FiresOnRemove_WithCorrectPayload()
    {
        var sut = new ObservableList<string>();
        sut.Add("x");
        var received = new List<(string Item, int Index)>();
        sut.ItemRemoved += (_, e) => received.Add((e.Item, e.Index));

        sut.Remove("x");

        received.Should().ContainSingle().Which.Should().Be(("x", 0));
    }

    [Fact]
    public void ItemRemoved_FiresOnRemoveAt_WithIndexBeforeRemoval()
    {
        var sut = new ObservableList<int>();
        sut.Add(10);
        sut.Add(20);
        sut.Add(30);
        var received = new List<(int Item, int Index)>();
        sut.ItemRemoved += (_, e) => received.Add((e.Item, e.Index));

        sut.RemoveAt(1);

        received.Should().ContainSingle().Which.Should().Be((20, 1));
    }

    [Fact]
    public void ItemRemoved_IndexIsPositionBeforeRemoval()
    {
        var sut = new ObservableList<string>();
        sut.Add("a");
        sut.Add("b");
        sut.Add("c");
        var received = new List<(string Item, int Index)>();
        sut.ItemRemoved += (_, e) => received.Add((e.Item, e.Index));

        sut.Remove("b"); // "b" was at index 1

        received.Should().ContainSingle().Which.Should().Be(("b", 1));
    }

    // ── ItemReplaced ──────────────────────────────────────────────────────────

    [Fact]
    public void ItemReplaced_FiresOnReplace_WithCorrectPayload()
    {
        var sut = new ObservableList<string>();
        sut.Add("old");
        var received = new List<(string NewItem, string OldItem, int Index)>();
        sut.ItemReplaced += (_, e) => received.Add((e.NewItem, e.OldItem, e.Index));

        sut.Replace(0, "new");

        received.Should().ContainSingle().Which.Should().Be(("new", "old", 0));
    }

    [Fact]
    public void ItemReplaced_DoesNotFirePropertyChangedCount()
    {
        var sut = new ObservableList<string>();
        sut.Add("a");
        var propEvents = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propEvents.Add(e.PropertyName);

        sut.Replace(0, "b");

        propEvents.Should().NotContain("Count");
    }

    // ── Reset ─────────────────────────────────────────────────────────────────

    [Fact]
    public void Reset_FiresOnClear()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        int resetCount = 0;
        sut.Reset += (_, _) => resetCount++;

        sut.Clear();

        resetCount.Should().Be(1);
    }

    // ── INotifyCollectionChanged ──────────────────────────────────────────────

    [Fact]
    public void CollectionChanged_FiresOnAdd_WithAddAction()
    {
        var sut = new ObservableList<string>();
        var events = new List<NotifyCollectionChangedEventArgs>();
        ((INotifyCollectionChanged)sut).CollectionChanged += (_, e) => events.Add(e);

        sut.Add("item");

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Add);
    }

    [Fact]
    public void CollectionChanged_FiresOnRemove_WithRemoveAction()
    {
        var sut = new ObservableList<string>();
        sut.Add("item");
        var events = new List<NotifyCollectionChangedEventArgs>();
        ((INotifyCollectionChanged)sut).CollectionChanged += (_, e) => events.Add(e);

        sut.RemoveAt(0);

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Remove);
    }

    [Fact]
    public void CollectionChanged_FiresOnReplace_WithReplaceAction()
    {
        var sut = new ObservableList<string>();
        sut.Add("old");
        var events = new List<NotifyCollectionChangedEventArgs>();
        ((INotifyCollectionChanged)sut).CollectionChanged += (_, e) => events.Add(e);

        sut.Replace(0, "new");

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Replace);
    }

    [Fact]
    public void CollectionChanged_FiresOnClear_WithResetAction()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        var events = new List<NotifyCollectionChangedEventArgs>();
        ((INotifyCollectionChanged)sut).CollectionChanged += (_, e) => events.Add(e);

        sut.Clear();

        events.Should().ContainSingle()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    // ── PropertyChanged("Count") ordering ────────────────────────────────────

    [Fact]
    public void PropertyChangedCount_FiresAfterItemAdded()
    {
        var sut = new ObservableList<int>();
        var callOrder = new List<string>();
        sut.ItemAdded += (_, _) => callOrder.Add("item_added");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) =>
            callOrder.Add($"prop:{e.PropertyName}");

        sut.Add(1);

        callOrder.Should().Equal("item_added", "prop:Count");
    }

    [Fact]
    public void PropertyChangedCount_FiresAfterItemRemoved()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        var callOrder = new List<string>();
        sut.ItemRemoved += (_, _) => callOrder.Add("item_removed");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) =>
            callOrder.Add($"prop:{e.PropertyName}");

        sut.RemoveAt(0);

        callOrder.Should().Equal("item_removed", "prop:Count");
    }

    // ── BatchUpdate ───────────────────────────────────────────────────────────

    [Fact]
    public void BatchUpdate_SuppressesGranularEvents_FiresOneReset()
    {
        var sut = new ObservableList<int>();
        var granular = new List<string>();
        int resetCount = 0;

        sut.ItemAdded += (_, _) => granular.Add("added");
        sut.ItemRemoved += (_, _) => granular.Add("removed");
        sut.ItemReplaced += (_, _) => granular.Add("replaced");
        sut.Reset += (_, _) => resetCount++;

        using (sut.BatchUpdate())
        {
            sut.Add(1);
            sut.Add(2);
            sut.RemoveAt(0);
            sut.Replace(0, 99);
        }

        granular.Should().BeEmpty();
        resetCount.Should().Be(1);
    }

    [Fact]
    public void BatchUpdate_WithNoMutations_FiresNoReset()
    {
        var sut = new ObservableList<int>();
        int resetCount = 0;
        sut.Reset += (_, _) => resetCount++;

        using (sut.BatchUpdate()) { /* no mutations */ }

        resetCount.Should().Be(0);
    }

    [Fact]
    public void BatchUpdate_Nested_FiresResetOnlyOnOutermostDispose()
    {
        var sut = new ObservableList<int>();
        var granular = new List<string>();
        int resetCount = 0;

        sut.ItemAdded += (_, _) => granular.Add("added");
        sut.Reset += (_, _) => resetCount++;

        using (var outer = sut.BatchUpdate())
        {
            sut.Add(1);
            using (var inner = sut.BatchUpdate())
            {
                sut.Add(2);
            }
            // inner disposed — no reset yet
            resetCount.Should().Be(0);
            granular.Should().BeEmpty();
        }
        // outer disposed — one reset
        resetCount.Should().Be(1);
        granular.Should().BeEmpty();
    }

    [Fact]
    public void AfterBatch_NormalEventsResume()
    {
        var sut = new ObservableList<int>();
        var received = new List<(int Item, int Index)>();
        sut.ItemAdded += (_, e) => received.Add((e.Item, e.Index));

        using (sut.BatchUpdate()) { sut.Add(1); }

        sut.Add(2);

        received.Should().ContainSingle().Which.Should().Be((2, 1));
    }

    [Fact]
    public void BatchUpdate_CollectionChanged_FiresResetOnBatchExit()
    {
        var sut = new ObservableList<int>();
        var collectionEvents = new List<NotifyCollectionChangedAction>();
        ((INotifyCollectionChanged)sut).CollectionChanged += (_, e) =>
            collectionEvents.Add(e.Action);

        using (sut.BatchUpdate())
        {
            sut.Add(1);
            sut.Add(2);
        }

        collectionEvents.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    // ── BatchUpdate Count notification (spec §3.3) ────────────────────────────

    [Fact]
    public void BatchUpdate_CountGrew_EmitsPropertyChangedCount()
    {
        var sut = new ObservableList<int>();
        var propChanges = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propChanges.Add(e.PropertyName);

        using (sut.BatchUpdate())
        {
            sut.Add(1);
            sut.Add(2);
        }

        propChanges.Should().Contain("Count");
    }

    [Fact]
    public void BatchUpdate_CountShrank_EmitsPropertyChangedCount()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        sut.Add(3);
        var propChanges = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propChanges.Add(e.PropertyName);

        using (sut.BatchUpdate())
        {
            sut.RemoveAt(0);
            sut.RemoveAt(0);
        }

        propChanges.Should().Contain("Count");
    }

    [Fact]
    public void BatchUpdate_CountUnchanged_DoesNotEmitPropertyChangedCount()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        var propChanges = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propChanges.Add(e.PropertyName);

        // Replace operations keep count the same; net change = 0.
        using (sut.BatchUpdate())
        {
            sut.Replace(0, 10);
            sut.Replace(1, 20);
        }

        propChanges.Where(p => p == "Count").Should().BeEmpty();
    }

    [Fact]
    public void BatchUpdate_AddAndRemoveNetZero_DoesNotEmitPropertyChangedCount()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        var propChanges = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propChanges.Add(e.PropertyName);

        // Add one, remove one — net count change = 0.
        using (sut.BatchUpdate())
        {
            sut.Add(99);
            sut.RemoveAt(1);
        }

        propChanges.Where(p => p == "Count").Should().BeEmpty();
    }

    [Fact]
    public void BatchUpdate_Nested_CountChanged_EmitsPropertyChangedCountOnOutermostExit()
    {
        var sut = new ObservableList<int>();
        var propChanges = new List<string?>();
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) => propChanges.Add(e.PropertyName);

        using (var outer = sut.BatchUpdate())
        {
            using (var inner = sut.BatchUpdate())
            {
                sut.Add(1);
            }
            // inner disposed — no Count notification yet
            propChanges.Where(p => p == "Count").Should().BeEmpty();
        }

        // outermost disposed — Count changed (0 → 1), so notification fires
        propChanges.Should().Contain("Count");
    }

    // ── Edge cases ────────────────────────────────────────────────────────────

    [Fact]
    public void DuplicateItems_Remove_RemovesFirstOccurrence()
    {
        var sut = new ObservableList<string>();
        sut.Add("dup");
        sut.Add("dup");
        var received = new List<(string Item, int Index)>();
        sut.ItemRemoved += (_, e) => received.Add((e.Item, e.Index));

        sut.Remove("dup");

        sut.Should().ContainSingle().Which.Should().Be("dup");
        received.Should().ContainSingle().Which.Should().Be(("dup", 0));
    }

    [Fact]
    public void Indexer_ReturnsCorrectItem()
    {
        var sut = new ObservableList<int>();
        sut.Add(10);
        sut.Add(20);
        sut[0].Should().Be(10);
        sut[1].Should().Be(20);
    }

    [Fact]
    public void IsEnumerable()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        sut.Add(2);
        sut.Should().ContainInOrder(1, 2);
    }
}
