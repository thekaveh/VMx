using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-048..COL-055 — complete serviced collection parity.
/// </summary>
public class COL_048_to_055_ServicedObservableCollectionParityTests
{
    [Fact, Trait("Conformance", "COL-048")]
    public void COL_048_ValueRemovalTargetsFirstDuplicateAndMissingIsNoOp()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>(hub) { "a", "b", "a" };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.Remove("a").Should().BeTrue();

        sut.Should().Equal("b", "a");
        local.Should().ContainSingle();
        var message = messages.Should().ContainSingle().Which
            .Should().BeOfType<CollectionChangedMessage<string>>().Subject;
        message.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        message.OldItems.Should().Equal("a");
        message.Index.Should().Be(0);
        message.OldIndex.Should().Be(0);
        message.NewIndex.Should().Be(-1);

        local.Clear();
        messages.Clear();
        sut.Remove("missing").Should().BeFalse();
        sut.Should().Equal("b", "a");
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-049")]
    public void COL_049_IndexedRemovalPublishesPositionsAndRejectsInvalidIndicesAtomically()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>(hub) { "a", "b", "c" };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.RemoveAt(1);

        sut.Should().Equal("a", "c");
        local.Should().ContainSingle();
        var message = (CollectionChangedMessage<string>)messages.Should().ContainSingle().Which;
        message.OldItems.Should().Equal("b");
        message.Index.Should().Be(1);
        message.OldIndex.Should().Be(1);
        message.NewIndex.Should().Be(-1);

        local.Clear();
        messages.Clear();
        Action negative = () => sut.RemoveAt(-1);
        Action atCount = () => sut.RemoveAt(sut.Count);
        negative.Should().Throw<ArgumentOutOfRangeException>();
        atCount.Should().Throw<ArgumentOutOfRangeException>();
        sut.Should().Equal("a", "c");
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-050")]
    public void COL_050_NamedReplacementAlwaysPublishesAndInvalidIndexIsAtomic()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<string>(hub) { "a", "b" };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.Replace(1, "c");

        sut.Should().Equal("a", "c");
        var message = (CollectionChangedMessage<string>)messages.Should().ContainSingle().Which;
        message.Action.Should().Be(NotifyCollectionChangedAction.Replace);
        message.OldItems.Should().Equal("b");
        message.NewItems.Should().Equal("c");
        message.Index.Should().Be(1);
        message.OldIndex.Should().Be(1);
        message.NewIndex.Should().Be(1);

        local.Clear();
        messages.Clear();
        sut.Replace(1, sut[1]);
        local.Should().ContainSingle();
        messages.Should().ContainSingle();

        local.Clear();
        messages.Clear();
        Action invalid = () => sut.Replace(sut.Count, "x");
        invalid.Should().Throw<ArgumentOutOfRangeException>();
        sut.Should().Equal("a", "c");
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-051")]
    public void COL_051_ReplaceAllSnapshotsAndEmitsExactlyOneReset()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>(hub) { 1, 2, 3 };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.ReplaceAll(sut);

        sut.Should().Equal(1, 2, 3);
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        var reset = (CollectionChangedMessage<int>)messages.Should().ContainSingle().Which;
        reset.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        reset.NewItems.Should().BeEmpty();
        reset.OldItems.Should().BeEmpty();
        reset.Index.Should().Be(-1);
        reset.OldIndex.Should().Be(-1);
        reset.NewIndex.Should().Be(-1);

        local.Clear();
        messages.Clear();
        sut.ReplaceAll(new List<int> { 1, 2, 3 });
        local.Should().ContainSingle();
        messages.Should().ContainSingle();

        local.Clear();
        messages.Clear();
        Action failing = () => sut.ReplaceAll(ThrowDuringEnumeration());
        failing.Should().Throw<InvalidOperationException>().WithMessage("enumeration failed");
        sut.Should().Equal(1, 2, 3);
        local.Should().BeEmpty();
        messages.Should().BeEmpty();

        var empty = new ServicedObservableCollection<int>(hub);
        empty.CollectionChanged += (_, args) => local.Add(args);
        empty.ReplaceAll(Array.Empty<int>());
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-052")]
    public void COL_052_MovePreservesIdentityAndPublishesPrecisePositions()
    {
        var a = new object();
        var b = new object();
        var c = new object();

        AssertMove(new[] { a, b, c }, 0, 2, new[] { b, c, a }, a);
        AssertMove(new[] { a, b, c }, 2, 0, new[] { c, a, b }, c);
    }

    [Fact, Trait("Conformance", "COL-053")]
    public void COL_053_MoveSameIndexAndInvalidBoundsAreAtomicNoOps()
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>(hub) { 1, 2, 3 };
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.Move(1, 1);

        sut.Should().Equal(1, 2, 3);
        local.Should().BeEmpty();
        messages.Should().BeEmpty();

