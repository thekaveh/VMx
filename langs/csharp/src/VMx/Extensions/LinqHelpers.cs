namespace VMx.Extensions;

/// <summary>
/// Small LINQ utility helpers for in-memory sequence operations.
///
/// These helpers are C#-only per ADR-0033 — Python and TypeScript cover
/// the same ground with their respective language built-ins
/// (<c>itertools.product</c> / slice-with-step / <c>math.prod</c> in Python;
/// <c>flatMap</c> / <c>filter</c>+modulo / <c>reduce</c> in TypeScript).
/// </summary>
public static class LinqHelpers
{
    /// <summary>
    /// Cartesian product of two sequences, returned as a sequence of value-tuples.
    /// </summary>
    /// <typeparam name="TA">Element type of the first sequence.</typeparam>
    /// <typeparam name="TB">Element type of the second sequence.</typeparam>
    /// <param name="a">First sequence.</param>
    /// <param name="b">Second sequence. Enumerated once and buffered.</param>
    /// <returns>Sequence of <c>(a_i, b_j)</c> pairs, in row-major order.</returns>
    public static IEnumerable<(TA, TB)> CartesianProduct<TA, TB>(
        IEnumerable<TA> a, IEnumerable<TB> b)
    {
        var bList = b.ToList();
        foreach (var x in a)
            foreach (var y in bList)
                yield return (x, y);
    }

    /// <summary>
    /// Every Nth element of the source sequence, starting from index 0.
    /// </summary>
    /// <typeparam name="T">Element type.</typeparam>
    /// <param name="source">Source sequence.</param>
    /// <param name="every">
    ///   Sampling interval. Must be ≥ 1; throws
    ///   <see cref="ArgumentOutOfRangeException"/> otherwise.
    /// </param>
    /// <returns>Elements at indices 0, N, 2N, 3N, …</returns>
    public static IEnumerable<T> Sample<T>(this IEnumerable<T> source, int every)
    {
        // Validate eagerly: the iterator body below is deferred, so without
        // this wrapper a bad interval would only throw on first enumeration,
        // far from the buggy call site.
        if (every < 1)
            throw new ArgumentOutOfRangeException(nameof(every), every, "Sampling interval must be ≥ 1.");

        return SampleIterator(source, every);
    }

    private static IEnumerable<T> SampleIterator<T>(IEnumerable<T> source, int every)
    {
        var i = 0;
        foreach (var item in source)
        {
            if (i % every == 0) yield return item;
            i++;
        }
    }

    /// <summary>
    /// Multiplicative aggregate of an integer sequence. Returns 1 for an empty sequence
    /// (the multiplicative identity).
    /// </summary>
    /// <param name="source">Source sequence.</param>
    /// <returns>Product of all elements, or 1 if the sequence is empty.</returns>
    public static int Product(this IEnumerable<int> source)
        => source.Aggregate(1, (acc, x) => acc * x);
}
