# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The midimap editor screen.

A modal over the browser: the unit's own parameter table, with the value
under a cell cursor. Each of the sixteen channels is collapsed to a single
summary row by default (its selected preset -- named when a catalog is
plumbed in, otherwise just the program number -- then volume, pan, mix bus
and how many switches are on) and expands on Enter to show its twenty
parameters; Global/Effects rows are always expanded. A screen owns no
worker and sends nothing on its own -- every change goes out through a
callback: ``on_edit`` for a single word, ``on_name`` for the
twelve-character name, ``on_channel`` for a channel's preset pair, and
``on_pick`` to ask for a preset picker. ``name_for`` supplies the preset
name to display (the catalog is the app's, not the screen's).
``set_unstored`` is the screen's own scratch/stored marker: the app calls
it after a write (``True``) and after a store (``False``), and the screen
only displays the tag -- it sends nothing.
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

from emorphed.text import literal
from emu import midimap as mm
from vinsynlib.ui.modals import ChoiceScreen
from vinsynlib.ui.prompt import PromptScreen

__all__ = ["MidimapEditScreen"]


_NAME_WORDS = 12
_ASCII_FIRST = 32
_ASCII_LAST = 128
_CHANNEL_STRIDE = 20
_CHANNEL_BASE = 12
_GLOBAL_BASE = 332  # 12 + 16 * 20; boundaries in PARAMS


def _channel_index(offset: int) -> int:
    """The in-block index (0-19) of a channel-block offset, else ``-1``."""
    if not _CHANNEL_BASE <= offset < _GLOBAL_BASE:
        return -1
    return (offset - _CHANNEL_BASE) % _CHANNEL_STRIDE


def _channel_of_offset(offset: int) -> int:
    """The channel (1-16) a channel-block offset belongs to."""
    return (offset - _CHANNEL_BASE) // _CHANNEL_STRIDE + 1


_FX_A_TYPE_OFFSET = 333
_FX_A_PARM_FIRST = 334
_FX_A_PARM_LAST = 343
_FX_B_TYPE_OFFSET = 344
_FX_B_PARM_FIRST = 345
_FX_B_PARM_LAST = 354


