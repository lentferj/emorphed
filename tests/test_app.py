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
import asyncio
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from textual.pilot import Pilot
from textual.widgets import DataTable, Static
from textual.worker import WorkerFailed

from emorphed.app import (
    VIEW_ALL,
    VIEW_ALL_FAVOURITES,
    VIEW_BANK_FAVOURITES,
    EmorphedApp,
)
from emorphed.demo import DemoDevice, _seed_midimap
from emorphed.scan import ScanScreen
from emorphed.screens import (
    KeyHints,
    MidimapPickerScreen,
    ReportScreen,
)
from emu import backup as bk
from emu import banks, config
from emu import catalog as cat
from emu import favorites as fav
from emu import midimap as mm
from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.modals import RatingFilter


@pytest.fixture
def device() -> DemoDevice:
    return DemoDevice()


@pytest.fixture
def app(device: DemoDevice) -> EmorphedApp:
    return EmorphedApp(device, catalog=cat.empty())


class InterleaveDemo(DemoDevice):
    """A demo whose MIDI calls are slow enough to overlap on purpose.

    It counts how many calls are inside the device at once, so a test can
    tell "one exchange at a time" (peak 1) from two workers driving the
    same device together (peak 2).
    """

    def __init__(self, delay: float = 0.2) -> None:
        super().__init__()
        self.delay = delay
        self._count_lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def _enter(self) -> None:
        with self._count_lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def _exit(self) -> None:
        with self._count_lock:
            self.active -= 1

    def names(
        self, kind: str = banks.Kind.PRESET, *, timeout: float | None = None
    ) -> list[str]:
        self._enter()
        try:
            time.sleep(self.delay)
            return super().names(kind, timeout=timeout)
        finally:
            self._exit()

    def select(self, target: banks.Slot) -> None:
        self._enter()
        try:
            time.sleep(self.delay)
            super().select(target)
        finally:
            self._exit()

    def select_midimap(self, number: int) -> None:
        self._enter()
        try:
            time.sleep(self.delay)
            super().select_midimap(number)
        finally:
            self._exit()


class Boom(Exception):
    """Not in ``_BRIDGE_ERRORS``, so the worker's ``finally`` is the guard."""


class ExplodingDemo(InterleaveDemo):
    """A device whose ``select`` raises past the worker's error handling."""

    def select(self, target: banks.Slot) -> None:
        self._enter()
        try:
            raise Boom("synthetic select failure")
        finally:
            self._exit()

    def select_midimap(self, number: int) -> None:
        self._enter()
        try:
            raise Boom("synthetic select failure")
        finally:
            self._exit()


