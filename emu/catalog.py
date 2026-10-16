# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# emorphed is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.

"""Preset names, and where each one came from.

Two sources, kept apart all the way to the screen:

* **Printed** names, from the generated catalog file built from the
  preset lists in the Morpheus Operation Manual. They are E-mu's and
  the file is gitignored.
* **Live** names, read from a unit over System Exclusive.

The storage grammar -- keys built with ``make_key``, the ``"--"``
placeholder for an unnamed slot, ``split_key`` for reading keys back --
comes from ``vinsynlib.catalog``. This module keeps only the
emorphed-specific surface the browser calls: ``entry``, ``display_name``,
``search``, ``set_live_name``, ``is_live``, ``differs``, ``load`` and
``empty``. Morpheus rows carry no ``kind``; bank ids already name the
region (``P-RAM``, ``P-ROM`` ...).

Nothing in here plays anything. Reading names is silent on this
instrument whichever way it is done.
"""

from __future__ import annotations

import os
import sys

from vinsynlib.catalog import (
    UNNAMED,
    Entry,
    dump,
    make_key,
    split_key,
)
from vinsynlib.catalog import (
    Catalog as _BaseCatalog,
)
from vinsynlib.catalog import (
    load as _vlib_load,
)

__all__ = [
    "DEFAULT_PATH",
    "UNNAMED",
    "Catalog",
    "Entry",
    "dump",
    "empty",
    "load",
    "make_key",
    "split_key",
]

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "catalog.json"
)


class Catalog(_BaseCatalog):
    """Printed names, plus whatever has been read from a unit.

    A thin binding over :class:`vinsynlib.catalog.Catalog`, keeping the
    emorphed-shaped ``search`` result (carrying the disagreement flag as
    its fourth element) so the browser's call sites stay unchanged.
    """

    def search(  # type: ignore[override]
        self, needle: str, *, kind: str | None = None
    ) -> list[tuple[str, int, str, bool]]:
        """Case-insensitive substring search over both layers.

        Each hit is ``(bank_id, number, name, disagrees)``. The unit's
        name wins in ``name``; ``disagrees`` is whether the unit and the
        catalog differ about that slot. Morpheus rows carry no kind, so
        the kind filter is usually left at ``None``.
        """
        legacy = []
        for bank_id, found_kind, number, name in super().search(
            needle, kind=kind
        ):
            disagrees = self.differs(bank_id, number, found_kind)
            legacy.append((bank_id, number, name, disagrees))
        return legacy

    @property
    def live_count(self) -> int:
        """How many names are in the live layer.

        Read off the unit and kept in the sidecar, so they survive a
        restart. Counted here rather than by the caller because the live
        layer is this class's own state and the browser's status line has
        to tell "no names at all" from "names from the unit only".
        """
        return len(self._live)

    def disagreement(
        self, bank_id: str, number: int, writable: bool = False
    ) -> str | None:
        """Why the unit and the catalog differ here, or ``None``.

        ``writable`` controls the wording: a writable bank that differs
        means somebody saved their own work; otherwise the printed list is
        wrong.
        """
        if not self.differs(bank_id, number):
            return None
        if writable:
            return "saved over the factory preset"
        return "the printed list is wrong; the unit is right"


def empty() -> Catalog:
    """A catalog that knows no names. What you get with no data file."""
    return Catalog()


def load(path: str | None = None) -> Catalog:
    """Load the generated catalog, or an empty one.

    A missing file is normal and not an error: emorphed works without it,
    showing numbers only, and a connected unit can supply every name
    itself. One bad row costs one row, not the file: unreadable rows are
    counted to stderr and skipped. Morpheus rows carry no ``kind``.
    """
    target = path or DEFAULT_PATH
    try:
        base = _vlib_load(target)
    except (OSError, ValueError):
        print(
            f"warning: {target} could not be read as a catalog",
            file=sys.stderr,
        )
        return empty()
    out = Catalog.__new__(Catalog)
    out.__dict__.update(base.__dict__)
    return out
