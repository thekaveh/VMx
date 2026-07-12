using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-056..COL-064 — keyed serviced collection parity.
/// </summary>
public class COL_056_to_064_KeyedServicedObservableCollectionTests
{
    [Fact, Trait("Conformance", "COL-056")]
    public void COL_056_LookupUsesCapturedKeysAndPreservesOrder()
    {
        var projections = new List<string>();
        var a = new Item("a", "A");
        var b = new Item("b", "B");
        var c = new Item("c", "C");
        var sut = new KeyedServicedObservableCollection<string, Item>(item =>
        {
            projections.Add(item.Key);
            return item.Key;
        }) { a, b, c };

        sut.TryGetValue("a", out var foundA).Should().BeTrue();
        foundA.Should().BeSameAs(a);
        sut.ContainsKey("b").Should().BeTrue();
        sut.TryGetValue("c", out var foundC).Should().BeTrue();
        foundC.Should().BeSameAs(c);
        sut.Should().Equal(a, b, c);
        sut.ToArray().Should().Equal(a, b, c);
        projections.Should().Equal("a", "b", "c");

        b.Key = "changed";

        sut.TryGetValue("b", out var foundB).Should().BeTrue();
        foundB.Should().BeSameAs(b);
        sut.ContainsKey("changed").Should().BeFalse();
        sut.TryGetValue("missing", out var missing).Should().BeFalse();
        missing.Should().BeNull();
        projections.Should().Equal("a", "b", "c");
    }

    [Fact, Trait("Conformance", "COL-057")]
    public void COL_057_DuplicateAndProjectionFailuresAreAtomic()
    {
        var hub = new TestHub();
        var sut = new KeyedServicedObservableCollection<string, Item>(
            item => item.Key == "boom" ? throw new ProjectorException() : item.Key,
            hub) { new("a", "A"), new("b", "B") };
        var local = ObserveLocal(sut);
        var messages = ObserveHub(hub);

        Action duplicateAdd = () => sut.Add(new Item("a", "duplicate"));
        Action duplicateInsert = () => sut.Insert(1, new Item("b", "duplicate"));
        Action duplicateReplace = () => sut[0] = new Item("b", "duplicate");
        Action duplicateReset = () => sut.ReplaceAll(new[]
        {
            new Item("x", "X"),
            new Item("x", "duplicate"),
        });
        Action projectorFailure = () => sut.Add(new Item("boom", "failure"));

        duplicateAdd.Should().Throw<ArgumentException>();
        duplicateInsert.Should().Throw<ArgumentException>();
        duplicateReplace.Should().Throw<ArgumentException>();
        duplicateReset.Should().Throw<ArgumentException>();
        projectorFailure.Should().Throw<ProjectorException>();
        sut.Select(item => item.Key).Should().Equal("a", "b");
        sut.ContainsKey("a").Should().BeTrue();
        sut.ContainsKey("b").Should().BeTrue();
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-058")]
    public void COL_058_UpsertAddsOrReplacesAtStablePosition()
    {
        var hub = new TestHub();
        var a = new Item("a", "A");
        var b = new Item("b", "B");
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub)
        {
            a,
            b,
        };
        var local = ObserveLocal(sut);
        var messages = ObserveHub(hub);
        local.Clear();
        messages.Clear();
        sut.CollectionChanged += (_, _) => AssertLookupMatchesOrder(sut);
        hub.Messages.Subscribe(_ => AssertLookupMatchesOrder(sut));

        sut.Upsert(new Item("c", "C")).Should().BeTrue();

        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Add);
        AssertMessage(messages.Single(), NotifyCollectionChangedAction.Add, 2, -1, 2);
        local.Clear();
        messages.Clear();

        var b2 = new Item("b", "B2");
        sut.Upsert(b2).Should().BeFalse();

        sut.Should().Equal(a, b2, sut[2]);
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        var replacement = AssertMessage(
            messages.Single(), NotifyCollectionChangedAction.Replace, 1, 1, 1);
        replacement.OldItems.Should().ContainSingle().Which.Should().BeSameAs(b);
        replacement.NewItems.Should().ContainSingle().Which.Should().BeSameAs(b2);
        local.Clear();
        messages.Clear();

