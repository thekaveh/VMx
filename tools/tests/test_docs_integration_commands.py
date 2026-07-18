"""Keep integration recipes on the public VM and command surfaces."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "docs" / "content" / "integration"


def test_integration_recipes_do_not_invent_component_command_members() -> None:
    offenders: list[str] = []
    for name in ("react", "vue", "svelte", "solid", "nicegui", "tkinter", "textual"):
        path = INTEGRATION / f"{name}.md"
        text = path.read_text(encoding="utf-8")
        for unsupported in ("vm.saveCommand", "vm.save_command", "_vm.save_command"):
            if unsupported in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {unsupported}")

    assert offenders == []


def test_integration_recipes_accept_commands_separately_from_base_vms() -> None:
    for name in ("react", "vue", "svelte", "solid"):
        text = (INTEGRATION / f"{name}.md").read_text(encoding="utf-8")
        assert "ICommand" in text
        assert "saveCommand.execute()" in text

    for name in ("nicegui", "tkinter", "textual"):
        text = (INTEGRATION / f"{name}.md").read_text(encoding="utf-8")
        assert "RelayCommand" in text
        assert "save_command.execute(None)" in text or "_save_command.execute(None)" in text
