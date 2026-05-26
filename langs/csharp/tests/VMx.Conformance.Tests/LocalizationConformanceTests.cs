using FluentAssertions;
using VMx.Localization;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for localization hooks, LOC-001..003.
/// See spec/17-localization.md and ADR-0019.
/// </summary>
public class LocalizationConformanceTests
{
    [Fact, Trait("Conformance", "LOC-001")]
    public void LOC_001_Localize_Returns_String()
    {
        ILocalizer loc = new FakeLocalizer();
        loc.Localize("greeting").Should().Be("hello");
    }

    [Fact, Trait("Conformance", "LOC-002")]
    public void LOC_002_NullLocalizer_Returns_Key_Verbatim()
    {
        var loc = NullLocalizer.Instance;
        loc.Localize("some-key").Should().Be("some-key");
        loc.Localize("some-key", new object?[] { "a", "b" }).Should().Be("some-key");
    }

    [Fact, Trait("Conformance", "LOC-003")]
    public void LOC_003_Custom_Localizer_Can_Substitute()
    {
        ILocalizer loc = new XLocalizer();
        loc.Localize("foo").Should().Be("X:foo");
    }

    private sealed class FakeLocalizer : ILocalizer
    {
        public string Localize(string key) => key == "greeting" ? "hello" : key;
        public string Localize(string key, IEnumerable<object?> args) => Localize(key);
    }

    private sealed class XLocalizer : ILocalizer
    {
        public string Localize(string key) => "X:" + key;
        public string Localize(string key, IEnumerable<object?> args) => Localize(key);
    }
}
