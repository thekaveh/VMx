using System.Collections.Specialized;
using System.Reflection;
using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-070: <c>ObservableDictionary.Keys1</c> and <c>Keys2</c> are read-only
/// <see cref="ReadOnlyObservableList{T}"/> views. They list the distinct keys in
/// first-appearance order and give callers no mutator and no batch member
/// (spec/21-collections.md §4.1–§4.2, ADR-0193, #1316).
/// </summary>
public class COL_070_DictionaryKeyViewsReadOnly_Tests
{
    private static readonly string[] Mutators =
        ["Add", "Insert", "Remove", "RemoveAt", "Replace", "ReplaceAll", "Clear", "BatchUpdate"];

    private static ObservableDictionary<string, int, string> TwoEntries()
    {
        var dict = new ObservableDictionary<string, int, string>();
        dict.Add("a", 1, "one");
        dict.Add("b", 2, "two");
        return dict;
    }

    [Fact, Trait("Conformance", "COL-070")]
    public void COL_070_KeyViewsListDistinctKeysInFirstAppearanceOrder()
    {
        var dict = TwoEntries();

        Assert.IsType<ReadOnlyObservableList<string>>(dict.Keys1);
        Assert.IsType<ReadOnlyObservableList<int>>(dict.Keys2);
        dict.Keys1.Should().Equal("a", "b");
        dict.Keys2.Should().Equal(1, 2);
    }

    [Theory, Trait("Conformance", "COL-070")]
    [InlineData(typeof(ReadOnlyObservableList<string>))]
    [InlineData(typeof(ReadOnlyObservableList<int>))]
    public void COL_070_KeyViewTypeHasNoMutatorAndNoBatchMember(Type viewType)
    {
        var members = viewType
            .GetMembers(BindingFlags.Public | BindingFlags.Instance)
            .Select(member => member.Name);

        members.Should().NotIntersectWith(Mutators);
    }

    [Fact, Trait("Conformance", "COL-070")]
    public void COL_070_KeyViewsCannotBeCastToTheBackingList()
    {
        var dict = TwoEntries();

        ((object)dict.Keys1).Should().NotBeAssignableTo<ObservableList<string>>();
        ((object)dict.Keys2).Should().NotBeAssignableTo<ObservableList<int>>();
    }

    [Fact, Trait("Conformance", "COL-070")]
    public void COL_070_KeyViewCollectionChangedSenderIsTheView()
    {
        var dict = TwoEntries();
        var senders = new List<object?>();
        INotifyCollectionChanged keys1 = dict.Keys1;
        INotifyCollectionChanged keys2 = dict.Keys2;
        keys1.CollectionChanged += (sender, _) => senders.Add(sender);
        keys2.CollectionChanged += (sender, _) => senders.Add(sender);

        dict.Add("c", 3, "three");

        senders.Should().HaveCount(2);
        senders.Should().Contain(s => ReferenceEquals(s, dict.Keys1));
        senders.Should().Contain(s => ReferenceEquals(s, dict.Keys2));
    }
}
