using System.Text.Json;

namespace VMx.Conformance.Tests.Fixtures;

/// <summary>
/// Loads the JSON fixtures from spec/fixtures/. The fixture files are copied
/// into the test bin/ directory via the csproj's &lt;None Include="..."&gt; block.
/// </summary>
public static class FixtureLoader
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static T Load<T>(string fixtureFileName)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", fixtureFileName);
        if (!File.Exists(path))
            throw new FileNotFoundException($"Fixture not found at {path}", path);
        var json = File.ReadAllText(path);
        return JsonSerializer.Deserialize<T>(json, Options)!;
    }
}
