using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// A null child is rejected before the container opens its membership
/// transaction, so later adds and cross-thread disposal still proceed (#1048).
/// </summary>
public class NullChildMembershipTests
{
    private static ComponentVM<string> Child(string name) => ComponentVM<string>.Builder()
        .Name(name)
        .Services(NullMessageHub.Instance, NullDispatcher.Instance)
        .Model(name)
        .Build();

    private static IList<ComponentVM<string>> Container(string kind) => kind == "group"
        ? GroupVM<ComponentVM<string>>.Builder()
            .Name("group")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build()
        : CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();

    public static IEnumerable<object[]> Cases()
    {
        foreach (var kind in new[] { "group", "composite" })
        {
            foreach (var mutation in new[] { "add", "insert", "indexer" })
                yield return [kind, mutation];
        }
    }

    private static void MutateWithNull(IList<ComponentVM<string>> container, string mutation)
    {
        switch (mutation)
        {
            case "add": container.Add(null!); break;
            case "insert": container.Insert(0, null!); break;
            default: container[0] = null!; break;
        }
    }

    [Theory]
    [MemberData(nameof(Cases))]
    public void Null_Child_Is_Rejected_Without_Changing_The_Children(string kind, string mutation)
    {
        var container = Container(kind);
        var seed = Child("seed");
        container.Add(seed);

        var act = () => MutateWithNull(container, mutation);

        act.Should().Throw<ArgumentNullException>();
        container.Should().ContainSingle().Which.Should().BeSameAs(seed);
    }

    [Theory]
    [MemberData(nameof(Cases))]
    public async Task Null_Child_Leaves_No_Open_Membership_Transaction(string kind, string mutation)
    {
        var container = Container(kind);
        container.Add(Child("seed"));
        try { MutateWithNull(container, mutation); }
        catch (ArgumentNullException) { }

        var sameThread = Child("same-thread");
        container.Add(sameThread);
        var otherThread = Child("other-thread");
        await Task.Run(() => container.Add(otherThread)).WaitAsync(HangGuard);
        container.Should().Contain(sameThread).And.Contain(otherThread);

        await Task.Run(() => ((IDisposable)container).Dispose()).WaitAsync(HangGuard);
    }
}
