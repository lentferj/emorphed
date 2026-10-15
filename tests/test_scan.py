# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors

"""The whole-device name scan: offer, progress, no MIDI."""

import asyncio
import threading
import time
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Static

from emorphed.app import EmorphedApp
from emorphed.demo import DemoDevice
from emorphed.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen
from emu import banks
from emu import catalog as cat

pytestmark = pytest.mark.asyncio


class SlowDemo(DemoDevice):
    def names(
        self, kind: str = banks.Kind.PRESET, *, timeout: float | None = None
    ) -> list[str]:
        time.sleep(0.08)
        return super().names(kind, timeout=timeout)


def make(
    tmp_path: Path,
    catalog: cat.Catalog | None = None,
    device: DemoDevice | None = None,
    **kwargs: object,
) -> EmorphedApp:
    return EmorphedApp(
        device if device is not None else DemoDevice(),
        catalog=catalog if catalog is not None else cat.empty(),
        config_path=str(tmp_path / "config.toml"),
        **kwargs,  # type: ignore[arg-type]
    )


async def _wait(
    app: EmorphedApp, pilot: object, cls: type, tries: int = 200
) -> bool:
    for _ in range(tries):
        if isinstance(app.screen, cls):
            return True
        await asyncio.sleep(0.05)
        await pilot.pause()  # type: ignore[attr-defined]
    return False


class TestOfferScreens:
    async def _answer(self, key: str) -> list[str]:
        results: list[str] = []

        class H(App[None]):
            def on_mount(self) -> None:
                self.push_screen(
                    ScanOfferScreen(),
                    lambda answer: results.append(answer or ""),
                )

        app = H()
        async with app.run_test() as pilot:
            await pilot.press(key)
        return results

    async def test_y(self) -> None:
        assert await self._answer("y") == ["scan"]

    async def test_n(self) -> None:
        assert await self._answer("n") == ["later"]

    async def test_d(self) -> None:
        assert await self._answer("d") == ["never"]

    async def test_escape(self) -> None:
        assert await self._answer("escape") == ["later"]

    async def test_prompt(self) -> None:
        assert "presets" in SCAN_OFFER
        assert "silent" in SCAN_OFFER
        assert "nothing audible" in SCAN_OFFER


class TestProgress:
    async def test_before_mount(self) -> None:
        s = ScanScreen(threading.Event())
        s.set_progress("x")
        assert s._line == "x"

    async def test_after_mount(self) -> None:
        s = ScanScreen(threading.Event())
        app = App[None]()
        async with app.run_test() as pilot:
            app.push_screen(s)
            await pilot.pause()
            s.set_progress("x")
            await pilot.pause()
            assert app.screen.query_one("#scan-line", Static).content == "x"

    async def test_cancel(self) -> None:
        e = threading.Event()
        s = ScanScreen(e)
        s.action_cancel()
        assert e.is_set()
        assert s.cancelled

    async def test_cancel_button(self) -> None:
        e = threading.Event()
        s = ScanScreen(e)
        app = App[None]()
        async with app.run_test() as pilot:
            app.push_screen(s)
            await pilot.pause()
            await pilot.click("#cancel")
            assert e.is_set()


class TestFlow:
    async def test_offered(self, tmp_path: Path) -> None:
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            assert await _wait(app, pilot, ScanOfferScreen)

    async def test_not_offered_unless_asked(self, tmp_path: Path) -> None:
        app = make(tmp_path, catalog=cat.empty())
        async with app.run_test() as pilot:
            await asyncio.sleep(0.8)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_never_persists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved: dict[str, object] = {}

        def fake_save(key: str, value: object, path: object = None) -> None:
            saved[key] = value

        monkeypatch.setattr("emu.config.save_ui_state", fake_save)
        monkeypatch.setattr(
            "emu.config.load_ui_bool",
            lambda key, **kwargs: False,
        )
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._scan_offer_answered("never")
            assert saved == {"scan_offer_dismissed": True}

    async def test_dismissed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "emu.config.load_ui_bool",
            lambda key, **kwargs: True,
        )
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await asyncio.sleep(0.8)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_demo_refuses(self, tmp_path: Path) -> None:
        app = make(tmp_path, device=DemoDevice(), demo=True, offer_scan=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            assert not app._busy

    async def test_scan_reads(self, tmp_path: Path) -> None:
        path = str(tmp_path / "live.json")
        app = EmorphedApp(
            DemoDevice(),
            catalog=cat.empty(),
            config_path=str(tmp_path / "config.toml"),
            live_names_path=path,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            for _ in range(400):
                if not app._busy:
                    break
                await pilot.pause()
            assert not app._busy
            assert app.catalog.live_name("P-RAM", 0) is not None
            assert app.catalog.live_name("H-RAM", 0) is not None
            assert app.catalog.live_name("M-RAM", 0) is not None

    async def test_cancel(self, tmp_path: Path) -> None:
        app = make(tmp_path, device=SlowDemo())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            for _ in range(50):
                if isinstance(app.screen, ScanScreen):
                    break
                await pilot.pause()
            assert isinstance(app.screen, ScanScreen)
            app.screen.action_cancel()
            assert app._scan_cancel.is_set()
            for _ in range(400):
                if not app._busy:
                    break
                await pilot.pause()
            assert not app._busy
