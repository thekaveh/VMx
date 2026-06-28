// Polyfills required for netstandard2.0. The net8.0 target gets these from
// the BCL; netstandard2.0 callers/compilers see them via these private
// stubs so that init-only setters and nullable-flow attributes work the
// same on both target frameworks.
// IDE0161 (file-scoped namespace) suppressed: the #if guard requires block-scoped syntax.
#if NETSTANDARD2_0
#pragma warning disable IDE0161
namespace System.Runtime.CompilerServices
{
    // Polyfill for init-only setters on netstandard2.0.
    internal static class IsExternalInit { }
}

namespace System.Diagnostics.CodeAnalysis
{
    // Polyfill for the nullable-flow analyser hint
    // [NotNull] arg: post-call, the compiler treats `arg` as non-null.
    [AttributeUsage(AttributeTargets.Parameter)]
    internal sealed class NotNullAttribute : Attribute { }

    // [MaybeNull] field/return: the member may hold null/default even when its
    // declared type is non-nullable (e.g. a lazily-initialised generic cache).
    [AttributeUsage(
        AttributeTargets.Field | AttributeTargets.Parameter |
        AttributeTargets.Property | AttributeTargets.ReturnValue)]
    internal sealed class MaybeNullAttribute : Attribute { }

    // [MaybeNullWhen(returnValue)] out arg: when the method returns the given
    // bool, the out parameter may be null even if its type is non-nullable.
    [AttributeUsage(AttributeTargets.Parameter)]
    internal sealed class MaybeNullWhenAttribute : Attribute
    {
        public MaybeNullWhenAttribute(bool returnValue) => ReturnValue = returnValue;

        public bool ReturnValue { get; }
    }
}
#pragma warning restore IDE0161
#endif