class CountingLock:
    """A ``threading.Lock`` that counts releases, for the scan test."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.releases = 0

    def acquire(self, blocking: bool = True) -> bool:
        return bool(self._lock.acquire(blocking=blocking))

    def release(self) -> None:
        self.releases += 1
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


def _app_with(device: DemoDevice, tmp_path: Path) -> EmorphedApp:
    return EmorphedApp(
        device,
        catalog=cat.empty(),
        config_path=str(tmp_path / "config.toml"),
    )


def _capture(app: EmorphedApp) -> list[tuple[str, bool]]:
    """Record every status message the app reports from now on."""
    said: list[tuple[str, bool]] = []
    original = app.notify_status

    def capture(message: str, *, refused: bool = False) -> None:
        said.append((message, refused))
        original(message, refused=refused)

    app.notify_status = capture  # type: ignore[method-assign]
    return said


async def _settle(
    app: EmorphedApp, pilot: Pilot[None], tries: int = 400
) -> None:
    """Wait until the app reports no exchange in flight."""
    for _ in range(tries):
        if not app._busy:
            return
        await asyncio.sleep(0.01)
        await pilot.pause()


async def _wait_for_live(
    app: EmorphedApp, pilot: Pilot[None], tries: int = 400
) -> None:
    """Wait until a read has landed a live name on the main thread."""
    for _ in range(tries):
        if app.catalog.live_name("P-RAM", 0) is not None:
            return
        await asyncio.sleep(0.01)
        await pilot.pause()


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
                await pilot.press("v")
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

    async def test_enter_on_a_midimap_opens_a_confirmation(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("M-RAM")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert device.selected_log == []
            assert device.selected_midimaps == []

    async def test_confirming_makes_the_midimap_current(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("M-RAM")
            await pilot.pause()
            table = app.query_one("#slot-table", DataTable)
            table.move_cursor(row=3)
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            for _ in range(20):
                await pilot.pause()
            assert device.selected_midimaps == [3]
            assert device.selected_log == []

    async def test_cancelling_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("M-RAM")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("n")
            for _ in range(8):
                await pilot.pause()
            assert device.selected_midimaps == []
            assert device.selected_log == []

    async def test_enter_on_a_midimap_sends_nothing_before_confirming(
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
            assert device.selected_midimaps == []
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


class TestHyperpresetSelectable:
    async def test_enter_on_a_hyperpreset_selects(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("H-RAM")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            _capture(app)
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert len(device.selected_log) == 1
            assert device.selected_log[0][0].kind == banks.Kind.HYPERPRESET
            assert device.selected_midimaps == []


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
            assert app.catalog.live_name("P-RAM", 0) is not None
            assert app.catalog.live_name("P-ROM", 0) is not None

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
            assert app.catalog.live_name("P-CARD", 0) is None


class TestPrintedNamesComeBack:
    """The key grammar is kindless on both front ends, so a printed name
    reaches the browser before anything has been read off the unit."""

    async def test_a_printed_name_shows_before_any_read(self) -> None:
        catalog = cat.Catalog([cat.Entry("P-RAM", 0, "Invented Name")])
        app = EmorphedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#slot-table", DataTable)
            assert table.get_cell("P-RAM:000", "name") == "Invented Name"

    async def test_a_live_name_wins_and_is_marked(self) -> None:
        catalog = cat.Catalog([cat.Entry("P-RAM", 0, "Invented Name")])
        catalog.set_live_name("P-RAM", 0, "Other")
        app = EmorphedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#slot-table", DataTable)
            shown = table.get_cell("P-RAM:000", "name")
            assert "Other" in shown
            assert "*" in shown
            assert "Invented Name" not in shown


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


class TestOneExchangeAtATime:
    """Two workers must never drive the device at once.

    The shared gate refuses on the main thread, but entering the gate
    clears that refusal -- so a worker that consumes its own reservation
    leaves a window where both ``check()`` and ``is_busy()`` are clear.
    The exchange claim closes it: the main thread takes it before
    spawning and the worker releases it in a ``finally``.
    """

    async def test_a_read_while_selecting_is_refused(
        self, tmp_path: Path
    ) -> None:
        device = InterleaveDemo()
        app = _app_with(device, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            said = _capture(app)
            app.action_select()
            app.action_read_names()
            await _settle(app, pilot)
            assert ("busy", True) in said
            assert len(device.selected_log) == 1
            assert device.peak == 1

    async def test_a_select_while_reading_is_refused(
        self, tmp_path: Path
    ) -> None:
        device = InterleaveDemo()
        app = _app_with(device, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            said = _capture(app)
            app.action_read_names()
            app.action_select()
            await _settle(app, pilot)
            assert ("busy", True) in said
            assert device.selected_log == []
            assert device.peak == 1

    async def test_a_cancelled_scan_releases_once(
        self, tmp_path: Path
    ) -> None:
        device = InterleaveDemo()
        app = _app_with(device, tmp_path)
        counting = CountingLock()
        app._exchange = cast("threading.Lock", counting)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            for _ in range(100):
                if isinstance(app.screen, ScanScreen):
                    break
                await pilot.pause()
            assert isinstance(app.screen, ScanScreen)
            app.screen.action_cancel()
            await _settle(app, pilot)
            assert not counting.locked()
            assert counting.releases == 1
            said = _capture(app)
            app.action_read_names()
            await _settle(app, pilot)
            assert ("busy", True) not in said
            assert counting.releases == 2

    async def test_the_lock_survives_an_uncaught_select_error(
        self, tmp_path: Path
    ) -> None:
        device = ExplodingDemo()
        app = _app_with(device, tmp_path)
        # The error is not in _BRIDGE_ERRORS, so it reaches the worker's
        # finally and then surfaces (wrapped) when the app shuts down. The
        # claim must be free either way.
        with pytest.raises(WorkerFailed) as caught:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#slot-table").focus()
                await pilot.pause()
                app.action_select()
                for _ in range(200):
                    if not app._exchange.locked():
                        break
                    await pilot.pause()
                assert not app._exchange.locked()
                said = _capture(app)
                app.action_read_names()
                await _wait_for_live(app, pilot)
                assert ("busy", True) not in said
                assert app.catalog.live_name("P-RAM", 0) is not None
        assert "synthetic select failure" in str(caught.value)

    async def test_device_info_works_when_idle(self, tmp_path: Path) -> None:
        """`i` now claims the exchange too; an idle press still reports."""
        device = DemoDevice()
        app = _app_with(device, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_device_info()
            for _ in range(200):
                if isinstance(app.screen, ReportScreen):
                    break
                await pilot.pause()
            assert isinstance(app.screen, ReportScreen)
            assert not app._exchange.locked()


class TestMidimapAppWriteGateAndStore:
    async def test_gate_locked_edit_sends_nothing(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            said: list[tuple[str, bool]] = []
            original_say = screen.say

            def captured_say(message: str, *, refused: bool = False) -> None:
                said.append((message, refused))
                original_say(message, refused=refused)

            screen.say = captured_say
            before = len(device.parameter_writes)
            screen.action_nudge_up()
            await pilot.pause()
            assert len(device.parameter_writes) == before
            assert any("write gate is locked" in msg for msg, _ in said)

            screen.action_toggle_write_gate()
            await pilot.pause()
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) == before + 1

    async def test_backup_failure_announced_write_proceeds_flag_stays_false(
        self,
        app: EmorphedApp,
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[bool] = []

        def boom(*args: Any, **kwargs: Any) -> Any:
            calls.append(True)
            raise RuntimeError("backup boom")

        monkeypatch.setattr(bk, "save_midimap", boom)
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            screen.action_toggle_write_gate()
            before = len(device.parameter_writes)
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert calls == [True]
            assert len(device.parameter_writes) == before + 1
            assert app._midimap_backed_up is False
            assert any("could not back up" in msg for msg, _ in said)

            stores_before = len(device.midimap_stores)
            app._store_midimap()
            await pilot.pause()
            assert len(device.midimap_stores) == stores_before
            assert any("store refused" in msg for msg, _ in said)

    async def test_store_opens_the_midimap_picker_then_confirms(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_midimap()
            await pilot.pause()
            # a browser of the midimaps, by bank and name -- not a number
            assert isinstance(app.screen, MidimapPickerScreen)
            assert len(device.midimap_stores) == stores_before
            await pilot.press("tab")  # the slot pane
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            confirm = cast(Any, app.screen)
            assert "STORE to M" in confirm.prompt_text
            assert "erases" in confirm.prompt_text
            assert len(device.midimap_stores) == stores_before
            await pilot.press("escape")
            await pilot.pause()

    async def test_write_holds_exchange_lock(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        device.latency = 0.2
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            screen.action_toggle_write_gate()
            await pilot.pause()
            before = len(device.parameter_writes)
            screen.action_nudge_up()
            await pilot.pause(0)
            capture_list: list[tuple[str, bool]] = []
            original_notify = app.notify_status

            def capture(message: str, *, refused: bool = False) -> None:
                capture_list.append((message, refused))
                original_notify(message, refused=refused)

            app.notify_status = capture  # type: ignore[method-assign]
            screen.action_nudge_up()
            await pilot.pause()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) == before + 1

    async def test_store_confirmed_runs_worker_and_records_one_send(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        words = [5] * 360
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_confirmed(2, words, True)
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.midimap_stores) - stores_before == 1
            assert device.midimap_stores[-1][0] == 2
            messages = [m for m, _ in said]
            assert any("stored to M02" in m for m in messages), messages
            assert any("survives a power cycle" in m for m in messages), (
                messages
            )
            assert any("read back 360/360 words" in m for m in messages), (
                messages
            )

    async def test_store_readback_disagreement_is_refused(
        self,
        app: "EmorphedApp",
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app._midimap_backed_up = True
        words = [5] * 360

        def changed(index: int, *, timeout: float | None = None) -> list[int]:
            out = list(words)
            out[0] = 999
            return out

        monkeypatch.setattr(device, "read_midimap", changed)
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_confirmed(2, words, True)
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.midimap_stores) - stores_before == 1
            messages = [m for m, _ in said]
            assert any("disagree" in m.lower() for m in messages), messages
            assert not any(
                "(read back 360/360 words agree)" in m for m in messages
            ), messages
            assert any(
                refused and "disagree" in msg.lower() for msg, refused in said
            ), said

    async def test_store_confirmed_false_sends_nothing(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        words = [5] * 360
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_confirmed(2, words, False)
            await pilot.pause()
            assert len(device.midimap_stores) == stores_before

    async def test_store_confirmed_none_sends_nothing(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        words = [5] * 360
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_confirmed(2, words, None)
            await pilot.pause()
            assert len(device.midimap_stores) == stores_before

    async def test_cancelling_the_midimap_picker_stores_nothing(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_midimap()
            await pilot.pause()
            assert isinstance(app.screen, MidimapPickerScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmScreen)
            assert len(device.midimap_stores) == stores_before


class TestStartupSaysWhereTheNamesCameFrom:
    """The status line counted only the printed layer.

    With the sidecar full (names read off the unit survive a restart) the
    browser still said "no catalog" on every launch, and the scan offer came
    back every time, because both looked at the printed layer alone.
    """

    async def test_live_names_are_not_reported_as_no_catalog(self) -> None:
        catalog = cat.empty()
        catalog.set_live_name("P-RAM", 0, "Invented Name")
        app = EmorphedApp(DemoDevice(), catalog=catalog)
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
        messages = [message for message, _ in said]
        assert not any("no catalog" in message for message in messages), (
            messages
        )
        assert any("1 names read from the unit" in m for m in messages), (
            messages
        )

    async def test_the_offer_stays_away_when_live_names_exist(self) -> None:
        catalog = cat.empty()
        catalog.set_live_name("P-RAM", 0, "Invented Name")
        app = EmorphedApp(DemoDevice(), catalog=catalog, offer_scan=True)
        pushed: list[Any] = []
        original = app.push_screen

        def record(screen: Any, *rest: Any, **kwargs: Any) -> Any:
            pushed.append(type(screen).__name__)
            return original(screen, *rest, **kwargs)

        app.push_screen = record  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
        assert "ScanOfferScreen" not in pushed, pushed

    async def test_both_layers_are_counted(self) -> None:
        catalog = cat.Catalog([cat.Entry("P-ROM", 0, "Printed")])
        catalog.set_live_name("P-RAM", 0, "Invented Name")
        app = EmorphedApp(DemoDevice(), catalog=catalog)
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
        messages = [message for message, _ in said]
        assert any(
            "1 names from the catalog" in m and "1 read from the unit" in m
            for m in messages
        ), messages


class TestMidimapParamUndo:
    async def test_param_write_armed_then_z_restores_previous_value(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            said = _capture(app)
            writes_before = len(device.parameter_writes)
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 1
            param, written = device.parameter_writes[-1]
            assert written != 0
            # The demo seed's channel-1 Ch. Program is 0, so undo must put
            # the seed's value back rather than a bare zero.
            seeded_old = _seed_midimap()[param - mm.PARAM_BASE]

            writes_before2 = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before2 == 1
            assert device.parameter_writes[-1][0] == param
            assert device.parameter_writes[-1][1] == seeded_old
            assert device.read_parameter(param) == seeded_old
            assert not any(refused for _, refused in said), said
            assert app._changes == []

            # a second undo writes nothing more and reports nothing to undo
            said2 = _capture(app)
            writes_before3 = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) == writes_before3
            assert any("nothing to undo" in m for m, _ in said2), said2

            # z then Z does not re-apply the nudged value
            app.action_undo_all()
            await _settle(app, pilot)
            await pilot.pause()
            assert device.read_parameter(param) == seeded_old


class TestMidimapCurrentIndexAndScratch:
    async def test_current_midimap_none_then_number(
        self, device: DemoDevice
    ) -> None:
        assert device.current_midimap is None
        device.select_midimap(7)
        assert device.current_midimap == 7

    async def test_editor_open_assumed_when_none(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        assert device.current_midimap is None
        said = _capture(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            messages = [m for m, _ in said]
            assert any("assumed" in m for m in messages), messages

    async def test_r_re_reads_scratch_not_stored_dump(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        device.write_parameter(2048, 7)
        device.write_parameter(2049, 42)
        device.parameter_reads.clear()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            before_reads = len(device.parameter_reads)
            before_stores = len(device.midimap_stores)
            before_midimap_reads = len(device.midimap_reads)
            screen.action_re_read()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_reads) - before_reads == 360
            # Not a 0x46 stored dump: no new midimap read/store happened.
            assert len(device.midimap_stores) == before_stores
            assert len(device.midimap_reads) == before_midimap_reads
            assert getattr(screen, "_values", {}).get(0) == 7
            assert getattr(screen, "_values", {}).get(1) == 42
            said_status = None
            try:
                said_status = str(
                    screen.query_one(".status", Static).renderable
                )
            except Exception:
                said_status = None
            if said_status is not None:
                assert (
                    "re-read the scratch" in said_status
                    or "did not answer" in said_status
                )


class TestMidimapNameWrite:
    async def test_name_write_locked_gate_zero_writes(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            writes_before = len(device.parameter_writes)
            said = _capture(app)
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 0
            assert any("write gate is locked" in m for m, _ in said)

    async def test_name_write_armed_gate_twelve_writes_agreement(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            writes_before = len(device.parameter_writes)
            reads_before = len(device.parameter_reads)
            said = _capture(app)
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 12
            assert len(device.parameter_reads) - reads_before == 12
            messages = [m for m, _ in said]
            assert any("agree" in m for m in messages), messages
            assert screen._values.get(0) == ord("H")
            assert screen._values.get(1) == ord("i")

    async def test_name_write_armed_write_then_z_restores_same_gate(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            # undo restores the previous name, through the same gate
            writes_before2 = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before2 == 12

    async def test_name_write_undo_refused_when_locked(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            app._gate.toggle()  # lock again
            writes_before = len(device.parameter_writes)
            said = _capture(app)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 0
            assert any("write gate is locked" in m for m, _ in said)

    async def test_name_write_invalid_char_refused_32_127(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm, so only the range check refuses
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            writes_before = len(device.parameter_writes)
            said = _capture(app)
            app._apply_midimap_name(chr(1))
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 0
            assert any("32-127" in m for m, _ in said)

    async def test_name_write_readback_disagreement_records_nothing(
        self,
        app: "EmorphedApp",
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            words_before = list(app._current_midimap_words[:12])
            original_read = device.read_parameter
            calls = {"n": 0}

            def fake(param_id: int) -> int:
                calls["n"] += 1
                if calls["n"] == 1:
                    return 9999
                return cast(int, original_read(param_id))

            monkeypatch.setattr(device, "read_parameter", fake)
            said = _capture(app)
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            messages = [m for m, _ in said]
            assert any("disagreed" in m.lower() for m in messages), messages
            assert app._changes == []
            assert app._current_midimap_words[:12] == words_before


class TestTheBrowserRemembersWhereItWas:
    """The window opens where it was left: bank, slot cursor, and both
    cycling views (`v`, emorphed's spelling of the family's `favourites
    view` key, and `k`), through the one `_save_ui_state` helper, with
    :data:`config.UNSET` meaning "leave this key alone"."""

    def _app(self, config_path: str | None, **kwargs: Any) -> EmorphedApp:
        return EmorphedApp(
            DemoDevice(),
            catalog=cat.empty(),
            config_path=config_path,
            **kwargs,
        )

    async def test_bank_slot_and_both_cycles_come_back(
        self, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("H-RAM", 3, name="Invented")
        try:
            first = self._app(path, favorites=store)
            async with first.run_test() as pilot:
                await pilot.pause()
                await pilot.press("k")  # hyperpreset
                await pilot.press("v")  # bank favourites
                await pilot.pause()
                first.query_one("#bank-table").focus()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")  # P-CARD
                await pilot.pause()
            second = self._app(path, favorites=store)
            async with second.run_test() as pilot:
                await pilot.pause()
                assert second.kind_view == banks.Kind.HYPERPRESET
                assert second.view_mode == VIEW_BANK_FAVOURITES
                assert second._current_bank == banks.region_ids()[2]
                bank_table = second.query_one("#bank-table", DataTable)
                assert bank_table.cursor_row == 2
                assert bank_table.has_focus
        finally:
            store.close()

    async def test_a_saved_slot_row_and_pane_come_back(
        self, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")
        first = self._app(path)
        async with first.run_test() as pilot:
            await pilot.pause()
            slot_table = first.query_one("#slot-table", DataTable)
            slot_table.focus()
            await pilot.pause()
            for _ in range(6):
                await pilot.press("down")
            await pilot.pause()
            assert slot_table.cursor_row == 6
        second = self._app(path)
        async with second.run_test() as pilot:
            await pilot.pause()
            slot_table = second.query_one("#slot-table", DataTable)
            assert slot_table.cursor_row == 6
            assert slot_table.has_focus

    async def test_a_saved_slot_row_is_clamped_to_the_list(
        self, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")
        config.save_ui_state("slot_cursor", 400, path)
        app = self._app(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            slot_table = app.query_one("#slot-table", DataTable)
            # P-RAM holds 128 slots; 400 clamps to the last row.
            assert slot_table.cursor_row == slot_table.row_count - 1
            assert slot_table.has_focus

    async def test_garbage_stored_values_leave_the_defaults(
        self, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")
        config.save_ui_state("bank_index", 999, path)
        config.save_ui_state("view_mode", "nope", path)
        config.save_ui_state("kind_view", "nope", path)
        app = self._app(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view_mode == VIEW_ALL
            assert app.kind_view == banks.Kind.PRESET
            assert app._current_bank == banks.region_ids()[0]
            assert app.query_one("#bank-table", DataTable).cursor_row == 0
            assert app.query_one("#bank-table", DataTable).has_focus

    async def test_no_config_path_runs_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        store_dir = tmp_path.parent / "elsewhere"
        store_dir.mkdir()
        store = fav.Favorites(str(store_dir / "f.db"))
        store.add("H-RAM", 3, name="Invented")
        try:
            app = self._app(None, favorites=store)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#bank-table").focus()
                await pilot.press("down")
                await pilot.pause()
                app.query_one("#slot-table").focus()
                await pilot.pause()
                await pilot.press("down")
                await pilot.press("v")
                await pilot.pause()
                await pilot.press("k")
                for _ in range(4):
                    await pilot.pause()
                assert app.view_mode == VIEW_BANK_FAVOURITES
                assert app.kind_view == banks.Kind.HYPERPRESET
        finally:
            store.close()
        assert list(tmp_path.iterdir()) == [], "a test wrote into the checkout"

    async def test_the_rating_filter_keeps_its_keys(
        self, tmp_path: Path
    ) -> None:
        """Saving the browser state forwards only what it is given:
        :data:`config.UNSET` on the four browser keys leaves the rating
        filter's two keys in the file untouched."""
        path = str(tmp_path / "config.toml")
        config.save_ui_state("rating_stars", 2, path)
        config.save_ui_state("rating_at_least", True, path)
        store = fav.Favorites(str(tmp_path / "f.db"))
        try:
            first = self._app(path, favorites=store)
            assert first.rating_filter is not None
            assert first.rating_filter.stars == 2
            async with first.run_test() as pilot:
                await pilot.pause()
                first.query_one("#bank-table").focus()
                await pilot.press("down")
                await pilot.press("v")
                await pilot.press("k")
                for _ in range(4):
                    await pilot.pause()
            second = self._app(path, favorites=store)
            async with second.run_test():
                await asyncio.sleep(0)
                assert second.rating_filter is not None
                assert second.rating_filter.stars == 2
                assert second.rating_filter.at_least
        finally:
            store.close()
        assert config.load_ui_int("rating_stars", path) == 2
        assert config.load_ui_bool("rating_at_least", path) is True


