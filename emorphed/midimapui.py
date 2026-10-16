# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The midimap editor screen.

A modal over the browser: the unit's own parameter table, one row per word,
with the value under a cell cursor. A screen owns no worker and sends
nothing on its own -- every change goes out through ``on_edit``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from emu import midimap as mm
from vinsynlib.ui.modals import ChoiceScreen
from vinsynlib.ui.prompt import PromptScreen

__all__ = ["MidimapEditScreen"]


class MidimapEditScreen(ModalScreen[None]):
    """Edit the current midimap's parameters."""

    DEFAULT_CSS = """
    MidimapEditScreen { align: center middle; }
    MidimapEditScreen > Vertical {
        width: 92; height: 86%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    MidimapEditScreen DataTable { height: 1fr; }
    MidimapEditScreen .status { height: auto; color: $text; padding-top: 1; }
    MidimapEditScreen .hints { height: auto; color: $text-muted; }
    """

    BINDINGS: ClassVar[Any] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("plus", "nudge_up", "Value +"),
        Binding("equals", "nudge_up", "Value +"),
        Binding("minus", "nudge_down", "Value -"),
        Binding("enter", "edit_current", "Edit", priority=True),
        Binding("w", "toggle_write_gate", "Write gate"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        Binding("r", "re_read", "Re-read"),
        Binding("s", "store", "Store"),
    ]

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        editor: Any,
        params: dict[int, int] | None = None,
        on_edit: Callable[[int, int], None] | None = None,
        on_re_read: Callable[[], None] | None = None,
        on_undo: Callable[[int | None], None] | None = None,
        on_store: Callable[[], None] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # allow positional callbacks after params
        if args:
            if on_edit is None and len(args) >= 1:
                on_edit = args[0]
            if on_re_read is None and len(args) >= 2:  # noqa: PLR2004
                on_re_read = args[1]
            if on_undo is None and len(args) >= 3:  # noqa: PLR2004
                on_undo = args[2]
            if on_store is None and len(args) >= 4:  # noqa: PLR2004
                on_store = args[3]
        super().__init__(**kwargs)
        self._editor = editor
        self._values: dict[int, int] = dict(params or {})
        self._on_edit = on_edit
        self._on_re_read = on_re_read
        self._on_undo = on_undo
        self._on_store = on_store
        self._ordered: list[int] = sorted(self._values)
        self._typing: str = ""
        self._typing_offset: int | None = None

    @property
    def editor(self) -> Any:
        return self._editor

    @property
    def gate(self) -> Any:
        return getattr(self._editor, "gate", self._editor)

    def _current_offset(self) -> int | None:
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            if self._ordered:
                return self._ordered[0]
            return None
        row = table.cursor_row
        if self._ordered and 0 <= row < len(self._ordered):
            return self._ordered[row]
        return None

    def _current_param(self) -> Any:
        off = self._current_offset()
        if off is None:
            return None
        try:
            return mm.param_at(off)
        except (ValueError, KeyError):
            return None

    def _spell(self, offset: int, value: int) -> str:
        try:
            return mm.spell(mm.param_at(offset), value)
        except Exception:
            return str(value)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Midimap edit[/b]")
            yield DataTable(
                id="midimap-table", cursor_type="cell", zebra_stripes=True
            )
            yield Static("", classes="status")
            yield Static(
                "[dim]w gate · + / - nudge · digits type · enter choices · "
                "r re-read · s store · z / Z undo · esc / q close[/dim]",
                classes="hints",
            )

    def on_mount(self) -> None:
        table = self.query_one("#midimap-table", DataTable)
        table.add_column("offset", key="offset")
        table.add_column("label", key="label")
        table.add_column("value", key="value")
        table.add_column("range", key="range")
        for off in self._ordered:
            param = None
            with contextlib.suppress(Exception):
                param = mm.param_at(off)
            value = self._values.get(off, 0)
            label = getattr(param, "label", f"offset {off}")
            if param is not None and param.choices:
                rng = f"{param.low}-{param.high} ({len(param.choices)} named)"
            elif param is not None:
                rng = f"{param.low}-{param.high}"
            else:
                rng = "?"
            table.add_row(
                str(off),
                label,
                self._spell(off, value),
                rng,
                key=str(off),
            )
        if table.row_count:
            table.move_cursor(row=0, column=2)

    def say(self, message: str, *, refused: bool = False) -> None:
        try:
            status = self.query_one(".status", Static)
        except Exception:
            return
        prefix = "[b]refused[/b] · " if refused else ""
        status.update(prefix + message)

    def result(
        self,
        ok: bool,
        message: str,
        parameter_id: int | None = None,
        value: int | None = None,
        offset: int | None = None,
        **_extra: Any,
    ) -> None:
        if ok:
            off = parameter_id if parameter_id is not None else offset
            if off is not None and value is not None:
                self._values[off] = value
                try:
                    table = self.query_one("#midimap-table", DataTable)
                    with contextlib.suppress(Exception):
                        mm.param_at(off)
                    spelled = self._spell(off, value)
                    table.update_cell(str(off), "value", spelled)
                except Exception:  # noqa: S110
                    pass
        self.say(message, refused=not ok)

    def _report(self) -> str:
        try:
            return str(self._editor.gate.describe())
        except Exception:
            return ""

    def action_close(self) -> None:
        self.dismiss(None)

    def action_toggle_write_gate(self) -> None:
        gate = self.gate
        gate.toggle()
        self.say(gate.describe())
        with contextlib.suppress(Exception):
            self.query_one(".status", Static).update("" + gate.describe())

    def action_nudge_up(self) -> None:
        self._nudge(1)

    def action_nudge_down(self) -> None:
        self._nudge(-1)

    def _nudge(self, by: int) -> None:
        off = self._current_offset()
        if off is None:
            return
        param = None
        try:
            param = mm.param_at(off)
        except Exception:
            param = None
        if param is None:
            return
        current = self._values.get(off, param.low)
        on_edit = self._on_edit

        # choices step through list
        if param.choices if param is not None else ():
            low = getattr(param, "low", 0)
            idx = current - low
            if by > 0:
                idx = (idx + 1) % len(param.choices)
            else:
                idx = (idx - 1) % len(param.choices)
            value = low + idx
        else:
            low = getattr(param, "low", 0)
            high = getattr(param, "high", 0)
            value = min(high, max(low, current + by))

        # gate check
        refusal = None
        try:
            refusal = getattr(self._editor, "allow", lambda _o, _v: None)(
                off, value
            )
        except Exception:
            refusal = None
        if refusal is not None:
            # also editor.gate.refuse
            with contextlib.suppress(Exception):
                refusal = self._editor.gate.refuse() or refusal
        if refusal is not None:
            self.say(refusal, refused=True)
            return
        self._values[off] = value
        if on_edit is not None:
            on_edit(off, value)

    def action_edit_current(self) -> None:  # noqa: C901
        off = self._current_offset()
        if off is None:
            return
        param = None
        try:
            param = mm.param_at(off)
        except Exception:
            param = None
        if param is not None and param.choices:
            choices = list(param.choices)
            current_val = self._values.get(off, param.low)
            idx = max(0, min(len(choices) - 1, current_val - param.low))

            def picked(chosen: int | None) -> None:
                if chosen is None:
                    return
                value = param.low + chosen
                # gate check
                refusal = self._editor.allow(off, value)
                if refusal is not None:
                    self.say(refusal, refused=True)
                    return
                self._values[off] = value
                if self._on_edit is not None:
                    self._on_edit(off, value)

            self.app.push_screen(
                ChoiceScreen("Pick a value:", choices, current=idx), picked
            )
        else:
            # digits typing already handles; open prompt as fallback
            param_low = getattr(param, "low", 0) if param else 0
            param_high = getattr(param, "high", 0) if param else 0

            def apply(text: str | None) -> None:
                if not text:
                    return
                try:
                    value = int(text.strip())
                except ValueError:
                    self.say(f"{text!r} is not a number", refused=True)
                    return
                refusal = self._editor.allow(off, value)
                if refusal is not None:
                    self.say(refusal, refused=True)
                    return
                self._values[off] = value
                if self._on_edit is not None:
                    self._on_edit(off, value)

            self.app.push_screen(
                PromptScreen(f"value ({param_low}-{param_high}):", ""),
                apply,
            )

    def action_re_read(self) -> None:
        if self._on_re_read is not None:
            self._on_re_read()

    def action_store(self) -> None:
        if self._on_store is not None:
            self._on_store()

    def action_undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo(1)

    def action_undo_all(self) -> None:
        if self._on_undo is not None:
            self._on_undo(None)

    def on_key(self, event: Any) -> None:  # noqa: C901, PLR0911
        key = getattr(event, "key", "")
        char = getattr(event, "character", None)
        # Digits type in place for the current cell.
        if char is not None and char.isdigit():
            off = self._current_offset()
            if off is None:
                return
            if self._typing_offset != off:
                self._typing = ""
                self._typing_offset = off
            self._typing += char
            try:
                status = self.query_one(".status", Static)
                status.update(f"typing: {self._typing}")
            except Exception:  # noqa: S110
                pass
            event.prevent_default()
            return
        if key in ("enter", "return") and self._typing:
            # commit typed number
            off = self._current_offset() or self._typing_offset
            if off is None:
                self._typing = ""
                return
            try:
                value = int(self._typing)
            except ValueError:
                self.say(f"{self._typing!r} is not a number", refused=True)
                self._typing = ""
                return
            refusal = None
            try:
                refusal = self._editor.allow(off, value)
            except Exception:
                refusal = None
            if refusal is not None:
                self.say(refusal, refused=True)
                self._typing = ""
                return
            self._values[off] = value
            if self._on_edit is not None:
                self._on_edit(off, value)
            self._typing = ""
            self._typing_offset = None
            event.prevent_default()
            return
        if key in ("backspace",) and self._typing:
            self._typing = self._typing[:-1]
            event.prevent_default()
            return
        if key in ("escape",):
            self._typing = ""
            self._typing_offset = None

    def update_params(self, params: dict[int, int]) -> None:
        self._values = dict(params)
        self._ordered = sorted(self._values)
        try:
            table = self.query_one("#midimap-table", DataTable)
            table.clear()
            for off in self._ordered:
                param = None
                try:
                    param = mm.param_at(off)
                except Exception:
                    param = None
                value = self._values.get(off, 0)
                label = param.label if param is not None else f"offset {off}"
                if param is not None and param.choices:
                    rng = (
                        f"{param.low}-{param.high} "
                        f"({len(param.choices)} named)"
                    )
                elif param is not None:
                    rng = f"{param.low}-{param.high}"
                else:
                    rng = "?"
                table.add_row(
                    str(off),
                    label,
                    self._spell(off, value),
                    rng,
                    key=str(off),
                )
        except Exception:  # noqa: S110
            pass
