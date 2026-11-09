using FluentAssertions;
using VMx.Collections;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-071: <c>ObservableDictionary.Add</c> of a key pair that is already present
/// throws <see cref="ArgumentException"/>. The stored value, the entries, the
/// key views and <c>Count</c> do not change, and no local event or hub message
/// is sent (spec/21-collections.md §4.1, ADR-0214, #1308).
/// </summary>
public class COL_071_DictionaryDuplicateAdd_Tests
{
    [Fact, Trait("Conformance", "COL-071")]
    public void COL_071_DuplicateAddThrowsArgumentExceptionAndChangesNothing()
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.Add("a", 1, "one");
        dict.Add("b", 2, "two");
        var events = new List<string>();
        hub.Messages.Subscribe(_ => events.Add("hub"));
        dict.ItemAdded += (_, _) => events.Add("added");
        dict.ItemRemoved += (_, _) => events.Add("removed");
        dict.ItemReplaced += (_, _) => events.Add("replaced");
        dict.Reset += (_, _) => events.Add("reset");
        dict.CollectionChanged += (_, _) => events.Add("collection");
        dict.Keys1.CollectionChanged += (_, _) => events.Add("keys1");
        dict.Keys2.CollectionChanged += (_, _) => events.Add("keys2");

        var act = () => dict.Add("a", 1, "uno");

        act.Should().ThrowExactly<ArgumentException>();
        dict["a", 1].Should().Be("one");
        dict.Count.Should().Be(2);
        dict.Select(entry => $"{entry.Key.Item1}{entry.Key.Item2}{entry.Value}")
            .Should().Equal("a1one", "b2two");
        dict.Keys1.Should().Equal("a", "b");
        dict.Keys2.Should().Equal(1, 2);
        events.Should().BeEmpty();
    }
}
