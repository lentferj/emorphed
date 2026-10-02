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

"""Preset names, and where each one came from.

Two sources, kept apart all the way to the screen:

* **Printed** names, transcribed from the preset lists in the Morpheus
  Operation Manual. Generated locally into ``emu/data/catalog.json``,
  which is gitignored -- those names are E-mu's and are not
  redistributed here.
* **Live** names, read from a unit over System Exclusive.

A single mapping cannot keep them distinguishable, and the distinction is
the useful part: a RAM preset whose live name differs from the printed one
is a slot somebody has saved their own work into, and that is the single
most informative thing this program can put on a screen.

**A catalog matters less here than in the sibling projects**, and it is
worth saying why. This instrument will hand over every preset name in one
silent exchange -- ``Preset List Request``, one message out and every name
back -- so working from the unit is cheap and working without it is the
unusual case. The catalog is for reading a ``.syx`` file on a train, and
for the two regions a unit cannot supply when no card is fitted.

Nothing in this module plays anything. Reading names is silent on this
instrument whichever way it is done.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["DEFAULT_PATH", "Catalog", "Entry", "empty", "load"]

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "catalog.json"
)


@dataclass(frozen=True)
class Entry:
    bank_id: str
    #: The slot's position within its region, matching
    #: :attr:`banks.Slot.number`. **Not** a program change: on this
    #: instrument a Program Map decides what program number reaches a
    #: preset, and `banks.Slot.program_change` is documented as an
    #: assumption for exactly that reason. Naming this field after the
    #: assumption would have enshrined it.
    number: int
    name: str

    @property
    def key(self) -> str:
        return f"{self.bank_id}:{self.number:03d}"


class Catalog:
    """Printed names, plus whatever has been read from a unit."""

    def __init__(
        self,
        entries: Iterable[Entry] = (),
        *,
        source: str = "",
        generated: str = "",
    ) -> None:
        self._entries: dict[str, Entry] = {}
        for entry in entries:
            self._entries[entry.key] = entry
        self._live: dict[str, str] = {}
        self.source = source
        self.generated = generated

    # --- printed ------------------------------------------------------------

    def entry(self, bank_id: str, number: int) -> Entry | None:
        return self._entries.get(f"{bank_id}:{number:03d}")

    def name(self, bank_id: str, number: int) -> str | None:
        found = self.entry(bank_id, number)
        return found.name if found is not None else None

    def has(self, bank_id: str) -> bool:
        prefix = f"{bank_id}:"
        return any(key.startswith(prefix) for key in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    # --- live ---------------------------------------------------------------

    def set_live_name(self, bank_id: str, number: int, name: str) -> None:
        self._live[f"{bank_id}:{number:03d}"] = name

    def live_name(self, bank_id: str, number: int) -> str | None:
        return self._live.get(f"{bank_id}:{number:03d}")

    def is_live(self, bank_id: str, number: int) -> bool:
        return f"{bank_id}:{number:03d}" in self._live

    def differs(self, bank_id: str, number: int) -> bool:
        """Whether the unit and the printed list disagree about this slot.

        **What a disagreement means depends on the bank.** In a user bank it
        means somebody has saved their own work over the factory preset,
        which is the most useful thing this program can point out. In a ROM
        bank it cannot mean that -- ROM does not change -- so it means the
        printed list is wrong, and the unit is right.

        **Nothing in this project has yet compared the two**: no unit has
        answered emorphed, so every name it has seen came from a file or
        from the manual. The sibling projects each found their
        disagreements to be whitespace -- an instrument holding two spaces
        where a printed list shows one -- and that is the shape to expect
        here too, but expecting is not knowing. Callers should say which
        kind of disagreement they are showing; see :meth:`disagreement`.
        """
        live = self.live_name(bank_id, number)
        if live is None:
            return False
        printed = self.name(bank_id, number)
        return printed is not None and printed != live

    def disagreement(
        self, bank_id: str, number: int, writable: bool
    ) -> str | None:
        """Why the unit and the catalog differ here, in words.

        ``None`` when they agree or the slot has not been read.
        """
        if not self.differs(bank_id, number):
            return None
        if writable:
            return "saved over the factory preset"
        return "the printed list is wrong; the unit is right"

    def display_name(self, bank_id: str, number: int) -> str:
        """What to show: the unit's name if known, else the printed one."""
        live = self.live_name(bank_id, number)
        if live is not None:
            return live
        return self.name(bank_id, number) or ""

    # --- search -------------------------------------------------------------

    def search(self, needle: str) -> list[tuple[str, int, str, bool]]:
        """Case-insensitive substring search over both sources.

        Each hit carries whether the unit and the printed list disagree
        about that slot, so a caller can show the same marker the browser
        does. Search is where it matters most: the browser marks a slot the
        user is already looking at, while a search result is a name from a
        bank they have not opened.
        """
        wanted = needle.strip().lower()
        if not wanted:
            return []
        seen: dict[str, tuple[str, int, str]] = {}
        for key, entry in self._entries.items():
            if wanted in entry.name.lower():
                seen[key] = (entry.bank_id, entry.number, entry.name)
        for key, name in self._live.items():
            if wanted in name.lower():
                bank_id, _, number = key.rpartition(":")
                seen[key] = (bank_id, int(number), name)
        return [
            seen[key] + (self.differs(*seen[key][:2]),) for key in sorted(seen)
        ]


def empty() -> Catalog:
    return Catalog()


def load(path: str | None = None) -> Catalog:
    """Load the generated catalog, or an empty one.

    A missing catalog is normal and not an error: emorphed works without it,
    showing numbers only, and a connected unit can supply every name itself.
    """
    target = path or DEFAULT_PATH
    if not os.path.exists(target):
        return empty()
    try:
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty()
    entries = []
    skipped = 0
    for bank_id, rows in payload.get("banks", {}).items():
        for row in rows:
            # One bad row must not cost the whole catalog. A missing one is
            # already normal here -- the program runs on numbers alone and
            # a connected unit can supply every name -- so a corrupt one
            # taking the program down with it is the odd behaviour, not
            # skipping it.
            try:
                entries.append(
                    Entry(
                        bank_id=bank_id,
                        number=int(row["pc"]),
                        name=row["name"],
                    )
                )
            except (KeyError, TypeError, ValueError):
                skipped += 1
    if skipped:
        print(
            f"warning: {target} has {skipped} unreadable row(s), skipped; "
            f"regenerate it with tools/extract_catalog.py",
            file=sys.stderr,
        )
    return Catalog(
        entries,
        source=payload.get("source", ""),
        generated=payload.get("generated", ""),
    )
