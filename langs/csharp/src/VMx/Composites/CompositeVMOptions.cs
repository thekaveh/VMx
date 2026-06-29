using VMx.Components;
using VMx.Services;

namespace VMx.Composites;

/// <summary>
/// Options record for the additive positional-options construction form of
/// <see cref="CompositeVM{VM}"/> (non-modeled). Pass to
/// <see cref="CompositeVM{VM}.Create(CompositeVMOptions{VM})"/> as a one-call alternative to the fluent
/// <see cref="CompositeVMBuilder{VM}"/>; the factory delegates to that builder, so
/// validation and the resulting VM are identical (ADR-0055 / VMX-020).
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed record CompositeVMOptions<VM>
    where VM : class, IComponentVM
{
    /// <summary>Required VM name.</summary>
    public string? Name { get; init; }

    /// <summary>Optional hint (default: empty string).</summary>
    public string Hint { get; init; } = "";

    /// <summary>Required message hub.</summary>
    public IMessageHub? Hub { get; init; }

    /// <summary>Required dispatcher.</summary>
    public IDispatcher? Dispatcher { get; init; }

    /// <summary>
    /// Required children factory, invoked lazily on Construct. For an initially
    /// empty composite, pass <c>() =&gt; Array.Empty&lt;VM&gt;()</c> (spec/10 §3 / ADR-0035).
    /// </summary>
    public Func<IEnumerable<VM>>? Children { get; init; }

    /// <summary>Optional async-selection flag (default: false).</summary>
    public bool AsyncSelection { get; init; }

    /// <summary>Optional auto-construct-on-add flag (default: false).</summary>
    public bool AutoConstructOnAdd { get; init; }

    /// <summary>Optional initial-current selector (see ADR-0042 / COMP-025).</summary>
    public Func<IEnumerable<VM>, VM?>? Current { get; init; }

    /// <summary>Optional current-changed callback (see ADR-0042 / COMP-026).</summary>
    public Action<VM?>? OnCurrentChanged { get; init; }

    /// <summary>Optional OnConstruct lifecycle callback.</summary>
    public Action? OnConstruct { get; init; }

    /// <summary>Optional OnDestruct lifecycle callback.</summary>
    public Action? OnDestruct { get; init; }
}
