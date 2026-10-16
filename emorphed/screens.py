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

from typing import Any, ClassVar

from emorphed.text import escape, literal
from vinsynlib import keys
from vinsynlib.keys import wrap_blocks
from vinsynlib.ui.hints import KeyHints
from vinsynlib.ui.prompt import PromptScreen
from vinsynlib.ui.report import ReportScreen as _Frame

__all__ = [
    "KEY_HINTS",
    "KeyHints",
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
