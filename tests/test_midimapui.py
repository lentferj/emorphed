# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke tests for the midimap editor screen."""

from __future__ import annotations

from emorphed.app import EmorphedApp
from emorphed.demo import DemoDevice
from emorphed.edit import EditGate, MidimapEditor
from emorphed.midimapui import MidimapEditScreen


def test_screen_constructs() -> None:
    app = EmorphedApp(DemoDevice())
    gate = EditGate()
    editor = MidimapEditor(gate=gate)
    screen = MidimapEditScreen(editor, {0: 65}, on_edit=lambda _o, _v: None)
    assert screen is not None
    assert app is not None
