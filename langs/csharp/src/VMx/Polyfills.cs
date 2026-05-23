// Polyfill for init-only setters on netstandard2.0.
// The C# compiler emits a reference to this type when 'init' is used;
// on netstandard2.0 it's not in the BCL, so we provide it ourselves.
// IDE0161 (file-scoped namespace) suppressed: the #if guard requires block-scoped syntax.
#if NETSTANDARD2_0
#pragma warning disable IDE0161
namespace System.Runtime.CompilerServices
{
    internal static class IsExternalInit { }
}
#pragma warning restore IDE0161
#endif
