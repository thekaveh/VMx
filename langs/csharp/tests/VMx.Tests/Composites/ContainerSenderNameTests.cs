using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// A container's hub <see cref="CollectionChangedMessage{T}"/> carries the
/// container's <c>Name</c> as its sender name, also for the batch Reset
/// (spec/21 §2.4, ADR-0194, #1309).
/// </summary>
public class ContainerSenderNameTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    public static IEnumerable<object[]> Containers()
    {
        yield return new object[] { "composite" };
        yield return new object[] { "group" };
    }

    private static IComponentVM Container(MessageHub hub, string kind, string name) => kind == "composite"
        ? CompositeVM<IComponentVM>.Builder().Name(name).Services(hub, Dispatcher).Children(() => []).Build()
        : GroupVM<IComponentVM>.Builder().Name(name).Services(hub, Dispatcher).Children(() => []).Build();

    [Theory]
    [MemberData(nameof(Containers))]
    public void Batch_Reset_Carries_The_Container_Name(string kind)
    {
        using var hub = new MessageHub();
        var container = Container(hub, kind, "people");
        var messages = new List<CollectionChangedMessage<IComponentVM>>();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>().Subscribe(messages.Add);

        if (container is CompositeVM<IComponentVM> composite)
        {
            using (composite.BatchUpdate())
                composite.Add(Child(hub, "a"));
        }
        else
        {
            var group = (GroupVM<IComponentVM>)container;
            using (group.BatchUpdate())
                group.Add(Child(hub, "a"));
        }

        var reset = messages.Should().ContainSingle().Which;
        reset.Action.Should().Be(NotifyCollectionChangedAction.Reset);
        reset.SenderName.Should().Be("people");
    }
}
