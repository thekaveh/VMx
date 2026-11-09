using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COMP-050..COMP-052 — the disposed-child, Destructing and child-select rules
/// of spec/06 §3, §3.1, §4.3 and §5 (ADR-0188, ADR-0189). Disposing the
/// current child clears Current, and a disposed child is not selectable. A
/// non-null selection while the composite is Destructing changes nothing and
/// raises nothing. A refused child Select() or Deselect() changes nothing and
/// raises nothing.
/// </summary>
public class COMP_050_to_052_SelectionRefusal_Tests
{
    private static ComponentVM<string> Child(
        IMessageHub hub, string name, Action? onConstruct = null, Action? onDestruct = null)
    {
        var builder = ComponentVM<string>.Builder()
            .Name(name).Services(hub, NullDispatcher.Instance).Model(name);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        if (onDestruct is not null) builder = builder.OnDestruct(onDestruct);
        return builder.Build();
    }

    /// <summary>Records each PropertyChangedMessage as "sender.property".</summary>
    private static List<string> RecordProperties(TestHub hub)
    {
        var log = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is PropertyChangedMessage<IComponentVM> changed)
                log.Add($"{changed.SenderName}.{changed.PropertyName}");
        });
        return log;
    }

    // ── COMP-050 — Disposing the current child clears Current ──

    [Fact, Trait("Conformance", "COMP-050")]
    public void COMP_050_Disposing_The_Current_Child_Clears_Current()
    {
        using var hub = new TestHub();
        var changes = new List<string?>();
        var p = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(hub, NullDispatcher.Instance)
            .Children(() => [])
            .OnCurrentChanged(value => changes.Add(value?.Name))
            .Build();
        var a = Child(hub, "a");
        var b = Child(hub, "b");
        p.Add(a);
        p.Add(b);
        p.Construct();
        p.Current = a;
        var properties = RecordProperties(hub);
        changes.Clear();

        a.Dispose();

        p.Current.Should().BeNull("the dispose clear runs before a.Dispose() returns");
        a.IsCurrent.Should().BeFalse();
        properties.Count(entry => entry == "p.Current").Should().Be(1);
        changes.Should().Equal(new string?[] { null });
        properties.Should().NotContain("a.IsCurrent", "a Disposed VM publishes nothing");

        // A Disposed child is not a member for selection (rule 2).
        p.CanSelectComponent(a).Should().BeFalse();
        var select = () => { p.Current = a; };
        select.Should().Throw<InvalidOperationException>().WithMessage("*not a member*");
        p.Current.Should().BeNull();

        // The composite's own dispose cascade does not clear Current.
        p.Current = b;
        properties.Clear();
        p.Dispose();
        b.Status.Should().Be(ConstructionStatus.Disposed);
        properties.Should().NotContain("p.Current");
    }

    // ── COMP-051 — A selection while the composite is Destructing changes nothing ──

    private sealed class DestructingScenario
    {
        public DestructingScenario()
        {
            Hub = new TestHub();
            P = CompositeVM<ComponentVM<string>>.Builder()
                .Name("p").Services(Hub, NullDispatcher.Instance)
                .Children(() => [])
                .OnCurrentChanged(OnCurrentChanged)
                .Build();
            A = Child(Hub, "a");
            B = Child(Hub, "b", onDestruct: OnDestructB);
            C = Child(Hub, "c");
            P.Add(A);
            P.Add(B);
            P.Add(C);
            Properties = RecordProperties(Hub);
        }

        public TestHub Hub { get; }

        public CompositeVM<ComponentVM<string>> P { get; }

        public ComponentVM<string> A { get; }

        public ComponentVM<string> B { get; }

        public ComponentVM<string> C { get; }

        public List<string> Properties { get; }

        public List<string?> Changes { get; } = new();

        public List<Exception> Errors { get; } = new();

        public List<bool> CanSelectC { get; } = new();

        public void Reset()
        {
            Properties.Clear();
            Changes.Clear();
            Errors.Clear();
            CanSelectC.Clear();
        }

        private void Run(Action action)
        {
            try { action(); }
            catch (Exception error) { Errors.Add(error); }
        }

        private void OnCurrentChanged(ComponentVM<string>? value)
        {
            Changes.Add(value?.Name);
            if (value is not null || P.Status != ConstructionStatus.Destructing) return;
            Run(() => P.Current = B);
            Run(() => P.SelectComponent(B));
            Run(() => B.Select());
        }

        private void OnDestructB()
        {
            Run(() => P.Current = C);
            Run(() => C.Select());
            CanSelectC.Add(P.CanSelectComponent(C));
            Run(() => P.Current = A); // a is already Destructed
            Run(() => P.Current = null);
        }

        public void AssertDestructPhase()
        {
            Errors.Should().BeEmpty();
            P.Current.Should().BeNull();
            CanSelectC.Should().Equal(false);
            Properties.Count(entry => entry == "p.Current").Should().Be(1);
            Changes.Should().Equal(new string?[] { null });
        }
    }

    [Fact, Trait("Conformance", "COMP-051")]
    public void COMP_051_A_Selection_While_Destructing_Changes_Nothing()
    {
        var s = new DestructingScenario();
        s.P.Construct();
        s.P.Current = s.A;
        s.Reset();

        var destruct = () => s.P.Destruct();

        destruct.Should().NotThrow();
        s.AssertDestructPhase();
        s.P.Status.Should().Be(ConstructionStatus.Destructed);
        s.A.Status.Should().Be(ConstructionStatus.Destructed);
        s.B.Status.Should().Be(ConstructionStatus.Destructed);
        s.C.Status.Should().Be(ConstructionStatus.Destructed);

        // The destruct phase of Reconstruct() follows the same rule.
        s.P.Construct();
        s.P.Current = s.A;
        s.Reset();

        var reconstruct = () => s.P.Reconstruct();

        reconstruct.Should().NotThrow();
        s.AssertDestructPhase();
        s.P.Status.Should().Be(ConstructionStatus.Constructed);
        s.P.Current.Should().BeNull();
        s.Hub.Dispose();
    }

    // ── COMP-052 — A refused child Select() or Deselect() changes nothing ──

    [Fact, Trait("Conformance", "COMP-052")]
    public void COMP_052_A_Refused_Child_Select_Or_Deselect_Changes_Nothing()
    {
        using var hub = new TestHub();
        CompositeVM<ComponentVM<string>>? p = null;
        ComponentVM<string>? a = null;
        ComponentVM<string>? c = null;
        p = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(hub, NullDispatcher.Instance)
            .Children(() => [])
            .AutoConstructOnAdd(true)
            .OnCurrentChanged(value =>
            {
                if (!ReferenceEquals(value, c)) return;
                p!.Dispose(); // deferred: the current publication is still running
                a!.Select();
            })
            .Build();
        a = Child(hub, "a");
        var b = Child(hub, "b");
        c = Child(hub, "c");
        p.Add(a);
        p.Add(b);
        p.Add(c);
        p.Construct();
        b.Destruct();
        b.Status.Should().Be(ConstructionStatus.Destructed);
        var properties = RecordProperties(hub);

        // A member that is not Constructed.
        var selectB = () => b.Select();
        selectB.Should().NotThrow();
        p.Current.Should().BeNull();

        // Deselect of a child that is not current.
        var deselectA = () => a.Deselect();
        deselectA.Should().NotThrow();
        p.Current.Should().BeNull();

        // The caller's own uncommitted membership transaction (rule 4).
        var d = Child(hub, "d", onConstruct: () => a.Select());
        var add = () => p.Add(d);
        add.Should().NotThrow();
        p.Current.Should().BeNull();
        d.Status.Should().Be(ConstructionStatus.Constructed);

        // A pending disposal of the composite (rule 3).
        var selectC = () => { p.Current = c; };
        selectC.Should().NotThrow();
        p.Current.Should().BeSameAs(c);
        properties.Count(entry => entry == "p.Current").Should().Be(1);

        // The deferred disposal ran once the publication ended.
        p.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
