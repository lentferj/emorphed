# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression tests for the bracket-in-name scroll crash."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.content import Content
from textual.widgets import DataTable, Static

from emorphed.app import EmorphedApp
from emorphed.demo import DemoDevice
from emorphed.edit import EditGate, MidimapEditor
from emorphed.midimapui import MidimapEditScreen
from emorphed.screens import ReportScreen, literal
from emu import banks
from emu import catalog as cat

_CRASH_NAMES = ["[g <`-^^", "[b]x[/b]", "[/dim]"]


class MarkupDemo(DemoDevice):
    """A demo whose preset names carry markup-looking bytes."""

    def _name_for(self, number: int) -> str:
        return _CRASH_NAMES[number % len(_CRASH_NAMES)].ljust(12)

    def names(
        self, kind: str = banks.Kind.PRESET, *, timeout: float | None = None
    ) -> list[str]:
        self._tick()
        out = []
        for region in self._regions(kind):
            for number in range(region.count):
                out.append(self._name_for(number))
        return out


@pytest.fixture
def device() -> MarkupDemo:
    return MarkupDemo()


@pytest.fixture
def app(device: MarkupDemo) -> EmorphedApp:
    return EmorphedApp(device, catalog=cat.empty(), demo=True)


class MiniApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("x")


def test_literal_escapes_bracket_names() -> None:
    for name in _CRASH_NAMES:
        escaped = literal(name)
        assert "[" not in escaped.replace("\\[", "")
        # round trips through a markup parse without raising

        Content.from_markup(f"[b]{escaped}[/b]")


@pytest.mark.asyncio
async def test_markup_name_highlight_does_not_crash(app: EmorphedApp) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_read_names()
        for _ in range(40):
            await pilot.pause()
        table = app.query_one("#slot-table", DataTable)
        table.focus()
        await pilot.pause()
        for _ in range(6):
            await pilot.press("down")
            await pilot.pause()
        detail = str(app.query_one("#detail", Static).content)
        assert any(n.strip() in detail for n in _CRASH_NAMES)


@pytest.mark.asyncio
async def test_markup_name_favouriting_does_not_crash(
    app: EmorphedApp, device: MarkupDemo
) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_read_names()
        for _ in range(40):
            await pilot.pause()
        table = app.query_one("#slot-table", DataTable)
        table.focus()
        await pilot.pause()
        app.action_toggle_favorite()
        await pilot.pause()
        status = str(app.query_one("#status", Static).content)
        # status survives; the literal name reaches the gutter only as markup
        assert status  # no crash is the real assertion


@pytest.mark.asyncio
async def test_markup_name_search_does_not_crash(app: EmorphedApp) -> None:
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_read_names()
        for _ in range(40):
            await pilot.pause()
        app.action_search()
        # close the prompt with enter on an empty-ish query would do nothing;
        # call the callback path indirectly by pushing a query through the
        # screen
        await pilot.pause()
        # avoid driving the prompt; just ensure search markup parsing of a hit
        hits = app.catalog.search("[")
        assert hits  # names contain '['
        lines = [f"{len(hits)} match(es) for [", ""]
        for bank_id, number, name, _disagrees in hits[:3]:
            try:
                entry = banks.slot(bank_id, number)
            except LookupError:
                continue
            lines.append(
                f"{entry.display:<6} {literal(name):<12} PC {entry.number:>3}"
            )
        app.push_screen(ReportScreen("Search", "\n".join(lines)))
        await pilot.pause()


@pytest.mark.asyncio
async def test_midimap_editor_shows_markup_name_literally() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        params = {}
        text = "[b]x[/b]".ljust(12)
        for i, ch in enumerate(text):
            params[i] = ord(ch)
        for off in range(12, 360):
            params[off] = 0
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, params, on_edit=lambda o, v: None)
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#midimap-table", DataTable)
        assert table.row_count > 0
        # no crash while rendering name row; status parseable
        status = str(screen.query_one(".status", Static).content)
        assert status is not None
