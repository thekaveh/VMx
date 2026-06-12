"""Smoke tests — boot/teardown plus real-wiring regressions.

The boot test alone masked a dead message log (call_from_thread raised on
the app thread, the hub swallowed the error per HUB-007, and nothing was
rendered); the real-wiring test drives keys and asserts rendered state.
"""

from __future__ import annotations

import pytest

from vmx_inspector.app import VMxInspectorApp


@pytest.mark.asyncio
async def test_app_boots_and_exits() -> None:
    app = VMxInspectorApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()


@pytest.mark.asyncio
async def test_lifecycle_keys_feed_the_message_log_and_refresh_labels() -> None:
    """Pressing a lifecycle key must produce hub-message rows in the log
    and refresh the affected tree label (real-wiring audit, pass 7)."""
    from textual.widgets import DataTable, Tree

    app = VMxInspectorApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table.row_count == 0

        await pilot.press("down")
        await pilot.press("d")  # destruct the highlighted VM
        for _ in range(4):
            await pilot.pause()

        assert table.row_count > 0, "hub messages must reach the log"
        tree = app.query_one(Tree)

        def _labels(node) -> list[str]:
            out = [str(node.label)]
            for child in node.children:
                out.extend(_labels(child))
            return out

        assert any("DESTRUCTED" in label for label in _labels(tree.root)), (
            "tree labels must refresh on lifecycle changes"
        )
