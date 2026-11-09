using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Properties;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// DPROP-013: a failing <c>ValueChanged</c> subscriber stops neither the
/// property nor the other subscribers. C# discards the failure, so it never
/// reaches the code that made the source emit (spec/15 §4.1, spec/03 §3.6,
/// ADR-0191).
/// </summary>
public class DPROP_013_FailingValueChangedSubscriber_Tests
{
    private sealed class SubscriberFailure() : Exception("subscriber failed");

    private static (List<int> A, List<int> B) Attach(DerivedProperty<int> property)
    {
        var a = new List<int>();
        var b = new List<int>();
        property.ValueChanged.Subscribe(value =>
        {
            a.Add(value);
            throw new SubscriberFailure();
        });
        property.ValueChanged.Subscribe(b.Add);
        return (a, b);
    }

    [Fact, Trait("Conformance", "DPROP-013")]
    public void DPROP_013_Single_Source_Keeps_Property_And_Subscribers_Live()
    {
        using var source = new BehaviorSubject<int>(0);
        using var property = DerivedProperty.From(source, x => x * 10);
        var (a, b) = Attach(property);

        source.Invoking(s => s.OnNext(1)).Should().NotThrow();
        source.Invoking(s => s.OnNext(2)).Should().NotThrow();

        property.Value.Should().Be(20);
        a.Should().Equal(10, 20);
        b.Should().Equal(10, 20);
    }

    [Fact, Trait("Conformance", "DPROP-013")]
    public void DPROP_013_Combined_Sources_Keep_Property_And_Subscribers_Live()
    {
        using var left = new BehaviorSubject<int>(0);
        using var right = new BehaviorSubject<int>(0);
        using var property = DerivedProperty.From(left, right, (x, y) => (x * 10) + y);
        var (a, b) = Attach(property);

        left.Invoking(s => s.OnNext(1)).Should().NotThrow();
        right.Invoking(s => s.OnNext(2)).Should().NotThrow();

        property.Value.Should().Be(12);
        a.Should().Equal(10, 12);
        b.Should().Equal(10, 12);
    }
}
