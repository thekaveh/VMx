"""Keep the desktop host lifecycle checks wired to CI and to the real examples.

Each check runs an example's own window on its toolkit's event loop (#360):
the Tk todo app under Xvfb, the WPF TodoApp window on an STA Dispatcher, and
the SwiftUI bridge in an AppKit window. These tests fail when a workflow stops
running a check or a check stops exercising the example it names.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_ci_runs_the_tk_todo_app_host_check_under_xvfb() -> None:
    steps = [line for line in _read(".github/workflows/python.yml").splitlines() if "run:" in line]

    assert any("xvfb-run" in step and "-m todo_app.host_check" in step for step in steps)
    host_check = _read("examples/python/tk/todo_app/host_check.py")
    assert "from .__main__ import MainWindow" in host_check
    assert 'protocol("WM_DELETE_WINDOW")' in host_check


def test_ci_runs_the_wpf_todo_app_window_on_a_dispatcher() -> None:
    project = "examples/csharp/wpf/TodoAppHostCheck/TodoAppHostCheck.csproj"

    assert f"dotnet run --project {project}" in _read(".github/workflows/csharp.yml")
    linked = _read(project)
    for source in ("MainWindow.xaml", "MainWindow.xaml.cs", "MainWindowViewModel.cs"):
        assert f'Include="../TodoApp/{source}"' in linked, f"{source} is not the example's own file"


def test_the_showcase_suite_hosts_the_swiftui_bridge_in_an_appkit_window() -> None:
    tests = _read("examples/swift/notes-showcase/Tests/NotesShowcaseTests/HostLifecycleTests.swift")

    assert "NSHostingController" in tests
    assert "BindableVM(" in tests
    assert "swift test" in _read(".github/workflows/swift.yml")


def test_the_integration_guide_lists_every_host_check() -> None:
    guide = _read("docs/content/integration/index.md")
    section = guide.split("## 9.1.7. Host Coverage", 1)[1]

    for check in ("todo_app.host_check", "TodoAppHostCheck", "HostLifecycleTests"):
        assert check in section
