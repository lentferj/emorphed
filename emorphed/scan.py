# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors

"""placeholder"""

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
