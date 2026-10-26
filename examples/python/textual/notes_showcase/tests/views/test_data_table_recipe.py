"""Executes the DataTable recipe and the ``bind_data_table`` bridge on a running App (#576).

``data_table_recipe.py`` is the exact code shown in
docs/content/integration/textual.md. No conformance-ID markers (integration
recipe).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from vmx import Message, MessageHub

from tests.views.data_table_recipe import Instance, InstanceGrid, InstanceTable

NAMES = ["alpha", "bravo", "charlie", "delta", "echo"]


class RecordingGrid(InstanceGrid):
    """Counts the selections the table asks for."""

    def __init__(self, hub: MessageHub[Message], page_size: int = 0) -> None:
        super().__init__(hub, page_size)
        self.selections: list[str] = []

    def select(self, key: str) -> None:
        self.selections.append(key)
        super().select(key)


class RecordingTable(InstanceTable):
    """Records the thread each row is added on."""

    def __init__(self, grid: InstanceGrid) -> None:
        super().__init__(grid)
        self.add_row_threads: list[int] = []

    def add_row(self, *cells: Any, **options: Any) -> Any:
        self.add_row_threads.append(threading.get_ident())
        return super().add_row(*cells, **options)


class GridApp(App[None]):
    def __init__(self, table: InstanceTable) -> None:
        super().__init__()
        self.table = table
        self.thread_id = 0

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self) -> None:
        self.thread_id = threading.get_ident()


def _grid(names: Iterable[str] = NAMES, page_size: int = 0) -> RecordingGrid:
    grid = RecordingGrid(MessageHub[Message](), page_size)
    for index, name in enumerate(names):
        grid.instances.append(Instance(f"i{index}", name, "up"))
    return grid


def _instance(grid: InstanceGrid, key: str) -> Instance:
    return next(instance for instance in grid.instances if instance.id == key)


def _keys(table: InstanceTable) -> list[str]:
    return [str(row.key.value) for row in table.ordered_rows]


def _cursor_key(table: InstanceTable) -> str:
    return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)


async def _settle(pilot: Pilot[None]) -> None:
    # Two pauses: one for scheduled renders, one for the messages they post.
    await pilot.pause()
    await pilot.pause()


async def test_rows_follow_the_page_and_the_filter() -> None:
    grid = _grid(page_size=2)
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        assert _keys(table) == ["i0", "i1"]
        assert [str(cell) for cell in table.get_row("i0")] == ["alpha", "up"]

        grid.page.move_to_next_page()
        await _settle(pilot)
        assert _keys(table) == ["i2", "i3"]

        grid.filter.model = "e"  # charlie, delta, echo; page 2 holds echo
        await _settle(pilot)
        assert _keys(table) == ["i4"]

    assert grid.selections == []


async def test_an_arrow_move_selects_its_row_once() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        table.focus()
        await pilot.press("down")
        assert grid.selections == ["i1"]
        await pilot.press("down")
        await pilot.press("up")
        await _settle(pilot)

    assert grid.selections == ["i1", "i2", "i1"]
    assert grid.selection.model == "i1"


async def test_rebuilds_the_first_row_and_show_cursor_select_nothing() -> None:
    grid = _grid(names=[], page_size=2)
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        grid.instances.append(Instance("i0", "alpha", "up"))  # the first row's highlight
        await _settle(pilot)
        for index, name in enumerate(NAMES[1:], start=1):
            grid.instances.append(Instance(f"i{index}", name, "up"))
        grid.page.move_to_next_page()
        grid.filter.model = "a"
        await _settle(pilot)
        table.show_cursor = False
        table.show_cursor = True
        await _settle(pilot)

        assert _keys(table) == ["i2", "i3"]

    assert grid.selections == []


async def test_a_rebuild_keeps_the_cursor_on_the_selected_row() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        grid.selection.model = "i3"
        await _settle(pilot)
        assert _cursor_key(table) == "i3"

        grid.filter.model = "d"  # only delta (i3) remains, now on the first row
        await _settle(pilot)
        assert _keys(table) == ["i3"]
        assert _cursor_key(table) == "i3"

        grid.filter.model = ""
        await _settle(pilot)
        assert table.cursor_row == 3

    assert grid.selections == []


async def test_a_removed_selected_row_selects_no_other_row() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        table.focus()
        await pilot.press("down")
        grid.instances.remove(_instance(grid, "i1"))
        await _settle(pilot)

        assert "i1" not in _keys(table)

    assert grid.selections == ["i1"]
    assert grid.selection.model == "i1"


async def test_a_filtered_out_selected_row_selects_no_other_row() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        table.focus()
        await pilot.press("down", "down")
        grid.filter.model = "alpha"
        await _settle(pilot)
        assert _keys(table) == ["i0"]
        assert grid.selections == ["i1", "i2"]

        await pilot.press("down")  # a one-row table has nowhere to move
        await _settle(pilot)
        assert grid.selections == ["i1", "i2"]

        await pilot.press("enter")  # the operator picks the remaining row
        await _settle(pilot)

    assert grid.selections == ["i1", "i2", "i0"]


async def test_enter_selects_the_only_row_of_a_single_row_table() -> None:
    grid = _grid(names=["alpha"])
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        table.focus()
        await pilot.press("enter")
        await pilot.press("enter")  # already selected: nothing more to ask
        await _settle(pilot)

    assert grid.selections == ["i0"]


async def test_a_cell_cursor_selects_the_row_of_the_chosen_cell() -> None:
    grid = _grid(names=["alpha", "bravo"])
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        table.cursor_type = "cell"
        table.focus()
        await pilot.press("right")  # same row: not a selection
        await pilot.press("enter")  # CellSelected on the first row
        await pilot.press("down")
        await _settle(pilot)

    assert grid.selections == ["i0", "i1"]


async def test_a_selection_changed_by_the_vm_moves_the_cursor_without_echo() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        grid.selection.model = "i4"
        await _settle(pilot)
        assert _cursor_key(table) == "i4"

        grid.selection.model = "i9"  # not a visible row: the cursor stays put
        await _settle(pilot)
        assert _cursor_key(table) == "i4"

    assert grid.selections == []


async def test_a_worker_thread_change_is_rendered_on_the_app_thread() -> None:
    grid = _grid()
    table = RecordingTable(grid)
    app = GridApp(table)

    async with app.run_test() as pilot:
        table.add_row_threads.clear()
        worker = threading.Thread(
            target=lambda: grid.instances.append(Instance("i5", "foxtrot", "up"))
        )
        worker.start()
        worker.join()
        await _settle(pilot)

        assert _keys(table) == ["i0", "i1", "i2", "i3", "i4", "i5"]
        assert table.add_row_threads
        assert set(table.add_row_threads) == {app.thread_id}
        assert worker.ident not in table.add_row_threads


async def test_dispose_stops_rendering_and_selecting_and_restores_the_table() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        assert table._binding is not None
        grid.filter.model = "a"  # schedules a render, then the binding goes away
        table._binding.dispose()
        table._binding.dispose()  # idempotent
        grid.instances.append(Instance("i5", "foxtrot", "up"))
        table.focus()
        await pilot.press("down", "enter")
        await _settle(pilot)

        assert _keys(table) == ["i0", "i1", "i2", "i3", "i4"]
        assert "watch_cursor_coordinate" not in vars(table)
        assert "post_message" not in vars(table)

    assert grid.selections == []


async def test_unmount_disposes_the_binding_and_leaves_the_grid_to_its_owner() -> None:
    grid = _grid()
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        await table.remove()
        await _settle(pilot)
        assert table._binding is None

        grid.instances.append(Instance("i5", "foxtrot", "up"))
        grid.selection.model = "i5"
        await _settle(pilot)

    assert grid.selection.model == "i5"
    grid.dispose()


async def test_a_filter_that_removes_the_current_page_shows_the_last_page() -> None:
    grid = _grid(page_size=2)
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        grid.page.move_to_last_page()  # page 2 holds echo
        await _settle(pilot)
        assert _keys(table) == ["i4"]

        grid.filter.model = "a"  # alpha, bravo, charlie, delta: two pages
        await _settle(pilot)

        assert grid.page.current_page_index == 1
        assert _keys(table) == ["i2", "i3"]


async def test_removing_instances_past_the_current_page_shows_the_last_page() -> None:
    grid = _grid(page_size=2)
    table = InstanceTable(grid)

    async with GridApp(table).run_test() as pilot:
        grid.page.move_to_last_page()
        await _settle(pilot)

        grid.instances.remove(_instance(grid, "i4"))  # page 2 no longer exists
        await _settle(pilot)
        assert grid.page.current_page_index == max(0, grid.page.page_count - 1) == 1
        assert _keys(table) == ["i2", "i3"]

        for key in ("i3", "i2", "i1"):
            grid.instances.remove(_instance(grid, key))
        await _settle(pilot)
        assert grid.page.current_page_index == max(0, grid.page.page_count - 1) == 0
        assert _keys(table) == ["i0"]

        grid.instances.remove(_instance(grid, "i0"))  # no pages left
        await _settle(pilot)
        assert grid.page.page_count == 0
        assert grid.page.current_page_index == 0
        assert _keys(table) == []
