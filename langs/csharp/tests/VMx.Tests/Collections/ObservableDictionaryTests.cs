using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// Unit tests for <see cref="ObservableDictionary{TKey1,TKey2,TValue}"/>.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class ObservableDictionaryTests
{
    // ── Basic CRUD — no subscribers ───────────────────────────────────────────

    [Fact]
    public void Add_IncrementsCount()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("b", 2, 2.0);
        sut.Count.Should().Be(2);
    }

    [Fact]
    public void Add_DuplicateKey_ThrowsArgumentException()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Invoking(d => d.Add("a", 1, 9.9))
           .Should().Throw<ArgumentException>();
    }

    [Fact]
    public void Remove_ExistingEntry_ReturnsTrue_AndDecrementsCount()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Remove("a", 1).Should().BeTrue();
        sut.Count.Should().Be(0);
    }

    [Fact]
    public void Remove_MissingEntry_ReturnsFalse()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Remove("x", 99).Should().BeFalse();
    }

    [Fact]
    public void ContainsKey_TrueAfterAdd_FalseAfterRemove()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.ContainsKey("a", 1).Should().BeTrue();
        sut.Remove("a", 1);
        sut.ContainsKey("a", 1).Should().BeFalse();
    }

    [Fact]
    public void Indexer_Get_ThrowsKeyNotFound_WhenAbsent()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Invoking(d => _ = d["missing", 99])
           .Should().Throw<KeyNotFoundException>();
    }

    [Fact]
    public void Indexer_Set_AddsEntry_WhenNotPresent()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut["a", 1] = 5.5;
        sut.ContainsKey("a", 1).Should().BeTrue();
        sut["a", 1].Should().Be(5.5);
    }

    [Fact]
    public void Indexer_Set_ReplacesValue_WhenPresent()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut["a", 1] = 9.9;
        sut["a", 1].Should().Be(9.9);
        sut.Count.Should().Be(1);
    }

    [Fact]
    public void TryGetValue_TrueAndValue_WhenPresent()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 42.0);
        sut.TryGetValue("a", 1, out double val).Should().BeTrue();
        val.Should().Be(42.0);
    }

    [Fact]
    public void TryGetValue_False_WhenAbsent()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.TryGetValue("missing", 99, out _).Should().BeFalse();
    }

    // ── Hub injection ─────────────────────────────────────────────────────────

    [Fact]
    public void Hub_Injection_PublishesAddMessageOnAdd()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);
        var received = new List<IMessage>();
        hub.Messages.Subscribe(m => received.Add(m));

        sut.Add("a", 1, 42.0);

        received.Should().ContainSingle()
            .Which.Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Add);
    }

    [Fact]
    public void Hub_Add_Index_Is_Captured_Before_A_Reentrant_Add()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);
        var indices = new Dictionary<string, int>();
        hub.Messages.Subscribe(m =>
        {
            var change = (ICollectionChangedMessage<KeyValuePair<(string, int), double>>)m;
            foreach (var item in change.NewItems) indices[item.Key.Item1] = change.Index;
        });
        sut.ItemAdded += (_, e) =>
        {
            if (e.Key1 == "a") sut.Add("b", 2, 2.0);
        };

        sut.Add("a", 1, 1.0);

        indices.Should().BeEquivalentTo(new Dictionary<string, int> { ["a"] = 0, ["b"] = 1 });
    }

    // #733: a key-view handler runs before the hub publication.
    [Theory]
    [InlineData("Keys1")]
    [InlineData("Keys2")]
    public void Hub_Add_Index_Is_Captured_Before_A_Key_View_Reentrant_Add(string view)
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, string, int>(hub);
        var indices = new Dictionary<string, int>();
        hub.Messages.Subscribe(m =>
        {
            var change = (ICollectionChangedMessage<KeyValuePair<(string, string), int>>)m;
            foreach (var item in change.NewItems) indices[item.Key.Item1] = change.Index;
        });
        var nested = false;
        EventHandler<ItemAddedEventArgs<string>> addNested = (_, _) =>
        {
            if (nested) return;
            nested = true;
            sut.Add("z", "z", 1);
        };
        if (view == "Keys1") sut.Keys1.ItemAdded += addNested;
        else sut.Keys2.ItemAdded += addNested;

        sut.Add("a", "a", 0);

        indices.Should().BeEquivalentTo(new Dictionary<string, int> { ["a"] = 0, ["z"] = 1 });
    }

    [Theory]
    [InlineData("Remove", 0)]
    [InlineData("Clear", -1)]
    public void Hub_Add_Index_Follows_A_Key_View_Reentrant_Remove_Or_Clear(string nested, int expected)
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, string, int>(hub);
        sut.Add("x", "x", 9);
        var indices = new Dictionary<string, int>();
        hub.Messages.Subscribe(m =>
        {
            var change = (ICollectionChangedMessage<KeyValuePair<(string, string), int>>)m;
            foreach (var item in change.NewItems) indices[item.Key.Item1] = change.Index;
        });
        var done = false;
        sut.Keys1.ItemAdded += (_, _) =>
        {
            if (done) return;
            done = true;
            if (nested == "Remove") sut.Remove("x", "x");
            else sut.Clear();
        };

        sut.Add("a", "a", 0);

        indices.Should().BeEquivalentTo(new Dictionary<string, int> { ["a"] = expected });
    }

    // #772: an entry added from a key-view handler keeps both views in
    // first-appearance order.
    [Theory]
    [InlineData("Keys1")]
    [InlineData("Keys2")]
    public void Key_Views_Keep_First_Appearance_Order_After_A_Key_View_Reentrant_Add(string view)
    {
        var sut = new ObservableDictionary<string, int, string>();
        var nested = false;
        void AddNested()
        {
            if (nested) return;
            nested = true;
            sut.Add("b", 2, "nested");
        }
        if (view == "Keys1") sut.Keys1.ItemAdded += (_, _) => AddNested();
        else sut.Keys2.ItemAdded += (_, _) => AddNested();

        sut.Add("a", 1, "outer");

        sut.Keys1.Should().Equal("a", "b");
        sut.Keys2.Should().Equal(1, 2);
    }

    // Runs nested once, from the Keys2 handler for key2 1, then adds (a, 1).
    private static void AddFromAKeys2Handler(ObservableDictionary<string, int, string> sut, Action nested)
    {
        var done = false;
        sut.Keys2.ItemAdded += (_, e) =>
        {
            if (done || e.Item != 1) return;
            done = true;
            nested();
        };
        sut.Add("a", 1, "outer");
    }

    [Fact]
    public void Key_Views_Stay_Empty_When_A_Keys2_Handler_Removes_The_New_Entry()
    {
        var sut = new ObservableDictionary<string, int, string>();

        AddFromAKeys2Handler(sut, () => sut.Remove("a", 1));

        sut.Count.Should().Be(0);
        sut.Keys1.Should().BeEmpty();
        sut.Keys2.Should().BeEmpty();
    }

    [Fact]
    public void Keys1_Lists_A_Pending_Key1_Before_A_Key_That_A_Keys2_Handler_Adds()
    {
        var sut = new ObservableDictionary<string, int, string>();
        sut.Add("x", 0, "first");

        AddFromAKeys2Handler(sut, () =>
        {
            sut.Add("c", 5, "nested");
            sut.Add("a", 3, "nested");
        });

        sut.Keys1.Should().Equal("x", "a", "c");
        sut.Keys2.Should().Equal(0, 1, 5, 3);
    }

    [Fact]
    public void Keys1_Keeps_Its_Order_When_A_Keys2_Handler_Moves_A_Key1_Later()
    {
        var sut = new ObservableDictionary<string, int, string>();
        sut.Add("x", 0, "first");
        sut.Add("y", 2, "second");

        AddFromAKeys2Handler(sut, () =>
        {
            sut.Add("x", 4, "nested");
            sut.Remove("x", 0);
        });

        sut.Keys1.Should().Equal("x", "y", "a");
        sut.Keys2.Should().Equal(2, 1, 4);
    }

    [Fact]
    public void Keys2_Contains_The_New_Key2_When_Keys1_Notifies()
    {
        var sut = new ObservableDictionary<string, int, string>();
        int[]? seen = null;
        sut.Keys1.ItemAdded += (_, _) => seen = [.. sut.Keys2];

        sut.Add("a", 1, "outer");

        seen.Should().Equal(1);
    }

    // #1075: an entry added from a key-view Reset handler during Clear keeps
    // both views equal to the keys of the remaining entries.
    [Theory]
    [InlineData("Keys1")]
    [InlineData("Keys2")]
    public void Key_Views_Match_The_Entries_After_A_Key_View_Reset_Handler_Adds_During_Clear(string view)
    {
        var sut = new ObservableDictionary<string, string, string>();
        sut.Add("a", "a", "outer");
        var done = false;
        void AddNested(object? sender, EventArgs e)
        {
            if (done) return;
            done = true;
            sut.Add("b", "b", "nested");
        }
        if (view == "Keys1") sut.Keys1.Reset += AddNested;
        else sut.Keys2.Reset += AddNested;

        sut.Clear();

        sut.Select(e => e.Key).Should().Equal(("b", "b"));
        sut.Keys1.Should().Equal("b");
        sut.Keys2.Should().Equal("b");

        sut.Remove("b", "b");

        sut.Count.Should().Be(0);
        sut.Keys1.Should().BeEmpty();
        sut.Keys2.Should().BeEmpty();
    }

    // #1075: an entry added or removed from a key-view ItemRemoved handler
    // during Remove keeps both views equal to the distinct keys of the entries.
    // Keys1 never lists a key twice, also while a handler runs.
    [Theory]
    [InlineData("Keys1", "Add", "b,c,a", "y,z,x")]
    [InlineData("Keys1", "Remove", "c", "z")]
    [InlineData("Keys2", "Add", "b,c,a", "y,z,x")]
    [InlineData("Keys2", "Remove", "c", "z")]
    public void Key_Views_Match_The_Entries_After_A_Key_View_Handler_Changes_Them_During_Remove(
        string view, string nested, string keys1, string keys2)
    {
        var sut = new ObservableDictionary<string, string, string>();
        sut.Add("a", "x", "outer");
        sut.Add("b", "y", "kept");
        sut.Add("c", "z", "kept");
        var done = false;
        void ChangeNested(object? sender, ItemRemovedEventArgs<string> e)
        {
            if (done) return;
            done = true;
            if (nested == "Add") sut.Add("a", "x", "nested");
            else sut.Remove("b", "y");
        }
        if (view == "Keys1") sut.Keys1.ItemRemoved += ChangeNested;
        else sut.Keys2.ItemRemoved += ChangeNested;
        var snapshots = new List<string[]>();
        sut.Keys1.ItemAdded += (_, _) => snapshots.Add([.. sut.Keys1]);

        sut.Remove("a", "x");

        var entries = sut.Select(e => e.Key).ToList();
        entries.Select(k => k.Item1).Distinct().Should().Equal(keys1.Split(','));
        entries.Select(k => k.Item2).Distinct().Should().Equal(keys2.Split(','));
        sut.Keys1.Should().Equal(keys1.Split(','));
        sut.Keys2.Should().Equal(keys2.Split(','));
        snapshots.Should().NotContain(keys => keys.Distinct().Count() != keys.Length);
    }

    // #1075: Remove and Clear update Keys2 first, as Add does, so a Keys1
    // handler already reads the updated Keys2.
    [Fact]
    public void Keys2_Is_Updated_When_Keys1_Notifies_A_Remove_Or_A_Clear()
    {
        var sut = new ObservableDictionary<string, string, string>();
        sut.Add("a", "a", "first");
        sut.Add("b", "b", "second");
        var seen = new List<string[]>();
        sut.Keys1.ItemRemoved += (_, _) => seen.Add([.. sut.Keys2]);
        sut.Keys1.Reset += (_, _) => seen.Add([.. sut.Keys2]);

        sut.Remove("a", "a");
        sut.Clear();

        seen.Should().HaveCount(2);
        seen[0].Should().Equal("b");
        seen[1].Should().BeEmpty();
    }

    [Theory]
    [InlineData("Remove")]
    [InlineData("Clear")]
    public void Key_Views_Stay_In_Step_When_A_Keys2_Handler_Throws(string operation)
    {
        // #1075: Keys1 is updated even when a Keys2 handler throws during the
        // Keys2 notification, so a later add does not list a key twice.
        var sut = new ObservableDictionary<string, string, string>();
        sut.Add("a", "x", "first");
        var failing = true;
        sut.Keys2.ItemRemoved += (_, _) =>
        {
            if (failing) throw new InvalidOperationException("keys2 handler failed");
        };
        sut.Keys2.Reset += (_, _) =>
        {
            if (failing) throw new InvalidOperationException("keys2 handler failed");
        };

        var act = operation == "Remove" ? (Action)(() => sut.Remove("a", "x")) : sut.Clear;
        act.Should().Throw<InvalidOperationException>().WithMessage("keys2 handler failed");
        failing = false;

        sut.Keys1.Should().BeEmpty();
        sut.Add("a", "y", "again");
        sut.Keys1.Should().Equal("a");
        sut.Remove("a", "y");
        sut.Keys1.Should().BeEmpty();
        sut.Keys2.Should().BeEmpty();
        sut.Count.Should().Be(0);
    }

    [Fact]
    public void Hub_Injection_PublishesRemoveMessageOnRemove()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);
        sut.Add("a", 1, 1.0);
        var received = new List<IMessage>();
        hub.Messages.Subscribe(m => received.Add(m));

        sut.Remove("a", 1);

        received.Should().ContainSingle()
            .Which.Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Remove);
    }

    [Fact]
    public void Hub_Injection_PublishesReplaceMessageOnIndexerSet()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);
        sut.Add("a", 1, 1.0);
        var received = new List<IMessage>();
        hub.Messages.Subscribe(m => received.Add(m));

        sut["a", 1] = 9.9;

        received.Should().ContainSingle()
            .Which.Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Replace);
    }

    [Fact]
    public void Hub_Injection_PublishesResetMessageOnClear()
    {
        using var hub = new MessageHub();
        var sut = new ObservableDictionary<string, int, double>(hub);
        sut.Add("a", 1, 1.0);
        var received = new List<IMessage>();
        hub.Messages.Subscribe(m => received.Add(m));

        sut.Clear();

        received.Should().ContainSingle()
            .Which.Should().BeAssignableTo<ICollectionChangedMessage<KeyValuePair<(string, int), double>>>()
            .Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void Hub_Null_DoesNotThrowOnAnyMutation()
    {
        var sut = new ObservableDictionary<string, int, double>();
        var act = () =>
        {
            sut.Add("a", 1, 1.0);
            sut["a", 1] = 2.0;
            sut.Remove("a", 1);
            sut.Add("b", 2, 3.0);
            sut.Clear();
        };
        act.Should().NotThrow();
    }

    [Fact]
    public void Clear_EmptiesDictionaryAndKeyViews()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("b", 2, 2.0);
        sut.Clear();
        sut.Count.Should().Be(0);
        sut.Keys1.Count.Should().Be(0);
        sut.Keys2.Count.Should().Be(0);
    }

    // ── Null-key guard ────────────────────────────────────────────────────────

    [Fact]
    public void NullKey1_ThrowsArgumentNullException()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Invoking(d => d.Add(null!, 1, 0.0))
           .Should().Throw<ArgumentNullException>();
    }

    // ── Distinct-key views ────────────────────────────────────────────────────

    [Fact]
    public void Keys1_ContainsDistinctKey1Values()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("a", 2, 2.0);
        sut.Add("b", 3, 3.0);
        sut.Keys1.Count.Should().Be(2);
        sut.Keys1.Should().Contain("a").And.Contain("b");
    }

    [Fact]
    public void Keys2_ContainsDistinctKey2Values()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("b", 1, 2.0);
        sut.Add("c", 2, 3.0);
        sut.Keys2.Count.Should().Be(2);
        sut.Keys2.Should().Contain(1).And.Contain(2);
    }

    [Fact]
    public void Keys1_DropsKey_WhenLastEntryForThatKeyIsRemoved()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("a", 2, 2.0);
        sut.Remove("a", 1);
        sut.Keys1.Should().Contain("a"); // still has ("a",2)
        sut.Remove("a", 2);
        sut.Keys1.Should().NotContain("a");
    }

    [Fact]
    public void Keys1_InsertionOrder_IsPreserved()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("c", 1, 1.0);
        sut.Add("a", 2, 2.0);
        sut.Add("b", 3, 3.0);
        sut.Keys1.ToArray().Should().ContainInOrder("c", "a", "b");
    }

    // ── Events ────────────────────────────────────────────────────────────────

    [Fact]
    public void ItemAdded_FiresOnAdd_WithCorrectPayload()
    {
        var sut = new ObservableDictionary<string, int, double>();
        var events = new List<(string K1, int K2, double V)>();
        sut.ItemAdded += (_, e) => events.Add((e.Key1, e.Key2, e.Value));

        sut.Add("a", 1, 7.7);

        events.Should().ContainSingle().Which.Should().Be(("a", 1, 7.7));
    }

    [Fact]
    public void ItemRemoved_FiresOnRemove_WithCorrectPayload()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 7.7);
        var events = new List<(string K1, int K2, double V)>();
        sut.ItemRemoved += (_, e) => events.Add((e.Key1, e.Key2, e.Value));

        sut.Remove("a", 1);

        events.Should().ContainSingle().Which.Should().Be(("a", 1, 7.7));
    }

    [Fact]
    public void ItemReplaced_FiresOnIndexerSet_WithOldAndNewValues()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        var events = new List<(double NewV, double OldV)>();
        sut.ItemReplaced += (_, e) => events.Add((e.NewValue, e.OldValue));

        sut["a", 1] = 9.9;

        events.Should().ContainSingle().Which.Should().Be((9.9, 1.0));
    }

    [Fact]
    public void Reset_FiresOnClear()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        int resetCount = 0;
        sut.Reset += (_, _) => resetCount++;

        sut.Clear();

        resetCount.Should().Be(1);
    }

    [Fact]
    public void CollectionChanged_FiresAdd_OnAdd()
    {
        var sut = new ObservableDictionary<string, int, double>();
        var actions = new List<NotifyCollectionChangedAction>();
        sut.CollectionChanged += (_, e) => actions.Add(e.Action);

        sut.Add("a", 1, 1.0);

        actions.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Add);
    }

    [Fact]
    public void CollectionChanged_FiresRemove_OnRemove()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        var actions = new List<NotifyCollectionChangedAction>();
        sut.CollectionChanged += (_, e) => actions.Add(e.Action);

        sut.Remove("a", 1);

        actions.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Remove);
    }

    [Fact]
    public void CollectionChanged_FiresReplace_OnIndexerSet()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        var actions = new List<NotifyCollectionChangedAction>();
        sut.CollectionChanged += (_, e) => actions.Add(e.Action);

        sut["a", 1] = 9.9;

        actions.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Replace);
    }

    [Fact]
    public void CollectionChanged_FiresReset_OnClear()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        var actions = new List<NotifyCollectionChangedAction>();
        sut.CollectionChanged += (_, e) => actions.Add(e.Action);

        sut.Clear();

        actions.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    // ── Enumeration ───────────────────────────────────────────────────────────

    [Fact]
    public void Enumeration_YieldsAllEntries_InInsertionOrder()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.1);
        sut.Add("b", 2, 2.2);
        sut.Add("c", 3, 3.3);

        var entries = sut.ToList();
        entries.Should().HaveCount(3);
        entries[0].Should().Be(new KeyValuePair<(string, int), double>(("a", 1), 1.1));
        entries[1].Should().Be(new KeyValuePair<(string, int), double>(("b", 2), 2.2));
        entries[2].Should().Be(new KeyValuePair<(string, int), double>(("c", 3), 3.3));
    }

    [Fact]
    public void Enumeration_Empty_YieldsNoEntries()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Should().BeEmpty();
    }

    // ── Edge cases ────────────────────────────────────────────────────────────

    [Fact]
    public void Keys1_ObservableList_FiresItemAdded_OnNewKey1()
    {
        var sut = new ObservableDictionary<string, int, double>();
        var keys1Added = new List<string>();
        sut.Keys1.ItemAdded += (_, e) => keys1Added.Add(e.Item);

        sut.Add("x", 1, 1.0);
        sut.Add("x", 2, 2.0); // same Key1 — no new event

        keys1Added.Should().ContainSingle().Which.Should().Be("x");
    }

    [Fact]
    public void Keys2_ObservableList_FiresItemRemoved_WhenLastEntryForKey2Removed()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 5, 1.0);
        var keys2Removed = new List<int>();
        sut.Keys2.ItemRemoved += (_, e) => keys2Removed.Add(e.Item);

        sut.Remove("a", 5);

        keys2Removed.Should().ContainSingle().Which.Should().Be(5);
    }

    [Fact]
    public void Clear_DoesNotFireIndividualItemRemovedEvents()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("a", 1, 1.0);
        sut.Add("b", 2, 2.0);
        sut.Add("c", 3, 3.0);
        var removedEvents = new List<string>();
        sut.ItemRemoved += (_, _) => removedEvents.Add("removed");

        sut.Clear();

        removedEvents.Should().BeEmpty("Clear must NOT fire per-entry ItemRemoved events per ADR-0026 batch semantics");
    }

    [Fact]
    public void Keys1_InsertionOrderPreserved_AfterRemovesAndReAdds()
    {
        var sut = new ObservableDictionary<string, int, double>();
        sut.Add("b", 1, 1.0);
        sut.Add("a", 2, 2.0);
        sut.Remove("b", 1);
        sut.Add("c", 3, 3.0);

        // "b" removed, "a" and "c" remain
        sut.Keys1.Should().ContainInOrder("a", "c");
    }

    [Fact]
    public void TryGetValue_Miss_ReturnsFalse_And_DefaultValue_VMX071()
    {
        // With [MaybeNullWhen(false)] the out value is default(TValue) on a miss —
        // null for a reference TValue — and the hit branch is non-null (VMX-071).
        var sut = new ObservableDictionary<string, int, string>();
        sut.Add("a", 1, "x");

        sut.TryGetValue("a", 1, out var hit).Should().BeTrue();
        hit.Should().Be("x");

        sut.TryGetValue("missing", 99, out var miss).Should().BeFalse();
        miss.Should().BeNull("a TryGetValue miss yields default(TValue)");
    }
}
