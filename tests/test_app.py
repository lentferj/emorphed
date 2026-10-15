# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The wire protocol is transcribed as data from E-mu's own MIDI
# Specification, printed in full as pages 225-250 of the Morpheus
# Operation Manual (E-mu Systems, 1993), and checked against 2176 preset
# dumps the instrument produced. The transport layer is ported from the
# sibling p2ked, x5ded, kwsed, rxved and nanosyned projects.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)

"""The browser. Every fixture is invented; no MIDI port is ever opened."""

import ast
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual.widgets import DataTable

from emorphed.app import VIEW_ALL_FAVOURITES, EmorphedApp
from emorphed.demo import DemoDevice
from emu import banks
from emu import catalog as cat
from emu import favorites as fav
from vinsynlib.ui.modals import RatingFilter


@pytest.fixture
def device() -> DemoDevice:
    return DemoDevice()


@pytest.fixture
def app(device: DemoDevice) -> EmorphedApp:
    return EmorphedApp(device, catalog=cat.empty())


class TestStartup:
    async def test_both_panes_fill(self, app: EmorphedApp) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#bank-table", DataTable).row_count == len(
                banks.REGIONS
            )
            assert app.query_one("#slot-table", DataTable).row_count == 128


class TestCursorIsSilent:
    """The property that decides whether this can sit open next to a
    running sequencer. First test in every sibling project."""

    async def test_moving_in_the_slot_pane_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            for _ in range(12):
                await pilot.press("down")
            await pilot.press("end")
            await pilot.pause()
            assert device.selected_log == []

    async def test_moving_between_regions_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#bank-table").focus()
            for _ in range(len(banks.REGIONS) + 2):
                await pilot.press("down")
            await pilot.pause()
            assert device.selected_log == []

    async def test_reading_names_sends_no_program_change(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(20):
                await pilot.pause()
            assert device.selected_log == []

    async def test_cycling_the_view_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(4):
                await pilot.press("F")
            await pilot.pause()
            assert device.selected_log == []


class TestOnlyPresetsAreSelected:
    """A midimap has no program change. One aimed at it would land on a
    preset instead, so Enter refuses before anything is sent."""

    async def test_enter_on_a_preset_selects(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert len(device.selected_log) == 1
            assert device.selected_log[0][0].kind == banks.Kind.PRESET

    async def test_enter_on_a_midimap_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("M-RAM")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert device.selected_log == []

    async def test_two_selections_in_a_row_send_one(self) -> None:
        """The busy guard is set where it is checked, on the main thread."""
        demo = DemoDevice(latency=0.5)
        app = EmorphedApp(demo, catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            app.action_select()
            app.action_select()
            for _ in range(60):
                await pilot.pause()
            assert len(demo.selected_log) == 1


class TestReadingNames:
    async def test_one_request_fills_every_region_of_that_kind(
        self, app: EmorphedApp
    ) -> None:
        """The reply is one flat list across RAM, ROM and card; splitting
        it back into regions is the only place that mapping exists."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(30):
                await pilot.pause()
            assert app.catalog.live_name("P-RAM", 0, kind="preset") is not None
            assert app.catalog.live_name("P-ROM", 0, kind="preset") is not None

    async def test_a_missing_card_leaves_its_region_empty(
        self, app: EmorphedApp
    ) -> None:
        """The demo has no card, so the reply is short -- which is what a
        missing card looks like, not a fault."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(30):
                await pilot.pause()
            assert app.catalog.live_name("P-CARD", 0, kind="preset") is None


class TestFavouritesActOnTheRowNotThePane:
    async def test_f_uses_the_rows_own_region(self, tmp_path: Path) -> None:
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("P-ROM", 5, name="Invented", rating=3)
        app = EmorphedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_mode = VIEW_ALL_FAVOURITES
            app._fill("P-RAM")  # pane elsewhere; row is P-ROM 5
            await pilot.pause()
            assert [(e.bank_id, e.number) for e in app._current] == [
                ("P-ROM", 5)
            ]
            app.query_one("#slot-table").focus()
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()
            assert store.get("P-RAM", 5) is None, "favourited the wrong region"
            assert store.get("P-ROM", 5) is None, "P-ROM 5 should be off now"
        store.close()


class TestTheDeviceIdIsNotTheChannel:
    """This instrument has both, set in different places on it."""

    async def test_the_picker_rejects_an_out_of_range_id(
        self, app: EmorphedApp
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            before = app.device.device_id
            app.action_pick_device_id()
            await pilot.pause()
            app.screen.dismiss("99")
            for _ in range(4):
                await pilot.pause()
            assert app.device.device_id == before


class TestStructuralRules:
    def _workers(self) -> Iterator[ast.FunctionDef]:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "emorphed",
            "app.py",
        )
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(
                (
                    isinstance(d, ast.Call)
                    and getattr(d.func, "id", "") == "work"
                )
                or getattr(d, "id", "") == "work"
                for d in node.decorator_list
            ):
                yield node

    def test_there_are_workers_to_check(self) -> None:
        assert list(self._workers())

    def test_no_worker_touches_the_store_or_the_catalog(self) -> None:
        """SQLite refuses cross-thread use, and a worker that asks for
        `len(self.favorites)` raises out of the worker, ending the app."""
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Attribute)
                    and inner.attr in ("favorites", "catalog")
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "self"
                ):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} reach self.favorites or "
            f"self.catalog; workers do MIDI and hand off"
        )

    def test_no_worker_sets_the_busy_flag_itself(self) -> None:
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and any(
                        isinstance(t, ast.Attribute) and t.attr == "_busy"
                        for t in inner.targets
                    )
                    and getattr(inner.value, "value", None) is True
                ):
                    offenders.append(node.name)
        assert not offenders, f"worker(s) {offenders} set _busy themselves"


class TestUndoPins:
    def test_busy_undo_refuses(self, app: "EmorphedApp") -> None:
        said = []

        def capture(message: str, refused: bool = False) -> None:
            said.append((message, refused))

        app.notify_status = capture  # type: ignore[method-assign]
        app._busy_gate.refuse("busy")
        app.action_undo()
        assert ("busy", True) in said

    def test_favouriting_pushes_change(self, tmp_path: Path) -> None:
        store = fav.Favorites(str(tmp_path / "f.db"))
        try:
            app = EmorphedApp(
                DemoDevice(), catalog=cat.empty(), favorites=store
            )
            assert app._changes == []
        finally:
            store.close()


class TestRatingFilterPins:
    def test_filter_narrows_the_visible_list(self, tmp_path: Path) -> None:
        store = fav.Favorites(str(tmp_path / "f.db"))
        try:
            bank = banks.region_ids()[0]
            slots = banks.slots(bank)
            store.add(bank, slots[0].number, name="invented 0", rating=3)
            store.add(bank, slots[1].number, name="invented 1", rating=5)
            app = EmorphedApp(
                DemoDevice(), catalog=cat.empty(), favorites=store
            )
            app.rating_filter = RatingFilter(stars=3, at_least=False)
            shown = [e.number for e in app._visible(bank)]
            assert slots[0].number in shown
            # the 5-star slot is filtered out under an exact-3 filter
            assert slots[1].number not in shown
        finally:
            store.close()