        Action negativeSource = () => sut.Move(-1, 0);
        Action negativeDestination = () => sut.Move(0, -1);
        Action sourceAtCount = () => sut.Move(sut.Count, 0);
        Action destinationAtCount = () => sut.Move(0, sut.Count);
        negativeSource.Should().Throw<ArgumentOutOfRangeException>();
        negativeDestination.Should().Throw<ArgumentOutOfRangeException>();
        sourceAtCount.Should().Throw<ArgumentOutOfRangeException>();
        destinationAtCount.Should().Throw<ArgumentOutOfRangeException>();
        sut.Should().Equal(1, 2, 3);
        local.Should().BeEmpty();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "COL-054")]
    public void COL_054_EveryMutationDeliversLocalBeforeHubWithFinalStateVisible()
    {
        AssertDelivery(Array.Empty<int>(), sut => sut.Add(1), new List<int> { 1 });
        AssertDelivery(new List<int> { 1, 2 }, sut => sut.Remove(1), new List<int> { 2 });
        AssertDelivery(new List<int> { 1, 2 }, sut => sut.Replace(1, 3), new List<int> { 1, 3 });
        AssertDelivery(
            new List<int> { 1, 2 },
            sut => sut.ReplaceAll(new List<int> { 3, 4 }),
            new List<int> { 3, 4 });
        AssertDelivery(
            new List<int> { 1, 2, 3 },
            sut => sut.Move(0, 2),
            new List<int> { 2, 3, 1 });
        AssertDelivery(new List<int> { 1, 2 }, sut => sut.Clear(), Array.Empty<int>());
    }

    [Fact, Trait("Conformance", "COL-055")]
    public void COL_055_ClearNoOpAndAllMutationsPreserveCallerOwnership()
    {
        var hub = new TestHub();
        var empty = new ServicedObservableCollection<DisposableProbe>(hub);
        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        empty.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        empty.Clear();

        local.Should().BeEmpty();
        messages.Should().BeEmpty();

        var a = new DisposableProbe();
        var b = new DisposableProbe();
        var c = new DisposableProbe();
        var d = new DisposableProbe();
        var sut = new ServicedObservableCollection<DisposableProbe>(hub) { a, b, c };
        messages.Clear();
        sut.Remove(a);
        sut.RemoveAt(0);
        sut.Replace(0, d);
        sut.ReplaceAll(new[] { a, b, c, d });
        sut.Move(0, 3);
        sut.Clear();

        new[] { a, b, c, d }.Should().OnlyContain(item => !item.IsDisposed);
        var reset = (CollectionChangedMessage<DisposableProbe>)messages[^1];
        reset.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        reset.Index.Should().Be(-1);
        reset.OldIndex.Should().Be(-1);
        reset.NewIndex.Should().Be(-1);
    }

    private static IEnumerable<int> ThrowDuringEnumeration()
    {
        yield return 9;
        throw new InvalidOperationException("enumeration failed");
    }

    private static void AssertMove(
        IEnumerable<object> initial,
        int oldIndex,
        int newIndex,
        IEnumerable<object> expected,
        object moved)
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<object>(hub);
        foreach (var item in initial) sut.Add(item);

        var local = new List<NotifyCollectionChangedEventArgs>();
        var messages = new List<IMessage>();
        sut.CollectionChanged += (_, args) => local.Add(args);
        hub.Messages.Subscribe(messages.Add);

        sut.Move(oldIndex, newIndex);

        sut.Should().Equal(expected);
        local.Should().ContainSingle().Which.Action.Should().Be(NotifyCollectionChangedAction.Move);
        var message = (CollectionChangedMessage<object>)messages.Should().ContainSingle().Which;
        message.Action.Should().Be(NotifyCollectionChangedAction.Move);
        message.Index.Should().Be(newIndex);
        message.OldIndex.Should().Be(oldIndex);
        message.NewIndex.Should().Be(newIndex);
        message.OldItems.Should().ContainSingle().Which.Should().BeSameAs(moved);
        message.NewItems.Should().ContainSingle().Which.Should().BeSameAs(moved);
    }

    private static void AssertDelivery(
        IEnumerable<int> initial,
        Action<ServicedObservableCollection<int>> mutation,
        IEnumerable<int> expected)
    {
        var hub = new TestHub();
        var sut = new ServicedObservableCollection<int>(hub);
        foreach (int item in initial) sut.Add(item);

        var order = new List<string>();
        var snapshots = new List<int[]>();
        sut.CollectionChanged += (_, _) =>
        {
            order.Add("local");
            snapshots.Add(sut.ToArray());
        };
        hub.Messages.Subscribe(_ =>
        {
            order.Add("hub");
            snapshots.Add(sut.ToArray());
        });

        mutation(sut);

        order.Should().Equal("local", "hub");
        snapshots.Should().HaveCount(2);
        snapshots.Should().OnlyContain(snapshot => snapshot.SequenceEqual(expected));
    }

    private sealed class DisposableProbe : IDisposable
    {
        public bool IsDisposed { get; private set; }

        public void Dispose() => IsDisposed = true;
    }
}
