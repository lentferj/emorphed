# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#

"""Modal screens, the key legend.

Split out of :mod:`emorphed.app` so the browser itself stays readable, on the
same shape as :mod:`rxved.screens`. This module holds every widget the
application opens, plus the legend. It imports nothing from
:mod:`emorphed.app`, so the dependency runs one way only.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from emorphed.text import escape, literal
from emu import banks
from vinsynlib import keys
from vinsynlib.keys import wrap_blocks
from vinsynlib.ui.hints import KeyHints as _LibraryKeyHints
from vinsynlib.ui.prompt import PromptScreen
from vinsynlib.ui.report import ReportScreen as _Frame

__all__ = [
    "KEY_HINTS",
    "VIEW_ALL",
    "VIEW_ALL_FAVOURITES",
    "VIEW_BANK_FAVOURITES",
    "VIEW_CYCLE",
    "VIEW_LABEL",
    "KeyHints",
    "MidimapPickerScreen",
    "PickerPosition",
    "PresetPickerScreen",
    "PromptScreen",
    "ReportScreen",
    "escape",
    "literal",
    "wrap_blocks",
]


#: rxved's shape: ``enter`` closes as well. Three lines, no rewrite --
#: so the frame's words are the library's and the only difference is the
#: key that closes it.
class ReportScreen(_Frame):
    """emorphed's shape: ``enter`` closes as well. Three lines, no rewrite."""

    BINDINGS: ClassVar[list[Any]] = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("enter", "close", "Close"),
    ]


class KeyHints(_LibraryKeyHints):
    """The library legend, relaid out after every re-wrap.

    The library widget re-wraps its text on mount and on resize but never
    asks for a layout, so ``height: auto`` keeps whatever height the first
    render gave it. That first render happens before the widget has a width:
    the wrap falls back to its minimum, the whole legend stacks into about a
    dozen lines, and the footer stays that tall -- a band of empty panel
    under the keys -- until the terminal is resized. Requesting the layout
    after each re-wrap keeps the footer only as tall as the wrapped text,
    which is the point of wrapping it here at all.
    """

    def on_mount(self) -> None:
        super().on_mount()
        self.call_after_refresh(self.refresh, layout=True)

    def on_resize(self) -> None:
        super().on_resize()
        self.call_after_refresh(self.refresh, layout=True)


#: Re-exported from vinsynlib: one line of text, submits on enter, cancels
#: on escape. Kept as a name so call sites read exactly as they did.


def _view_key(blocks: tuple[str, ...]) -> tuple[str, ...]:
    """Swap the family's ``F favourites view`` for this tool's ``v``.

    ``f`` writes the favourites database and ``F`` does not, so the family's
    shift-pair left a write one slip away from a read; ``v`` has no such
    twin. rxved and p2ked made the same swap, and the family asks a tool
    that renames a shared key to say why in its own test -- see
    tests/test_conformance.py, where the whole divergence is two sentences.

    The extras are this tool's own keys: the legend is a promise about which
    keys work, and the app binds every one of them.
    """
    return tuple(
        "v favourites view" if block == "F favourites view" else block
        for block in blocks
    )


#: The legend. Every binding the app has, in the order somebody meets them.
KEY_HINTS = _view_key(
    keys.legend(
        (
            "d device ID",
            "k kind",
            "S scan device",
            "* rating",
            "V rating filter",
            "z undo",
            "Z undo all",
            "m midimap edit",
            "w write gate",
        )
    )
)


#: What the slot pane is showing. Cycled by `v`.
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"

#: The order `v` steps through.
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)

VIEW_LABEL = {
    VIEW_ALL: "all slots",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "all favourites",
}


@dataclass(frozen=True)
class PickerPosition:
    """Where the preset picker was left."""

    bank: str | None = None
    slot: str | None = None
    focus: str = "picker-banks"


