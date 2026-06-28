using System.Diagnostics.CodeAnalysis;

namespace VMx.Internal;

/// <summary>
/// Internal argument-validation helpers shared across target frameworks.
/// </summary>
internal static class ThrowHelper
{
    /// <summary>
    /// Throws <see cref="ArgumentNullException"/> when <paramref name="argument"/> is null.
    /// <para>
    /// Generic on purpose: the BCL <c>ArgumentNullException.ThrowIfNull(object?, string?)</c>
    /// overload boxes a value-type generic argument merely to null-check it, and it does not
    /// exist on netstandard2.0. This non-boxing form works on both targets and lets the call
    /// sites drop their per-site CA1510 suppressions — centralising the one remaining,
    /// documented suppression here (VMX-072).
    /// </para>
    /// </summary>
    public static void ThrowIfNull<T>([NotNull] T argument, string? paramName)
    {
        // CA1510 would suggest ArgumentNullException.ThrowIfNull(argument), but that overload
        // takes object? and would box a value-type T. Keep the non-boxing generic check.
#pragma warning disable CA1510
        if (argument is null)
            throw new ArgumentNullException(paramName);
#pragma warning restore CA1510
    }
}
