using System.Reactive.Subjects;
using System.Text.Json;
using FluentAssertions;
using VMx.Properties;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for derived properties, DPROP-001..012.
/// See spec/15-derived-properties.md and ADR-0011.
/// </summary>
public class DerivedPropertiesConformanceTests
{
    // ── DPROP-001 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-001: single-source derived value computes on construction.</summary>
    [Fact, Trait("Conformance", "DPROP-001")]
    public void DPROP_001_Single_Source_Initial_Value()
    {
        using var s1 = new BehaviorSubject<int>(10);
        using var dp = DerivedProperty.From(s1, x => x * 2);
        dp.Value.Should().Be(20);
    }

    // ── DPROP-002 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-002: source change triggers recompute.</summary>
    [Fact, Trait("Conformance", "DPROP-002")]
    public void DPROP_002_Source_Change_Triggers_Recompute()
    {
        using var s1 = new BehaviorSubject<int>(10);
        using var dp = DerivedProperty.From(s1, x => x * 2);
        s1.OnNext(5);
        dp.Value.Should().Be(10);
    }

    // ── DPROP-003 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-003: two-source derived value.</summary>
    [Fact, Trait("Conformance", "DPROP-003")]
    public void DPROP_003_Two_Source_Derived()
    {
        using var s1 = new BehaviorSubject<int>(3);
        using var s2 = new BehaviorSubject<int>(4);
        using var dp = DerivedProperty.From(s1, s2, (a, b) => a + b);
        dp.Value.Should().Be(7);
        s2.OnNext(6);
        dp.Value.Should().Be(9);
    }

    // ── DPROP-004 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-004: five-source derived value (spec minimum).</summary>
    [Fact, Trait("Conformance", "DPROP-004")]
    public void DPROP_004_Five_Source_Derived()
    {
        using var s1 = new BehaviorSubject<int>(1);
        using var s2 = new BehaviorSubject<int>(2);
        using var s3 = new BehaviorSubject<int>(3);
        using var s4 = new BehaviorSubject<int>(4);
        using var s5 = new BehaviorSubject<int>(5);
        using var dp = DerivedProperty.From(s1, s2, s3, s4, s5, (a, b, c, d, e) => a + b + c + d + e);
        dp.Value.Should().Be(15);
    }

    // ── DPROP-005 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-005: mutation of any source recomputes.</summary>
    [Fact, Trait("Conformance", "DPROP-005")]
    public void DPROP_005_Mutation_Of_Any_Source_Recomputes()
    {
        using var s1 = new BehaviorSubject<int>(1);
        using var s2 = new BehaviorSubject<int>(2);
        using var s3 = new BehaviorSubject<int>(3);
        using var s4 = new BehaviorSubject<int>(4);
        using var s5 = new BehaviorSubject<int>(5);
        using var dp = DerivedProperty.From(s1, s2, s3, s4, s5, (a, b, c, d, e) => a + b + c + d + e);
        s3.OnNext(30);
        dp.Value.Should().Be(1 + 2 + 30 + 4 + 5);
    }

    // ── DPROP-006 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-006: default-built derived property is read-only.</summary>
    [Fact, Trait("Conformance", "DPROP-006")]
    public void DPROP_006_Default_Is_Read_Only()
    {
        using var s1 = new BehaviorSubject<int>(1);
        using var dp = DerivedProperty.From(s1, x => x);
        foreach (var v in new[] { 0, 1, 42, -7 })
            dp.CanSet(v).Should().BeFalse();
    }

    // ── DPROP-007 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-007: validator + write-back enables SetValue.</summary>
    [Fact, Trait("Conformance", "DPROP-007")]
    public void DPROP_007_Validator_Plus_Write_Back()
    {
        using var s1 = new BehaviorSubject<int>(0);
        var recorder = new List<int>();
        using var dp = DerivedProperty.From<int, int>(
            s1, x => x,
            canSet: v => v > 0,
            setAction: recorder.Add);

        dp.SetValue(5);
        recorder.Should().Equal(5);

        var act = () => dp.SetValue(-1);
        act.Should().Throw<InvalidOperationException>();
        recorder.Should().Equal(5);
    }

    // ── DPROP-008 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-008: write-back action receives the value.</summary>
    [Fact, Trait("Conformance", "DPROP-008")]
    public void DPROP_008_Write_Back_Action_Receives_Value()
    {
        using var s1 = new BehaviorSubject<int>(0);
        var recorder = new List<int>();
        using var dp = DerivedProperty.From<int, int>(
            s1, x => x,
            canSet: _ => true,
            setAction: recorder.Add);

        dp.SetValue(7);
        recorder.Should().Equal(7);
    }

