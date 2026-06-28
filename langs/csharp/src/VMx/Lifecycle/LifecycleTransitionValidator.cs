using System.Text.Json;
using System.Text.Json.Serialization;

namespace VMx.Lifecycle;

/// <summary>
/// Validates lifecycle operation invocations against the transition matrix
/// declared in spec/fixtures/lifecycle-transitions.json. The fixture is
/// embedded into the assembly so end users do not need a runtime file.
/// </summary>
public static class LifecycleTransitionValidator
{
    private const string EmbeddedResourceName = "VMx.Lifecycle.lifecycle-transitions.json";

    // Lazy<T> default mode is ExecutionAndPublication: LoadTable() runs at most
    // once across all threads, and any concurrent first-readers block on the
    // same initialization. Safe for the static-state read pattern below.
    private static readonly Lazy<TransitionTable> Table = new(LoadTable);

    /// <summary>
    /// Throws <see cref="StatusTransitionException"/> if the operation is
    /// illegal from the current state. No-op for legal operations.
    /// </summary>
    public static void Require(ConstructionStatus current, string operation)
    {
        if (!IsLegal(current, operation))
            throw new StatusTransitionException(current, operation);
    }

    /// <summary>
    /// Returns <see langword="true"/> if the operation is allowed from the current state.
    /// </summary>
    public static bool IsLegal(ConstructionStatus current, string operation)
    {
        var row = Table.Value.Find(current, operation);
        return row?.Legal ?? false;
    }

    /// <summary>
    /// Returns the final <see cref="ConstructionStatus"/> after the operation completes,
    /// or throws <see cref="StatusTransitionException"/> if the operation is illegal.
    /// </summary>
    public static ConstructionStatus FinalState(ConstructionStatus current, string operation)
    {
        var row = Table.Value.Find(current, operation)
                  ?? throw new StatusTransitionException(current, operation);
        if (!row.Legal || row.ToFinal is null)
            throw new StatusTransitionException(current, operation);
        return ParseStatus(row.ToFinal);
    }

    private static TransitionTable LoadTable()
    {
        var assembly = typeof(LifecycleTransitionValidator).Assembly;
        using var stream = assembly.GetManifestResourceStream(EmbeddedResourceName)
            ?? throw new InvalidOperationException(
                $"Embedded resource not found: {EmbeddedResourceName}. " +
                "Ensure spec/fixtures/lifecycle-transitions.json is embedded via the csproj.");
        var table = JsonSerializer.Deserialize<TransitionTable>(stream, Options)!;
        // Build the (from, via) → row index once, under the Lazy's
        // ExecutionAndPublication lock, so every later Find is an O(1) lookup
        // with no per-row enum→string allocation (VMX-073).
        table.BuildIndex();
        return table;
    }

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    private static ConstructionStatus ParseStatus(string name) =>
#if NETSTANDARD2_0
        (ConstructionStatus)Enum.Parse(typeof(ConstructionStatus), name, ignoreCase: false);
#else
        Enum.Parse<ConstructionStatus>(name, ignoreCase: false);
#endif

    private sealed class TransitionTable
    {
        [JsonPropertyName("transitions")]
        public List<Row> Transitions { get; init; } = new();

        // (from, via) → row. ValueTuple<string,string> keys hash with ordinal
        // string equality — the same comparison the old linear scan used.
        [JsonIgnore]
        private Dictionary<(string From, string Via), Row> _index = new();

        /// <summary>
        /// Materializes the lookup index from <see cref="Transitions"/>. Called once
        /// after deserialization. First row wins on a duplicate (from, via), matching
        /// the previous <c>FirstOrDefault</c> semantics.
        /// </summary>
        public void BuildIndex()
        {
            var map = new Dictionary<(string From, string Via), Row>(Transitions.Count);
            foreach (var r in Transitions)
            {
                var key = (r.From, r.Via);
                if (!map.ContainsKey(key))
                    map[key] = r;
            }
            _index = map;
        }

        public Row? Find(ConstructionStatus from, string operation) =>
            _index.TryGetValue((from.ToString(), operation), out var row) ? row : null;
    }

    private sealed class Row
    {
        public string From { get; init; } = "";
        public string Via { get; init; } = "";
        public string? ToIntermediate { get; init; }
        public string? ToFinal { get; init; }
        public bool Legal { get; init; }
    }
}
