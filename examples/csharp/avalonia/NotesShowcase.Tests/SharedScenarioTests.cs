using System.Reactive.Linq;
using System.Text.Json;
using NotesShowcase.Messages;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Commands;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests;

/// <summary>
/// Shared Notes scenario <c>notes-lifecycle-v1</c> (#346). Runs
/// <c>examples/notes-showcase-scenario.json</c> through this showcase's view
/// models and compares every step's semantic snapshot with the shared
/// expectation. The Python, TypeScript, and Swift showcases run the same file
/// through their own adapters.
/// </summary>
public sealed class SharedScenarioTests
{
    private const string Flavor = "csharp";

    private static JsonElement LoadScenario()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "notes-showcase-scenario.json");
            if (File.Exists(candidate))
                return JsonDocument.Parse(File.ReadAllText(candidate)).RootElement.Clone();
            directory = directory.Parent;
        }
        throw new FileNotFoundException("examples/notes-showcase-scenario.json was not found above the test output");
    }

    private sealed class Adapter
    {
        private readonly List<string> _events = new();
        private bool _savedCompleted;

        public Adapter()
        {
            var repo = new InMemoryNoteRepository(
                SeedData.Build(),
                loadAllDelay: TimeSpan.Zero,
                loadNotesDelay: TimeSpan.Zero,
                saveNoteDelay: TimeSpan.Zero,
                addNotebookDelay: TimeSpan.Zero);
            var hub = new MessageHub();
            hub.Messages.OfType<ThemeChangedMessage>()
                .Subscribe(message => _events.Add($"theme:{message.Previous.Name}->{message.Current.Name}"));
            Workspace = WorkspaceVM.Builder().Repository(repo).MessageHub(hub).Build();
        }

        public WorkspaceVM Workspace { get; }

        public async Task<string?> RunAsync(JsonElement step)
        {
            var action = step.GetProperty("action").GetString();
            try
            {
                switch (action)
                {
                    case "construct":
                        await Workspace.ConstructAsync();
                        // The note form exists once the workspace is constructed.
                        Workspace.NoteForm.OnSaved.Subscribe(
                            model => _events.Add($"saved:{model.Title}"),
                            () => _savedCompleted = true);
                        break;
                    case "create_note":
                        await ((AsyncRelayCommand)Workspace.NewNoteCommand).ExecuteAsync();
                        break;
                    case "select_note":
                        Workspace.NotesView.Current = Workspace.NotesView.Inner[step.GetProperty("index").GetInt32()];
                        break;
                    case "edit_title":
                        Workspace.NoteForm.Title = step.GetProperty("title").GetString()!;
                        break;
                    case "save":
                        await Workspace.NoteForm.ApproveAsync();
                        break;
                    case "delete_selected_declined":
                        // The default dialog service declines every confirmation.
                        var current = Workspace.NotesView.Current
                            ?? throw new InvalidOperationException("no selected note");
                        await ((ConfirmationDecoratorCommand)current.DeleteCommand).ExecuteAsync(null);
                        break;
                    case "set_theme":
                        Workspace.Theme.SetThemeCommand.Execute(step.GetProperty("theme").GetString());
                        break;
                    case "dispose":
                        Workspace.Dispose();
                        break;
                    default:
                        throw new InvalidOperationException($"unknown scenario action {action}");
                }
            }
            catch (ArgumentException) when (action == "set_theme")
            {
                return "invalid";
            }
            return null;
        }

        public Dictionary<string, object?> Snapshot(string? error)
        {
            if (_savedCompleted)
                return new() { ["events"] = Drain(), ["error"] = error, ["disposed"] = true };
            var view = Workspace.NotesView;
            var form = Workspace.NoteForm;
            return new()
            {
                ["notebook"] = view.BoundNotebookId,
                ["notes"] = view.Inner.Snapshot().Select(note => note.Model.Title).ToList(),
                ["selected"] = view.Current?.Model.Title,
                ["form"] = form.HasBoundNote
                    ? new Dictionary<string, object?> { ["title"] = form.Title, ["dirty"] = form.IsDirty, ["valid"] = form.IsValid }
                    : null,
                ["theme"] = Workspace.Theme.CurrentTheme.Value.Name,
                ["events"] = Drain(),
                ["error"] = error,
                ["disposed"] = false,
            };
        }

        private List<string> Drain()
        {
            var events = _events.ToList();
            _events.Clear();
            return events;
        }
    }

    private static IEnumerable<string> Differences(JsonElement expected, Dictionary<string, object?> actual)
    {
        foreach (var property in expected.EnumerateObject())
        {
            if (!actual.TryGetValue(property.Name, out var value))
            {
                yield return $"{property.Name}: expected {property.Value.GetRawText()}, got <absent>";
                continue;
            }
            var got = JsonSerializer.SerializeToElement(value);
            if (!JsonElement.DeepEquals(property.Value, got))
                yield return $"{property.Name}: expected {property.Value.GetRawText()}, got {got.GetRawText()}";
        }
    }

    [Fact]
    public async Task Shared_notes_scenario_matches_the_semantic_expectation()
    {
        var scenario = LoadScenario();
        var id = scenario.GetProperty("id").GetString();
        var adapter = new Adapter();
        var failures = new List<string>();
        var number = 0;
        foreach (var step in scenario.GetProperty("steps").EnumerateArray())
        {
            number++;
            var actual = adapter.Snapshot(await adapter.RunAsync(step));
            foreach (var difference in Differences(step.GetProperty("expect"), actual))
                failures.Add($"{id} [{Flavor}] step {number} {step.GetProperty("action").GetString()}: {difference}");
        }
        Assert.True(failures.Count == 0, string.Join(Environment.NewLine, failures));
    }
}
