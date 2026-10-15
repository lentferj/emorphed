# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The key-hint legend is ported from the sibling rxved and p2ked projects,
# which port it from s3ked, eosed and k2kremote:
#   Copyright (C) 2026  rxved / p2ked / s3ked / eosed / k2kremote
#   contributors                                     - GPL-2.0-or-later
#
# emorphed is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# emorphed is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""``emorphed`` -- a terminal browser for the E-mu Morpheus.

Two panes: regions on the left, that region's contents on the right.

Four rules, each about not lying to the user:

**Moving the cursor never sends anything.** Selecting a preset changes
what the instrument plays. Selection is bound to Enter and nothing else,
and a test enforces it.

**Reading names makes no sound, and costs one message.** This instrument
has a Preset List Request that returns every name in the order it shows
them -- and the same for hyperpresets and midimaps. None of the sibling
instruments can do that, which is why `r` here reads a whole kind at once
rather than walking it.

**A preset index is not a program number.** The index is what System
Exclusive addresses; a Program Map decides what program change reaches a
preset, and for ROM or card presets there may be no program number at all
until a map gives one. The status line says which it used whenever it
sends one.

**Two of the seven regions need a card.** A request for one with no card
fitted is ignored outright -- not refused, ignored -- so those regions are
marked and a read of them that comes back empty is reported as "no card"
rather than as a fault.
"""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Header, Static

from emorphed.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen
from emorphed.screens import KEY_HINTS, PromptScreen, ReportScreen
from emu import banks
from emu import catalog as cat
from emu import livenames as _livenames
from emu import messages as msg
from emu.device import Device
from emu.favorites import Favorite, Favorites
from vinsynlib.build import build_of
from vinsynlib.cli import add_common_arguments, make_parser, validate_common
from vinsynlib.keys import wrap_blocks as _wrap_blocks
from vinsynlib.ui.hints import KeyHints
from vinsynlib.ui.modals import RatingFilter, RatingFilterScreen
from vinsynlib.ui.work import QUIET_BRIDGE_ERRORS, BusyGate, close_when_idle
from vinsynlib.undo import Record, UndoLog

__all__ = ["KEY_HINTS", "EmorphedApp", "build_parser", "main", "wrap_blocks"]

_SEP = " · "

#: What `F` steps through. The same three the sibling rxved and p2ked use,
#: so the key means the same thing across these projects.
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all slots",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}


def wrap_blocks(blocks: Sequence[str], width: int, sep: str = _SEP) -> str:
    """Pack hints into lines no wider than ``width``.

    Re-exported from :func:`vinsynlib.keys.wrap_blocks`, which every tool
    in this family now uses. Kept as a name because it is part of this
    module's published surface.
    """
    return _wrap_blocks(blocks, width, sep)


#: Family quiet set plus this instrument's own bridge errors.
_BRIDGE_ERRORS: tuple[type[BaseException], ...] = (
    *QUIET_BRIDGE_ERRORS,
    ValueError,
    LookupError,
    RuntimeError,
    SystemError,
)


@dataclass(frozen=True)
class FavouriteChange:
    bank_id: str
    number: int
    was_favourite: bool


@dataclass(frozen=True)
class RatingChange:
    bank_id: str
    number: int
    was_rating: int


@dataclass
class TagNoteChange:
    bank_id: str
    number: int
    field: str = "tags"
    old: str | None = None
    old_text: str | None = None
    text: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        if self.old_text is None and self.old is not None:
            object.__setattr__(self, "old_text", self.old)
        if self.old is None and self.old_text is not None:
            object.__setattr__(self, "old", self.old_text)
        if self.text is None:
            object.__setattr__(self, "text", self.old_text)
        if self.value is None:
            object.__setattr__(self, "value", self.old_text)


class _ChangesView(list[Any]):
    def __init__(self, log: UndoLog, changes: list[Any]) -> None:
        super().__init__(changes)
        self._log = log

    def append(self, change: object) -> None:
        label = _change_label(change)
        self._log.push(Record(label, change))
        super().append(change)


def _change_label(change: object) -> str:
    if isinstance(change, FavouriteChange):
        return "favourite"
    if isinstance(change, RatingChange):
        return "rating"
    if isinstance(change, TagNoteChange):
        field = getattr(change, "field", "tags")
        return "note" if field == "note" else "tags"
    return "change"


Change = FavouriteChange | RatingChange | TagNoteChange


class EmorphedApp(App[None]):
    """The browser."""

    CSS = """
    Screen { layers: base; }
    #panes { height: 1fr; }
    /* Sized to its content. A fixed width does not truncate the end
       of a label -- the table scrolls sideways and clips the
       *start*, so a bank reads as nonsense rather than as narrow. */
    #bank-table {
        width: auto; min-width: 20; max-width: 52;
        border-right: solid $panel;
    }
    #slot-table { width: 1fr; }
    DataTable { height: 1fr; }
    #detail { height: 3; padding: 0 1; border-top: solid $panel; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        # Enter is NOT bound here: a focused DataTable consumes it for its
        # own row selection, so it arrives as RowSelected instead.
        Binding("r", "read_names", "Read names"),
        Binding("S", "scan_device", "Scan device"),
        Binding("left_square_bracket", "channel_down", "Channel -"),
        Binding("right_square_bracket", "channel_up", "Channel +"),
        Binding("c", "pick_channel", "Set channel"),
        Binding("d", "pick_device_id", "Set device ID"),
        Binding("f", "toggle_favorite", "Favourite"),
        Binding("F", "cycle_favorites", "Favourites view"),
        Binding("t", "edit_tags", "Tags"),
        Binding("n", "edit_note", "Note"),
        Binding("asterisk", "edit_rating", "Rating"),
        Binding("V", "rating_filter", "Rating filter"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        Binding("slash", "search", "Search"),
        Binding("i", "device_info", "Device"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
        Binding("k", "cycle_kind", "Kind view"),
    ]

    def __init__(  # noqa: PLR0913
        self,
        device: Device,
        *,
        catalog: cat.Catalog | None = None,
        favorites: Favorites | None = None,
        config_path: str | None = None,
        live_names_path: str | None = None,
        demo: bool = False,
        offer_scan: bool = False,
    ) -> None:
        super().__init__()
        #: Everything ``z`` can reverse, in the order it happened. Made
        #: first in ``__init__`` because a watcher can fire before the
        #: constructor has finished -- the undo log has to be there first.
        self._undo_log = UndoLog(gate_hook=self._undo_gate)
        self.device = device
        self.catalog = catalog if catalog is not None else cat.empty()
        #: Injected, never opened here, so a test cannot write into the
        #: user's real database.
        self.favorites = favorites
        #: Where the send channel is remembered. Injected and None
        #: in tests, so a test cannot drop a config into the
        #: working directory.
        self._config_path = config_path
        #: Where names read off the unit are kept between runs.
        self._live_names_path = live_names_path
        #: Whether this is the demo device. The demo invents its names, so a
        #: scan of it must never be written to the real catalog.
        self._demo = demo
        #: Whether to offer a scan when there is no catalog at all. Set by
        #: the entrypoint; off by default so a test never gets a modal it
        #: did not ask for.
        self._offer_scan = offer_scan
        #: Raised by the scan modal's Cancel and checked between kinds.
        self._scan_cancel = threading.Event()
        self.view_mode = VIEW_ALL
        #: Which kind's view the right pane is currently showing. Cycles
        #: preset -> hyperpreset -> midimap on `k`. A pure read: it sends
        #: nothing to the unit.
        self.kind_view = banks.Kind.PRESET
        self._kind_view = self.kind_view
        self._bank_ids: list[str] = banks.region_ids()
        self._current_bank = self._bank_ids[0]
        self._current: list[banks.Slot] = []
        #: Busy gate replaces the old ``_busy`` flag / RLock pair. Thread-safe:
        #: the gate refuses on the main thread before a worker is spawned and
        #: tracks the exchange's in-progress state for an idle close.
        self._busy_gate = BusyGate()
        #: One exchange at a time, claimed on the main thread. The main
        #: thread takes it (non-blocking) before it spawns the worker and
        #: the worker always releases it in a ``finally``. The gate alone
        #: cannot carry this: entering the gate *clears* a refusal, so
        #: between reserving one and entering it for real a second action
        #: would find neither ``check()`` nor ``is_busy()`` set and start a
        #: second worker. ``_busy`` reads this claim as a third signal.
        self._exchange = threading.Lock()
        self._filling = False
        # Load persisted rating filter from ui-state.
        self.rating_filter: RatingFilter | None = None
        if self._config_path is not None:
            try:
                from emu import config as _cfg

                stars = _cfg.load_ui_int("rating_stars", self._config_path)
                at_least = _cfg.load_ui_bool(
                    "rating_at_least", self._config_path
                )
                if stars is not None:
                    self.rating_filter = RatingFilter(
                        stars=stars, at_least=bool(at_least)
                    )
            except Exception:
                self.rating_filter = None
                # The cache is best-effort; ignore a bad read.
                _ = None

    @property
    def _changes(self) -> list[Any]:
        return _ChangesView(
            self._undo_log, [r.payload for r in self._undo_log]
        )

    @_changes.setter
    def _changes(self, changes: list[Any]) -> None:
        self._undo_log.clear()
        for change in changes:
            self._push_change(change)

    def _push_change(self, change: object) -> None:
        self._undo_log.push(Record(_change_label(change), change))

    def _undo_gate(self) -> str | None:
        return "busy" if self._busy else None

    @property
    def _busy(self) -> bool:
        return (
            self._busy_gate.check() is not None
            or self._busy_gate.is_busy()
            or self._exchange.locked()
        )

    @_busy.setter
    def _busy(self, value: bool) -> None:
        # Compatibility pin only: the gate owns the busy state. Tests that set
        # it directly (the legacy pin) are migrated to ``_busy_gate.refuse``;
        # this keeps an assignment from crashing a stray caller.
        if value:
            if self._busy_gate.check() is None:
                self._busy_gate.refuse("busy")
        else:
            with self._busy_gate._lock:
                self._busy_gate._refused = None

    def action_undo(self) -> None:
        self._undo_master_edits(1)

    def action_undo_all(self) -> None:
        self._undo_master_edits(None)

    def _undo_master_edits(self, count: int | None = None) -> None:  # noqa: C901
        taken = self._undo_log.plan(
            len(self._changes) if count is None else count
        )
        if not taken:
            refusal = self._undo_log.last_refusal
            if refusal is not None:
                self.notify_status(refusal, refused=True)
            elif not self._changes:
                self.notify_status("nothing to undo")
            return
        changes = [record.payload for record in taken]
        favourites = 0
        ratings = 0
        tags_notes = 0
        for change in changes:
            if isinstance(change, FavouriteChange):
                favourites += 1
                self._undo_favourite(change)
            elif isinstance(change, RatingChange):
                ratings += 1
                self._undo_rating(change)
            elif isinstance(change, TagNoteChange):
                tags_notes += 1
                self._undo_tag_note(change)
        if self.favorites is not None:
            self._refill_keeping_place()
        parts = []
        if favourites:
            parts.append(
                f"{favourites} favourite{'s' if favourites != 1 else ''}"
            )
        if ratings:
            parts.append(f"{ratings} rating{'s' if ratings != 1 else ''}")
        if tags_notes:
            parts.append(
                f"{tags_notes} tag/note{'s' if tags_notes != 1 else ''}"
            )
        msg = "undid " + ", ".join(parts) if parts else "undid"
        self.notify_status(msg)

    def _undo_favourite(self, change: FavouriteChange) -> None:
        if self.favorites is None:
            return
        name = self.catalog.display_name(change.bank_id, change.number)
        self.favorites.toggle(change.bank_id, change.number, name=name)

    def _undo_rating(self, change: RatingChange) -> None:
        if self.favorites is None:
            return
        self.favorites.set_rating(
            change.bank_id, change.number, change.was_rating
        )

    def _undo_tag_note(self, change: TagNoteChange) -> None:
        if self.favorites is None:
            return
        text = change.old_text if change.old_text is not None else ""
        if change.field == "note":
            self.favorites.set_note(change.bank_id, change.number, text)
        else:
            self.favorites.set_tags(change.bank_id, change.number, text)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            yield DataTable(id="bank-table", cursor_type="row")
            yield DataTable(id="slot-table", cursor_type="row")
        yield Static("", id="detail")
        yield Static("", id="status")
        # KEY_HINTS passed explicitly: the shared widget defaults to the
        # canonical family legend, and this tool's own hints -- `d device ID`
        # -- are its business, not the library's.
        yield KeyHints(KEY_HINTS)

    def on_mount(self) -> None:
        self.title = "emorphed"
        table = self.query_one("#bank-table", DataTable)
        for label, key in (
            ("region", "bank"),
            ("n", "n"),
            ("", "src"),
            ("♥", "fav"),
        ):
            table.add_column(label, key=key)
        for bank_id in self._bank_ids:
            entry = banks.region(bank_id)
            marked = len(self._favorite_keys(bank_id))
            table.add_row(
                entry.label,
                str(entry.count),
                (
                    "card"
                    if entry.needs_card
                    else ("" if entry.writable else "rom")
                ),
                # blank rather than "0": a column of zeroes is
                # noise, and the eye wants the few that differ
                str(marked) if marked else "",
                key=bank_id,
            )

        slots = self.query_one("#slot-table", DataTable)
        # The favourite marker leads the row rather than trailing it: it is
        # a gutter mark the eye runs down, and gluing it to the name would
        # carry it into anything that sorts or searches.
        for label, key in (
            ("♥", "fav"),
            ("#", "num"),
            ("name", "name"),
            ("index", "index"),
        ):
            slots.add_column(label, key=key)
        self._fill(self._current_bank)
        table.focus()
        self.notify_status(
            f"{len(self.catalog)} names from the catalog"
            if self.catalog
            else "no catalog -- numbers only. Build one with "
            "tools/extract_catalog.py, or press r to read from the unit."
        )
        if self._offer_scan:
            self.set_timer(0.6, self._maybe_offer_scan)

    # --- filling ------------------------------------------------------------

    def _favorite_keys(self, bank_id: str) -> set[int]:
        if self.favorites is None:
            return set()
        return self.favorites.keys_for_bank(bank_id)

    def _all_favourites(self) -> list[banks.Slot]:
        """Every favourite in every bank, in bank order then number.

        Built from the slots rather than from the favourites rows, so a row
        naming a bank this build does not know is skipped rather than
        breaking the list.
        """
        if self.favorites is None:
            return []
        wanted: dict[str, set[int]] = {}
        for favourite in self.favorites.all(order="bank"):
            wanted.setdefault(favourite.bank_id, set()).add(favourite.number)
        out: list[banks.Slot] = []
        for bank_id in banks.region_ids():
            numbers = wanted.get(bank_id)
            if not numbers:
                continue
            out.extend(e for e in banks.slots(bank_id) if e.number in numbers)
        return out

    def _visible(self, bank_id: str) -> list[banks.Slot]:
        if self.view_mode == VIEW_ALL_FAVOURITES:
            entries = self._all_favourites()
        else:
            entries = banks.slots(bank_id)
            if self.view_mode == VIEW_BANK_FAVOURITES:
                marked = self._favorite_keys(bank_id)
                entries = [e for e in entries if e.number in marked]
        return self._by_rating(entries)

    def _by_rating(self, entries: list[banks.Slot]) -> list[banks.Slot]:
        if self.rating_filter is None or self.favorites is None:
            return entries
        flt = self.rating_filter
        out = []
        for entry in entries:
            fav = self.favorites.get(entry.bank_id, entry.number)
            rating = fav.rating if fav is not None else 0
            if flt.at_least:
                if rating >= flt.stars:
                    out.append(entry)
            elif rating == flt.stars:
                out.append(entry)
        return out

    def action_rating_filter(self) -> None:
        current = self.rating_filter or RatingFilter(stars=0, at_least=False)

        def apply(value: RatingFilter | None) -> None:
            if value is None:
                return
            if value.stars == 0 and value.at_least:
                self.rating_filter = None
            else:
                self.rating_filter = value
            self._save_rating_filter()
            self._refill_keeping_place()

        self.push_screen(RatingFilterScreen(current), apply)

    def _save_rating_filter(self) -> None:
        if self._config_path is None:
            return
        try:
            from emu import config as _cfg

            if self.rating_filter is None:
                _cfg.save_ui_state("rating_stars", None, self._config_path)
                _cfg.save_ui_state("rating_at_least", None, self._config_path)
            else:
                _cfg.save_ui_state(
                    "rating_stars", self.rating_filter.stars, self._config_path
                )
                _cfg.save_ui_state(
                    "rating_at_least",
                    bool(self.rating_filter.at_least),
                    self._config_path,
                )
        except Exception:
            # The cache is best-effort.
            _ = None

    def _cursor_entry(self) -> banks.Slot | None:
        """The row under the cursor, or None."""
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return None
        return self._current[row]

    # --- the send channel ---------------------------------------------------

    def _channel(self) -> int:
        return getattr(self.device, "channel", 0)

    def _set_channel(self, channel: int) -> None:
        """Change the channel selections are sent on, and remember it."""
        channel = max(0, min(15, channel))
        try:
            self.device.channel = channel
        except Exception:
            self.notify_status(
                "this device has no settable channel", refused=True
            )
            return
        self._remember_channel(channel)
        self.notify_status(f"sending on MIDI channel {channel + 1}")

    def _remember_channel(self, channel: int) -> None:
        """Save it for next time. Only OSError is swallowed."""
        if getattr(self, "_config_path", None) is None:
            return
        from emu import config

        try:
            config.save_channel(channel, self._config_path)
        except OSError:
            pass

    def action_channel_up(self) -> None:
        self._set_channel(self._channel() + 1)

    def action_channel_down(self) -> None:
        self._set_channel(self._channel() - 1)

    def action_pick_device_id(self) -> None:
        """Set the SysEx device ID. Not the MIDI channel: this instrument
        has both and they are set in different places on it."""

        def done(text: str | None) -> None:
            if not text:
                return
            try:
                value = int(text)
            except ValueError:
                self.notify_status(f"{text!r} is not a number", refused=True)
                return
            if not 0 <= value <= 15:
                self.notify_status("a device ID is 0-15", refused=True)
                return
            self.device.device_id = value
            self._remember_device_id(value)
            self.notify_status(f"device ID {value}")

        self.push_screen(
            PromptScreen(
                "SysEx device ID (0-15), not the MIDI channel:",
                str(getattr(self.device, "device_id", 0)),
            ),
            done,
        )

    def _remember_device_id(self, value: int) -> None:
        if self._config_path is None:
            return
        from emu import config

        try:
            config.save_device_id(value, self._config_path)
        except OSError:
            pass

    def action_pick_channel(self) -> None:
        def apply(text: str | None) -> None:
            if not text:
                return
            try:
                value = int(text)
            except ValueError:
                self.notify_status(f"{text!r} is not a number", refused=True)
                return
            if not 1 <= value <= 16:
                self.notify_status("MIDI channels are 1-16", refused=True)
                return
            self._set_channel(value - 1)

        self.push_screen(
            PromptScreen("MIDI channel (1-16):", str(self._channel() + 1)),
            apply,
        )

    def action_toggle_favorite(self) -> None:
        """Mark or unmark the slot under the cursor. Sends no MIDI."""
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return
        entry = self._current[row]
        # entry.bank_id, not self._current_bank. In the all-favourites view
        # the rows come from every bank while the bank pane sits on one of
        # them, so using the pane's bank favourited a slot the user was not
        # looking at and left the one they were. _fill has always read the
        # row's own bank; these did not.
        bank_id = entry.bank_id
        name = self.catalog.display_name(bank_id, entry.number)
        # Favorites.toggle, not remove-then-add: un-favouriting keeps
        # the row so a rating, tags, a note and the original date
        # survive being toggled off and on. As a delete followed by a
        # fresh add this destroyed all four, and this is one keystroke.
        was = self.favorites.get(bank_id, entry.number) is not None
        now = self.favorites.toggle(bank_id, entry.number, name=name)
        self._push_change(FavouriteChange(bank_id, entry.number, was))
        self.notify_status(f"{'favourited' if now else 'unfavourited'} {name}")
        self._refill_keeping_place()

    def _favourite_under_cursor(
        self,
    ) -> tuple[tuple[str, int] | None, Favorite | None]:
        """The favourite row for the slot under the cursor, if there is one.

        Tags and notes hang off a favourite, so there is nothing to attach
        them to until `f` has been pressed. Saying so is better than
        silently creating one: the user asked to annotate, not to favourite.
        """
        entry = self._cursor_entry()
        if entry is None or self.favorites is None:
            return None, None
        # The row's bank, for the reason action_toggle_favorite gives: in
        # the all-favourites view a tag or a note written against the bank
        # pane's bank lands on a different slot than the one on screen.
        bank_id = entry.bank_id
        number = entry.number
        return (bank_id, number), self.favorites.get(bank_id, number)

    def action_edit_tags(self) -> None:
        if self.favorites is None:
            return
        favorites = self.favorites
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status(
                "not a favourite yet -- press f first", refused=True
            )
            return

        def apply(value: str | None) -> None:
            if value is None:
                return
            old = existing.tags
            favorites.set_tags(where[0], where[1], value)
            self._push_change(
                TagNoteChange(where[0], where[1], "tags", old=old)
            )
            self._refill_keeping_place()
            self.notify_status("tags set")

        self.push_screen(
            PromptScreen("Tags (comma separated):", existing.tags), apply
        )

    def action_edit_note(self) -> None:
        if self.favorites is None:
            return
        favorites = self.favorites
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status(
                "not a favourite yet -- press f first", refused=True
            )
            return

        def apply(value: str | None) -> None:
            if value is None:
                return
            old = existing.note
            favorites.set_note(where[0], where[1], value)
            self._push_change(
                TagNoteChange(where[0], where[1], "note", old=old)
            )
            self._refill_keeping_place()
            self.notify_status("note set")

        self.push_screen(PromptScreen("Note:", existing.note), apply)

    def action_cycle_favorites(self) -> None:
        """Step: all slots -> this bank's favourites -> every favourite.

        Always exactly three steps, even when a view is empty: skipping one
        to be helpful makes a keypress land somewhere different depending on
        what happens to be favourited.
        """
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        index = VIEW_CYCLE.index(self.view_mode)
        self.view_mode = VIEW_CYCLE[(index + 1) % len(VIEW_CYCLE)]
        self._refill_keeping_place()
        shown = len(self._current)
        if self.view_mode == VIEW_ALL:
            self.notify_status(VIEW_LABELS[self.view_mode])
        elif not shown:
            where = (
                "this bank"
                if self.view_mode == VIEW_BANK_FAVOURITES
                else "any bank"
            )
            self.notify_status(
                f"{VIEW_LABELS[self.view_mode]} - nothing favourited in "
                f"{where} yet"
            )
        else:
            self.notify_status(f"{VIEW_LABELS[self.view_mode]} - {shown}")

    def _refill_keeping_place(self) -> None:
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row or 0
        self._fill(self._current_bank)
        if self._current:
            table.move_cursor(row=min(row, len(self._current) - 1))

    def _fill(self, bank_id: str) -> None:
        table = self.query_one("#slot-table", DataTable)
        self._current_bank = bank_id
        self._current = self._visible(bank_id)
        marked = self._favorite_keys(bank_id)
        self._filling = True
        try:
            table.clear()
            for entry in self._current:
                name = self.catalog.display_name(entry.bank_id, entry.number)
                if self.catalog.differs(entry.bank_id, entry.number):
                    shown = f"[b]{name}[/b] [dim]*[/dim]"
                elif self.catalog.is_live(entry.bank_id, entry.number):
                    shown = f"[b]{name}[/b]"
                else:
                    shown = name
                here = (
                    self._favorite_keys(entry.bank_id)
                    if self.view_mode == VIEW_ALL_FAVOURITES
                    else marked
                )
                table.add_row(
                    "[b]♥[/b]" if entry.number in here else "",
                    f"{entry.number:03d}",
                    shown,
                    str(entry.index),
                    key=entry.key,
                )
        finally:
            self._filling = False
        self._detail(0)

    def _detail(self, row: int) -> None:
        if not self._current or row >= len(self._current):
            self.query_one("#detail", Static).update("")
            return
        entry = self._current[row]
        name = self.catalog.display_name(entry.bank_id, entry.number)
        source = (
            "read from the unit"
            if self.catalog.is_live(entry.bank_id, entry.number)
            else "from the catalog"
        )
        if entry.region.needs_card:
            source += " · needs a card fitted"
        if entry.kind == banks.Kind.PRESET:
            bank = banks.bank_of(entry.kind, entry.index)
            how = (
                f"Bank Select (CC32) [b]{bank}[/b] · Program Change "
                f"[b]{entry.number}[/b] [dim](under the default "
                f"Program Map)[/dim]"
            )
        elif entry.kind == banks.Kind.MIDIMAP:
            how = (
                "[dim]no program change reaches a midimap; System "
                "Exclusive is the only way[/dim]"
            )
        else:
            how = "[dim]selected as a preset in the hyperpreset range[/dim]"
        self.query_one("#detail", Static).update(
            f"[b]{entry.display}[/b]  {name}   [dim]index "
            f"{entry.index}[/dim]\n{how} · {source}"
        )

    def notify_status(self, message: str, *, refused: bool = False) -> None:
        prefix = "[b]refused[/b] · " if refused else ""
        self.query_one("#status", Static).update(prefix + message)

    # --- navigation ---------------------------------------------------------

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if self._filling:
            return
        if event.data_table.id == "bank-table":
            row = event.cursor_row
            if 0 <= row < len(self._bank_ids):
                self._fill(self._bank_ids[row])
        elif event.data_table.id == "slot-table":
            self._detail(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a slot. It arrives here, not as a binding."""
        if event.data_table.id == "slot-table":
            self.action_select()

    def action_switch_pane(self) -> None:
        left = self.query_one("#bank-table", DataTable)
        right = self.query_one("#slot-table", DataTable)
        (right if left.has_focus else left).focus()

    def action_cycle_kind(self) -> None:
        """Cycle the right pane's view: preset -> hyperpreset -> midimap.

        A pure read-side switch: it sends nothing to the unit. It only
        changes which kind's slots are being browsed (and which kind the
        next `r` would read), so there is no sound and no MIDI.
        """
        kinds = list(banks.Kind.ALL)
        current = getattr(self, "kind_view", banks.Kind.PRESET)
        idx = kinds.index(current)
        nxt = kinds[(idx + 1) % len(kinds)]
        self.kind_view = nxt
        self._kind_view = nxt
        # Land on the first region of the newly selected kind.
        ids = banks.region_ids(nxt)
        if ids:
            self._current_bank = ids[0]
            self._fill(self._current_bank)
        self.notify_status(f"{nxt} view")

    # --- operations ---------------------------------------------------------

    def action_select(self) -> None:
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not 0 <= row < len(self._current):
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        entry = self._current[row]
        if entry.kind != banks.Kind.PRESET:
            # Refused here rather than in the worker, so that nothing is
            # sent at all. A midimap has no program change; a program
            # change aimed at one would land on a preset instead.
            self.notify_status(
                f"a {entry.kind} is not selected with a program change; "
                f"only presets are",
                refused=True,
            )
            return
        # Claim the one exchange on the main thread before spawning: a
        # @work method returns at once, so two quick presses would
        # otherwise both pass.
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._select_worker(entry)

    @work(thread=True)
    def _select_worker(self, entry: banks.Slot) -> None:
        """**MIDI only.** The gate tracks the exchange in progress."""
        try:
            with self._busy_gate:
                self.device.select(entry)
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(
                self.notify_status, f"select: {exc}", refused=True
            )
            return
        finally:
            self._exchange.release()
        self.call_from_thread(
            self.notify_status,
            f"selected {entry.display} — Bank Select (CC32) "
            f"{banks.bank_of(entry.kind, entry.index)} then Program Change "
            f"{entry.number} on channel {self.device.channel + 1}; "
            f"that number reaches it under the default Program Map",
        )

    def action_read_names(self) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        entry = banks.region(self._current_bank)
        self._read_worker(entry.kind)

    @work(thread=True)
    def _read_worker(self, kind: str) -> None:
        """**MIDI only** -- the catalog is updated on the main thread.

        One request for the whole kind. The gate tracks the exchange in
        progress.
        """
        try:
            with self._busy_gate:
                self.call_from_thread(
                    self.notify_status,
                    f"asking for every {kind} name in one message (silent)...",
                )
                names = self.device.names(kind)
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(
                self.notify_status, f"read: {exc}", refused=True
            )
            return
        finally:
            self._exchange.release()
        self.call_from_thread(self._adopt_kind, kind, names)

    def _adopt_kind(self, kind: str, names: list[str]) -> None:  # noqa: C901
        """File a flat list of names back into the regions it spans.

        The reply is "every preset, in the order they appear" -- one list
        across RAM, ROM and card. Splitting it by region here is the only
        place that mapping exists, and it has to skip the regions a
        missing card leaves out, which is why it walks the returned length
        rather than the declared one.
        """
        adopted = 0
        cursor = 0
        for region in banks.regions(kind):
            for number in range(region.count):
                if cursor >= len(names):
                    break
                self.catalog.set_live_name(
                    region.id, number, names[cursor].rstrip()
                )
                cursor += 1
                adopted += 1
        if self.favorites is not None:
            self.favorites.refresh_names(
                lambda bank, number: self.catalog.live_name(bank, number)
            )
        # Persist the live names just read, keyed the way the catalog is.
        live_path = getattr(self, "_live_names_path", None)
        if live_path is not None:
            to_save: dict[str, str] = {}
            cursor = 0
            for region in banks.regions(kind):
                for number in range(region.count):
                    if cursor >= len(names):
                        break
                    name = names[cursor].rstrip()
                    to_save[_livenames.key(region.id, number)] = name
                    cursor += 1
                if cursor >= len(names):
                    break
            try:
                _livenames.save(names=to_save, path=live_path)
            except Exception:
                # The cache is best-effort.
                _ = None
        self._fill(self._current_bank)
        short = ""
        expected = sum(r.count for r in banks.regions(kind))
        if adopted < expected:
            short = (
                f"; {expected - adopted} short of {expected}, which "
                f"is what no card fitted looks like"
            )
        self.notify_status(f"read {adopted} {kind} name(s){short}")

    def _maybe_offer_scan(self) -> None:
        """Offer a scan when there is nothing to start from."""
        if self._demo or self._busy or self.catalog:
            return
        from emu import config as _cfg

        try:
            if self._config_path is not None:
                dismissed = _cfg.load_ui_bool(
                    "scan_offer_dismissed", self._config_path, default=False
                )
            else:
                dismissed = _cfg.load_ui_bool(
                    "scan_offer_dismissed", default=False
                )
            if dismissed:
                return
        except Exception:  # noqa: S110
            pass
        self.push_screen(
            ScanOfferScreen(SCAN_OFFER),
            self._scan_offer_answered,
        )

    def _scan_offer_answered(self, answer: str | None) -> None:
        if answer == "never":
            from emu import config as _cfg

            if self._config_path is not None:
                try:
                    _cfg.save_ui_state(
                        "scan_offer_dismissed", True, self._config_path
                    )
                except Exception:  # noqa: S110
                    pass
            else:
                try:
                    _cfg.save_ui_state("scan_offer_dismissed", True)
                except Exception:  # noqa: S110
                    pass
            return
        if answer == "scan":
            self.action_scan_device()

    def action_scan_device(self) -> None:
        if self._demo:
            self.notify_status(
                "the demo invents its names; nothing to scan", refused=True
            )
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        kinds = list(banks.Kind.ALL)
        if not kinds:
            self.notify_status(
                "nothing to scan: no unit answered", refused=True
            )
            return
        # One claim for the whole scan, not one per kind: a scan is a
        # single exchange even though it sends a message per kind.
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._scan_cancel = threading.Event()
        self.push_screen(ScanScreen(self._scan_cancel))
        self._scan_worker(kinds)

    @work(thread=True)
    def _scan_worker(self, kinds: list[str]) -> None:
        """**MIDI only** -- one request per kind, cancel between kinds."""
        done = 0
        total = len(kinds)
        try:
            with self._busy_gate:
                for kind in kinds:
                    if self._scan_cancel.is_set():
                        break
                    try:
                        names = self.device.names(kind)
                    except _BRIDGE_ERRORS as exc:
                        self.call_from_thread(
                            self.notify_status, f"scan: {exc}", refused=True
                        )
                        continue
                    done += 1
                    self.call_from_thread(
                        self._scan_progress, kind, done, total
                    )
                    self.call_from_thread(self._adopt_kind, kind, names)
        finally:
            self._exchange.release()
            self.call_from_thread(self._scan_finished, done, total)

    def _scan_progress(self, kind: str, done: int, total: int) -> None:
        screen = self.screen
        if isinstance(screen, ScanScreen):
            screen.set_progress(
                f"reading {kind} names ({done}/{total} kinds, silent)"
            )

    def _scan_finished(self, done: int, total: int) -> None:
        screen = self.screen
        if isinstance(screen, ScanScreen):
            screen.dismiss()
        cancelled = self._scan_cancel.is_set()
        if cancelled:
            self.notify_status(f"scan stopped after {done} of {total} kinds")
        else:
            self.notify_status(
                f"scanned {done} kind(s); names kept for next time"
            )

    def action_search(self) -> None:
        def done(text: str | None) -> None:
            if not text:
                return
            hits = self.catalog.search(text)
            if not hits:
                self.notify_status(f"nothing matching {text!r}")
                return
            lines = [f"{len(hits)} match(es) for {text!r}", ""]
            for bank_id, number, name, _disagrees in hits[:400]:
                try:
                    entry = banks.slot(bank_id, number)
                except LookupError:
                    continue
                lines.append(
                    f"{entry.display:<6} {name:<12} PC {entry.number:>3}"
                )
            if len(hits) > 400:
                lines.append(f"... and {len(hits) - 400} more")
            self.push_screen(ReportScreen("Search", "\n".join(lines)))

        self.push_screen(PromptScreen("Search names:"), done)

    def action_device_info(self) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._info_worker()

    @work(thread=True)
    def _info_worker(self) -> None:
        """**MIDI only** -- the report is built on the main thread."""
        try:
            with self._busy_gate:
                version = self.device.version()
                try:
                    configuration = self.device.configuration()
                except Exception:
                    configuration = None
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(
                self.notify_status, f"device: {exc}", refused=True
            )
            return
        finally:
            self._exchange.release()
        self.call_from_thread(self._show_info, version, configuration)

    def _show_info(
        self, version: list[int], configuration: list[int] | None
    ) -> None:
        lines = [
            _build_line(),
            "",
            f"connection      {self.device.description}",
            f"device ID       {self.device.device_id}",
            f"MIDI channel    {self.device.channel + 1}",
            "",
        ]
        lines.append("manufacturer    " + f"{msg.EMU_ID:02X}  (E-mu)")
        lines.append(f"product         {msg.MORPHEUS_ID:02X}  (Morpheus)")
        lines.append(
            "version bytes   " + " ".join(f"{b:02X}" for b in version)
        )
        if configuration is not None:
            lines.append(
                "configuration   "
                + " ".join(f"{b:02X}" for b in configuration)
            )
        lines.append("")
        lines.append("The device ID and the MIDI channel are different")
        lines.append("things and are set in different places on the unit.")
        lines.append("A request with the wrong device ID is answered with")
        lines.append("silence, which looks exactly like a wrong cable.")
        lines.append("")
        lines.append("The last byte of a version reply may be a checksum;")
        lines.append("whether unnumbered replies carry one is not")
        lines.append("established. See TODO item 1.")
        lines.append("")
        lines.append(
            f"catalog         {len(self.catalog)} names"
            + (f" from {self.catalog.source}" if self.catalog.source else "")
        )
        lines.append(
            "favourites      "
            + (
                f"{len(self.favorites)}"
                if self.favorites is not None
                else "(none open)"
            )
        )
        self.push_screen(ReportScreen("Device", "\n".join(lines)))

    def action_help(self) -> None:
        self.push_screen(
            ReportScreen("emorphed", f"{_build_line()}\n\n{_HELP}")
        )


_HELP = """What the Morpheus holds

  Presets       RAM 0-127 (yours), ROM 128-255, card 256-383.
  Hyperpresets  RAM 0-127, card 128-255. Each stacks up to 16 zones
                of presets across the keyboard.
  Midimaps      RAM 0-15, card 16-31. One preset per MIDI channel --
                and **no program change reaches a midimap at all**.
                System Exclusive is the only way in.

Two regions need a card fitted. A request for one without a card is
ignored outright, so a read that comes back short is saying "no card",
not failing.

Numbers

An *index* is what SysEx addresses. A *program change* is what selects,
and only for presets -- a Program Map sits between the two, so the number
shown is the one that works under the default map. Bank Select is
Controller 32 with Controller 0 held at zero.

Names

`r` reads every name of the current kind in **one** message, which this
instrument can do and its siblings cannot. Names read from the unit show
in bold; a `*` marks a slot where the unit and the catalog disagree.

Keys

  ↑↓        move; this never sends anything
  tab       switch pane
  ⏎         select on the unit -- presets only
  r         read every name of this kind (silent, one message)
  /         search the names
  [ ]       previous / next MIDI channel
  c         set the MIDI channel
  d         set the SysEx device ID -- a different thing
  f         favourite the slot under the cursor
  F         all slots / favourites here / every favourite
  t n       tags, note
  *         rate the slot under the cursor
  V         rating filter
  z Z       undo / undo all
  k         kind view
  S         scan names
  i         what the unit says it is
  q         quit
"""


def _build_line() -> str:
    """One line naming both builds: this tool, and the library under it."""
    parts = []
    for name, origin in (("emorphed", __file__), ("vinsynlib", None)):
        build = build_of(name, origin=origin)
        where = build.version or "an unknown version"
        if build.commit:
            tagged = ""
            if build.tag:
                tagged = f", {build.tag.removeprefix('refs/tags/')}"
            where += f" ({build.commit[:7]}{tagged})"
        parts.append(f"{name} {where}")
    return "built from " + " and ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser(
        "emorphed", "Browse an E-mu Morpheus.", distribution="emorphed"
    )
    # Every flag's help text is the family's, from vinsynlib.spec. This tool
    # used to word four of them its own way, which is how "SysEx device ID
    # 0-15; not the MIDI channel" came to be in one program and something
    # else in the other eight.
    #
    # --midi-channel is the family's older spelling of --device-channel and
    # is still accepted: the Morpheus's own base channel is a different
    # number from the channel a program change is sent on, and the old name
    # is on nine command lines already.
    add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        device_channel=True,
        device_id=True,
        catalog=True,
        config=True,
        favorites=True,
    )
    parser.add_argument(
        "--live-names",
        default=None,
        help="where names read from the unit are kept between runs "
        "(default: beside the favourites database)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915
    args = build_parser().parse_args(argv)
    from emu import config as cfg

    config_path = getattr(args, "config", None) or cfg.DEFAULT_PATH
    # The family's range checks, before anything is opened: a mistyped
    # channel costs a message rather than a wrong program change sent to a
    # real instrument.
    validate_common(args)
    # ...and then this unit's own narrower one. A SysEx device ID is a byte
    # family-wide, but the Morpheus only answers to the low sixteen of them,
    # and the shared check cannot know that.
    if args.device_id is not None and not 0 <= args.device_id <= 15:
        sys.exit("error: --device-id is 0-15 on a Morpheus")

    device: Device | None = None
    if args.demo:
        from emorphed.demo import DemoDevice

        device = DemoDevice()
    else:
        from emu import bridge as b

        # The channel on the command line wins; otherwise the one used last
        # time, so it does not have to be given again every run.
        remembered = cfg.load_channel(config_path)
        try:
            channel = (
                (args.device_channel - 1)
                if args.device_channel is not None
                else (remembered if remembered is not None else 0)
            )
            device_id = (
                args.device_id
                if args.device_id is not None
                else (cfg.load_device_id(config_path) or 0)
            )
            if args.port:
                bridge = b.MorpheusBridge.open(
                    args.port,
                    recv_port=(
                        args.recv_port or cfg.load_last_recv_port(config_path)
                    ),
                    device_id=device_id,
                    channel=channel,
                )
            else:
                # One Version Request to the remembered port; the sweep only
                # when there is nothing remembered, when the remembered port
                # no longer answers, or when --scan asks for it.
                bridge = b.MorpheusBridge.connect(
                    config_path=config_path,
                    channel=channel,
                    device_id=device_id,
                    scan=args.scan,
                    on_try=lambda n: print(
                        f"  probing {n}...", file=sys.stderr
                    ),
                )
            device = bridge
        except Exception as exc:
            sys.exit(f"error: {exc}")

        # Remember whatever channel is actually in use -- which after a
        # sweep is the one the unit reported, not the one asked for.
        try:
            cfg.save_channel(bridge.channel, config_path)
            if bridge.port:
                cfg.save_last_port(bridge.port, config_path)
                cfg.save_device_id(bridge.device_id, config_path)
            recv = bridge.recv_port
            if recv and recv != bridge.port:
                cfg.save_last_recv_port(recv, config_path)
        except OSError:
            pass

    from emu import livenames as _ln
    from emu.favorites import Favorites

    catalog = cat.load(args.catalog)
    try:
        _ln.apply_to(catalog, getattr(args, "live_names", None))
    except Exception:
        # The cache is best-effort.
        _ = None
    try:
        store = Favorites(args.favorites)
    except Exception as exc:
        # _migrate refuses a database written by a newer build, which is the
        # right refusal, and sqlite3 raises on a file that is not a database
        # at all. Every other startup failure here leaves by sys.exit; these
        # two used to print a traceback.
        raise SystemExit(f"error: {exc}")
    app = EmorphedApp(
        device,
        catalog=catalog,
        favorites=store,
        config_path=config_path,
        live_names_path=getattr(args, "live_names", None)
        or _ln.default_path(),
        demo=args.demo,
        offer_scan=not args.demo,
    )
    try:
        app.run()
    finally:
        store.close()
        with close_when_idle(device, gate=app._busy_gate):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
