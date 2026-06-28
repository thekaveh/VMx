using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Options record for the additive positional-options construction form of
/// <see cref="ComponentVM"/> (non-modeled). Pass to
/// <see cref="ComponentVM.Create(ComponentVMOptions)"/> as a one-call alternative
/// to the fluent <see cref="ComponentVMBuilder"/>; the
/// factory delegates to that builder, so validation and the resulting VM are
/// identical (ADR-0055 / VMX-020).
/// </summary>
public sealed record ComponentVMOptions
{
    /// <summary>Required VM name.</summary>
    public string? Name { get; init; }

    /// <summary>Optional hint (default: empty string).</summary>
    public string Hint { get; init; } = "";

    /// <summary>Required message hub.</summary>
    public IMessageHub? Hub { get; init; }

    /// <summary>Required dispatcher.</summary>
    public IDispatcher? Dispatcher { get; init; }

    /// <summary>Optional OnConstruct lifecycle callback.</summary>
    public Action? OnConstruct { get; init; }

    /// <summary>Optional OnDestruct lifecycle callback.</summary>
    public Action? OnDestruct { get; init; }

    /// <summary>Optional background-construction flag (default: false).</summary>
    public bool Background { get; init; }
}

/// <summary>
/// Options record for the additive positional-options construction form of
/// <see cref="ComponentVM{M}"/> (modeled). Pass to
/// <see cref="ComponentVM{M}.Create(ComponentVMOptions{M})"/> as a one-call alternative to the fluent
/// <see cref="ComponentVMBuilder{M}"/>; the factory delegates to that builder, so
/// validation and the resulting VM are identical (ADR-0055 / VMX-020).
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public sealed record ComponentVMOptions<M>
{
    /// <summary>Required VM name.</summary>
    public string? Name { get; init; }

    /// <summary>Optional hint (default: empty string).</summary>
    public string Hint { get; init; } = "";

    /// <summary>
    /// The model value. Supplied as a normal field (default: <c>default(M)</c>);
    /// unlike the fluent builder — whose <c>Model(...)</c> setter is a required
    /// step — the options form always carries a model, so there is no separate
    /// "model not set" validation here.
    /// </summary>
    public M Model { get; init; } = default!;

    /// <summary>Optional modeled-hint projection (default: <c>_ => ""</c>).</summary>
    public Func<M, string>? ModeledHinter { get; init; }

    /// <summary>Optional OnModelChanged callback.</summary>
    public Action<M>? OnModelChanged { get; init; }

    /// <summary>Required message hub.</summary>
    public IMessageHub? Hub { get; init; }

    /// <summary>Required dispatcher.</summary>
    public IDispatcher? Dispatcher { get; init; }

    /// <summary>Optional OnConstruct lifecycle callback.</summary>
    public Action? OnConstruct { get; init; }

    /// <summary>Optional OnDestruct lifecycle callback.</summary>
    public Action? OnDestruct { get; init; }

    /// <summary>Optional background-construction flag (default: false).</summary>
    public bool Background { get; init; }

    /// <summary>Optional VM type (default: <see cref="ViewModelType.Component"/>).</summary>
    public ViewModelType Type { get; init; } = ViewModelType.Component;
}
