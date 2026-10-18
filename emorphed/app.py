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
import contextlib
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

from emorphed import edit as edmod
from emorphed.midimapui import MidimapEditScreen
from emorphed.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen
from emorphed.screens import (
    KEY_HINTS,
    KeyHints,
    MidimapPickerScreen,
    PresetPickerScreen,
    PromptScreen,
    ReportScreen,
)
from emorphed.text import literal
from emu import backup as bkmod
from emu import banks
from emu import catalog as cat
from emu import livenames as _livenames
from emu import messages as msg
from emu import midimap as mm
from emu.config import UNSET
from emu.device import Device
from emu.favorites import Favorite, Favorites
from vinsynlib.build import build_of
from vinsynlib.cli import add_common_arguments, make_parser, validate_common
from vinsynlib.keys import wrap_blocks as _wrap_blocks
from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.modals import RatingFilter, RatingFilterScreen
from vinsynlib.ui.work import QUIET_BRIDGE_ERRORS, BusyGate, close_when_idle
from vinsynlib.undo import Record, UndoLog

__all__ = ["KEY_HINTS", "EmorphedApp", "build_parser", "main", "wrap_blocks"]

_SEP = " · "

#: What `v` steps through. The same three the sibling rxved and p2ked use,
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


@dataclass(frozen=True)
class ParamChange:
    offset: int
    old: int
    new: int


@dataclass(frozen=True)
class NameChange:
    """One midimap name write: twelve parameters (offsets 0-11).

    Carried as a single undo record so that one `z` restores the
    whole previous name; a per-character record would leave the
    other eleven characters behind. The old and new texts are the
    names before and after, each already padded to twelve chars.
    """

    old_text: str
    new_text: str


@dataclass(frozen=True)
class ChannelPresetChange:
    """One channel preset write: the bank word and the program word.

    Carried as a single undo record so that one `z` restores both
    words together. Only the previous pair is needed for undo.
    """

    channel: int
    old_bank: int
    old_number: int


@dataclass(frozen=True)
class MidimapChange:
    """One whole-map store: the location and the words it held before."""

    index: int
    words: tuple[int, ...]


class _ChangesView(list[Any]):
    def __init__(self, log: UndoLog, changes: list[Any]) -> None:
        super().__init__(changes)
        self._log = log

    def append(self, change: object) -> None:
        label = _change_label(change)
        self._log.push(Record(label, change))
        super().append(change)


