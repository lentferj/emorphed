# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""The Midimap's own parameter table.

A ``Midimap`` (command ``0x47``) carries 360 fourteen-bit words: a twelve-
character name followed by twenty settings for each of sixteen channels and
a twenty-eight-word global tail. Each word has its own meaning, printed as
the ``Midimap Data`` table on pages 232-233 of the E-mu Morpheus Operator's
Manual (1993). Those meanings are transcribed here as :data:`PARAMS`, and
checked against the parameter list in the sibling edisyn project
(``EmuMorpheusMap.java``, ``parameters`` array, 360 entries).

The parameter IDs a unit answers for these are ``PARAM_BASE`` (2048) through
``PARAM_BASE + 359`` (2407), printed on page 250 as "Midimap Vers. 1 Parms".
A parameter *write* reaches the **scratch** midimap (manual p.232 says a
map loaded into the current location is loaded into the scratch map, and
permanence needs a store). This module is the read/parse/display side only;
it does not write to the instrument.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from emu import messages as m

__all__ = [
    "PARAMS",
    "PARAM_BASE",
    "Param",
    "offset_of",
    "param_at",
    "parse_dump",
    "spell",
]


_PARAM_MANUAL = "Morpheus Operation Manual p.232-233, Midimap Data"

_NAME_WORDS = m.NAME_CHARS
_ASCII_FIRST = 32
_ASCII_LAST = 128


@dataclass(frozen=True)
class Param:
    """One Midimap parameter word, as the manual documents it.

    ``offset`` is the word's position (0-359) in a midimap body.
    ``low`` and ``high`` are inclusive, in the **signed** values the wire
    uses. ``choices`` names the enumerated values in the unit's own order;
    empty means a plain integer range. ``note`` carries what the manual
    says that does not fit in the range.
    """

    offset: int
    label: str
    low: int
    high: int
    choices: tuple[str, ...] = ()
    note: str = ""


_PROGRAM_BANKS: tuple[str, ...] = (
    "RAM Presets",
    "ROM Presets",
    "RAM Hypers",
    "Card Presets",
    "Card Hypers",
)

_MIX_BUS: tuple[str, ...] = (
    "Preset",
    "Main",
    "Sub1",
    "FX A",
    "FX B",
)

_OFF_ON: tuple[str, ...] = ("Off", "On")

_FX_BUS: tuple[str, ...] = ("Main", "Sub1", "Sub2")

_PAN: tuple[str, ...] = (
    "Preset",
    "-7",
    "-6",
    "-5",
    "-4",
    "-3",
    "-2",
    "-1",
    "0",
    "+1",
    "+2",
    "+3",
    "+4",
    "+5",
    "+6",
    "+7",
)


_CHANNEL_BLOCK: tuple[tuple[str, int, int, tuple[str, ...]], ...] = (
    ("Ch. Program", 0, 127, ()),
    ("Ch. Bank", 0, 4, _PROGRAM_BANKS),
    ("Ch. Volume", 0, 127, ()),
    ("Ch. Pan", -8, 7, _PAN),
    ("Ch. Mix Bus", -1, 3, _MIX_BUS),
    ("Ch. Enable", 0, 1, _OFF_ON),
    ("Ch. ProgChg Enbl", 0, 1, _OFF_ON),
    ("Ch. BankChg Enbl", 0, 1, _OFF_ON),
    ("Ch. VolCtl Enbl", 0, 1, _OFF_ON),
    ("Ch. PanCtl Enbl", 0, 1, _OFF_ON),
    ("Ch. PWhl Enbl", 0, 1, _OFF_ON),
    ("Ch. MPress Enbl", 0, 1, _OFF_ON),
    ("Ch. PPress Enbl", 0, 1, _OFF_ON),
    ("Ch. Ctl. A Enbl", 0, 1, _OFF_ON),
    ("Ch. Ctl. B Enbl", 0, 1, _OFF_ON),
    ("Ch. Ctl. C Enbl", 0, 1, _OFF_ON),
    ("Ch. Ctl. D Enbl", 0, 1, _OFF_ON),
    ("Ch. Ftsw. 1 Enbl", 0, 1, _OFF_ON),
    ("Ch. Ftsw. 2 Enbl", 0, 1, _OFF_ON),
    ("Ch. Ftsw. 3 Enbl", 0, 1, _OFF_ON),
)

_PROG_MAP_CHOICES: tuple[str, ...] = ("None", "0", "1", "2", "3")


_entries: list[Param] = []

