# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#

"""Plain-text-to-markup escaping.

Names travel from the instrument (or from a favourites file the user
edited, or from a name the user typed in the midimap editor) into
Textual/Rich widgets whose content is parsed as markup. The instrument has
no idea what markup is, and neither do any of those other sources, so a
single bracket in a name breaks every widget that quotes one. Wrapping the
supplier text with :func:`literal` on the way in makes it render as exactly
itself.

This module imports nothing from the rest of :mod:`emorphed`, so both
:mod:`emorphed.app` and :mod:`emorphed.midimapui` can use it without a
cycle.
"""

from __future__ import annotations

__all__ = ["escape", "escape_markup", "literal", "markup_escape"]


def literal(text: str) -> str:
    """``text`` rendered as Rich markup that displays as exactly itself.

    Names come off the instrument (and tags, notes and midimap names come
    from the user), and none of those sources knows what markup is, so any
    ``[...]`` they carry has to be defanged before it reaches a widget
    whose content is markup-parsed. A name containing ``[`` would
    otherwise swallow the tags wrapped around it and crash the app.
    """
    return text.replace("[", "\\[")


# Alias kepts so callers using any of the obvious names find the helper.
escape = literal
markup_escape = literal
escape_markup = literal
