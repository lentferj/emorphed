# SPDX-License-Identifier: GPL-2.0-or-later
"""Real tests for the midimap editor screen."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from emorphed.edit import EditGate, MidimapEditor
from emorphed.midimapui import MidimapEditScreen


class MiniApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("x")


def _status(screen: MidimapEditScreen) -> str:
    try:
        return str(screen.query_one(".status", Static).content)
    except Exception:
        return ""


@pytest.mark.asyncio
async def test_nudge_and_typing_call_on_edit() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor, {14: 5}, on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.action_nudge_up()
        await pilot.pause()
        assert (14, 6) in calls

        # typing a number commits through on_edit
        ev_digit = type(
            "E",
            (),
            {
                "key": "7",
                "character": "7",
                "prevent_default": lambda self: None,
            },
        )()
        screen.on_key(ev_digit)
        ev_enter = type(
            "E",
            (),
            {
                "key": "enter",
                "character": "\r",
                "prevent_default": lambda self: None,
            },
        )()
        screen.on_key(ev_enter)
        await pilot.pause()
        assert (14, 7) in calls


@pytest.mark.asyncio
async def test_locked_gate_no_on_edit_and_refusal() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor()  # locked by default
        screen = MidimapEditScreen(
            editor, {14: 5}, on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()
        said: list[tuple[str, bool]] = []
        original = screen.say

        def captured(message: str, *, refused: bool = False) -> None:
            said.append((message, refused))
            original(message, refused=refused)

        screen.say = captured  # type: ignore[method-assign]
        screen.action_nudge_up()
        await pilot.pause()
        assert calls == []
        assert any("write gate is locked" in msg for msg, _ in said)


@pytest.mark.asyncio
async def test_choices_opens_picker_and_returns_value() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor, {13: 0}, on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()

        def fake_push(_scr: Any, callback: Any = None) -> None:
            if callback is not None:
                callback(2)

        app.push_screen = fake_push  # type: ignore[assignment]
        screen.action_edit_current()
        await pilot.pause()
        assert (13, 2) in calls


@pytest.mark.asyncio
async def test_r_calls_on_reread() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        reads: list[bool] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor, {14: 5}, on_re_read=lambda: reads.append(True)
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.action_re_read()
        await pilot.pause()
        assert reads == [True]


@pytest.mark.asyncio
async def test_s_sends_nothing_before_confirmation() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        stores: list[bool] = []
        edits: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor,
            {14: 5},
            on_edit=lambda o, v: edits.append((o, v)),
            on_store=lambda: stores.append(True),
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.action_store()
        await pilot.pause()
        assert stores == [True]
        assert edits == []


@pytest.mark.asyncio
async def test_mismatching_readback_shows_mismatch_sentence() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, {14: 5})
        app.push_screen(screen)
        await pilot.pause()
        screen.result(
            False,
            "Ch. Volume did not take 7: the unit still reports 9",
        )
        await pilot.pause()
        assert "did not take" in _status(screen)
