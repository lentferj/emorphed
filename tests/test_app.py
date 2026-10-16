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

from emorphed.app import VIEW_ALL_FAVOURITES, EmorphedApp
from emorphed.demo import DemoDevice
from emorphed.scan import ScanScreen
from emorphed.screens import PromptScreen, ReportScreen
from emu import backup as bk
from emu import banks
from emu import catalog as cat
from emu import favorites as fav
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
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=1, column=2
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
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=1, column=2
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

    async def test_store_fence_requires_prompt_and_confirmation(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        app._midimap_backed_up = True
        async with app.run_test() as pilot:
            await pilot.pause()
            stores_before = len(device.midimap_stores)
            app._store_midimap()
            await pilot.pause()
            assert isinstance(app.screen, PromptScreen)
            assert len(device.midimap_stores) == stores_before
            await pilot.press("5")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            confirm = cast(Any, app.screen)
            assert "STORE to location 5" in confirm.prompt_text
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
            screen.query_one("#midimap-table", DataTable).move_cursor(
                row=1, column=2
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
            screen.action_re_read()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_reads) - before_reads == 360
            # Not a 0x46 stored dump: no new midimap read/store happened.
            assert len(device.midimap_stores) == before_stores
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
    async def test_name_write_twelve_frames_readback_agreement_and_undo(
        self, app: EmorphedApp, device: DemoDevice
    ) -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_midimap_edit()
            await _settle(app, pilot)
            await pilot.pause()
            screen = cast(Any, app.screen)
            # capture baseline
            writes_before = len(device.parameter_writes)
            reads_before = len(device.parameter_reads)
            said = _capture(app)
            # old name as twelve question marks (stored map is zeroed)
            app._apply_midimap_name("Hi there")
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before == 12
            assert len(device.parameter_reads) - reads_before == 12
            # status reports agreement
            messages = [m for m, _ in said]
            assert any("agree" in m for m in messages), messages
            # values reflect name
            assert screen._values.get(0) == ord("H")
            assert screen._values.get(1) == ord("i")
            # undo restores
            writes_before2 = len(device.parameter_writes)
            app.action_undo()
            await _settle(app, pilot)
            await pilot.pause()
            assert len(device.parameter_writes) - writes_before2 == 12