    // ── DPROP-009 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-009: ValueChanged emits on recompute.</summary>
    [Fact, Trait("Conformance", "DPROP-009")]
    public void DPROP_009_ValueChanged_Emits_On_Recompute()
    {
        using var s1 = new BehaviorSubject<int>(1);
        using var dp = DerivedProperty.From(s1, x => x);
        var observed = new List<int>();
        using var sub = dp.ValueChanged.Subscribe(observed.Add);
        s1.OnNext(2);
        s1.OnNext(3);
        observed.Should().Equal(2, 3);
    }

    // ── DPROP-010 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-010: ValueChanged does not emit if transform output unchanged.</summary>
    [Fact, Trait("Conformance", "DPROP-010")]
    public void DPROP_010_Distinct_Until_Changed()
    {
        using var s1 = new BehaviorSubject<int>(5);
        using var s2 = new BehaviorSubject<int>(5);
        using var dp = DerivedProperty.From(s1, s2, (a, b) => a + b);
        var observed = new List<int>();
        using var sub = dp.ValueChanged.Subscribe(observed.Add);
        s1.OnNext(3);          // 3+5 = 8 → emit
        s2.OnNext(7);          // 3+7 = 10 → emit (different from 8)
        observed.Should().Equal(8, 10);
        s1.OnNext(3);          // 3+7 still 10 → no emit
        observed.Should().Equal(8, 10);
    }

    // ── DPROP-011 ───────────────────────────────────────────────────────────

    /// <summary>DPROP-011: Dispose ends subscriptions; ValueChanged completes.</summary>
    [Fact, Trait("Conformance", "DPROP-011")]
    public void DPROP_011_Dispose_Completes_ValueChanged()
    {
        using var s1 = new BehaviorSubject<int>(1);
        var dp = DerivedProperty.From(s1, x => x);
        var observed = new List<int>();
        var completed = false;
        using var sub = dp.ValueChanged.Subscribe(observed.Add, () => completed = true);
        s1.OnNext(2);
        observed.Should().Equal(2);
        dp.Dispose();
        completed.Should().BeTrue();
        s1.OnNext(3);
        dp.Value.Should().Be(2);  // not updated after dispose
    }

    // ── DPROP-012 ───────────────────────────────────────────────────────────

    private static readonly Dictionary<string, Func<IReadOnlyList<object?>, object?>> Transforms =
        new()
        {
            ["sum"] = values => values.Sum(v => Convert.ToInt64(v, System.Globalization.CultureInfo.InvariantCulture)),
            ["concat"] = values => string.Concat(values.Select(v => v?.ToString() ?? "")),
        };

    /// <summary>DPROP-012: fixture-driven scenarios.</summary>
    [Fact, Trait("Conformance", "DPROP-012")]
    public void DPROP_012_Fixture_Scenarios()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "derived-properties.json");
        File.Exists(path).Should().BeTrue($"fixture missing at {path}");
        using var stream = File.OpenRead(path);
        var doc = JsonDocument.Parse(stream);
        var scenarios = doc.RootElement.GetProperty("scenarios");
        foreach (var scenario in scenarios.EnumerateArray())
        {
            var name = scenario.GetProperty("name").GetString()!;
            var transformName = scenario.GetProperty("transform").GetString()!;
            var transform = Transforms[transformName];

            var initial = scenario.GetProperty("sources_initial").EnumerateArray()
                .Select(e => (object?)ExtractScalar(e)).ToList();
            var subjects = initial.Select(v => new BehaviorSubject<object?>(v)).ToList();

            try
            {
                using var dp = DerivedProperty.FromMany<object?>(
                    subjects.Select(s => (IObservable<object?>)s).ToList(),
                    transform);

                var actuals = new List<object?> { dp.Value };
                foreach (var mut in scenario.GetProperty("mutations").EnumerateArray())
                {
                    var idx = mut[0].GetInt32();
                    var val = (object?)ExtractScalar(mut[1]);
                    subjects[idx].OnNext(val);
                    actuals.Add(dp.Value);
                }

                var expected = scenario.GetProperty("expected_values").EnumerateArray()
                    .Select(e => (object?)ExtractScalar(e)).ToList();
                actuals.Select(NormalizeForCompare).Should().Equal(
                    expected.Select(NormalizeForCompare),
                    $"scenario {name}");
            }
            finally
            {
                foreach (var sj in subjects) sj.Dispose();
            }
        }
    }

    private static object? ExtractScalar(JsonElement e) => e.ValueKind switch
    {
        JsonValueKind.Number => e.GetInt64(),
        JsonValueKind.String => e.GetString(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Null => null,
        _ => e.ToString(),
    };

    private static object? NormalizeForCompare(object? v) => v switch
    {
        long l => l,
        int i => (long)i,
        string s => s,
        _ => v,
    };
}
