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


#: The legend. Every binding the app has, in the order somebody meets them.
KEY_HINTS = keys.legend(("d device ID", "k kind"))
