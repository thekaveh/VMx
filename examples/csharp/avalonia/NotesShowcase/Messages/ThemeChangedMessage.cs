using NotesShowcase.Models;
using VMx.Messages;

namespace NotesShowcase.Messages;

/// <summary>
/// Published on the hub by <see cref="NotesShowcase.ViewModels.ThemeVM"/>
/// after every effective theme change.
///
/// See spec/proposals/2026-06-02-theme-vm-scenario.md §4 (event surface) and
/// §6 (conformance THEME-001/003/004).
///
/// <para>
/// <see cref="Previous"/> is the model the VM held immediately before the
/// transition; <see cref="Current"/> is the model just installed. The two
/// are guaranteed to differ by at least one field (the VM short-circuits a
/// no-op transition before publishing).
/// </para>
/// </summary>
/// <param name="Sender">Strongly-typed sender (the <c>ThemeVM</c>).</param>
/// <param name="SenderName">Human-readable sender identifier.</param>
/// <param name="Previous">The model installed prior to this transition.</param>
/// <param name="Current">The model now installed.</param>
public sealed record ThemeChangedMessage(
    object Sender,
    string SenderName,
    ThemeModel Previous,
    ThemeModel Current) : IMessage
{
    /// <inheritdoc/>
    public object SenderObject => Sender;
}
