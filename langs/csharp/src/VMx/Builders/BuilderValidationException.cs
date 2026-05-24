using System.Diagnostics.CodeAnalysis;

namespace VMx.Builders;

/// <summary>
/// Thrown by a builder's <c>Build()</c> method when a required field is missing.
/// See spec/10-builders.md §Validation.
/// </summary>
public sealed class BuilderValidationException : InvalidOperationException
{
    /// <summary>The name of the required field that was not supplied.</summary>
    public string MissingField { get; }

    /// <summary>Initializes a new instance of <see cref="BuilderValidationException"/>.</summary>
    /// <param name="missingField">The name of the required field.</param>
    public BuilderValidationException(string missingField)
        : base($"Required field '{missingField}' was not set on the builder.")
    {
        MissingField = missingField;
    }

    /// <summary>
    /// Throws <see cref="BuilderValidationException"/> if <paramref name="value"/> is
    /// <see langword="null"/>; otherwise no-op. The <see cref="NotNullAttribute"/> on
    /// <paramref name="value"/> lets the C# flow analyser treat the parameter as
    /// non-null after a successful call, so callers don't need a redundant
    /// nullability check.
    /// </summary>
    /// <param name="value">The builder field to validate.</param>
    /// <param name="fieldName">Human-readable name of the field (surfaced via <see cref="MissingField"/>).</param>
    public static void Require([NotNull] object? value, string fieldName)
    {
        if (value is null) throw new BuilderValidationException(fieldName);
    }
}
