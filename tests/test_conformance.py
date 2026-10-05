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

"""emorphed keeps the contract the other eight projects in the family keep.

Every check below is the same one, run against this program rather than
written out again here. The reasons are in docs/UX-SPEC.md section 5 and
in the library: what drifted was never a bug anyone chose, it was a copy
that nobody had a second copy to compare against.
"""

from emorphed.app import KEY_HINTS, EmorphedApp, build_parser
from emu.terms import TERMS
from vinsynlib import conformance


def test_flags_match_the_family() -> None:
    # A tuple rather than the set in the template: check_flags takes a
    # Sequence, and mypy --strict is right that a set is not one.
    assert not conformance.check_flags(
        build_parser(),
        required=("port", "demo", "config", "catalog"),
    )


def test_keys_match_the_family() -> None:
    # select=False, and the reason is in emorphed/app.py: a focused
    # DataTable consumes Enter for its own row selection, so it arrives as
    # RowSelected and calls action_select from there. The key works and the
    # legend promises it; what it cannot be is a BINDINGS entry, because
    # binding it would mean the App taking Enter from the table and every
    # other table key with it. Checked from the other side below.
    assert not conformance.check_bindings(
        EmorphedApp, favourites=True, channel=True, select=False
    )


def test_the_legend_matches_the_family() -> None:
    # select=True here even though the binding check above says False: the
    # legend is a promise about which keys work, and this one does.
    assert not conformance.check_legend(KEY_HINTS, extras=("d device ID",))


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)
