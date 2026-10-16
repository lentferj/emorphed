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
        required=("port", "scan", "recv-port", "demo", "config", "catalog"),
    )


#: This tool's own legend blocks, in the family's display order. The legend
#: is a promise about which keys work, and the app binds every one of these.
EXTRA_HINTS = (
    "d device ID",
    "k kind",
    "S scan device",
    "* rating",
    "V rating filter",
    "z undo",
    "Z undo all",
)


def test_keys_match_the_family() -> None:
    # select=False, and the reason is in emorphed/app.py: a focused
    # DataTable consumes Enter for its own row selection, so it arrives as
    # RowSelected and calls action_select from there. The key works and the
    # legend promises it; what it cannot be is a BINDINGS entry, because
    # binding it would mean the App taking Enter from the table and every
    # other table key with it. Checked from the other side below.
    problems = conformance.check_bindings(
        EmorphedApp, favourites=True, channel=True, select=False
    )
    # One deliberate divergence: emorphed moves the favourites view off the
    # family's `F` and onto `v`, exactly as rxved and p2ked do. `f` writes
    # the favourites database and `F` does not, so the shift-pair left a
    # write one slip away from a read; `v` has no such twin. The family asks
    # a tool that renames a shared key to say why in its own test, and these
    # two lines are the whole of the divergence -- anything else appearing
    # here is a real drift.
    assert set(problems) == {
        "F is not bound; the family binds it to cycle_favorites",
        "cycle_favorites is not reachable from F; it is bound to v",
    }, "\n".join(problems)


def test_the_legend_matches_the_family() -> None:
    # select=True here even though the binding check above says False: the
    # legend is a promise about which keys work, and this one does. The two
    # problems left are the `v` rename the docstring above records and
    # nothing else.
    problems = conformance.check_legend(KEY_HINTS, extras=EXTRA_HINTS)
    assert set(problems) == {
        "the legend is missing 'F favourites view'",
        "the legend shows 'v favourites view', which is not in the family's",
    }, "\n".join(problems)


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)
