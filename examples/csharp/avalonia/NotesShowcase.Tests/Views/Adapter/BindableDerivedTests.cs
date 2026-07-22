using System.ComponentModel;
using System.Reactive.Subjects;
using NotesShowcase.Views.Adapter;
using VMx.Properties;
using Xunit;

namespace NotesShowcase.Tests.Views.Adapter;

/// <summary>
/// Adapter contract for the derived-property binding scenario: given a
/// <see cref="DerivedProperty{T}"/> backed by a seeded source, the
/// <see cref="BindableDerived{T}"/> sidecar exposes the same <c>Value</c> and
/// raises <see cref="INotifyPropertyChanged.PropertyChanged"/> for <c>Value</c>
/// on every distinct recompute (parity with Python ``bind_derived_property``
/// and React ``useDerivedProperty``).
/// </summary>
public sealed class BindableDerivedTests
{
    private static (BindableDerived<int> bindable, BehaviorSubject<int> source, DerivedProperty<int> dp) Build(int seed = 0)
    {
        var source = new BehaviorSubject<int>(seed);
        var dp = DerivedProperty.From(source, v => v * 2);
        var bindable = new BindableDerived<int>(dp);
        return (bindable, source, dp);
    }

    [Fact]
    public void Throws_when_source_DerivedProperty_is_null()
    {
        Assert.Throws<ArgumentNullException>(() => new BindableDerived<int>(null!));
    }

    [Fact]
    public void Value_reads_through_to_underlying_DerivedProperty()
    {
        var (bindable, _, _) = Build(seed: 5);
        Assert.Equal(10, bindable.Value);
    }

    [Fact]
    public void Value_returns_default_when_DerivedProperty_has_no_emission_yet()
    {
        // Construct a DP backed by a plain Subject (no seeding) — `.Value`
        // would normally throw; the bindable wrapper must swallow that and
        // return default!.
        var source = new Subject<int>();
        var dp = DerivedProperty.From(source, v => v);
        var bindable = new BindableDerived<int>(dp);
        Assert.Equal(0, bindable.Value);
    }

    [Fact]
    public void PropertyChanged_fires_on_every_distinct_recompute()
    {
        var (bindable, source, _) = Build(seed: 0);
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        source.OnNext(1);
        source.OnNext(2);

        Assert.Equal(2, observed.Count);
        Assert.All(observed, n => Assert.Equal(nameof(BindableDerived<int>.Value), n));
        Assert.Equal(4, bindable.Value);
    }

    [Fact]
    public void PropertyChanged_does_not_fire_for_equal_value_repeats()
    {
        var (bindable, source, _) = Build(seed: 1);
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        // Underlying DP equality-guards; same input → same output → no notify.
        source.OnNext(1);
        source.OnNext(1);

        Assert.Empty(observed);
    }

    [Fact]
    public void Dispose_releases_subscription_and_stops_raising_PropertyChanged()
    {
        var (bindable, source, _) = Build();
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        bindable.Dispose();
        source.OnNext(99);

        Assert.Empty(observed);
    }

    [Fact]
    public void Dispose_is_idempotent()
    {
        var (bindable, _, _) = Build();
        bindable.Dispose();
        bindable.Dispose(); // must not throw
    }
}
