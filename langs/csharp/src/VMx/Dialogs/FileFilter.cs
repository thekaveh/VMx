namespace VMx.Dialogs;

/// <summary>
/// Describes a file-type filter for file-picker dialogs.
/// See spec/19-dialogs.md §2.
/// </summary>
/// <param name="Description">Human-readable label, e.g. "Image files".</param>
/// <param name="Extensions">File extension patterns, e.g. <c>["*.png", "*.jpg"]</c>.</param>
public sealed record FileFilter(string Description, IReadOnlyList<string> Extensions);