class MidimapEditScreen(ModalScreen[None]):
    """Edit the current midimap's parameters."""

    DEFAULT_CSS = """
    MidimapEditScreen { align: center middle; }
    MidimapEditScreen > Vertical {
        width: 92%; height: 86%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    MidimapEditScreen DataTable { height: 1fr; }
    MidimapEditScreen .status { height: auto; color: $text; padding-top: 1; }
    MidimapEditScreen .status.refused {
        background: $error; color: $text; text-style: bold;
    }
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
        Binding("s", "store", "Store to a location"),
        Binding("h", "go_name", "Name"),
        Binding("x", "go_effects", "Effects"),
        Binding("n", "next_section", "Next section"),
        Binding("p", "prev_section", "Prev section"),
        Binding("c", "toggle_all_channels", "Collapse/expand all channels"),
        Binding("delete", "reset", "Reset to the default midimap"),
        Binding("/", "filter", "Filter"),
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
        on_name: Callable[[str], None] | None = None,
        on_reset: Callable[[], None] | None = None,
        name_for: Callable[[int, int], str] | None = None,
        on_channel: Callable[[int, int, int], None] | None = None,
        on_pick: Callable[[int], None] | None = None,
        index: int | None = None,
        **kwargs: Any,
    ) -> None:
        # allow positional callbacks after params (legacy shim)
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
        self._pre_edit: dict[int, int] = {}
        self._on_edit = on_edit
        self._on_re_read = on_re_read
        self._on_undo = on_undo
        self._on_store = on_store
        self._on_name = on_name
        self._on_reset = on_reset
        self._name_for = name_for
        self._on_channel = on_channel
        self._on_pick = on_pick
        self._typing: str = ""
        self._typing_offset: int | None = None
        self._filter: str = ""
        self._expanded: set[int] = set()
        self._unstored: bool = False
        #: The unit's midimap location, 0-31, for the title's ``MNN``.
        self._index: int = 0 if index is None else index
        self._build_rows()
        self._ordered: list[Any] = self._visible_rows()

    @property
    def editor(self) -> Any:
        return self._editor

    @property
    def gate(self) -> Any:
        return getattr(self._editor, "gate", self._editor)

    # ------------------------------------------------------------------ rows

    def _has_name_block(self) -> bool:
        return any(0 <= off < _NAME_WORDS for off in self._values)

    def _build_rows(self) -> None:
        rows: list[Any] = []
        if self._has_name_block():
            rows.append("name")
        for channel in range(1, 17):
            rows.append(f"ch{channel}")
            if channel in self._expanded:
                base = _CHANNEL_BASE + (channel - 1) * _CHANNEL_STRIDE
                for index in range(_CHANNEL_STRIDE):
                    rows.append(base + index)
        for off in sorted(self._values):
            if off >= _GLOBAL_BASE:
                rows.append(off)
        self._all_rows: list[Any] = rows

    def _section_of(self, row: Any) -> str:
        if row == "name":
            return "Name"
        if isinstance(row, str) and row.startswith("ch"):
            try:
                return f"Channel {int(row[2:])}"
            except ValueError:
                pass
        off = int(row)
        if off < _GLOBAL_BASE:
            channel = (off - _CHANNEL_BASE) // _CHANNEL_STRIDE + 1
            # clamp: offsets below the channel base would be name chars
            channel = max(channel, 1)
            return f"Channel {channel}"
        return "Global / Effects"

    def _param_of(self, row: Any) -> Any:
        if row == "name":
            try:
                return mm.param_at(0)
            except Exception:
                return None
        if isinstance(row, str) and row.startswith("ch"):
            return None
        try:
            return mm.param_at(int(row))
        except Exception:
            return None

    def _label_of(self, row: Any) -> str:  # noqa: C901
        if row == "name":
            return "Midimap Name"
        if isinstance(row, str) and row.startswith("ch"):
            try:
                return f"Channel {int(row[2:])}"
            except ValueError:
                return str(row)
        off = int(row) if row != "name" else -1
        # FX parameter rows are labelled by the selected effect type.
        if _FX_A_PARM_FIRST <= off <= _FX_A_PARM_LAST:
            type_value = self._values.get(333, None)
            if type_value is None:
                try:
                    type_value = mm.param_at(_FX_A_TYPE_OFFSET).low
                except Exception:
                    type_value = 0
            params = mm.fx_params_for(type_value)
            index = off - _FX_A_PARM_FIRST
            if 0 <= index < len(params):
                return params[index][0]
        if _FX_B_PARM_FIRST <= off <= _FX_B_PARM_LAST:
            type_value = self._values.get(_FX_B_TYPE_OFFSET, None)
            if type_value is None:
                try:
                    type_value = mm.param_at(_FX_B_TYPE_OFFSET).low
                except Exception:
                    type_value = 128
            params = mm.fx_params_for(type_value)
            index = off - _FX_B_PARM_FIRST
            if 0 <= index < len(params):
                return params[index][0]
        param = self._param_of(row)
        return getattr(param, "label", f"offset {row}")

    def _raw_value(self, row: Any) -> int:
        if row == "name":
            return 0
        if isinstance(row, str) and row.startswith("ch"):
            return 0
        off = int(row)
        param = self._param_of(row)
        if param is None:
            return self._values.get(off, 0)
        return self._values.get(off, getattr(param, "low", 0))

    def _name_text(self) -> str:
        words = [self._values.get(i, 32) for i in range(12)]
        try:
            return mm.name_of(words)
        except Exception:
            return "".join(
                chr(w) if _ASCII_FIRST <= w < _ASCII_LAST else "?"
                for w in words
            )

    def _name_blank(self) -> bool:
        """A blank name: twelve words below 32, or only spaces and ``?``."""
        words = [self._values.get(i, _ASCII_FIRST) for i in range(_NAME_WORDS)]
        if all(w < _ASCII_FIRST for w in words):
            return True
        return set(self._name_text()) <= {" ", "?"}

    def _preset_text(self, bank: int, number: int) -> str:
        """A preset as it reads: ``003 - Name``, or just ``003`` unnamed.

        The bank and number are a channel's two words: ``Ch. Bank`` 0-4
        and ``Ch. Program`` 0-127. The name is ``name_for``'s answer; an
        empty (or absent) name means the slot has none, and the number
        stands alone.
        """
        name = ""
        if self._name_for is not None:
            with contextlib.suppress(Exception):
                name = self._name_for(bank, number) or ""
        if name:
            return f"{number:03d} - {name}"
        return f"{number:03d}"

    def _display_value(self, row: Any) -> str:  # noqa: C901, PLR0911
        if row == "name":
            if self._name_blank():
                return "(empty)"
            return literal(f'"{self._name_text()}"')
        if isinstance(row, str) and row.startswith("ch"):
            try:
                channel = int(row[2:])
            except ValueError:
                return ""
            base = _CHANNEL_BASE + (channel - 1) * _CHANNEL_STRIDE

            def _raw(off: int) -> int:
                try:
                    param = mm.param_at(off)
                except Exception:
                    param = None
                return self._values.get(
                    off, getattr(param, "low", 0) if param is not None else 0
                )

            def _spell(off: int) -> str:
                try:
                    return mm.spell(mm.param_at(off), _raw(off))
                except Exception:
                    return str(_raw(off))

            program_value = _raw(base + 0)
            bank_value = _raw(base + 1)
            lead = self._preset_text(bank_value, program_value)
            volume_spell = _spell(base + 2)
            pan_spell = _spell(base + 3)
            bus_spell = _spell(base + 4)
            switches = 0
            for index in range(5, _CHANNEL_STRIDE):
                off = base + index
                if _raw(off) == 1:
                    switches += 1
            return (
                f"{lead} · vol {volume_spell} · pan {pan_spell} · "
                f"bus {bus_spell} · {switches} switches on"
            )
        param = self._param_of(row)
        value = self._raw_value(row)
        # A channel's Ch. Program word shows the preset it selects, the
        # same text the collapsed summary leads with.
        if _channel_index(int(row)) == 0:
            bank = self._raw_value(int(row) + 1)
            return self._preset_text(bank, value)
        try:
            return mm.spell(param, value) if param is not None else str(value)
        except Exception:
            return str(value)

    def _range_text(self, row: Any) -> str:
        if row == "name":
            return "text · 12 chars"
        if isinstance(row, str) and row.startswith("ch"):
            try:
                channel = int(row[2:])
            except ValueError:
                channel = 0
            if channel in self._expanded:
                return "20 params · enter to collapse"
            return "20 params · enter to expand"
        param = self._param_of(row)
        if param is None:
            return "?"
        if param.choices:
            return f"{param.low}-{param.high} ({len(param.choices)} named)"
        return f"{param.low}-{param.high}"

    def _visible_rows(self) -> list[Any]:
        needle = self._filter.strip().lower()
        if not needle:
            return list(self._all_rows)
        # When filtering, ignore the collapse so a match is never hidden
        # inside a channel summary: build from every atomic row.
        rows: list[Any] = []
        if self._has_name_block():
            rows.append("name")
        for channel in range(1, 17):
            base = _CHANNEL_BASE + (channel - 1) * _CHANNEL_STRIDE
            for index in range(_CHANNEL_STRIDE):
                rows.append(base + index)
        for off in sorted(self._values):
            if off >= _GLOBAL_BASE:
                rows.append(off)
        out: list[Any] = []
        for row in rows:
            if needle in self._label_of(row).lower():
                out.append(row)
        return out

    def _refresh_table(self) -> None:
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            return
        self._ordered = self._visible_rows()
        table.clear()
        prev_section: str | None = None
        for row in self._ordered:
            section = self._section_of(row)
            if section == prev_section:
                section_cell = ""
            else:
                section_cell = section
                prev_section = section
            label = self._label_of(row)
            display = self._display_value(row)
            rng = self._range_text(row)
            key = "name" if row == "name" else str(row)
            table.add_row(
                key,
                section_cell,
                label,
                display,
                rng,
                key=key,
            )
        if table.row_count:
            table.move_cursor(row=0, column=0)

    def _current_row(self) -> Any | None:
        if not self._ordered:
            return None
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            return self._ordered[0]
        row = table.cursor_row
        if 0 <= row < len(self._ordered):
            return self._ordered[row]
        return self._ordered[0]

    def _current_offset(self) -> int | None:
        row = self._current_row()
        if row == "name" or row is None:
            return None
        try:
            return int(row)
        except Exception:
            return None

    def _current_param(self) -> Any:
        row = self._current_row()
        if row is None:
            return None
        return self._param_of(row)

    def _index_of_row(self, row_id: Any) -> int | None:
        try:
            return self._ordered.index(row_id)
        except ValueError:
            return None

    def _cursor_column(self) -> int:
        """The table's current column, or the first when it is not up yet."""
        try:
            return self.query_one("#midimap-table", DataTable).cursor_column
        except Exception:
            return 0

    def _move_to(self, row: Any, column: int) -> None:
        """Put the cell cursor back on ``row`` in ``column``; no-op if gone."""
        index = self._index_of_row(row)
        if index is None:
            return
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            return
        table.move_cursor(row=index, column=column)

    def _spell(self, offset: int, value: int) -> str:
        try:
            return mm.spell(mm.param_at(offset), value)
        except Exception:
            return str(value)

    def _update_status(self) -> None:
        row = self._current_row()
        if row is None:
            return
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            table = None
        index = 0
        if self._ordered:
            cur = table.cursor_row if table is not None else 0
            if not (0 <= cur < len(self._ordered)):
                cur = self._index_of_row(row) or 0
            index = cur
        total = len(self._ordered)
        section = self._section_of(row)
        label = self._label_of(row)
        value: Any = ""
        if row == "name":
            value = self._display_value(row)
            rng = "text · 12 chars"
        elif isinstance(row, str) and row.startswith("ch"):
            value = self._display_value(row)
            rng = self._range_text(row)
        else:
            off = int(row)
            param = self._param_of(row)
            value = self._raw_value(row)
            rng = f"{param.low}-{param.high}" if param is not None else "?"
            with contextlib.suppress(Exception):
                value = self._values.get(off, getattr(param, "low", value))
        tail = ""
        if self._unstored:
            tail = (
                " · unstored -- s store to a location (survives a power cycle)"
            )
        try:
            status = self.query_one(".status", Static)
            status.update(
                f"row {index + 1}/{total} · {section} · "
                f"{label} {rng} (now {value}){tail}"
            )
        except Exception:  # noqa: S110
            pass

    # --------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Midimap edit[/b]", id="midimap-title")
            yield DataTable(
                id="midimap-table", cursor_type="cell", zebra_stripes=True
            )
            yield Static("", classes="status")
            yield Static(
                "[dim]enter value · / filter · n / p section · c channels · "
                "x effects · h name · w gate · + / - nudge · digits type · "
                "r re-read · s store to a location (survives a power "
                "cycle) · del reset to the default · z / Z undo · "
                "esc / q close[/dim]",
                classes="hints",
            )

    def on_mount(self) -> None:
        table = self.query_one("#midimap-table", DataTable)
        table.add_column("#", key="#")
        table.add_column("section", key="section")
        table.add_column("parameter", key="parameter")
        table.add_column("value", key="value")
        table.add_column("allowed", key="allowed")
        self._refresh_title()
        self._refresh_table()
        self._update_status()

    def say(self, message: str, *, refused: bool = False) -> None:
        try:
            status = self.query_one(".status", Static)
        except Exception:
            return
        status.update(message)
        status.set_class(refused, "refused")

    def set_unstored(self, unstored: bool = True) -> None:
        """Mark the map on screen as edited scratch (or stored again).

        The app calls this after a write (``True``) and after a store
        (``False``): a parameter write edits the unit's **scratch** map,
        and only a Midimap Data frame to a location survives a power
        cycle (the store, manual p.233). The marker is this screen's own
        state and display only -- the status line names it and says what
        ``s`` does -- while the screen still sends nothing.
        """
        self._unstored = unstored
        self._refresh_title()

    def _refresh_title(self) -> None:
        """``Midimap edit - MNN - <name>`` (the location, then the name).

        The scratch/stored state is not in the title; the status line names
        it (`set_unstored`), so the top line stays the one-line identity of
        the map that is open.
        """
        try:
            title = self.query_one("#midimap-title", Label)
        except Exception:
            return
        name = "(empty)" if self._name_blank() else self._name_text()
        title.update(
            f"[b]Midimap edit[/b] - M{self._index:02d} - {literal(name)}"
        )

    def result(  # noqa: C901, PLR0912
        self,
        ok: bool,
        message: str,
        parameter_id: int | None = None,
        value: int | None = None,
        offset: int | None = None,
        **_extra: Any,
    ) -> None:
        off = parameter_id if parameter_id is not None else offset
        if ok:
            # Single-value update (usual case, scratch re-read path).
            if off is not None and value is not None:
                self._values[off] = value

                # Make sure the name row exists once a name char arrives.
                if (
                    isinstance(off, int)
                    and 0 <= off < _NAME_WORDS
                    and "name" not in self._all_rows
                ):
                    self._build_rows()
                    self._ordered = self._visible_rows()
                    self._refresh_table()

                try:
                    table = self.query_one("#midimap-table", DataTable)
                except Exception:
                    table = None
                if table is not None:
                    row_key = (
                        "name"
                        if isinstance(off, int) and 0 <= off < _NAME_WORDS
                        else str(off)
                    )
                    if row_key == "name":
                        with contextlib.suppress(Exception):
                            table.update_cell(
                                "name",
                                "value",
                                self._display_value("name"),
                            )
                    else:
                        with contextlib.suppress(Exception):
                            # A Ch. Program read-back shows the preset name,
                            # like the row does, not the bare number.
                            spelled = (
                                self._display_value(int(off))
                                if _channel_index(int(off)) == 0
                                else self._spell(int(off), value)
                            )
                            table.update_cell(row_key, "value", spelled)
                    # A collapsed channel's summary row must follow too.
                    if (
                        isinstance(off, int)
                        and _CHANNEL_BASE <= off < _GLOBAL_BASE
                    ):
                        channel = (off - _CHANNEL_BASE) // _CHANNEL_STRIDE + 1
                        with contextlib.suppress(Exception):
                            table.update_cell(
                                f"ch{channel}",
                                "value",
                                self._display_value(f"ch{channel}"),
                            )

                    # Re-label the FX parameter rows when a type changes.
                    if isinstance(off, int) and off in (
                        _FX_A_TYPE_OFFSET,
                        _FX_B_TYPE_OFFSET,
                    ):
                        base = (
                            _FX_A_PARM_FIRST
                            if off == _FX_A_TYPE_OFFSET
                            else _FX_B_PARM_FIRST
                        )
                        for index in range(10):
                            row_off = base + index
                            row_key = str(row_off)
                            with contextlib.suppress(Exception):
                                table.update_cell(
                                    row_key,
                                    "parameter",
                                    self._label_of(row_off),
                                )
                            # also refresh their value cell is unnecessary
                # Rebuild the table so _ordered and the rendered rows agree
                # (e.g. after an FX-type change relabels rows or a filter is
                # set); restore the cursor to the row that was current.
                if "name" in self._all_rows and self._filter:
                    current = self._current_row()
                    column = self._cursor_column()
                    self._build_rows()
                    self._refresh_table()
                    if current is not None:
                        self._move_to(current, column)
            if off is not None:
                self._pre_edit.pop(off, None)
        elif off is not None and off in self._pre_edit:
            self._values[off] = self._pre_edit.pop(off)
            self._refresh_table()
            self._update_status()
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

    def _nudge(self, by: int) -> None:  # noqa: C901, PLR0911, PLR0912, PLR0915
        row = self._current_row()
        if row is None:
            return
        if isinstance(row, str) and row.startswith("ch"):
            try:
                channel = int(row[2:])
            except ValueError:
                return
            base = _CHANNEL_BASE + (channel - 1) * _CHANNEL_STRIDE
            bank = self._raw_value(base + 1)
            number = self._raw_value(base)
            try:
                new_bank, new_number = mm.step_channel_preset(bank, number, by)
            except ValueError as exc:
                self.say(str(exc), refused=True)
                return
            # The pair is optimistic: both words are painted now and the
            # write itself belongs to on_channel (one exchange in the app).
            self._pre_edit.setdefault(base, self._values.get(base, number))
            self._pre_edit.setdefault(
                base + 1, self._values.get(base + 1, bank)
            )
            self._values[base] = new_number
            self._values[base + 1] = new_bank
            if self._on_channel is not None:
                self._on_channel(channel, new_bank, new_number)
            column = self._cursor_column()
            self._refresh_table()
            self._move_to(row, column)
            self._update_status()
            return
        if row == "name":
            self.say("the name is edited as text -- press enter")
            return
        off = int(row)
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
        has_choices = param is not None and bool(param.choices)
        if has_choices:
            pairs = list(mm.choices_for(param))
            values = [v for v, _ in pairs]
            try:
                idx = values.index(current)
            except ValueError:
                idx = 0
            if by > 0:
                idx = (idx + 1) % len(values)
            else:
                idx = (idx - 1) % len(values)
            value = values[idx]
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
            with contextlib.suppress(Exception):
                refusal = self._editor.gate.refuse() or refusal
        if refusal is not None:
            self.say(refusal, refused=True)
            return
        self._pre_edit.setdefault(off, self._values.get(off, value))
        self._values[off] = value
        if on_edit is not None:
            on_edit(off, value)
        column = self._cursor_column()
        self._refresh_table()
        # keep the cursor on the same row, in the column it was on
        self._move_to(row, column)
        self._update_status()

    def action_edit_current(self) -> None:  # noqa: C901, PLR0915
        row = self._current_row()
        if row is None:
            return
        if isinstance(row, str) and row.startswith("ch"):
            try:
                channel = int(row[2:])
            except ValueError:
                return
            if channel in self._expanded:
                self._expanded.discard(channel)
            else:
                self._expanded.add(channel)
            self._build_rows()
            column = self._cursor_column()
            self._refresh_table()
            self._move_to(row, column)
            self._update_status()
            return
        if row == "name":
            current_name = self._name_text()

            def apply_name(text: str | None) -> None:
                if text is None:
                    return
                if self._on_name is not None:
                    self._on_name(text)

            self.app.push_screen(
                PromptScreen("Midimap Name (12 chars):", current_name),
                apply_name,
            )
            return

        off = int(row)
        # A channel's Ch. Program / Ch. Bank row opens the preset picker
        # (on_pick) instead of a prompt, when the app plumbed one in.
        if _channel_index(off) in (0, 1) and self._on_pick is not None:
            self._on_pick(_channel_of_offset(off))
            return
        param = None
        try:
            param = mm.param_at(off)
        except Exception:
            param = None
        if param is not None and param.choices:
            pairs = list(mm.choices_for(param))
            labels = [label for _value, label in pairs]
            values = [value for value, _label in pairs]
            current_val = self._values.get(off, param.low)
            try:
                idx = values.index(current_val)
            except ValueError:
                idx = 0
            idx = max(0, min(len(labels) - 1, idx))

            def picked(chosen: int | None) -> None:
                if chosen is None:
                    return
                value = values[chosen]
                refusal = None
                try:
                    refusal = self._editor.allow(off, value)
                except Exception:
                    refusal = None
                if refusal is not None:
                    self.say(refusal, refused=True)
                    return
                self._pre_edit.setdefault(off, self._values.get(off, value))
                self._values[off] = value
                if self._on_edit is not None:
                    self._on_edit(off, value)
                column = self._cursor_column()
                self._refresh_table()
                self._move_to(row, column)
                self._update_status()

            self.app.push_screen(
                ChoiceScreen(param.label, labels, current=idx), picked
            )
        else:
            param_low = getattr(param, "low", 0) if param else 0
            param_high = getattr(param, "high", 0) if param else 0
            current_val = self._values.get(off, param_low) if param else 0

            def apply(text: str | None) -> None:
                if not text:
                    return
                try:
                    value = int(text.strip())
                except ValueError:
                    self.say(f"{text!r} is not a number", refused=True)
                    return
                refusal = None
                try:
                    refusal = self._editor.allow(off, value)
                except Exception:
                    refusal = None
                if refusal is not None:
                    self.say(refusal, refused=True)
                    return
                self._pre_edit.setdefault(off, self._values.get(off, value))
                self._values[off] = value
                if self._on_edit is not None:
                    self._on_edit(off, value)
                column = self._cursor_column()
                self._refresh_table()
                self._move_to(row, column)
                self._update_status()

            self.app.push_screen(
                PromptScreen(
                    f"{param.label if param else 'value'}: "
                    f"{param_low}-{param_high} (now {current_val})",
                    str(current_val),
                ),
                apply,
            )

    def action_re_read(self) -> None:
        if self._on_re_read is not None:
            self._on_re_read()

    def action_store(self) -> None:
        if self._on_store is not None:
            self._on_store()

    def action_reset(self) -> None:
        """Ask the app to reset this map to the factory default.

        The screen sends nothing itself: the app confirms, backs up and
        stores the captured factory-default midimap (``mm.DEFAULT_WORDS``).
        """
        if self._on_reset is not None:
            self._on_reset()

    def action_undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo(1)

    def action_undo_all(self) -> None:
        if self._on_undo is not None:
            self._on_undo(None)

    def action_go_name(self) -> None:
        column = self._cursor_column()
        self._filter = ""
        self._refresh_table()
        self._move_to("name", column)
        self._update_status()

    def action_go_effects(self) -> None:
        column = self._cursor_column()
        self._filter = ""
        self._refresh_table()
        for target, row in enumerate(self._ordered):
            if self._section_of(row) == "Global / Effects":
                try:
                    table = self.query_one("#midimap-table", DataTable)
                    table.move_cursor(row=target, column=column)
                except Exception:  # noqa: S110
                    pass
                break
        self._update_status()

    def action_toggle_all_channels(self) -> None:
        row = self._current_row()
        column = self._cursor_column()
        if self._expanded:
            self._expanded.clear()
        else:
            self._expanded = set(range(1, 17))
        self._build_rows()
        self._refresh_table()
        if row is not None:
            self._move_to(row, column)
        self._update_status()

    def action_next_section(self) -> None:  # noqa: C901, PLR0912
        if not self._ordered:
            return
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            table = None
        cur = table.cursor_row if table is not None else 0
        if not (0 <= cur < len(self._ordered)):
            cur = 0
        column = table.cursor_column if table is not None else 0
        # find section boundaries
        bounds: list[int] = [0]
        for i in range(1, len(self._ordered)):
            if self._section_of(self._ordered[i]) != self._section_of(
                self._ordered[i - 1]
            ):
                bounds.append(i)
        # find current boundary
        current_bound = 0
        for b in bounds:
            if b <= cur:
                current_bound = b
            else:
                break
        # next boundary strictly after current_bound
        next_bound = None
        for b in bounds:
            if b > current_bound:
                next_bound = b
                break
        if next_bound is None and bounds:
            next_bound = bounds[0]
        if next_bound is not None:
            try:
                t = self.query_one("#midimap-table", DataTable)
                t.move_cursor(row=next_bound, column=column)
            except Exception:  # noqa: S110
                pass
        self._update_status()

    def action_prev_section(self) -> None:  # noqa: C901, PLR0912
        if not self._ordered:
            return
        try:
            table = self.query_one("#midimap-table", DataTable)
        except Exception:
            table = None
        cur = table.cursor_row if table is not None else 0
        if not (0 <= cur < len(self._ordered)):
            cur = 0
        column = table.cursor_column if table is not None else 0
        bounds: list[int] = [0]
        for i in range(1, len(self._ordered)):
            if self._section_of(self._ordered[i]) != self._section_of(
                self._ordered[i - 1]
            ):
                bounds.append(i)
        # find current boundary
        current_bound = 0
        for b in bounds:
            if b <= cur:
                current_bound = b
            else:
                break
        # previous boundary strictly before current_bound
        prev_bound = None
        for b in reversed(bounds):
            if b < current_bound:
                prev_bound = b
                break
        if prev_bound is None and bounds:
            prev_bound = bounds[-1]
        if prev_bound is not None:
            try:
                t = self.query_one("#midimap-table", DataTable)
                t.move_cursor(row=prev_bound, column=column)
            except Exception:  # noqa: S110
                pass
        self._update_status()

    def action_filter(self) -> None:
        current = self._filter

        def apply(text: str | None) -> None:
            if text is None:
                self._filter = ""
            else:
                self._filter = text
            self._refresh_table()
            self._update_status()

        self.app.push_screen(PromptScreen("filter label:", current), apply)

    def on_key(self, event: Any) -> None:  # noqa: C901, PLR0911, PLR0912, PLR0915
        key = getattr(event, "key", "")
        char = getattr(event, "character", None)
        # Digits type in place for the current cell -- plain ranges only.
        if char is not None and char.isdigit():
            row = self._current_row()
            if row == "name" or (
                isinstance(row, str) and row.startswith("ch")
            ):
                event.prevent_default()
                return
            param = self._param_of(row) if row is not None else None
            if row is None or (param is not None and param.choices):
                return
            off = row
            if self._typing_offset != off:
                self._typing = ""
                self._typing_offset = off
            self._typing += char
            try:
                status = self.query_one(".status", Static)
                p = self._param_of(row)
                low = getattr(p, "low", 0) if p is not None else 0
                high = getattr(p, "high", 0) if p is not None else 0
                lbl = self._label_of(row)
                status.update(
                    f"typing {self._typing} for {lbl} ({low}-{high})"
                )
            except Exception:  # noqa: S110
                pass
            event.prevent_default()
            return
        if key in ("enter", "return") and self._typing:
            # commit typed number
            row = self._current_row()
            off = row
            if (
                off is None
                or off == "name"
                or (isinstance(off, str) and off.startswith("ch"))
            ):
                self._typing = ""
                self._typing_offset = None
                return
            try:
                value = int(self._typing)
            except ValueError:
                self.say(f"{self._typing!r} is not a number", refused=True)
                self._typing = ""
                self._typing_offset = None
                return
            refusal = None
            try:
                refusal = self._editor.allow(int(off), value)
            except Exception:
                refusal = None
            if refusal is not None:
                self.say(refusal, refused=True)
                self._typing = ""
                self._typing_offset = None
                return
            self._values[int(off)] = value
            if self._on_edit is not None:
                self._on_edit(int(off), value)
            self._typing = ""
            self._typing_offset = None
            column = self._cursor_column()
            self._refresh_table()
            self._move_to(row, column)
            self._update_status()
            event.prevent_default()
            return
        if key in ("backspace",) and self._typing:
            self._typing = self._typing[:-1]
            row = self._current_row()
            if (
                row is not None
                and row != "name"
                and not (isinstance(row, str) and row.startswith("ch"))
            ):
                try:
                    status = self.query_one(".status", Static)
                    p = self._param_of(row)
                    low = getattr(p, "low", 0) if p is not None else 0
                    high = getattr(p, "high", 0) if p is not None else 0
                    lbl = self._label_of(row)
                    status.update(
                        f"typing {self._typing} for {lbl} ({low}-{high})"
                    )
                except Exception:  # noqa: S110
                    pass
            event.prevent_default()
            return
        if key in ("escape",):
            self._typing = ""
            self._typing_offset = None

    def on_data_table_cell_highlighted(self, event: Any) -> None:
        self._typing = ""
        self._typing_offset = None
        self._update_status()

    def on_data_table_row_highlighted(self, event: Any) -> None:
        self._typing = ""
        self._typing_offset = None
        self._update_status()

    def update_params(self, params: dict[int, int]) -> None:
        """Replace every value -- a scratch re-read, a rename, a pair write.

        The cursor follows the row it was on, in its column: this lands
        asynchronously *after* a write, and jumping the user to the top-left
        cell on every ``+``/``-`` would silently lose their place.
        """
        row = self._current_row()
        column = self._cursor_column()
        self._values = dict(params)
        self._build_rows()
        self._filter = ""
        self._ordered = self._visible_rows()
        self._refresh_table()
        if row is not None:
            self._move_to(row, column)
        self._update_status()