        sut.Upsert(b2).Should().BeFalse();

        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        messages.Should().ContainSingle();
    }

    [Fact, Trait("Conformance", "COL-059")]
    public void COL_059_KeyedDeletionUsesPreRemovalPositionAndMissingIsNoOp()
    {
        var hub = new TestHub();
        var a = new Item("a", "A");
        var b = new Item("b", "B");
        var c = new Item("c", "C");
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub)
        {
            a,
            b,
            c,
        };
        var local = ObserveLocal(sut);
        var messages = ObserveHub(hub);

        sut.RemoveKey("b").Should().BeTrue();

        sut.Should().Equal(a, c);
        sut.ContainsKey("b").Should().BeFalse();
        local.Should().ContainSingle().Which.OldStartingIndex.Should().Be(1);
        var removal = AssertMessage(messages.Single(), NotifyCollectionChangedAction.Remove, 1, 1, -1);
        removal.OldItems.Should().ContainSingle().Which.Should().BeSameAs(b);
        local.Clear();
        messages.Clear();

        sut.RemoveKey("missing").Should().BeFalse();

        sut.Should().Equal(a, c);
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-060")]
    public void COL_060_RemovalAndExplicitRekeyKeepCapturedIndexSynchronized()
    {
        var first = new Item("a", "equal");
        var second = new Item("b", "equal");
        var third = new Item("c", "other");
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key)
        {
            first,
            second,
            third,
        };

        sut.Remove(new Item("unused", "equal")).Should().BeTrue();
        sut.ContainsKey("a").Should().BeFalse();
        sut.TryGetValue("b", out var foundB).Should().BeTrue();
        foundB.Should().BeSameAs(second);
        sut.RemoveAt(1);
        sut.ContainsKey("c").Should().BeFalse();

        second.Key = "rekeyed";
        sut[0] = second;
        sut.ContainsKey("b").Should().BeFalse();
        sut.TryGetValue("rekeyed", out var rekeyed).Should().BeTrue();
        rekeyed.Should().BeSameAs(second);

        sut.Add(new Item("other", "other"));
        second.Key = "other";
        Action duplicateRekey = () => sut[0] = second;
        duplicateRekey.Should().Throw<ArgumentException>();
        sut.ContainsKey("rekeyed").Should().BeTrue();
        sut[0].Should().BeSameAs(second);

        var shared = new Item("old", "shared");
        var aliasing = new KeyedServicedObservableCollection<string, Item>(item => item.Key)
        {
            shared,
        };
        shared.Key = "new";
        aliasing.Upsert(shared).Should().BeTrue();
        aliasing.Should().HaveCount(2);
        aliasing.TryGetValue("old", out var oldMembership).Should().BeTrue();
        aliasing.TryGetValue("new", out var newMembership).Should().BeTrue();
        oldMembership.Should().BeSameAs(shared);
        newMembership.Should().BeSameAs(shared);
    }

    [Fact, Trait("Conformance", "COL-061")]
    public void COL_061_ReplaceAllPreflightsKeysAndSelfInput()
    {
        var hub = new TestHub();
        var sut = new KeyedServicedObservableCollection<string, Item>(
            item => item.Key == "boom" ? throw new ProjectorException() : item.Key,
            hub) { new("a", "A"), new("b", "B") };
        var local = ObserveLocal(sut);
        var messages = ObserveHub(hub);

        sut.ReplaceAll(new[] { new Item("c", "C"), new Item("d", "D") });
        sut.Select(item => item.Key).Should().Equal("c", "d");
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        messages.Should().ContainSingle();
        local.Clear();
        messages.Clear();

        sut.ReplaceAll(sut);
        sut.Select(item => item.Key).Should().Equal("c", "d");
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        messages.Should().ContainSingle();
        local.Clear();
        messages.Clear();

        Action duplicate = () => sut.ReplaceAll(new[]
        {
            new Item("x", "X"),
            new Item("x", "duplicate"),
        });
        Action projection = () => sut.ReplaceAll(new[] { new Item("boom", "failure") });
        Action enumeration = () => sut.ReplaceAll(ThrowDuringEnumeration());
        duplicate.Should().Throw<ArgumentException>();
        projection.Should().Throw<ProjectorException>();
        enumeration.Should().Throw<InvalidOperationException>().WithMessage("enumeration failed");
        sut.Select(item => item.Key).Should().Equal("c", "d");
        sut.ContainsKey("c").Should().BeTrue();
        sut.ContainsKey("d").Should().BeTrue();
        local.Should().BeEmpty();
        messages.Should().BeEmpty();

        var empty = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub);
        var emptyLocal = ObserveLocal(empty);
        empty.ReplaceAll(Array.Empty<Item>());
        emptyLocal.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-062")]
    public void COL_062_MoveClearAndConveniencesPreserveIndexAndOwnership()
    {
        var hub = new TestHub();
        var a = new Item("a", "A");
        var b = new Item("b", "B");
        var c = new Item("c", "C");
        var d = new Item("d", "D");
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub)
        {
            a,
            c,
        };
        var local = ObserveLocal(sut);
        var messages = ObserveHub(hub);

        sut.Insert(1, b);
        sut.Add(d);
        sut.Move(0, 3);
        sut.Should().Equal(b, c, d, a);
        AssertLookupMatchesOrder(sut);
        AssertMessage(messages[^1], NotifyCollectionChangedAction.Move, 3, 0, 3);
        local.Clear();
        messages.Clear();

        sut.Move(2, 2);
        local.Should().BeEmpty();
        messages.Should().BeEmpty();

        sut.Clear();
        sut.Should().BeEmpty();
        sut.ContainsKey("a").Should().BeFalse();
        sut.ContainsKey("b").Should().BeFalse();
        sut.ContainsKey("c").Should().BeFalse();
        sut.ContainsKey("d").Should().BeFalse();
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        messages.Should().ContainSingle();
        new[] { a, b, c, d }.Should().OnlyContain(item => !item.IsDisposed);

        local.Clear();
        messages.Clear();
        sut.Clear();
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-063")]
    public void COL_063_DeliveryIsLocalBeforeHubAndRespectsHubBatch()
    {
        var hub = new MessageHub();
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub);
        var order = new List<string>();
        sut.CollectionChanged += (_, args) =>
        {
            AssertLookupMatchesOrder(sut);
            order.Add($"local:{((Item)args.NewItems![0]!).Key}");
        };
        hub.Messages.Subscribe(message =>
        {
            AssertLookupMatchesOrder(sut);
            var changed = (CollectionChangedMessage<Item>)message;
            order.Add($"hub:{changed.NewItems.Single().Key}");
        });

        sut.Add(new Item("a", "A"));
        order.Should().Equal("local:a", "hub:a");
        order.Clear();

        hub.Batch(() =>
        {
            sut.Add(new Item("b", "B"));
            sut.Add(new Item("c", "C"));
            order.Should().Equal("local:b", "local:c");
        });

        order.Should().Equal("local:b", "local:c", "hub:b", "hub:c");
    }

    [Fact, Trait("Conformance", "COL-064")]
    public void COL_064_ReentrantMutationPreservesIndexAndPerOperationOrdering()
    {
        var hub = new TestHub();
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub)
        {
            new("a", "A"),
        };
        var deliveries = new List<string>();
        var nested = false;
        sut.CollectionChanged += (_, args) =>
        {
            AssertLookupMatchesOrder(sut);
            string key = ((Item)args.NewItems![0]!).Key;
            deliveries.Add($"local:{key}");
            if (!nested)
            {
                nested = true;
                sut.Upsert(new Item("nested", "Nested"));
            }
        };
        hub.Messages.Subscribe(message =>
        {
            AssertLookupMatchesOrder(sut);
            var changed = (CollectionChangedMessage<Item>)message;
            deliveries.Add($"hub:{changed.NewItems.Single().Key}");
        });

        sut.Upsert(new Item("outer", "Outer"));

        sut.Select(item => item.Key).Should().Equal("a", "outer", "nested");
        deliveries.IndexOf("local:outer").Should().BeLessThan(deliveries.IndexOf("hub:outer"));
        deliveries.IndexOf("local:nested").Should().BeLessThan(deliveries.IndexOf("hub:nested"));
    }

    private static List<NotifyCollectionChangedEventArgs> ObserveLocal(
        KeyedServicedObservableCollection<string, Item> sut)
    {
        var events = new List<NotifyCollectionChangedEventArgs>();
        sut.CollectionChanged += (_, args) => events.Add(args);
        return events;
    }

    private static List<IMessage> ObserveHub(TestHub hub)
    {
        var messages = new List<IMessage>();
        hub.Messages.Subscribe(messages.Add);
        return messages;
    }

    private static CollectionChangedMessage<Item> AssertMessage(
        IMessage message,
        NotifyCollectionChangedAction action,
        int index,
        int oldIndex,
        int newIndex)
    {
        var changed = message.Should().BeOfType<CollectionChangedMessage<Item>>().Subject;
        changed.Action.Should().Be(action);
        changed.Index.Should().Be(index);
        changed.OldIndex.Should().Be(oldIndex);
        changed.NewIndex.Should().Be(newIndex);
        return changed;
    }

    private static void AssertLookupMatchesOrder(
        KeyedServicedObservableCollection<string, Item> sut)
    {
        for (int index = 0; index < sut.Count; index++)
        {
            sut.TryGetValue(sut[index].Key, out var found).Should().BeTrue();
            found.Should().BeSameAs(sut[index]);
        }
    }

    private static IEnumerable<Item> ThrowDuringEnumeration()
    {
        yield return new Item("unused", "Unused");
        throw new InvalidOperationException("enumeration failed");
    }

    private sealed class Item : IEquatable<Item>, IDisposable
    {
        public Item(string key, string value)
        {
            Key = key;
            Value = value;
        }

        public string Key { get; set; }

        public string Value { get; }

        public bool IsDisposed { get; private set; }

        public bool Equals(Item? other) => other is not null && Value == other.Value;

        public override bool Equals(object? obj) => obj is Item other && Equals(other);

        public override int GetHashCode() => Value.GetHashCode(StringComparison.Ordinal);

        public void Dispose() => IsDisposed = true;
    }

    private sealed class ProjectorException : Exception;
}
