# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The memory layout is transcribed as data from E-mu's MIDI Specification,
# pages 228 and 231-232 of the Morpheus Operation Manual (1993).
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# emorphed is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""What the Morpheus holds, and how to ask for a piece of it.

Three kinds of thing, each numbered in its own space:

=============  =========================  ====================
kind           numbers                    a bank is
=============  =========================  ====================
preset         0-127 RAM, 128-255 ROM,    128 presets
               256-383 CARD
hyperpreset    0-127 RAM, 128-255 CARD    128 hyperpresets
midimap        0-15 RAM, 16-31 CARD       16 midimaps
=============  =========================  ====================

**A preset index is not a program number.** The manual says so in the
first line of the Preset Request: "Uses preset index values (not the same
as program numbers)." The index is what SysEx addresses; the program
number is what a Program Change selects, and a Program Map sits between
them. :class:`Slot` therefore carries ``index`` and does **not** carry a
program change, because for a preset in ROM or on a card there may not be
one until a map gives it one.

**Bank Select is Controller 32, and Controller 0 is always zero.** The
manual's MIDI table gives the sequence literally: ``Bn 00 00 20 bb Cn
pp``. That is the opposite way round from the sibling nanosyned's
instrument, which ignores 32 and uses 0. Neither is wrong; they are just
different, and a helper that sent "both to be safe" would be lying about
one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from emu import messages as m

__all__ = [
    "Kind",
    "Region",
    "Slot",
    "REGIONS",
    "PRESETS_PER_BANK",
    "HYPERS_PER_BANK",
    "MIDIMAPS_PER_BANK",
    "TOTAL_PRESETS",
    "regions",
    "region",
    "region_ids",
    "slots",
    "slot",
    "kinds_of",
    "bank_of",
    "bank_request",
    "select_messages",
]


class Kind:
    """The three things that have names and numbers."""

    PRESET = "preset"
    HYPERPRESET = "hyperpreset"
    MIDIMAP = "midimap"

    ALL = (PRESET, HYPERPRESET, MIDIMAP)

    #: How many fit in one bank, which is what a bank request returns.
    PER_BANK = {PRESET: 128, HYPERPRESET: 128, MIDIMAP: 16}

    #: Which request asks for one of these.
    REQUEST = {
        PRESET: m.Command.PRESET_REQUEST,
        HYPERPRESET: m.Command.HYPERPRESET_REQUEST,
        MIDIMAP: m.Command.MIDIMAP_REQUEST,
    }

    #: ...and which asks for every name of that kind at once.
    LIST_REQUEST = {
        PRESET: m.Command.PRESET_LIST_REQUEST,
        HYPERPRESET: m.Command.HYPERPRESET_LIST_REQUEST,
        MIDIMAP: m.Command.MIDIMAP_LIST_REQUEST,
    }

    LIST_REPLY = {
        PRESET: m.Command.PRESET_LIST_DATA,
        HYPERPRESET: m.Command.HYPERPRESET_LIST_DATA,
        MIDIMAP: m.Command.MIDIMAP_LIST_DATA,
    }


PRESETS_PER_BANK = Kind.PER_BANK[Kind.PRESET]
HYPERS_PER_BANK = Kind.PER_BANK[Kind.HYPERPRESET]
MIDIMAPS_PER_BANK = Kind.PER_BANK[Kind.MIDIMAP]


@dataclass(frozen=True)
class Region:
    """A contiguous run of one kind, in one sort of memory."""

    id: str
    label: str
    kind: str
    first: int
    count: int
    writable: bool
    #: Whether it is only there when a card is in the slot.
    needs_card: bool
    note: str = ""

    @property
    def last(self) -> int:
        return self.first + self.count - 1


#: Every region, in index order within each kind.
REGIONS: Tuple[Region, ...] = (
    Region(
        "P-RAM",
        "Presets, RAM",
        Kind.PRESET,
        0,
        128,
        writable=True,
        needs_card=False,
        note="The 128 you can change.",
    ),
    Region(
        "P-ROM",
        "Presets, ROM",
        Kind.PRESET,
        128,
        128,
        writable=False,
        needs_card=False,
        note="Fixed in the instrument.",
    ),
    # 128, not the 64 the manual's Preset Request paragraph gives. That
    # paragraph says "256-319 CARD" and then, four lines later, that bank
    # requests take a bank number of 0-2 and "banks are blocks of 128
    # presets" -- which is 384, not 320. A real Favs_All.syx from this
    # instrument holds presets 0-383, contiguous. Two against one, and
    # the two are the ones that can be checked.
    Region(
        "P-CARD",
        "Presets, card",
        Kind.PRESET,
        256,
        128,
        writable=False,
        needs_card=True,
        note="A request is ignored outright if no card is fitted.",
    ),
    Region(
        "H-RAM",
        "Hyperpresets, RAM",
        Kind.HYPERPRESET,
        0,
        128,
        writable=True,
        needs_card=False,
        note="Each stacks up to 16 zones of presets.",
    ),
    Region(
        "H-CARD",
        "Hyperpresets, card",
        Kind.HYPERPRESET,
        128,
        128,
        writable=False,
        needs_card=True,
    ),
    Region(
        "M-RAM",
        "Midimaps, RAM",
        Kind.MIDIMAP,
        0,
        16,
        writable=True,
        needs_card=False,
        note="16 channels each. Selectable only over SysEx -- there "
        "is no program change for a midimap.",
    ),
    Region(
        "M-CARD",
        "Midimaps, card",
        Kind.MIDIMAP,
        16,
        16,
        writable=False,
        needs_card=True,
    ),
)

