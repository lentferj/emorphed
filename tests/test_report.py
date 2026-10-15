# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The adopted frame and the build line it carries."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from emorphed import app as emorphed_app
from emorphed.app import _build_line
from emorphed.screens import ReportScreen
from vinsynlib.build import Build, build_of


class ReportApp(App[None]):
    def __init__(self, screen: ReportScreen) -> None:
        super().__init__()
        self._screen = screen
        self.closed = False

    def compose(self) -> ComposeResult:
        yield from []

    def on_mount(self) -> None:
        def closed(_: None) -> None:
            self.closed = True

        self.push_screen(self._screen, closed)


class TestTheAdoptedFrame:
    """What survived the swap: the subclass, the keys, the scroll."""

    async def test_escape_closes(self) -> None:
        async with ReportApp(
            ReportScreen("emorphed", "test")
        ).run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(pilot.app, ReportApp) and pilot.app.closed

    async def test_q_closes(self) -> None:
        async with ReportApp(
            ReportScreen("emorphed", "test")
        ).run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(pilot.app, ReportApp) and pilot.app.closed

    async def test_enter_closes(self) -> None:
        async with ReportApp(
            ReportScreen("emorphed", "test")
        ).run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(pilot.app, ReportApp) and pilot.app.closed

    async def test_the_body_scrolls(self) -> None:
        body = "\n".join(f"line {n}" for n in range(200))
        async with ReportApp(
            ReportScreen("emorphed", body)
        ).run_test() as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            await pilot.press("pagedown")
            await pilot.pause()
            scroll = screen.query_one(VerticalScroll)
            assert scroll.scroll_offset.y > 0, "the body scrolled"

    async def test_the_box_is_84_by_32_thick(self) -> None:
        async with ReportApp(ReportScreen("emorphed", "Two panes.")).run_test(
            size=(100, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            box = screen.query_one("Vertical")
            region = box.region
            # The adopted library frame: 84x80% in a 100x40 area -> ~84x32.
            assert region.width == 84, f"width {region.width}"  # noqa: PLR2004
            assert region.height == 32, f"height {region.height}"  # noqa: PLR2004
            assert "thick" in str(box.styles.border), "border thick"

    async def test_the_frame_carries_emorphed_words(self) -> None:
        body_text = "What the Morpheus holds."
        async with ReportApp(
            ReportScreen("emorphed", body_text)
        ).run_test() as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            static_body = screen.query_one(".body", Static)
            body_str = str(static_body.visual) if static_body.visual else ""
            assert "emorphed" in body_str or "emorphed" in str(
                getattr(screen, "title_text", "")
            )
            assert "What the Morpheus holds." in body_str


COMMIT = "0bad4f2" * 5
CHECKOUT = Build(version=None, commit=COMMIT)
RELEASE = Build(version="0.4.1")
NEITHER = Build(version=None)


class TestTheBuildLine:
    """The tiers, stubbed and real."""

    @staticmethod
    def _line(
        monkeypatch: Any, tool: Build = CHECKOUT, library: Build = CHECKOUT
    ) -> str:
        def fake(name: str, origin: str | None = None) -> object:
            return tool if name == "emorphed" else library

        monkeypatch.setattr("emorphed.app.build_of", fake)
        return _build_line()

    def test_checkout_names_its_commit_and_no_version(
        self,
        monkeypatch: Any,
    ) -> None:
        line = self._line(monkeypatch, tool=CHECKOUT, library=CHECKOUT)
        assert COMMIT[:7] in line
        assert "emorphed" in line
        assert "vinsynlib" in line
        assert "0.4." not in line, "checkout invented a version"

    def test_release_names_version_and_no_commit(
        self, monkeypatch: Any
    ) -> None:
        line = self._line(monkeypatch, tool=RELEASE, library=RELEASE)
        assert "0.4.1" in line
        assert "(" not in line, "release printed a commit it cannot know"

    def test_neither_says_so(self, monkeypatch: Any) -> None:
        line = self._line(monkeypatch, tool=NEITHER, library=NEITHER)
        assert "emorphed" in line and "vinsynlib" in line
        assert "(" not in line
        assert "unknown" in line.lower() or line.endswith("unknown version")

    def test_the_real_environment_has_both_names(self) -> None:
        line = _build_line()
        assert "emorphed" in line
        assert "vinsynlib" in line

    def test_the_real_environment_prints_what_it_knows(self) -> None:
        line = _build_line()
        parts = line.split(" and ")
        emorphed_part = next(p for p in parts if "emorphed" in p)
        library_part = next(p for p in parts if "vinsynlib" in p)
        emorphed_commit = build_of(
            "emorphed", origin=emorphed_app.__file__
        ).commit
        library_commit = build_of("vinsynlib").commit
        assert ("(" in emorphed_part) == (emorphed_commit is not None)
        assert ("(" in library_part) == (library_commit is not None)
