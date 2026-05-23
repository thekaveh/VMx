"""Smoke test — app boots and tears down cleanly."""

from __future__ import annotations

import pytest

from vmx_inspector.app import VMxInspectorApp


@pytest.mark.asyncio
async def test_app_boots_and_exits() -> None:
    app = VMxInspectorApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
