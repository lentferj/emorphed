# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors

"""The scan offer and scan progress modal screens."""

from __future__ import annotations

import contextlib
import threading
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Static

__all__ = ["SCAN_OFFER", "ScanOffer", "ScanOfferScreen", "ScanScreen"]

ScanOffer = str

SCAN_OFFER = (
    "There is no name catalog yet, so the sounds show as numbers.\n\n"
    "Scanning reads all three kinds of name back from the unit -- "
    "presets, hyperpresets and midimaps -- one request per kind, about "
    "three requests in total. Every one of those reads is silent: "
    "nothing is selected, nothing plays, nothing is written to the "
    "instrument, and the reading costs nothing audible on the Morpheus. "
    "It takes a few seconds."
)


class ScanOfferScreen(ModalScreen[ScanOffer]):
    BINDINGS: ClassVar[list[Any]] = [
        ("y", "scan", "Scan"),
        ("n", "later", "Not now"),
        ("d", "never", "Don't ask again"),
        ("escape", "later", "Not now"),
        # Arrows move between the buttons. Textual's own navigation is Tab
        # and Shift+Tab only, which on a three-answer dialog reads as
        # broken next to the rating filter's arrow-driven grid; Enter
        # presses whichever button is focused. Up/down do the same as
        # left/right because the row is one-dimensional and reaching for
        # the wrong axis should not do nothing.
        ("left", "previous_button", "Previous"),
        ("up", "previous_button", "Previous"),
        ("right", "next_button", "Next"),
        ("down", "next_button", "Next"),
    ]

    def __init__(self, prompt: str = SCAN_OFFER) -> None:
        super().__init__()
        self.prompt_text = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="scan-offer"):
            yield Static(self.prompt_text, id="scan-offer-prompt")
            with Horizontal(id="scan-offer-buttons"):
                yield Button("Scan", variant="primary", id="scan")
                yield Button("Not now", id="later")
                yield Button("Don't ask again", id="never")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "later")

    def action_scan(self) -> None:
        self.dismiss("scan")

    def action_later(self) -> None:
        self.dismiss("later")

    def action_never(self) -> None:
        self.dismiss("never")

    def action_next_button(self) -> None:
        """Focus the next answer; wraps at the end."""
        self.focus_next()

    def action_previous_button(self) -> None:
        """Focus the previous answer; wraps at the start."""
        self.focus_previous()

    def focused_answer(self) -> str | None:
        """The id of the focused button, for the tests to assert on."""
        focused = self.focused
        return focused.id if focused is not None else None


class ScanScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[Any]] = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, cancel: threading.Event) -> None:
        super().__init__()
        self._cancel = cancel
        self._cancelled = False
        self._line = "starting..."

    def compose(self) -> ComposeResult:
        with Vertical(id="scan-dialog"):
            yield Static("[b]Scanning the device[/b]", id="scan-title")
            yield Static(self._line, id="scan-line")
            with Horizontal(id="scan-buttons"):
                yield Button("Cancel", id="cancel")

    def set_progress(self, line: str) -> None:
        self._line = line
        with contextlib.suppress(NoMatches):
            self.query_one("#scan-line", Static).update(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._cancel.set()
        self.set_progress("cancelling - stopping after this bank...")
        with contextlib.suppress(NoMatches):
            self.query_one("#cancel", Button).disabled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled
