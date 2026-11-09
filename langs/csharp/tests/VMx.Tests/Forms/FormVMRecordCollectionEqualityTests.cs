using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Forms;

/// <summary>
/// A record's synthesized equality compares a collection field by reference,
/// and the default snapshotter's System.Text.Json round-trip makes a new
/// collection. These tests pin the effect on <see cref="FormVM{TM}"/> and the
/// element-wise <c>Equals</c> override that the FormVM docs page shows (#1460).
/// </summary>
public class FormVMRecordCollectionEqualityTests
{
    // A record with a list field and the synthesized equality.
    public sealed record PlainNote(string Title, IReadOnlyList<string> Tags);

    // docs-snippet:start record-collection-equality
    public sealed record Note(string Title, IReadOnlyList<string> Tags)
    {
        // Compare Tags element by element, not by reference.
        public bool Equals(Note? other) =>
            other is not null
            && Title == other.Title
            && Tags.SequenceEqual(other.Tags);

        public override int GetHashCode()
        {
            var hash = new HashCode();
            hash.Add(Title);
            foreach (var tag in Tags)
                hash.Add(tag);
            return hash.ToHashCode();
        }
    }
    // docs-snippet:end record-collection-equality

    [Fact]
    public void Synthesized_Record_Equality_Makes_A_Fresh_Strict_Form_Dirty()
    {
        var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var sub = hub.Messages.Subscribe(messages.Add);
        using var sut = new FormVM<PlainNote>(
            new PlainNote("A", ["x"]), _ => Task.CompletedTask, hub: hub, strict: true);

        sut.IsDirty.Should().BeTrue("the snapshot's new list differs by reference");
        sut.ApproveCommand.CanExecute(null).Should().BeTrue("strict approve follows IsDirty");

        messages.Clear();
        sut.SetModel(new PlainNote("A", ["x"]));

        ModelMessages(messages, sut).Should().ContainSingle(
            "an equal-content list is not Equals under the synthesized equality");
        sut.IsDirty.Should().BeTrue();
    }

    [Fact]
    public void Element_Wise_Equals_Keeps_A_Fresh_Strict_Form_Clean()
    {
        var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var sub = hub.Messages.Subscribe(messages.Add);
        using var sut = new FormVM<Note>(
            new Note("A", ["x"]), _ => Task.CompletedTask, hub: hub, strict: true);

        sut.IsDirty.Should().BeFalse();
        sut.ApproveCommand.CanExecute(null).Should().BeFalse();

        messages.Clear();
        sut.SetModel(new Note("A", ["x"]));

        ModelMessages(messages, sut).Should().BeEmpty("an equal-content SetModel is a no-op");
        sut.IsDirty.Should().BeFalse();

        sut.SetModel(new Note("A", ["x", "y"]));

        sut.IsDirty.Should().BeTrue("a changed element makes the form dirty");
        sut.ApproveCommand.CanExecute(null).Should().BeTrue();
    }

    private static List<PropertyChangedMessage<FormVM<TM>>> ModelMessages<TM>(
        List<IMessage> messages, FormVM<TM> sut)
        where TM : notnull
        => messages
            .OfType<PropertyChangedMessage<FormVM<TM>>>()
            .Where(message => ReferenceEquals(message.Sender, sut) && message.PropertyName == "Model")
            .ToList();
}