# The name block: twelve ASCII characters, offsets 0-11. Each word carries
# one character (ASCII 32-127); see emu.messages.decode_name for the block as
# text. The manual prints this as a single row starting at offset 0.
for _i in range(12):
    _entries.append(
        Param(
            _i,
            "Midimap Name",
            32,
            127,
            (),
            _PARAM_MANUAL + "; char " + str(_i + 1) + " of 12",
        )
    )

# Sixteen identical channel blocks of twenty words, stride 20, starting at
# offset 12. The manual marks the block "... for 16 channels (20 parms each)".
for _channel in range(16):
    _base = 12 + _channel * 20
    for _index, (_label, _low, _high, _choices) in enumerate(_CHANNEL_BLOCK):
        _entries.append(
            Param(
                _base + _index,
                _label,
                _low,
                _high,
                _choices,
                _PARAM_MANUAL,
            )
        )

# Global tail, offsets 332-359.
_entries.append(
    Param(332, "Prog Map", -1, 3, _PROG_MAP_CHOICES, _PARAM_MANUAL)
)
_entries.append(
    Param(
        333,
        "FX A Type",
        0,
        16383,
        (),
        _PARAM_MANUAL + "; effect IDs are not indices (EFFECT LIST)",
    )
)
for _i in range(10):
    _entries.append(
        Param(
            334 + _i,
            "FX A Parm Vals",
            -8192,
            8191,
            (),
            _PARAM_MANUAL + "; one of ten effect parameter words",
        )
    )
_entries.append(
    Param(
        344,
        "FX B Type",
        0,
        16383,
        (),
        _PARAM_MANUAL + "; effect IDs are not indices (EFFECT LIST)",
    )
)
for _i in range(10):
    _entries.append(
        Param(
            345 + _i,
            "FX B Parm Vals",
            -8192,
            8191,
            (),
            _PARAM_MANUAL + "; one of ten effect parameter words",
        )
    )
_entries.append(Param(355, "FX A Amt", 0, 100, (), _PARAM_MANUAL))
_entries.append(Param(356, "FX B Amt", 0, 100, (), _PARAM_MANUAL))
_entries.append(
    Param(
        357,
        "B->A Amt",
        0,
        101,
        (),
        _PARAM_MANUAL + "; 101 = B->A only",
    )
)
_entries.append(Param(358, "FX A Bus", 0, 2, _FX_BUS, _PARAM_MANUAL))
_entries.append(Param(359, "FX B Bus", 0, 2, _FX_BUS, _PARAM_MANUAL))

PARAMS: tuple[Param, ...] = tuple(_entries)

#: Base parameter number for the whole Midimap block (manual p.250).
PARAM_BASE = 2048

_BY_OFFSET: dict[int, Param] = {param.offset: param for param in PARAMS}


def param_at(offset: int) -> Param:
    """The Param at ``offset`` (0-359)."""
    try:
        return _BY_OFFSET[offset]
    except KeyError as exc:
        raise ValueError(f"no midimap parameter at offset {offset}") from exc


def offset_of(label: str) -> int:
    """First offset whose label equals ``label``.

    Labels repeat once per channel, so the first is the RAM channel one.
    """
    for param in PARAMS:
        if param.label == label:
            return param.offset
    raise KeyError(label)


def parse_dump(words: Sequence[int]) -> dict[int, int]:
    """Map a 360-word midimap body to ``offset -> value``.

    The caller hands over the words of a command ``0x47`` reply (see
    :attr:`emu.messages.MIDIMAP_DATA_BYTES`); a body shorter than 360
    words is refused, since it is either a different message or a transfer
    cut short. Values are kept as the signed/unsigned words as they arrived
    -- see :func:`emu.messages.signed` for the conversion.
    """
    if len(words) < len(PARAMS):
        raise ValueError(f"a midimap body is 360 words; got {len(words)}")
    return {index: words[index] for index in range(len(PARAMS))}


def spell(param: Param, value: int) -> str:
    """How to say a parameter value out loud.

    Enumerations are spelled with their own names, signed ranges keep
    their sign, name characters come back as text and plain ranges are
    just the number.
    """
    signed_value = m.signed(value)
    if param.offset < _NAME_WORDS:
        if _ASCII_FIRST <= signed_value < _ASCII_LAST:
            return chr(signed_value)
        return "?"
    if param.choices:
        index = signed_value - param.low
        if 0 <= index < len(param.choices):
            return param.choices[index]
    return str(signed_value)
