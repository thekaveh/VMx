using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-068: <c>ObservableDictionary</c> Remove and Replace hub messages carry
/// the entry's position in enumeration order. Remove sets <c>Index</c> and
/// <c>OldIndex</c> to the pre-removal position and <c>NewIndex</c> to -1.
/// Replace sets all three to the entry's position
/// (spec/21-collections.md §4.7, ADR-0193, #1316).
/// </summary>
public class COL_068_DictionaryRemoveReplacePositions_Tests
{
    [Fact, Trait("Conformance", "COL-068")]
    public void COL_068_RemoveAndReplaceMessagesCarryTheEntryPosition()
    {
        var hub = new TestHub();
        var dict = new ObservableDictionary<string, int, string>(hub);
        dict.Add("a", 1, "one");
        dict.Add("b", 2, "two");
        dict.Add("c", 3, "three");
        var messages = new List<CollectionChangedMessage<KeyValuePair<(string, int), string>>>();
        hub.Messages.OfType<CollectionChangedMessage<KeyValuePair<(string, int), string>>>()
            .Subscribe(messages.Add);

        dict["c", 3] = "z";
        dict.Remove("b", 2).Should().BeTrue();

        messages.Should().HaveCount(2);
        var replace = messages[0];
        replace.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        (replace.Index, replace.OldIndex, replace.NewIndex).Should().Be((2, 2, 2));
        var remove = messages[1];
        remove.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        (remove.Index, remove.OldIndex, remove.NewIndex).Should().Be((1, 1, -1));
    }
}
