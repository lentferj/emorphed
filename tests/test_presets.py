# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
"""Tests for PresetPickerScreen."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable

from emorphed.screens import (
    VIEW_ALL,
    VIEW_ALL_FAVOURITES,
    VIEW_BANK_FAVOURITES,
    VIEW_CYCLE,
    PresetPickerScreen,
)
from emu import catalog, favorites


class MiniApp(App[None]):
    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_bank_list_is_five_regions_in_order() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        screen = PresetPickerScreen(
            catalog.empty(), favorites=favorites.Favorites(":memory:")
        )
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#picker-banks", DataTable)
        assert table.row_count == 5  # noqa: PLR2004
        keys = [
            str(
                table.coordinate_to_cell_key(
                    __import__(
                        "textual.coordinate", fromlist=["Coordinate"]
                    ).Coordinate(i, 0)
                )[0].value
            )
            for i in range(table.row_count)
        ]
        assert keys == ["P-RAM", "P-ROM", "H-RAM", "P-CARD", "H-CARD"]


@pytest.mark.asyncio
async def test_v_cycles_three_views() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        screen = PresetPickerScreen(
            catalog.empty(), favorites=favorites.Favorites(":memory:")
        )
        app.push_screen(screen)
        await pilot.pause()
        assert screen.view == 0
        assert VIEW_CYCLE[screen.view] == VIEW_ALL
        await pilot.press("v")
        await pilot.pause()
        assert screen.view == 1
        assert VIEW_CYCLE[screen.view] == VIEW_BANK_FAVOURITES
        await pilot.press("v")
        await pilot.pause()
        assert screen.view == 2  # noqa: PLR2004
        assert VIEW_CYCLE[screen.view] == VIEW_ALL_FAVOURITES
        await pilot.press("v")
        await pilot.pause()
        assert screen.view == 0


@pytest.mark.asyncio
async def test_confirm_returns_bank_and_number() -> None:
    app = MiniApp()
    result: dict[str, Any] = {}
    async with app.run_test() as pilot:
        screen = PresetPickerScreen(
            catalog.empty(), favorites=favorites.Favorites(":memory:")
        )
        app.push_screen(screen, lambda r: result.setdefault("r", r))
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        slots = screen.query_one("#picker-slots", DataTable)
        slots.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert result["r"] == (0, 0)


@pytest.mark.asyncio
async def test_cancel_returns_none() -> None:
    app = MiniApp()
    result: dict[str, Any] = {}
    async with app.run_test() as pilot:
        screen = PresetPickerScreen(
            catalog.empty(), favorites=favorites.Favorites(":memory:")
        )
        app.push_screen(screen, lambda r: result.setdefault("r", r))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert result["r"] is None

    app2 = MiniApp()
    result2: dict[str, Any] = {}
    async with app2.run_test() as pilot:
        screen2 = PresetPickerScreen(
            catalog.empty(), favorites=favorites.Favorites(":memory:")
        )
        app2.push_screen(screen2, lambda r: result2.setdefault("r", r))
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert result2["r"] is None


@pytest.mark.asyncio
async def test_favourite_only_view_lists_marked_slots() -> None:
    favs = favorites.Favorites(":memory:")
    favs.add("P-RAM", 5)
    favs.add("P-RAM", 9)
    app = MiniApp()
    async with app.run_test() as pilot:
        screen = PresetPickerScreen(catalog.empty(), favs)
        app.push_screen(screen)
        await pilot.pause()
        slots = screen.query_one("#picker-slots", DataTable)
        assert slots.row_count == 128  # noqa: PLR2004
        await pilot.press("v")
        await pilot.pause()
        slots = screen.query_one("#picker-slots", DataTable)
        assert slots.row_count == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_modal_scales() -> None:
    widths: dict[int, int] = {}
    for terminal_width in (80, 140):
        app = MiniApp()
        async with app.run_test(size=(terminal_width, 30)) as pilot:
            screen = PresetPickerScreen(
                catalog.empty(), favorites=favorites.Favorites(":memory:")
            )
            app.push_screen(screen)
            await pilot.pause()
            widths[terminal_width] = screen.query_one(Vertical).size.width
    assert widths[80] < 80  # noqa: PLR2004
    assert widths[140] > 100  # noqa: PLR2004