TOTAL_PRESETS = sum(r.count for r in REGIONS if r.kind == Kind.PRESET)

_BY_ID: Dict[str, Region] = {r.id: r for r in REGIONS}


@dataclass(frozen=True)
class Slot:
    """One addressable object."""

    region: Region
    #: What SysEx addresses. **Not** a program number -- see the module
    #: docstring; a Program Map decides what program number reaches this,
    #: and there may not be one.
    index: int

    @property
    def kind(self) -> str:
        return self.region.kind

    @property
    def bank_id(self) -> str:
        """What the favourites store and the catalog key on."""
        return self.region.id

    @property
    def number(self) -> int:
        """Its position within its region, counting from 0.

        The instrument's display counts presets from 0 within the region,
        so this is what a user reads off the front panel. It is kept
        apart from :attr:`index` because only one of them goes on the
        wire.
        """
        return self.index - self.region.first

    @property
    def key(self) -> str:
        return f"{self.region.id}:{self.number:03d}"

    @property
    def display(self) -> str:
        return f"{self.region.label} {self.number:03d}"

    @property
    def program_change(self) -> int:
        """The program number **if** the default map is in force.

        Presented as what it is: an assumption. The Morpheus reaches
        presets through a Program Map, so this is the right answer only
        when nothing has remapped it. Callers that send it say so.
        """
        return self.number


def regions(kind: Optional[str] = None) -> List[Region]:
    return [r for r in REGIONS if kind is None or r.kind == kind]


def region(region_id: str) -> Region:
    try:
        return _BY_ID[region_id]
    except KeyError:
        raise LookupError(
            f"no region {region_id!r}; have {', '.join(r.id for r in REGIONS)}"
        ) from None


def region_ids(kind: Optional[str] = None) -> List[str]:
    return [r.id for r in regions(kind)]


def kinds_of() -> Tuple[str, ...]:
    return Kind.ALL


def slots(region_id: str) -> List[Slot]:
    entry = region(region_id)
    return [Slot(entry, entry.first + n) for n in range(entry.count)]


def slot(region_id: str, number: int) -> Slot:
    entry = region(region_id)
    if not 0 <= number < entry.count:
        raise LookupError(
            f"{entry.label} holds {entry.count}, so {number} is not one "
            f"of them"
        )
    return Slot(entry, entry.first + number)


def bank_of(kind: str, index: int) -> int:
    """Which bank an index falls in, for a bank request."""
    return index // Kind.PER_BANK[kind]


def bank_request(kind: str, bank: int, *, device: int = 0) -> bytes:
    """Ask for a whole bank of one kind."""
    if kind not in Kind.ALL:
        raise LookupError(f"no kind {kind!r}; have {', '.join(Kind.ALL)}")
    if kind == Kind.PRESET:
        # The one the tests pin; built in one place rather than two.
        return m.preset_bank_request(bank, device=device)
    number = m.BANK_REQUEST_BASE + bank
    return m.frame(
        Kind.REQUEST[kind],
        [number & 0x7F, (number >> 7) & 0x7F],
        device=device,
    )


def select_messages(target: Slot, channel: int = 0) -> List[bytes]:
    """Bank Select then Program Change, in the manual's own order.

    ``Bn 00 00 20 bb Cn pp``: Controller 0 set to zero, Controller 32 the
    bank, then the program change. Both controllers every time, because
    sending only the program change leaves the bank wherever it was --
    possibly somewhere a sequencer put it.

    Only presets can be reached this way. A midimap has no program
    number at all and a hyperpreset is selected as a preset in the
    hyperpreset bank, so this refuses anything else rather than sending
    a program change that would land somewhere unrelated.
    """
    if target.kind != Kind.PRESET:
        raise LookupError(
            f"a {target.kind} is not selected with a program change; only "
            f"presets are"
        )
    if not 0 <= channel <= 15:
        raise ValueError(f"channel {channel} is outside 0-15")
    bank = bank_of(Kind.PRESET, target.index)
    status = 0xB0 | channel
    return [
        bytes([status, 0x00, 0x00]),
        bytes([status, 0x20, bank]),
        bytes([0xC0 | channel, target.program_change]),
    ]
