using System.Collections.Specialized;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Collections;

public class KeyedServicedObservableCollectionTests
{
    [Fact]
    public void Constructor_RejectsNullKeySelector()
    {
        Action act = () => _ = new KeyedServicedObservableCollection<string, Item>(null!);

        act.Should().Throw<ArgumentNullException>().WithParameterName("keySelector");
    }

    [Fact]
    public void CustomComparerControlsLookupAndUniqueness()
    {
        var sut = new KeyedServicedObservableCollection<string, Item>(
            item => item.Key,
            comparer: StringComparer.OrdinalIgnoreCase)
        {
            new("alpha", "first"),
        };

        sut.ContainsKey("ALPHA").Should().BeTrue();
        sut.TryGetValue("Alpha", out var found).Should().BeTrue();
        found.Should().NotBeNull();
        found!.Value.Should().Be("first");
        Action duplicate = () => sut.Add(new Item("ALPHA", "second"));
        duplicate.Should().Throw<ArgumentException>();
        sut.Should().ContainSingle();
    }

    [Fact]
    public void TryGetValue_DeclaresMaybeNullWhenFalse()
    {
        MethodInfo method = typeof(KeyedServicedObservableCollection<string, Item>)
            .GetMethod(nameof(KeyedServicedObservableCollection<string, Item>.TryGetValue))!;
        ParameterInfo itemParameter = method.GetParameters()[1];

        var attribute = itemParameter.GetCustomAttribute<MaybeNullWhenAttribute>();

        attribute.Should().NotBeNull();
        attribute!.ReturnValue.Should().BeFalse();
    }

    [Fact]
    public void NonProjectingMutationsNeverInvokeSelectorAgain()
    {
        var projections = 0;
        var sut = new KeyedServicedObservableCollection<string, Item>(item =>
        {
            projections++;
            return item.Key;
        })
        {
            new("a", "A"),
            new("b", "B"),
            new("c", "C"),
        };
        projections.Should().Be(3);

        sut.ContainsKey("a");
        sut.TryGetValue("b", out _);
        sut.Move(0, 2);
        sut.RemoveAt(0);
        sut.RemoveKey("a");
        sut.Clear();

        projections.Should().Be(3);
    }

    [Fact]
    public void RejectedReentrantMutationDoesNotCorruptIndex()
    {
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key);
        Exception? nestedError = null;
        sut.CollectionChanged += (_, _) =>
        {
            try
            {
                sut.Add(new Item("nested", "Nested"));
            }
            catch (Exception error)
            {
                nestedError = error;
            }
        };
        sut.CollectionChanged += (_, _) => { };

        sut.Add(new Item("outer", "Outer"));

        nestedError.Should().BeOfType<InvalidOperationException>();
        sut.Select(item => item.Key).Should().Equal("outer");
        sut.ContainsKey("outer").Should().BeTrue();
        sut.ContainsKey("nested").Should().BeFalse();
    }

    [Fact]
    public void InvalidBoundsLeaveItemsKeysAndChannelsUntouched()
    {
        var hub = new TestHub();
        var sut = new KeyedServicedObservableCollection<string, Item>(item => item.Key, hub)
        {
            new("a", "A"),
        };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<object>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        Action insert = () => sut.Insert(2, new Item("b", "B"));
        Action replace = () => sut[1] = new Item("b", "B");
        Action remove = () => sut.RemoveAt(-1);
        Action move = () => sut.Move(0, 1);

        insert.Should().Throw<ArgumentOutOfRangeException>();
        replace.Should().Throw<ArgumentOutOfRangeException>();
        remove.Should().Throw<ArgumentOutOfRangeException>();
        move.Should().Throw<ArgumentOutOfRangeException>();
        sut.Select(item => item.Key).Should().Equal("a");
        sut.ContainsKey("a").Should().BeTrue();
        sut.ContainsKey("b").Should().BeFalse();
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact]
    public void AppendAndPresentUpsertUseConstantDictionaryWork()
    {
        var comparer = new CountingComparer();
        var sut = new KeyedServicedObservableCollection<int, NumberedItem>(
            item => item.Key,
            comparer: comparer);
        for (int key = 0; key < 100; key++) sut.Add(new NumberedItem(key, key));

        comparer.Reset();
        sut.Add(new NumberedItem(100, 100));
        comparer.HashCalls.Should().BeLessThan(10);
        comparer.EqualityCalls.Should().BeLessThan(10);

        comparer.Reset();
        sut.Upsert(new NumberedItem(50, 500)).Should().BeFalse();
        comparer.HashCalls.Should().BeLessThan(10);
        comparer.EqualityCalls.Should().BeLessThan(10);
    }

    private sealed record NumberedItem(int Key, int Value);

    private sealed record Item(string Key, string Value);

    private sealed class CountingComparer : IEqualityComparer<int>
    {
        public int EqualityCalls { get; private set; }

        public int HashCalls { get; private set; }

        public bool Equals(int x, int y)
        {
            EqualityCalls++;
            return x == y;
        }

        public int GetHashCode(int obj)
        {
            HashCalls++;
            return obj;
        }

        public void Reset()
        {
            EqualityCalls = 0;
            HashCalls = 0;
        }
    }
}
