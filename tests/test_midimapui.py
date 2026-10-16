# SPDX-License-Identifier: GPL-2.0-or-later
"""Real tests for the midimap editor screen."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

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


def _full_params() -> dict[int, int]:
    values: dict[int, int] = {}
    text = "TESTNAME1234"
    for i, ch in enumerate(text):
        values[i] = ord(ch)
    for off in range(12, 360):
        values[off] = 0
    values[14] = 127
    values[13] = 0
    return values


def _event(key: str, char: str | None = None) -> Any:
    return type(
        "E",
        (),
        {
            "key": key,
            "character": char,
            "prevent_default": lambda self: None,
        },
    )()


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
        ev_digit = _event("7", "7")
        screen.on_key(ev_digit)
        ev_enter = _event("enter", "\r")
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


@pytest.mark.asyncio
async def test_range_enter_prompt_contains_label_range_value() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, {14: 127})
        app.push_screen(screen)
        await pilot.pause()

        pushed: list[Any] = []

        def fake_push(scr: Any, callback: Any = None) -> None:
            pushed.append(scr)

        app.push_screen = fake_push  # type: ignore[assignment]
        screen.action_edit_current()
        await pilot.pause()
        assert pushed
        title = str(getattr(pushed[-1], "_prompt_text", ""))
        assert "Ch. Volume" in title
        assert "0-127" in title
        assert "127" in title
        assert title != "value (0-127)"


@pytest.mark.asyncio
async def test_name_row_enter_opens_text_prompt_and_calls_on_name() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls_name: list[str] = []
        calls_edit: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor,
            _full_params(),
            on_name=calls_name.append,
            on_edit=lambda o, v: calls_edit.append((o, v)),
        )
        app.push_screen(screen)
        await pilot.pause()

        pushed: list[Any] = []

        def fake_push(scr: Any, callback: Any = None) -> None:
            pushed.append(scr)
            if callback is not None:
                callback("NEWNAME12345")

        app.push_screen = fake_push  # type: ignore[assignment]
        # cursor starts on name row
        screen.action_edit_current()
        await pilot.pause()
        assert calls_name == ["NEWNAME12345"]
        assert calls_edit == []
        assert pushed and "Midimap Name (12 chars):" in str(
            getattr(pushed[-1], "_prompt_text", "")
        )


@pytest.mark.asyncio
async def test_filter_and_escape_clears() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, _full_params())
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#midimap-table", DataTable)

        initial = table.row_count

        def fake_push_filter(scr: Any, callback: Any = None) -> None:
            if callback is not None:
                callback("Volume")

        app.push_screen = fake_push_filter  # type: ignore[assignment]
        screen.action_filter()
        await pilot.pause()
        assert table.row_count < initial
        assert table.row_count > 0

        def fake_push_clear(scr: Any, callback: Any = None) -> None:
            if callback is not None:
                callback(None)

        app.push_screen = fake_push_clear  # type: ignore[assignment]
        screen.action_filter()
        await pilot.pause()
        assert table.row_count == initial


@pytest.mark.asyncio
async def test_jump_keys() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, _full_params())
        app.push_screen(screen)
        await pilot.pause()

        screen.action_go_name()
        await pilot.pause()
        assert "Name" in _status(screen)

        screen.action_go_effects()
        await pilot.pause()
        assert "Global / Effects" in _status(screen)

        # h lands on name
        screen.action_go_name()
        await pilot.pause()
        assert "Midimap Name" in _status(screen) or "Name" in _status(screen)

        # n moves from name to next section
        screen.action_go_name()
        await pilot.pause()
        before = _status(screen)
        screen.action_next_section()
        await pilot.pause()
        assert _status(screen) != before
        assert "Channel 1" in _status(screen)

        # p moves back
        screen.action_prev_section()
        await pilot.pause()
        assert "Name" in _status(screen)


@pytest.mark.asyncio
async def test_typing_label_and_out_of_range() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor, {14: 5}, on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()

        screen.on_key(_event("2", "2"))
        screen.on_key(_event("0", "0"))
        screen.on_key(_event("0", "0"))
        status = _status(screen)
        assert "Ch. Volume" in status

        screen.on_key(_event("enter", "\r"))
        await pilot.pause()
        assert calls == []
        assert "0-127" in _status(screen)


@pytest.mark.asyncio
async def test_no_prompt_title_only_value() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, {14: 5})
        app.push_screen(screen)
        await pilot.pause()

        pushed: list[Any] = []

        def fake_push(scr: Any, callback: Any = None) -> None:
            pushed.append(scr)

        app.push_screen = fake_push  # type: ignore[assignment]
        screen.action_edit_current()
        await pilot.pause()
        for scr in pushed:
            title = str(getattr(scr, "_prompt_text", ""))
            assert title != "value (0-5)" and not title.startswith("value (")


@pytest.mark.asyncio
async def test_header_and_cell_order_agree() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, _full_params())
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#midimap-table", DataTable)
        assert list(table.columns) == [
            "offset",
            "section",
            "label",
            "value",
            "range",
        ]
        row = table.get_row_at(0)
        assert list(row) == [
            "name",
            "Name",
            "Midimap Name",
            "TESTNAME1234",
            "32-127",
        ]


@pytest.mark.asyncio
async def test_typedef_picker_returns_id_not_index() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        params = _full_params()
        params[333] = 0
        screen = MidimapEditScreen(
            editor, params, on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()
        ordered = screen._ordered
        index = ordered.index(333)
        table = screen.query_one("#midimap-table", DataTable)
        table.move_cursor(row=index, column=3)
        await pilot.pause()

        def fake_push(scr: Any, callback: Any = None) -> None:
            if callback is not None:
                callback(3)

        app.push_screen = fake_push  # type: ignore[assignment]
        screen.action_edit_current()
        await pilot.pause()
        assert (333, 16) in calls


@pytest.mark.asyncio
async def test_fx_parm_rows_relabel_after_type_change() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, _full_params())
        app.push_screen(screen)
        await pilot.pause()
        screen.result(True, "", parameter_id=333, value=11)
        await pilot.pause()
        assert screen._label_of(334) == "LFO Rate"
        table = screen.query_one("#midimap-table", DataTable)
        row = table.get_row_at(table.get_row_index("334"))
        assert row[2] == "LFO Rate"


@pytest.mark.asyncio
async def test_name_nudge_does_nothing() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        calls: list[tuple[int, int]] = []
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(
            editor, _full_params(), on_edit=lambda o, v: calls.append((o, v))
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.action_go_name()
        await pilot.pause()
        screen.action_nudge_up()
        await pilot.pause()
        screen.action_nudge_down()
        await pilot.pause()
        assert calls == []


@pytest.mark.asyncio
async def test_jump_keys_via_pilot() -> None:
    app = MiniApp()
    async with app.run_test() as pilot:
        editor = MidimapEditor(gate=EditGate(armed=True))
        screen = MidimapEditScreen(editor, _full_params())
        app.push_screen(screen)
        await pilot.pause()

        await pilot.press("h")
        await pilot.pause()
        assert "Name" in _status(screen)

        await pilot.press("x")
        await pilot.pause()
        assert "Global / Effects" in _status(screen)

        await pilot.press("n")
        await pilot.pause()
        # after effects, n wraps? just ensure status changes
        await pilot.press("h")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert "Channel 1" in _status(screen)

        await pilot.press("p")
        await pilot.pause()
        assert "Name" in _status(screen)


if __name__ == "__main__":
    pass
