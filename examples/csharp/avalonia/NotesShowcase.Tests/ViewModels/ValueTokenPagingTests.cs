using NotesShowcase.Models;
using VMx.Collections;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

/// <summary>
/// Value cursors for <see cref="TokenPagedComposition{TVM,TToken}"/> use
/// <c>int?</c>: <c>null</c> requests the first page and ends paging, and every
/// integer, including <c>0</c>, is a valid continuation.
/// </summary>
public class ValueTokenPagingTests
{
    [Fact]
    public async Task A_nullable_int_cursor_pages_every_note_once_and_treats_zero_as_a_cursor()
    {
        var notes = SeedData.Build().Notes;
        const int pageSize = 3;
        var pageCount = (notes.Count + pageSize - 1) / pageSize;
        var requested = new List<int?>();
        // The cursor counts the pages still to load after the requested one, so
        // the last continuation is 0 and null marks the end.
        using var paged = new TokenPagedComposition<NoteModel, int?>(remaining =>
        {
            requested.Add(remaining);
            var pageIndex = remaining is null ? 0 : pageCount - 1 - remaining.Value;
            var page = notes.Skip(pageIndex * pageSize).Take(pageSize).ToArray();
            int? next = pageIndex + 1 < pageCount ? pageCount - pageIndex - 2 : null;
            return Task.FromResult(new TokenPage<NoteModel, int?>(page, next));
        });

        while (paged.HasMore)
        {
            await paged.LoadMoreCommand.ExecuteAsync();
        }

        Assert.True(pageCount >= 3);
        Assert.Equal(notes.Select(note => note.Id), paged.Items.Select(note => note.Id));
        Assert.Null(paged.CurrentToken);
        Assert.False(paged.LoadMoreCommand.CanExecute(null));
        Assert.Null(requested[0]);
        Assert.Equal(0, requested[^1]);
        Assert.Equal(pageCount, requested.Count);
    }

    [Fact]
    public void A_non_nullable_int_cursor_is_rejected_with_guidance()
    {
        var error = Assert.Throws<NotSupportedException>(() =>
            new TokenPagedComposition<NoteModel, int>(_ =>
                Task.FromResult(new TokenPage<NoteModel, int>([], 0))));

        Assert.Contains("Int32?", error.Message);
    }
}