def _change_label(change: object) -> str:  # noqa: PLR0911
    if isinstance(change, FavouriteChange):
        return "favourite"
    if isinstance(change, RatingChange):
        return "rating"
    if isinstance(change, TagNoteChange):
        field = getattr(change, "field", "tags")
        return "note" if field == "note" else "tags"
    if isinstance(change, ParamChange):
        return "parameter"
    if isinstance(change, NameChange):
        return "name"
    if isinstance(change, ChannelPresetChange):
        return "channel preset"
    if isinstance(change, MidimapChange):
        return "midimap"
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
    /* The ID is repeated or the rule never paints: an ID selector outranks
       a class, so a bare ``.refused`` was dead CSS and every refusal drew in
       the same grey as a success. Red and bold, the sibling rxved's shape, so
       a locked write gate is legible at a glance. */
    #status.refused {
        background: $error;
        color: $text;
        text-style: bold;
    }
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
        # `v`, not the family's `F`: `f` writes the favourites database and
        # `F` does not, so the family's shift-pair left a write one slip away
        # from a read. `v` has no such twin. rxved and p2ked made the same
        # swap; the rename is declared in tests/test_conformance.py.
        Binding("v", "cycle_favorites", "Favourites view"),
        Binding("t", "edit_tags", "Tags"),
        Binding("n", "edit_note", "Note"),
        Binding("asterisk", "edit_rating", "Rating"),
        Binding("V", "rating_filter", "Rating filter"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        Binding("w", "toggle_write_gate", "Write gate"),
        Binding("m", "midimap_edit", "Midimap edit"),
        Binding("delete", "reset_midimap", "Reset midimap"),
        Binding("slash", "search", "Search"),
        Binding("i", "device_info", "Device"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
        Binding("k", "cycle_kind", "Kind view"),
    ]

    def __init__(  # noqa: PLR0913, PLR0915
        self,
        device: Device,
        *,
        catalog: cat.Catalog | None = None,
        favorites: Favorites | None = None,
        config_path: str | None = None,
        live_names_path: str | None = None,
        demo: bool = False,
        offer_scan: bool = False,
        allow_write: bool = False,
        verify_catalog_at_startup: bool = False,
    ) -> None:
        super().__init__()
        #: Everything ``z`` can reverse, in the order it happened. Made
        #: first in ``__init__`` because a watcher can fire before the
        #: constructor has finished -- the undo log has to be there first.
        self._busy_gate = BusyGate()
        self._exchange = threading.Lock()
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
        #: Starting state for the write gate.
        self._allow_write = allow_write
        #: Whether to re-read every kind's names once, quietly, after the
        #: first frame. The catalog on disk is a cache that painted the
        #: window; this corrects it from the unit. Off by default so a test
        #: never starts a background read it did not ask for.
        self._verify_catalog_at_startup = verify_catalog_at_startup
        #: The currently open midimap editor screen, if any.
        self._edit_screen: MidimapEditScreen | None = None
        #: Whether a midimap backup has succeeded this session.
        self._midimap_backed_up = False
        #: Whether scratch edits have been made this session and not yet
        #: stored. Drives the close-time warning.
        self._midimap_unstored = False
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
        #: One exchange at a time, claimed on the main thread. The main
        #: thread takes it (non-blocking) before it spawns the worker and
        #: the worker always releases it in a ``finally``. The gate alone
        #: cannot carry this: entering the gate *clears* a refusal, so
        #: between reserving one and entering it for real a second action
        #: would find neither ``check()`` nor ``is_busy()`` set and start a
        #: second worker. ``_busy`` reads this claim as a third signal.
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

        # Restore the persisted browser state: which region the left pane
        # was on, which row the right pane's cursor was on, and where both
        # cycling keys (`v` and `k`) stood. Loaded here, not in `on_mount`,
        # because the first `_fill` down there builds its rows out of
        # ``view_mode`` and ``_current_bank``; restoring anything later
        # would mean filling twice. Injected path only -- ``None`` means a
        # test that asked for silence and gets it.
        self._saved_slot_cursor: int | None = None
        if self._config_path is not None:
            try:
                from emu import config as _cfg

                saved_view = _cfg.load_ui_state("view_mode", self._config_path)
                # Never trust a stored value: a view this build renamed,
                # a kind it does not have, or a stale bank index is
                # ignored and the app opens on its defaults.
                if isinstance(saved_view, str) and saved_view in VIEW_CYCLE:
                    self.view_mode = saved_view
                saved_kind = _cfg.load_ui_state("kind_view", self._config_path)
                if (
                    isinstance(saved_kind, str)
                    and saved_kind in banks.Kind.ALL
                ):
                    self.kind_view = saved_kind
                    self._kind_view = saved_kind
                saved_bank = _cfg.load_ui_int("bank_index", self._config_path)
                if saved_bank is not None and 0 <= saved_bank < len(
                    self._bank_ids
                ):
                    self._current_bank = self._bank_ids[saved_bank]
                self._saved_slot_cursor = _cfg.load_ui_int(
                    "slot_cursor", self._config_path
                )
            except Exception:
                # The cache is best-effort; a bad read is a default
                # startup.
                self._saved_slot_cursor = None

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

    @property
    def _gate(self) -> edmod.EditGate:
        if getattr(self, "_write_gate", None) is None:
            self._write_gate = edmod.EditGate(armed=self._allow_write)
        return self._write_gate

    @property
    def _editor(self) -> edmod.MidimapEditor:
        if getattr(self, "_midimap_editor", None) is None:
            self._midimap_editor = edmod.MidimapEditor(gate=self._gate)
        return self._midimap_editor

    def _undo_gate(self) -> str | None:
        return "busy" if self._busy else None

    @property
    def _busy(self) -> bool:
        gate = getattr(self, "_busy_gate", None)
        exchange = getattr(self, "_exchange", None)
        return (
            (gate.check() is not None if gate else False)
            or (gate.is_busy() if gate else False)
            or (exchange.locked() if exchange else False)
        )

    def action_toggle_write_gate(self) -> None:
        self._gate.toggle()
        self.notify_status(self._gate.describe())

    def action_midimap_edit(self) -> None:
        """Read the current midimap in a worker, then open the editor."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._read_midimap_worker()

    @work(thread=True)
    def _read_midimap_worker(self) -> None:
        """**MIDI only** -- read the current midimap, then open the screen."""
        failure = None
        words = None
        index = 0
        assumed = False
        try:
            with self._busy_gate:
                cm = getattr(self.device, "current_midimap", None)
                _cm: int | None = cm
                assumed = _cm is None
                index = 0 if assumed else (_cm if _cm is not None else 0)
                words = self.device.read_midimap(index)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"midimap: {failure}", refused=True
            )
            return
        self.call_from_thread(self._open_midimap_screen, index, words, assumed)

    def _re_read_midimap_scratch(self) -> None:
        """Re-read the scratch map (r inside the editor)."""
        if self._busy:
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._read_midimap_scratch_worker()

    @work(thread=True)
    def _read_midimap_scratch_worker(self) -> None:
        """**MIDI only** -- 360 Parameter Requests against the scratch map."""
        failure = None
        values: list[int | None] | None = None
        try:
            with self._busy_gate:
                values = self.device.read_scratch_params()
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"re-read scratch: {failure}", refused=True
            )
            top = getattr(self, "_edit_screen", None)
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    self.call_later(
                        top.say, f"re-read scratch: {failure}", refused=True
                    )
            return
        if values is None:
            return
        silent = sum(v is None for v in values)
        self.call_from_thread(self._finish_re_read_scratch, values, silent)

    def _finish_re_read_scratch(self, values: list[Any], silent: int) -> None:
        top = getattr(self, "_edit_screen", None)
        # Update the screen cell-by-cell so rows that stayed silent keep
        # their previous value rather than disappearing.
        if top is not None and hasattr(top, "result"):
            for off, v in enumerate(values):
                if v is None:
                    continue
                with contextlib.suppress(Exception):
                    top.result(True, "", parameter_id=off, value=v)
        if getattr(self, "_current_midimap_words", None) is not None:
            for off, v in enumerate(values):
                if v is not None:
                    self._current_midimap_words[off] = v
        msg = (
            "re-read the scratch (360 parameter requests); "
            f"{silent} did not answer"
        )
        if top is not None and hasattr(top, "say"):
            with contextlib.suppress(Exception):
                top.say(msg)
        self.notify_status(msg)

    def _open_midimap_screen(  # noqa: C901, PLR0915
        self, index: int, words: list[int], assumed: bool = False
    ) -> None:
        self._current_midimap_index = index
        self._current_midimap_words = list(words)
        params = {off: words[off] for off in range(len(words))}
        import inspect

        from emorphed.midimapui import MidimapEditScreen

        editor = self._editor

        def _on_edit(offset: int, value: int) -> None:
            self._apply_parameter(offset, value)

        def _on_undo(count: int | None) -> None:
            self._undo_master_edits(count)

        ui_kwargs: dict[str, Any] = {
            "on_edit": _on_edit,
            "on_re_read": self._re_read_midimap_scratch,
            "on_undo": _on_undo,
            "on_store": self._store_midimap,
        }
        # The parallel midimapui agent is adding on_name(text); wire it when
        # available and otherwise stay compatible with the old screen.
        sig = inspect.signature(MidimapEditScreen.__init__).parameters
        if "index" in sig:
            ui_kwargs["index"] = index
        if "on_name" in sig:
            ui_kwargs["on_name"] = self._apply_midimap_name
        if "name_for" in sig:
            ui_kwargs["name_for"] = lambda bank, number: (
                self.catalog.display_name(mm.channel_bank(bank), number)
            )
        if "on_channel" in sig:
            ui_kwargs["on_channel"] = self._apply_channel_preset
        if "on_pick" in sig:
            ui_kwargs["on_pick"] = self._open_preset_picker
        if "on_reset" in sig:
            ui_kwargs["on_reset"] = self._reset_midimap_to_default

        screen = MidimapEditScreen(editor, params, **ui_kwargs)
        self._edit_screen = screen
        self._midimap_unstored = False
        self._mark_midimap_unstored(False)

        original_close = screen.action_close

        def _guarded_close() -> None:
            unstored = (
                bool(self._midimap_unstored)
                or bool(getattr(screen, "_unstored", False))
                or bool(getattr(screen, "unstored", False))
            )
            if not unstored:
                original_close()
                return
            sentence = (
                "scratch edits are not stored; they will be lost on a "
                "power cycle"
            )
            self.notify_status(sentence, refused=True)
            if hasattr(screen, "say"):
                with contextlib.suppress(Exception):
                    screen.say(sentence, refused=True)

            def answered(confirmed: bool | None) -> None:
                if confirmed:
                    self._midimap_unstored = False
                    if hasattr(screen, "set_unstored"):
                        with contextlib.suppress(Exception):
                            screen.set_unstored(False)
                    with contextlib.suppress(Exception):
                        screen.dismiss(None)

            self.push_screen(
                ConfirmScreen(
                    "Closing now discards the scratch edits made this "
                    "session; they are not stored and will be lost on a "
                    "power cycle"
                ),
                answered,
            )

        screen.action_close = _guarded_close  # type: ignore[method-assign]
        self.push_screen(screen, self._after_midimap_edit)
        if assumed:
            msg = f"midimap {index} (assumed -- nothing selected this session)"
            self.call_later(screen.say, msg)
            self.notify_status(msg)
        else:
            self.call_later(screen.say, f"stored map (midimap {index})")

    def _open_preset_picker(self, channel: int) -> None:
        screen = PresetPickerScreen(self.catalog, favorites=self.favorites)

        def done(result: tuple[int, int] | None) -> None:
            if result is None:
                return
            bank, number = result
            self._apply_channel_preset(channel, bank, number)

        self.push_screen(screen, done)

    def _apply_midimap_name(self, text: str) -> None:
        """Write a midimap name through twelve parameter writes."""
        # Gate every character first (offsets 0..11) -- the same gate a single
        # parameter write goes through. Refuse the whole write on the first
        # refusal; nothing is sent in that case.
        padded = (text[:12] if len(text) > 12 else text).ljust(12)
        for off, char in enumerate(padded):
            refusal = self._editor.allow(off, ord(char))
            if refusal is not None:
                self.notify_status(refusal, refused=True)
                top = getattr(self, "_edit_screen", None)
                if top is None:
                    top = self.screen
                if top is not None and hasattr(top, "say"):
                    with contextlib.suppress(Exception):
                        top.say(refusal, refused=True)
                return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._write_midimap_name_worker(text)

    def _apply_name_text(self, text: str) -> bool:
        """Restore a name (undo path): writes without a new undo record."""
        padded = (text[:12] if len(text) > 12 else text).ljust(12)
        for off, char in enumerate(padded):
            refusal = self._editor.allow(off, ord(char))
            if refusal is not None:
                self.notify_status(refusal, refused=True)
                top = getattr(self, "_edit_screen", None)
                if top is None:
                    top = self.screen
                if top is not None and hasattr(top, "say"):
                    with contextlib.suppress(Exception):
                        top.say(refusal, refused=True)
                return False
        if self._busy:
            self.notify_status("busy", refused=True)
            return False
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return False
        self._write_midimap_name_worker(text, record=False)
        return True

    @work(thread=True)
    def _write_midimap_name_worker(
        self, text: str, record: bool = True
    ) -> None:
        """**MIDI only**: twelve writes, twelve reads, report agreement."""
        failure = None
        agreed = False
        mismatch = 0
        new_text = text
        try:
            with self._busy_gate:
                self._backup_before_write()
                words = list(
                    getattr(self, "_current_midimap_words", None) or [0] * 360
                )
                if len(words) < 360:
                    words = words + [0] * (360 - len(words))
                old_text = mm.name_of(words)
                new_words = mm.set_name(words, text)
                for off in range(12):
                    self.device.write_parameter(
                        mm.PARAM_BASE + off, new_words[off]
                    )
                read_back = [
                    self.device.read_parameter(mm.PARAM_BASE + off)
                    for off in range(12)
                ]
                expected = new_words[:12]
                agreed = read_back == expected
                mismatch = sum(
                    1
                    for a, b in zip(read_back, expected, strict=True)
                    if a != b
                )
                new_text = mm.name_of(new_words)
                if (
                    agreed
                    and getattr(self, "_current_midimap_words", None)
                    is not None
                ):
                    for off in range(12):
                        self._current_midimap_words[off] = new_words[off]
                if record and agreed:
                    self._push_change(NameChange(old_text, new_text))
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            sentence = f"name: {failure}"
            self.call_from_thread(self.notify_status, sentence, refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    self.call_from_thread(top.say, sentence, refused=True)
            return
        self.call_from_thread(
            self._finish_name_write, new_text, agreed, mismatch
        )

    def _finish_name_write(
        self, new_text: str, agreed: bool, mismatch: int
    ) -> None:
        top = getattr(self, "_edit_screen", None)
        if top is None:
            top = self.screen
        if (
            top is not None
            and hasattr(top, "update_params")
            and getattr(self, "_current_midimap_words", None) is not None
        ):
            words = self._current_midimap_words
            params = {off: words[off] for off in range(len(words))}
            with contextlib.suppress(Exception):
                top.update_params(params)
        shown_name = literal(new_text)
        if agreed:
            msg = f"name written: {shown_name!r}; read-back agreed (12/12)"
            self._mark_midimap_unstored(True)
            index = getattr(self, "_current_midimap_index", None)
            words_now = self._current_midimap_words
            if index is not None and words_now is not None:
                self._remember_midimap_name(index, list(words_now))
        else:
            msg = (
                f"name written: {shown_name!r}; read-back disagreed "
                f"({12 - mismatch}/12)"
            )
        if top is not None and hasattr(top, "say"):
            with contextlib.suppress(Exception):
                top.say(msg)
        self.notify_status(msg)

    def _apply_parameter(  # noqa: C901
        self, offset: int, value: int, *, record: bool = True
    ) -> bool:
        refusal = self._editor.allow(offset, value)
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            top = self.screen
            if hasattr(top, "say"):
                try:
                    top.say(refusal, refused=True)
                except Exception:  # noqa: S110
                    pass
            if hasattr(top, "result"):
                try:
                    top.result(
                        False, refusal, parameter_id=offset, value=value
                    )
                except Exception:  # noqa: S110
                    pass
            return False
        if self._busy:
            self.notify_status("busy", refused=True)
            top = self.screen
            if hasattr(top, "result"):
                try:
                    top.result(False, "busy", parameter_id=offset, value=value)
                except Exception:  # noqa: S110
                    pass
            return False
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            top = self.screen
            if hasattr(top, "result"):
                try:
                    top.result(False, "busy", parameter_id=offset, value=value)
                except Exception:  # noqa: S110
                    pass
            return False
        self._apply_parameter_worker(offset, value, record)
        return True

    @work(thread=True)
    def _apply_parameter_worker(
        self, offset: int, value: int, record: bool = True
    ) -> None:
        """**MIDI only**: write, then read back."""
        failure = None
        old = None
        read_back = None
        try:
            with self._busy_gate:
                param_id = mm.PARAM_BASE + offset
                old = self.device.read_parameter(param_id)
                self._backup_before_write()
                self.device.write_parameter(param_id, value)
                read_back = self.device.read_parameter(param_id)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._parameter_edited,
            offset,
            value,
            old,
            read_back,
            failure,
            record=record,
        )

    def _apply_channel_preset(  # noqa: C901
        self, channel: int, bank: int, number: int, *, record: bool = True
    ) -> bool:
        bank_offset = mm.channel_bank_offset(channel)
        program_offset = mm.channel_program_offset(channel)
        # Gate both offsets before anything else; refuse the whole pair on
        # the first refusal and send nothing.
        for offset, value in (
            (bank_offset, bank),
            (program_offset, number),
        ):
            refusal = self._editor.allow(offset, value)
            if refusal is not None:
                self.notify_status(refusal, refused=True)
                top = getattr(self, "_edit_screen", None)
                if top is None:
                    top = self.screen
                if top is not None and hasattr(top, "say"):
                    with contextlib.suppress(Exception):
                        top.say(refusal, refused=True)
                if top is not None and hasattr(top, "result"):
                    with contextlib.suppress(Exception):
                        top.result(
                            False, refusal, parameter_id=offset, value=value
                        )
                return False
        if self._busy:
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "result"):
                with contextlib.suppress(Exception):
                    top.result(
                        False, "busy", parameter_id=bank_offset, value=bank
                    )
            return False
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "result"):
                with contextlib.suppress(Exception):
                    top.result(
                        False, "busy", parameter_id=bank_offset, value=bank
                    )
            return False
        self._apply_channel_preset_worker(channel, bank, number, record=record)
        return True

    @work(thread=True)
    def _apply_channel_preset_worker(
        self, channel: int, bank: int, number: int, *, record: bool = True
    ) -> None:
        """**MIDI only**: write the bank word, then the program word."""
        failure: BaseException | None = None
        old_bank: int | None = None
        old_number: int | None = None
        bank_read: int | None = None
        program_read: int | None = None
        try:
            with self._busy_gate:
                bank_offset = mm.channel_bank_offset(channel)
                program_offset = mm.channel_program_offset(channel)
                bank_param = mm.PARAM_BASE + bank_offset
                program_param = mm.PARAM_BASE + program_offset
                words = getattr(self, "_current_midimap_words", None)
                if words is not None and len(words) > program_offset:
                    old_bank = words[bank_offset]
                    old_number = words[program_offset]
                else:
                    old_bank = self.device.read_parameter(bank_param)
                    old_number = self.device.read_parameter(program_param)
                self._backup_before_write()
                self.device.write_parameter(bank_param, bank)
                bank_read = self.device.read_parameter(bank_param)
                self.device.write_parameter(program_param, number)
                program_read = self.device.read_parameter(program_param)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._finish_channel_preset_write,
            channel,
            bank,
            number,
            old_bank,
            old_number,
            bank_read,
            program_read,
            failure,
            record,
        )

    def _finish_channel_preset_write(  # noqa: PLR0913, PLR0917
        self,
        channel: int,
        bank: int,
        number: int,
        old_bank: int | None,
        old_number: int | None,
        bank_read: int | None,
        program_read: int | None,
        failure: BaseException | None,
        record: bool,
    ) -> None:
        bank_offset = mm.channel_bank_offset(channel)
        program_offset = mm.channel_program_offset(channel)
        if failure is not None:
            sentence = f"channel {channel} preset: {failure}"
            ok = False
        elif bank_read is None or program_read is None:
            sentence = (
                f"channel {channel} preset: the unit stayed silent "
                "(no read-back)"
            )
            ok = False
        else:
            agreed = bank_read == bank and program_read == number
            ok = agreed
            if agreed:
                if getattr(self, "_current_midimap_words", None) is not None:
                    self._current_midimap_words[bank_offset] = bank
                    self._current_midimap_words[program_offset] = number
                if record:
                    self._push_change(
                        ChannelPresetChange(
                            channel,
                            old_bank if old_bank is not None else bank,
                            old_number if old_number is not None else number,
                        )
                    )
                self._mark_midimap_unstored(True)
                sentence = (
                    f"channel {channel} preset written: "
                    f"bank {bank}, program {number}; read-back agreed"
                )
            else:
                sentence = (
                    f"channel {channel} preset: read-back disagreed "
                    f"(bank {bank_read!r} != {bank}, "
                    f"program {program_read!r} != {number}); "
                    "did not take"
                )
        refused = failure is not None or not ok
        self.notify_status(sentence, refused=refused)
        top = getattr(self, "_edit_screen", None)
        if top is None:
            top = self.screen
        if (
            top is not None
            and hasattr(top, "update_params")
            and getattr(self, "_current_midimap_words", None) is not None
        ):
            words = self._current_midimap_words
            params = {off: words[off] for off in range(len(words))}
            with contextlib.suppress(Exception):
                top.update_params(params)
        if top is not None and hasattr(top, "say"):
            with contextlib.suppress(Exception):
                top.say(sentence, refused=refused)

    def _mark_midimap_unstored(self, value: bool) -> None:
        """Track scratch edits and tell the editor screen (defensively)."""
        self._midimap_unstored = value
        screen = getattr(self, "_edit_screen", None)
        if screen is not None and hasattr(screen, "set_unstored"):
            with contextlib.suppress(Exception):
                screen.set_unstored(value)

    def _remember_midimap_name(self, index: int, words: list[int]) -> None:
        """Name a midimap in the catalog after a write.

        A rename, a store or a reset changes what the unit calls a midimap,
        but the browser's catalog is only refreshed by reading names off
        the unit. This keeps the one slot that changed in step, so the
        browser is not stale when the editor closes.
        """
        for region in banks.regions(banks.Kind.MIDIMAP):
            if region.first <= index <= region.last:
                try:
                    name = mm.name_of(words)
                except Exception:
                    return
                self.catalog.set_live_name(
                    region.id, index - region.first, name
                )
                return

    def _after_midimap_edit(self, _result: Any = None) -> None:
        """Reload the browser when the midimap editor closes.

        An edit can change a midimap's name (a rename, a store to another
        location, a reset to the default), so the slot pane is rebuilt from
        the catalog -- which the write paths above have kept in step --
        rather than left showing a name the unit no longer holds.
        """
        self._edit_screen = None
        if getattr(self, "_current_bank", None):
            with contextlib.suppress(Exception):
                self._refill_keeping_place()

    def _backup_before_write(self) -> None:
        if self._midimap_backed_up:
            return
        try:
            _cm = getattr(self.device, "current_midimap", None)
            index = 0 if _cm is None else _cm
            words = self.device.read_midimap(index)
            record = bkmod.save_midimap(
                words,
                device_id=self.device.device_id,
                slot=index,
                directory=self._backup_dir(),
                source="emorphed (midimap edit)",
            )
        except Exception as exc:
            self.call_from_thread(
                self.notify_status,
                f"could not back up the midimap: {exc}",
                refused=True,
            )
            return
        self._midimap_backed_up = True
        self.call_from_thread(
            self.notify_status, f"backed up the midimap as {record.id}"
        )

    def _backup_dir(self) -> str | None:
        # config maybe; keep None default under data dir
        return None

    def _parameter_edited(  # noqa: PLR0913
        self,
        offset: int,
        value: int,
        old: int | None,
        read_back: int | None,
        failure: BaseException | None,
        *,
        record: bool = True,
    ) -> None:
        if failure is not None:
            sentence = f"offset {offset}: {failure}"
            ok = False
        elif read_back is None:
            sentence = (
                f"offset {offset}: the unit stayed silent (no read-back)"
            )
            ok = False
        else:
            rb = read_back
            old_val = old if old is not None else value
            ok, sentence = self._editor.finish(offset, value, rb, old=old_val)
            if ok and record:
                self._push_change(ParamChange(offset, old_val, value))
        self.notify_status(sentence, refused=not ok)
        top = self.screen
        if hasattr(top, "result"):
            try:
                top.result(ok, sentence, parameter_id=offset, value=value)
            except Exception:  # noqa: S110
                pass
        # update current words
        if ok and getattr(self, "_current_midimap_words", None) is not None:
            self._current_midimap_words[offset] = value
        if ok:
            self._mark_midimap_unstored(True)

    def _store_midimap(self) -> None:
        refusal = self._editor.gate.refuse()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say(refusal, refused=True)
            return
        if not self._midimap_backed_up:
            sentence = "store refused: no midimap backup this session"
            self.notify_status(sentence, refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say(sentence, refused=True)
            return
        _idx = getattr(self, "_current_midimap_index", None)
        if _idx is None:
            _cm = getattr(self.device, "current_midimap", None)
            _idx = 0 if _cm is None else _cm
        index = _idx
        words = list(getattr(self, "_current_midimap_words", []))

        def answered(loc: int | None) -> None:
            if loc is None:
                return
            # The picker chose a location by bank and name; the erase is
            # still the destructive step, so it keeps its own confirmation
            # (manual p.36).
            self.push_screen(
                ConfirmScreen(f"STORE to M{loc:02d}: erases what is there"),
                lambda confirmed: self._store_confirmed(
                    loc, words, confirmed, index=index
                ),
            )

        self.push_screen(
            MidimapPickerScreen(self.catalog, current=index),
            answered,
        )

    def _store_confirmed(
        self,
        loc: int,
        words: list[int],
        confirmed: bool | None,
        *,
        index: int | None = None,
    ) -> None:
        if not confirmed:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say("busy", refused=True)
            return
        self._store_midimap_worker(loc, words, index=index)

    @work(thread=True)
    def _store_midimap_worker(
        self,
        loc: int,
        words: list[int],
        index: int | None = None,
        *,
        record: bool = True,
        backup: bool = False,
    ) -> None:
        failure = None
        stored: list[int] | None = None
        final_words = list(words)
        old_words: list[int] | None = None
        try:
            with self._busy_gate:
                # Read the target's current words before sending, best-effort:
                # a failed read leaves ``old_words`` as ``None`` and the store
                # still proceeds.
                try:
                    old_words = list(self.device.read_midimap(loc))
                except Exception:
                    old_words = None
                if not final_words:
                    try:
                        final_words = list(
                            self.device.read_midimap(
                                0 if index is None else index
                            )
                        )
                    except Exception:
                        final_words = []
                if backup and old_words is not None:
                    # Best-effort backup of what is about to be overwritten.
                    with contextlib.suppress(Exception):
                        bkmod.save_midimap(
                            old_words,
                            device_id=self.device.device_id,
                            slot=loc,
                            directory=self._backup_dir(),
                            source="emorphed (midimap undo)",
                        )
                self.device.send_midimap(loc, final_words)
                stored = list(self.device.read_midimap(loc))
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._finish_store,
            loc,
            final_words,
            stored,
            failure,
            old_words,
            record,
        )

    def _finish_store(  # noqa: PLR0913, PLR0917
        self,
        loc: int,
        words: list[int],
        stored: list[int] | None,
        failure: BaseException | None,
        old_words: list[int] | None = None,
        record: bool = True,
    ) -> None:
        top = getattr(self, "_edit_screen", None)
        if top is None:
            top = self.screen
        if failure is not None:
            sentence = f"store: {failure}"
            refused = True
        else:
            stored_list = stored if stored is not None else []
            total = len(words)
            if stored is None or total == 0 or len(stored_list) != total:
                sentence = (
                    f"store to M{loc:02d}: read-back was "
                    f"{len(stored_list)} words, not {total}; "
                    "did not take it"
                )
                refused = True
            else:
                agreed = sum(
                    1
                    for sent, got in zip(words, stored_list, strict=False)
                    if sent == got
                )
                if agreed == total and total > 0:
                    sentence = (
                        f"stored to M{loc:02d} -- survives a power cycle "
                        f"(read back {agreed}/{total} words)"
                    )
                    refused = False
                else:
                    sentence = (
                        f"store to M{loc:02d}: read-back disagreed "
                        f"({agreed}/{total} words agree); did not take it"
                    )
                    refused = True
        self.notify_status(sentence, refused=refused)
        if top is not None and hasattr(top, "say"):
            with contextlib.suppress(Exception):
                top.say(sentence, refused=refused)
        if not refused:
            self._mark_midimap_unstored(False)
            self._remember_midimap_name(loc, words)
            if record and old_words is not None and len(old_words) == 360:
                self._changes.append(MidimapChange(loc, tuple(old_words)))

    def _reset_midimap_to_default(self, index: int | None = None) -> None:
        """Reset a midimap to the factory default (the captured ``Dry`` map).

        The default is the application's captured factory-default midimap
        (``mm.DEFAULT_WORDS``, the unit's internal map named ``Dry``), not
        ``M00`` (which is an ordinary user map). A reset stores that map
        over the given location. It is a store, so it is fenced the same
        way -- a backup first, a confirmation that says what is erased, and
        a read-back. Like every write it is behind the gate: a locked gate
        refuses before the confirmation.

        When ``index`` is ``None`` the open editor's location is used
        (``self._current_midimap_index``, else ``device.current_midimap``,
        else ``0``), preserving the editor's behaviour.
        """
        refusal = self._editor.gate.refuse()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say(refusal, refused=True)
            return
        if index is None:
            _idx = getattr(self, "_current_midimap_index", None)
            if _idx is None:
                _cm = getattr(self.device, "current_midimap", None)
                _idx = 0 if _cm is None else _cm
            index = _idx

        def answered(confirmed: bool | None) -> None:
            if not confirmed:
                return
            if self._busy:
                self.notify_status("busy", refused=True)
                return
            if not self._exchange.acquire(blocking=False):
                self.notify_status("busy", refused=True)
                return
            self._reset_midimap_worker(index)

        self.push_screen(
            ConfirmScreen(
                f"reset M{index:02d} to the factory default midimap? "
                f"this erases the map there"
            ),
            answered,
        )

    @work(thread=True)
    def _reset_midimap_worker(
        self, index: int, *, record: bool = True
    ) -> None:
        """**MIDI only** -- back up, write the captured default, store it."""
        failure: BaseException | None = None
        backup_failed: BaseException | None = None
        default: list[int] = []
        stored: list[int] | None = None
        current: list[int] = []
        try:
            with self._busy_gate:
                # Back up what is about to be overwritten first: a store
                # without a successful backup is not offered (the fence).
                current = list(self.device.read_midimap(index))
                try:
                    bkmod.save_midimap(
                        current,
                        device_id=self.device.device_id,
                        slot=index,
                        directory=self._backup_dir(),
                        source="emorphed (midimap reset)",
                    )
                except Exception as exc:
                    backup_failed = exc
                else:
                    self._midimap_backed_up = True
                    default = list(mm.DEFAULT_WORDS)
                    self.device.send_midimap(index, default)
                    stored = list(self.device.read_midimap(index))
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._finish_reset,
            index,
            default,
            stored,
            failure,
            backup_failed,
            current,
            record,
        )

    def _finish_reset(  # noqa: PLR0913, PLR0917
        self,
        index: int,
        default: list[int],
        stored: list[int] | None,
        failure: BaseException | None,
        backup_failed: BaseException | None,
        current: list[int] | None = None,
        record: bool = True,
    ) -> None:
        top = getattr(self, "_edit_screen", None)
        if top is None:
            top = self.screen
        refused = True
        if failure is not None:
            sentence = f"reset: {failure}"
        elif backup_failed is not None:
            sentence = (
                f"reset refused: could not back up the midimap: "
                f"{backup_failed}"
            )
        elif stored is None or not default or len(stored) != len(default):
            sentence = (
                f"reset M{index:02d}: read-back was "
                f"{0 if stored is None else len(stored)} words, not "
                f"{len(default)}"
            )
        else:
            agreed = sum(
                1 for a, b in zip(default, stored, strict=False) if a == b
            )
            if agreed == len(default):
                refused = False
                self._current_midimap_words = list(default)
                self._midimap_unstored = False
                self._remember_midimap_name(index, default)
                if record and current is not None and len(current) == 360:
                    self._changes.append(MidimapChange(index, tuple(current)))
                if top is not None and hasattr(top, "update_params"):
                    params = {off: default[off] for off in range(len(default))}
                    with contextlib.suppress(Exception):
                        top.update_params(params)
                if top is not None and hasattr(top, "set_unstored"):
                    with contextlib.suppress(Exception):
                        top.set_unstored(False)
                with contextlib.suppress(Exception):
                    self._after_midimap_edit()
                sentence = (
                    f"reset M{index:02d} to the default midimap "
                    f"(read back {agreed}/{len(default)} words agree)"
                )
            else:
                sentence = (
                    f"reset M{index:02d}: read-back disagreed "
                    f"({agreed}/{len(default)} words agree)"
                )
        self.notify_status(sentence, refused=refused)
        if top is not None and hasattr(top, "say"):
            with contextlib.suppress(Exception):
                top.say(sentence, refused=refused)

    def action_undo(self) -> None:
        self._undo_master_edits(1)

    def action_undo_all(self) -> None:
        self._undo_master_edits(None)

    def _restore_midimap(self, index: int, words: tuple[int, ...]) -> bool:
        """Restore a whole map to ``index`` (one store).

        Best-effort backup first, then a read-back (the store's fence). The
        ``z`` keypress is the confirmation; this is not logged, so a second
        ``z`` is a no-op. Returns ``False`` without sending when busy, when
        the write gate is locked, or when the exchange cannot be acquired.
        """
        refusal = self._editor.gate.refuse()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say(refusal, refused=True)
            return False
        if self._busy:
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say("busy", refused=True)
            return False
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            top = getattr(self, "_edit_screen", None)
            if top is None:
                top = self.screen
            if top is not None and hasattr(top, "say"):
                with contextlib.suppress(Exception):
                    top.say("busy", refused=True)
            return False
        self._store_midimap_worker(
            index, list(words), record=False, backup=True
        )
        return True

    def _undo_master_edits(self, count: int | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
        # P2: refuse before consuming when the write gate is locked and the
        # batch contains a ParamChange or NameChange.
        n = (
            len(self._changes)
            if count is None
            else min(count, len(self._changes))
        )
        newest = self._changes[-n:] if n > 0 else []
        gate_refusal = self._editor.gate.refuse()
        if gate_refusal is not None and any(
            isinstance(
                c,
                (
                    ParamChange,
                    NameChange,
                    ChannelPresetChange,
                    MidimapChange,
                ),
            )
            for c in newest
        ):
            self.notify_status(gate_refusal, refused=True)
            return
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
        favourites = 0
        ratings = 0
        tags_notes = 0
        params = 0
        names = 0
        channel_presets = 0
        midimaps = 0
        not_applied: list[Any] = []
        for record in taken:
            change = record.payload
            if isinstance(change, FavouriteChange):
                favourites += 1
                self._undo_favourite(change)
            elif isinstance(change, RatingChange):
                ratings += 1
                self._undo_rating(change)
            elif isinstance(change, TagNoteChange):
                tags_notes += 1
                self._undo_tag_note(change)
            elif isinstance(change, ParamChange):
                if self._apply_parameter(
                    change.offset, change.old, record=False
                ):
                    params += 1
                else:
                    not_applied.append(record)
            elif isinstance(change, NameChange):
                if self._apply_name_text(change.old_text):
                    names += 1
                else:
                    not_applied.append(record)
            elif isinstance(change, ChannelPresetChange):
                if self._apply_channel_preset(
                    change.channel,
                    change.old_bank,
                    change.old_number,
                    record=False,
                ):
                    channel_presets += 1
                else:
                    not_applied.append(record)
            elif isinstance(change, MidimapChange):
                if self._restore_midimap(change.index, change.words):
                    midimaps += 1
                else:
                    not_applied.append(record)
        # Push back what was not applied, oldest-first.
        for record in reversed(not_applied):
            self._undo_log.push(record)
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
        if params:
            parts.append(f"{params} parameter{'s' if params != 1 else ''}")
        if names:
            parts.append(f"{names} name{'s' if names != 1 else ''}")
        if channel_presets:
            parts.append(
                f"{channel_presets} channel "
                f"preset{'s' if channel_presets != 1 else ''}"
            )
        if midimaps:
            parts.append(f"{midimaps} midimap{'s' if midimaps != 1 else ''}")
        if parts:
            msg = "undid " + ", ".join(parts)
            if not_applied:
                msg += (
                    f"; {len(not_applied)} could not be applied "
                    "-- press z again"
                )
        elif not_applied:
            msg = f"{len(not_applied)} could not be applied -- press z again"
        else:
            msg = "undid"
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

    def on_mount(self) -> None:  # noqa: C901
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
        # Open on the bank that was on screen last time: the left pane's
        # cursor has to sit on it before anything else moves, and its
        # row-highlighted event is safe because its bank is the one
        # already showing.
        table.move_cursor(row=self._bank_ids.index(self._current_bank))
        self._fill(self._current_bank)
        # The saved slot row, clamped to whatever this fill produced --
        # one use only, and only where the list has a row to take.
        saved_slot_cursor = self._saved_slot_cursor
        if saved_slot_cursor is not None and self._current:
            slots.move_cursor(
                row=min(saved_slot_cursor, len(self._current) - 1)
            )
        self._saved_slot_cursor = None
        if saved_slot_cursor is not None and self._current:
            slots.focus()
        else:
            table.focus()
        printed = len(self.catalog)
        live = self.catalog.live_count
        if printed and live:
            self.notify_status(
                f"{printed} names from the catalog · {live} read from the unit"
            )
        elif printed:
            self.notify_status(f"{printed} names from the catalog")
        elif live:
            # Not "no catalog": the unit supplied them, they are kept in
            # the sidecar, and saying otherwise read as "the scan never
            # made it" on every startup.
            self.notify_status(
                f"{live} names read from the unit (no printed catalog)"
            )
        else:
            self.notify_status(
                "no names yet -- press r to read the unit, or build a "
                "catalog with tools/extract_catalog.py"
            )
        if self._offer_scan:
            self.set_timer(0.6, self._maybe_offer_scan)
        if (
            self._verify_catalog_at_startup
            and not self._demo
            and (self.catalog or self.catalog.live_count)
        ):
            # The catalog painted this window; correct it from the unit in
            # the background once the first frame is up. Empty means the
            # scan offer handles the first run.
            self.set_timer(0.4, self._verify_catalog_now)

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

    def _save_ui_state(
        self,
        *,
        bank_index: Any = UNSET,
        slot_cursor: Any = UNSET,
        view_mode: Any = UNSET,
        kind_view: Any = UNSET,
    ) -> None:
        """Persist UI state (bank, slot cursor, both cycling views).

        :data:`UNSET` forwards nothing, so saving the view leaves the
        bank position alone: the four keys are saved individually, and
        only the ones named matter this time. ``None`` is the family's
        "remove the key", and this helper never has a reason to spell
        it -- the browser remembers where it was, it does not forget.

        Only :class:`OSError` is swallowed -- a read-only directory or
        a full disk, where forgetting the position is better than
        refusing to run. A programming error (a list where an int
        belongs) raises and is heard.
        """
        if self._config_path is None:
            return
        from emu import config as _cfg

        try:
            for key, value in (
                ("bank_index", bank_index),
                ("slot_cursor", slot_cursor),
                ("view_mode", view_mode),
                ("kind_view", kind_view),
            ):
                if value is UNSET:
                    continue
                _cfg.save_ui_state(key, value, self._config_path)
        except OSError:
            pass

    def _cursor_entry(self) -> banks.Slot | None:
        """The row under the cursor, or None."""
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return None
        return self._current[row]

    def action_reset_midimap(self) -> None:
        entry = self._cursor_entry()
        if entry is None:
            return
        if entry.kind != banks.Kind.MIDIMAP:
            self.notify_status(
                "only a midimap can be reset to its default", refused=True
            )
            return
        self._reset_midimap_to_default(entry.index)

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
                self.notify_status(
                    f"{literal(text)!r} is not a number", refused=True
                )
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
                self.notify_status(
                    f"{literal(text)!r} is not a number", refused=True
                )
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
        self.notify_status(
            f"{'favourited' if now else 'unfavourited'} {literal(name)}"
        )
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
        self._save_ui_state(view_mode=self.view_mode)
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
                name = literal(
                    self.catalog.display_name(entry.bank_id, entry.number)
                )
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
        name = literal(self.catalog.display_name(entry.bank_id, entry.number))
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
            bank = banks.bank_select_bank(entry.bank_id)
            how = (
                f"Bank Select (CC32) [b]{bank}[/b] · Program Change "
                f"[b]{entry.number}[/b] [dim](under the default "
                f"Program Map)[/dim]"
            )
        self.query_one("#detail", Static).update(
            f"[b]{entry.display}[/b]  {name}   [dim]index "
            f"{entry.index}[/dim]\n{how} · {source}"
        )

    def notify_status(self, message: str, *, refused: bool = False) -> None:
        """Say the last thing; a refusal goes red and bold.

        The family's shape (rxved): the widget carries a ``refused`` class
        rather than a text prefix, so a locked write gate is a red bar the
        eye cannot miss instead of another grey status line.
        """
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_class(refused, "refused")

    # --- navigation ---------------------------------------------------------

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if self._filling:
            return
        if event.data_table.id == "bank-table":
            row = event.cursor_row
            if 0 <= row < len(self._bank_ids):
                bank_id = self._bank_ids[row]
                # Idempotent on purpose. `_filling` cannot guard this --
                # the message is delivered after the flag is cleared --
                # so the handler has to be safe to receive for the bank
                # it is already showing. Saving is part of that: it
                # rewrites the same value, which is what idempotent
                # means to a cache.
                if bank_id != self._current_bank:
                    self._fill(bank_id)
                    self._save_ui_state(bank_index=row)
        elif event.data_table.id == "slot-table":
            self._detail(event.cursor_row)
            # Only save the slot cursor when the slot table is focused --
            # the user is actively navigating. Programmatic cursor moves
            # during startup (while the bank pane has focus) must not
            # overwrite the saved position they are busy restoring.
            if event.data_table.has_focus:
                self._save_ui_state(slot_cursor=event.cursor_row)

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
        self._save_ui_state(kind_view=nxt)
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
        if entry.kind == banks.Kind.MIDIMAP:
            # A midimap has no program change, but it can be made current
            # over System Exclusive -- two frames, per the manual's
            # page 159. That changes what plays, so it gets its own
            # confirmation before anything is sent.
            self._confirm_midimap(entry)
            return
        if entry.kind not in (
            banks.Kind.PRESET,
            banks.Kind.HYPERPRESET,
        ):
            self.notify_status(
                f"a {entry.kind} is not selected with a program change; "
                f"only presets and hyperpresets are",
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

    def _confirm_midimap(self, entry: banks.Slot) -> None:
        midimap_name = f"M{entry.index:02d}"
        prompt = (
            f"make Midimap {midimap_name} current on the unit; "
            f"this switches it to Multi mode and changes what plays"
        )
        self.push_screen(
            ConfirmScreen(prompt),
            lambda confirmed: self._midimap_answered(entry, confirmed),
        )

    def _midimap_answered(
        self, entry: banks.Slot, confirmed: bool | None
    ) -> None:
        if not confirmed:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._select_midimap_worker(entry)

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
            f"{banks.bank_select_bank(entry.bank_id)} then Program Change "
            f"{entry.number} on channel {self.device.channel + 1}; "
            f"that number reaches it under the default Program Map",
        )

    @work(thread=True)
    def _select_midimap_worker(self, entry: banks.Slot) -> None:
        """**MIDI only.** Makes a midimap current. The gate tracks
        the exchange in progress."""
        try:
            with self._busy_gate:
                self.device.select_midimap(entry.index)
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(
                self.notify_status, f"select midimap: {exc}", refused=True
            )
            return
        finally:
            self._exchange.release()
        self.call_from_thread(
            self.notify_status,
            f"made Midimap M{entry.index:02d} current on the unit",
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

    def _verify_catalog_now(self) -> None:
        """Re-read every kind's names once, in the background.

        The catalog on disk is a cache: it paints the window, but it can be
        a day old. This corrects it from the unit -- one list request per
        kind, silent -- without blocking the first frame and without moving
        the cursor. It shares the one-exchange lock, so it can never overlap
        a user action; if the wire is busy it simply does not run this time.
        """
        if self._demo:
            return
        if self._busy:
            return
        if not self._exchange.acquire(blocking=False):
            return
        self._verify_catalog_worker()

    @work(thread=True)
    def _verify_catalog_worker(self) -> None:
        """**MIDI only** -- all three name lists, quiet, best-effort.

        Whatever was read last time is already on screen when this runs, so
        it only ever *corrects* the display. A failure keeps the stored names
        (and says so); success says nothing, because the user did not ask
        for it and three "read N names" lines would bury the startup status.
        """
        try:
            with self._busy_gate:
                for kind in banks.Kind.ALL:
                    try:
                        names = self.device.names(kind)
                    except _BRIDGE_ERRORS as exc:
                        self.call_from_thread(
                            self.notify_status,
                            f"could not verify {kind} names ({exc}); "
                            f"keeping the ones read last time",
                            refused=True,
                        )
                        continue
                    self.call_from_thread(self._adopt_kind_quiet, kind, names)
        finally:
            self._exchange.release()

    def _adopt_kind_quiet(self, kind: str, names: list[str]) -> None:
        self._adopt_kind(kind, names, quiet=True)

    def _adopt_kind(  # noqa: C901
        self, kind: str, names: list[str], *, quiet: bool = False
    ) -> None:
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
        if not quiet:
            self.notify_status(f"read {adopted} {kind} name(s){short}")

    def _maybe_offer_scan(self) -> None:
        """Offer a scan when there is nothing to start from.

        "Nothing" means neither layer: a catalog from the generated file
        *or* names already read from the unit. Offering while the sidecar
        is full is how the offer came back on every launch.
        """
        if self._demo or self._busy:
            return
        if self.catalog or self.catalog.live_count:
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
                self.notify_status(f"nothing matching {literal(text)!r}")
                return
            lines = [f"{len(hits)} match(es) for {literal(text)!r}", ""]
            for bank_id, number, name, _disagrees in hits[:400]:
                try:
                    entry = banks.slot(bank_id, number)
                except LookupError:
                    continue
                lines.append(
                    f"{entry.display:<6} {literal(name):<12} "
                    f"PC {entry.number:>3}"
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
            f"connection      {literal(self.device.description)}",
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
and for presets and hyperpresets -- a Program Map sits between the
two, so the number shown is the one that works under the default map.
Bank Select is Controller 32 with Controller 0 held at zero.

Names

`r` reads every name of the current kind in **one** message, which this
instrument can do and its siblings cannot. Names read from the unit show
in bold; a `*` marks a slot where the unit and the catalog disagree.

Keys

  ↑↓        move; this never sends anything
  tab       switch pane
  ⏎         select on the unit -- presets and hyperpresets, or a
            midimap (confirms)
  r         read every name of this kind (silent, one message)
  /         search the names
  [ ]       previous / next MIDI channel
  c         set the MIDI channel
  d         set the SysEx device ID -- a different thing
  f         favourite the slot under the cursor
  v         all slots / favourites here / every favourite
  t n       tags, note
  *         rate the slot under the cursor
  V         rating filter
  z Z       undo / undo all
  k         kind view
  S         scan names
  i         what the unit says it is
  q         quit
"""


def _say_sweep(bridge: Any) -> None:
    """One line when the unit was found by a sweep, and silence otherwise.

    A sweep takes minutes on a busy host; saying so, once, is what keeps a
    slow launch from being mistaken for the normal one.
    """
    if not getattr(bridge, "swept", False):
        return
    print(
        f"swept for {bridge.probe_seconds:.1f} s; found "
        f"{bridge.port} (device {bridge.device_id})",
        file=sys.stderr,
    )


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
        allow_write=True,
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
                    on_try=lambda n: print(f"  probing {n}", file=sys.stderr),
                )
            device = bridge
            _say_sweep(bridge)
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
        allow_write=args.allow_write,
        verify_catalog_at_startup=not args.demo,
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