class TestGroupPUndoAndReadback:
    async def test_undo_two_nudges_one_lands_one_pushed_back(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            await pilot.pause()
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=3, column=2
            )
            await pilot.pause()
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(app._changes) == 2

            said = _capture(app)
            writes_before = len(device.parameter_writes)
            app.action_undo_all()
            await pilot.pause()
            assert len(app._changes) == 1
            assert any("could not be applied" in m for m, _ in said), said
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) == writes_before + 1

            # a later undo applies the remaining one
            said2 = _capture(app)
            writes_before2 = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) == writes_before2 + 1
            assert app._changes == []
            assert not any("could not be applied" in m for m, _ in said2), (
                said2
            )

    async def test_undo_under_locked_gate_survives(
        self, app: "EmorphedApp", device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            await pilot.pause()
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(app._changes) == 1
            app._gate.toggle()  # lock
            said = _capture(app)
            writes_before = len(device.parameter_writes)
            app.action_undo()
            await pilot.pause()
            assert len(device.parameter_writes) == writes_before
            assert any("write gate is locked" in m for m, _ in said), said
            assert len(app._changes) == 1

    async def test_silent_readback_not_logged(
        self,
        app: "EmorphedApp",
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app._gate.toggle()  # arm
        monkeypatch.setattr(device, "read_parameter", lambda _p: None)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            screen.action_toggle_all_channels()
            await pilot.pause()
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=2, column=2
            )
            await pilot.pause()
            said = _capture(app)
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert app._changes == []
            assert any("stayed silent" in m for m, _ in said), said


class TestChannelPreset:
    """A channel's preset is the bank word and the program word together."""

    async def test_a_pair_write_lands_bank_then_program(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            before = len(device.parameter_writes)
            assert app._apply_channel_preset(1, 2, 5) is True
            await _settle(app, pilot)
            await pilot.pause()
            assert device.parameter_writes[before:] == [
                (mm.PARAM_BASE + mm.channel_bank_offset(1), 2),
                (mm.PARAM_BASE + mm.channel_program_offset(1), 5),
            ]
            assert len(app._changes) == 1

    async def test_a_locked_gate_refuses_the_pair(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            before = len(device.parameter_writes)
            said = _capture(app)
            assert app._apply_channel_preset(1, 2, 5) is False
            await pilot.pause()
            assert len(device.parameter_writes) == before
            assert any(refused for _, refused in said), said

    async def test_a_disagreed_pair_is_not_logged(
        self,
        app: EmorphedApp,
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app._gate.toggle()  # arm
        program_param = mm.PARAM_BASE + mm.channel_program_offset(1)
        original = device.read_parameter

        def fake(param: int) -> int | None:
            if param == program_param:
                return 99  # the program read-back disagrees
            return original(param)

        monkeypatch.setattr(device, "read_parameter", fake)
        async with app.run_test() as pilot:
            await pilot.pause()
            said = _capture(app)
            assert app._apply_channel_preset(1, 2, 5) is True
            await _settle(app, pilot)
            await pilot.pause()
            assert app._changes == []
            assert any("disagreed" in m for m, _ in said), said

    async def test_one_undo_restores_both_words(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply_channel_preset(1, 2, 5)
            await _settle(app, pilot)
            await pilot.pause()
            before = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert device.parameter_writes[before:] == [
                (mm.PARAM_BASE + mm.channel_bank_offset(1), 0),
                (mm.PARAM_BASE + mm.channel_program_offset(1), 0),
            ]
            assert app._changes == []

    async def test_plus_on_a_channel_summary_writes_the_pair(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            table = screen.query_one("#midimap-table", DataTable)
            table.move_cursor(row=screen._ordered.index("ch1"), column=0)
            await pilot.pause()
            before = len(device.parameter_writes)
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - before == 2
            # the async write must not throw the cursor to the top-left cell
            assert screen._current_row() == "ch1"


class TestRefusalsAreVisible:
    """A refusal is a red bar, not the same grey as a success (rxved)."""

    async def test_a_refusal_marks_the_status_widget(
        self, app: EmorphedApp
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            status = app.query_one("#status", Static)
            app.notify_status("the write gate is locked", refused=True)
            await pilot.pause()
            assert status.has_class("refused")
            app.notify_status("all good")
            await pilot.pause()
            assert not status.has_class("refused")


class TestTheFooterFitsItsText:
    """The footer is a wrapped legend, not a fixed band.

    The library re-wraps the hints but never asks for a layout, so the first
    render -- before the widget has a width -- laid the whole legend out at
    the minimum width and left the footer that tall until the terminal was
    resized. The view then wasted half the screen on a few keys.
    """

    async def test_the_footer_is_a_few_lines_not_a_band(self) -> None:
        app = EmorphedApp(DemoDevice())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            hints = app.query_one(KeyHints)
            assert hints.size.height <= 4

    async def test_the_footer_reflows_when_the_terminal_changes(self) -> None:
        app = EmorphedApp(DemoDevice())
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            wide = app.query_one(KeyHints).size.height
            await pilot.resize_terminal(70, 40)
            await pilot.pause()
            narrow = app.query_one(KeyHints).size.height
        assert narrow > wide


class TestTheStorePersists:
    """A scratch edit is lost on a power cycle until it is stored (``s``)."""

    async def test_a_rename_backs_up_so_the_store_is_allowed(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm the write gate
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            assert app._midimap_backed_up is False
            app._apply_midimap_name("Hello World")
            await _settle(app, pilot)
            await pilot.pause()
            # a rename must take the backup too, or the store is refused
            assert app._midimap_backed_up is True

    async def test_closing_with_unstored_edits_warns(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._gate.toggle()  # arm the write gate
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            table = screen.query_one("#midimap-table", DataTable)
            table.move_cursor(row=screen._ordered.index("ch1"), column=0)
            screen.action_nudge_up()
            await _settle(app, pilot)
            await pilot.pause()
            assert app._midimap_unstored is True
            screen.action_close()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)

    async def test_del_resets_the_midimap_to_the_default(
        self,
        app: EmorphedApp,
        device: DemoDevice,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            index = app._current_midimap_index
            assert index is not None
            stores_before = len(device.midimap_stores)
            app._reset_midimap_to_default()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await _settle(app, pilot)
            await pilot.pause()
            # exactly one store, over the open location (the default is M00)
            assert len(device.midimap_stores) - stores_before == 1
            assert device.midimap_stores[-1][0] == index