class PresetPickerScreen(ModalScreen[tuple[int, int] | None]):
    """Pick a preset (bank word + slot number) for a midimap channel.

    Two panes: the five preset-bearing regions, and the selected region's
    slots. ``tab`` switches panes; arrows move; ``⏎`` confirms; ``escape`` /
    ``q`` cancel. ``v`` cycles the slot pane through all slots, this bank's
    favourites, and every favourite.
    """

    DEFAULT_CSS = """
    PresetPickerScreen { align: center middle; }
    PresetPickerScreen > Vertical {
        width: 90%; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    PresetPickerScreen DataTable { height: 1fr; width: 1fr; }
    PresetPickerScreen .hint { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("tab", "switch_pane", "Switch pane", show=False),
        Binding("v", "cycle_view", "Favourites view", show=False),
    ]

    def __init__(
        self,
        catalog: Any,
        *args: Any,
        favorites: Any = None,
        current: Any = None,
        view: int = 0,
        position: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._catalog = catalog
        positional_favorites: Any = None
        positional_current: Any = None
        if len(args) >= 1:
            first = args[0]
            if hasattr(first, "keys_for_bank"):
                positional_favorites = first
            else:
                positional_current = first
        if len(args) >= 2:  # noqa: PLR2004
            second = args[1]
            if hasattr(second, "keys_for_bank"):
                positional_favorites = second
            else:
                positional_current = second
        self._favorites = (
            favorites if favorites is not None else positional_favorites
        )
        self._current = current if current is not None else positional_current
        self._view = view
        self._position = position
        self._filled_bank: str | None = None
        #: The five preset-bearing regions, keyed by bank word.
        self._bank_ids: list[str] = [
            rid
            for rid, _ in sorted(
                banks.BANK_SELECT.items(), key=lambda kv: kv[1]
            )
        ]
        self._bank_id_set: set[str] = set(self._bank_ids)

    @property
    def view(self) -> int:
        return self._view

    @property
    def position(self) -> PickerPosition:
        return PickerPosition(
            bank=self._bank_id(),
            slot=self._cursor_key("#picker-slots"),
            focus=self._focused_pane(),
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title(), id="picker-title")
            with Horizontal():
                yield DataTable(
                    id="picker-banks", cursor_type="row", zebra_stripes=True
                )
                yield DataTable(
                    id="picker-slots", cursor_type="row", zebra_stripes=True
                )
            yield Static(
                "[dim]tab pane · v view · enter pick · esc cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        table = self.query_one("#picker-banks", DataTable)
        table.add_column("bank", key="bank")
        for region_id in self._bank_ids:
            table.add_row(region_id, key=region_id)
        table.focus()
        self._fill_slots()
        self._restore_position()

    def _bank_id(self) -> str | None:
        return self._cursor_key("#picker-banks")

    def _cursor_key(self, table_id: str) -> str | None:
        table = self.query_one(table_id, DataTable)
        if not table.row_count:
            return None
        return str(
            table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
        )

    def _select_row(self, table_id: str, key: str | None) -> None:
        if key is None:
            return
        table = self.query_one(table_id, DataTable)
        for index, row_key in enumerate(table.rows):
            if str(row_key.value) == key:
                table.move_cursor(row=index)
                return

    def _focused_pane(self) -> str:
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id is not None:
            return focused.id
        return "picker-banks"

    def _restore_position(self) -> None:
        position = self._position
        if position is None:
            return
        with contextlib.suppress(Exception):
            self._select_row("#picker-banks", position.bank)
            self._fill_slots()
            self._select_row("#picker-slots", position.slot)
            if position.focus in ("picker-banks", "picker-slots"):
                self.query_one(f"#{position.focus}", DataTable).focus()

    def _fill_slots(self) -> None:
        self._filled_bank = self._bank_id()
        table = self.query_one("#picker-slots", DataTable)
        table.clear(columns=True)
        table.add_column("#", key="number")
        table.add_column("name", key="name")
        for slot in self._visible_slots():
            name = self._catalog.display_name(slot.bank_id, slot.number)
            table.add_row(
                f"{slot.bank_id} {slot.number:03d}",
                name,
                key=slot.key,
            )

    def _visible_slots(self) -> list[Any]:
        view = VIEW_CYCLE[self._view]
        if view == VIEW_ALL:
            bank_id = self._bank_id()
            if bank_id is None:
                return []
            return banks.slots(bank_id)
        if self._favorites is None:
            return []
        if view == VIEW_BANK_FAVOURITES:
            bank_id = self._bank_id()
            if bank_id is None:
                return []
            marked = self._favorites.keys_for_bank(bank_id)
            return [s for s in banks.slots(bank_id) if s.number in marked]
        rows: list[Any] = []
        for favourite in self._favorites.all(order="bank"):
            if favourite.bank_id not in self._bank_id_set:
                continue
            try:
                rows.append(banks.slot(favourite.bank_id, favourite.number))
            except (LookupError, ValueError):
                continue
        return rows

    def _title(self) -> str:
        view = VIEW_CYCLE[self._view]
        return f"[b]Pick a preset[/b]  [dim]· {VIEW_LABEL[view]}[/dim]"

    def on_data_table_row_highlighted(self, event: Any) -> None:
        if getattr(event, "data_table", None) is None:
            return
        if event.data_table.id != "picker-banks":
            return
        if VIEW_CYCLE[self._view] == VIEW_ALL_FAVOURITES:
            return
        if self._bank_id() == self._filled_bank:
            return
        self._fill_slots()

    def on_data_table_row_selected(self, event: Any) -> None:
        if getattr(event, "data_table", None) is None:
            return
        if event.data_table.id != "picker-slots":
            return
        self.dismiss(self._slot())

    def _slot(self) -> tuple[int, int] | None:
        table = self.query_one("#picker-slots", DataTable)
        if not table.row_count:
            return None
        key = str(
            table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
        )
        bank_id, _, number_str = key.rpartition(":")
        try:
            number = int(number_str)
        except ValueError:
            return None
        if bank_id not in self._bank_id_set:
            return None
        bank_word = banks.BANK_SELECT[bank_id]
        return (int(bank_word), number)

    def action_switch_pane(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id == "picker-banks":
            self.query_one("#picker-slots", DataTable).focus()
        else:
            self.query_one("#picker-banks", DataTable).focus()

    def action_cycle_view(self) -> None:
        self._view = (self._view + 1) % len(VIEW_CYCLE)
        self.query_one("#picker-title", Label).update(self._title())
        self._fill_slots()

    def action_cancel(self) -> None:
        self.dismiss(None)


class MidimapPickerScreen(ModalScreen[int | None]):
    """Pick the midimap location to store to, by bank and name.

    Two panes: the midimap regions -- RAM 0-15, card 16-31 (manual p.233)
    -- and the selected bank's stored midimaps, named from the catalog.
    ``tab`` switches panes; arrows move; ``⏎`` picks; ``escape``/``q``
    cancel. Returns the location 0-31 -- the number a Midimap Data store
    writes to -- or ``None``.
    """

    DEFAULT_CSS = """
    MidimapPickerScreen { align: center middle; }
    MidimapPickerScreen > Vertical {
        width: 90%; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    MidimapPickerScreen DataTable { height: 1fr; width: 1fr; }
    MidimapPickerScreen .hint { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("tab", "switch_pane", "Switch pane", show=False),
    ]

    #: The midimap regions: RAM 0-15, card 16-31 (manual p.233).
    BANK_IDS: ClassVar[tuple[str, ...]] = ("M-RAM", "M-CARD")

    def __init__(
        self,
        catalog: Any,
        *,
        current: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._catalog = catalog
        self._current = current
        self._filled_bank: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Store to a midimap[/b]", id="picker-title")
            with Horizontal():
                yield DataTable(
                    id="picker-banks", cursor_type="row", zebra_stripes=True
                )
                yield DataTable(
                    id="picker-slots", cursor_type="row", zebra_stripes=True
                )
            yield Static(
                "[dim]tab pane · enter store here · esc cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        table = self.query_one("#picker-banks", DataTable)
        table.add_column("bank", key="bank")
        for region_id in self.BANK_IDS:
            table.add_row(banks.region(region_id).label, key=region_id)
        table.focus()
        self._fill_slots()
        self._select_current()

    def _bank_id(self) -> str | None:
        return self._cursor_key("#picker-banks")

    def _cursor_key(self, table_id: str) -> str | None:
        table = self.query_one(table_id, DataTable)
        if not table.row_count:
            return None
        return str(
            table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
        )

    def _select_row(self, table_id: str, key: str) -> None:
        table = self.query_one(table_id, DataTable)
        for index, row_key in enumerate(table.rows):
            if str(row_key.value) == key:
                table.move_cursor(row=index)
                return

    def _fill_slots(self) -> None:
        self._filled_bank = self._bank_id()
        table = self.query_one("#picker-slots", DataTable)
        table.clear(columns=True)
        table.add_column("midimap", key="number")
        table.add_column("name", key="name")
        if self._filled_bank is None:
            return
        for slot in banks.slots(self._filled_bank):
            name = self._catalog.display_name(self._filled_bank, slot.number)
            here = "  <- current" if slot.index == self._current else ""
            table.add_row(f"{slot.index:02d}", name + here, key=slot.key)

    def _select_current(self) -> None:
        if self._current is None:
            return
        for region_id in self.BANK_IDS:
            region = banks.region(region_id)
            if region.first <= self._current <= region.last:
                self._select_row("#picker-banks", region_id)
                self._fill_slots()
                self._select_row(
                    "#picker-slots",
                    f"{region_id}:{self._current - region.first:03d}",
                )
                return

    def _location(self) -> int | None:
        table = self.query_one("#picker-slots", DataTable)
        if not table.row_count:
            return None
        key = str(
            table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
        )
        region_id, _, number_str = key.rpartition(":")
        if region_id not in self.BANK_IDS:
            return None
        try:
            number = int(number_str)
        except ValueError:
            return None
        return banks.region(region_id).first + number

    def on_data_table_row_highlighted(self, event: Any) -> None:
        if getattr(event, "data_table", None) is None:
            return
        if event.data_table.id != "picker-banks":
            return
        if self._bank_id() == self._filled_bank:
            return
        self._fill_slots()

    def on_data_table_row_selected(self, event: Any) -> None:
        if getattr(event, "data_table", None) is None:
            return
        if event.data_table.id != "picker-slots":
            return
        self.dismiss(self._location())

    def action_switch_pane(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id == "picker-banks":
            self.query_one("#picker-slots", DataTable).focus()
        else:
            self.query_one("#picker-banks", DataTable).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
