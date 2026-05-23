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
}
