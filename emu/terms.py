# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
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

"""What the E-mu calls things, declared once.

**The instrument's word is the instrument's.** The Morpheus's own display
says PRESET and REGION, so those are the words every string a user reads
uses here -- the list view, the pane headings, the help, the README.

The wire's word is different and stays in the code that builds wire
messages: on the wire this is a *preset index*, and the Program Map that
turns an index into a program change is the thing that has to be
translated. That translation is not a naming exercise, so it stays in
``emu.banks`` where it is visible.
"""

from __future__ import annotations

from vinsynlib.terms import Terminology, register

__all__ = ["TERMS"]

TERMS = Terminology(
    app_name="emorphed",
    sound="preset",
    container="region",
    device="E-mu Morpheus",
)

#: Registered at import so the family's registry knows what this tool calls
#: its concepts. Registration rather than a monkeypatched module global: a
#: library cannot know the name of the program using it, and passing it in
#: is honest where patching is global.
register(TERMS)
