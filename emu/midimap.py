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
the ``Midimap Data`` table on pages 233-234 of the E-mu Morpheus Operation
Manual (1993). Those meanings are transcribed here as :data:`PARAMS`, and
checked against the parameter list in the sibling edisyn project
(``EmuMorpheusMap.java``, ``parameters`` array, 360 entries).

The parameter IDs a unit answers for these are ``PARAM_BASE`` (2048) through
``PARAM_BASE + 359`` (2407), printed on page 250 as "Midimap Vers. 1 Parms".
A parameter *write* reaches the **scratch** midimap (manual p.233 says a
map loaded into the current location is loaded into the scratch map, and
permanence needs a store). This module is the read/parse/display side only;
it does not write to the instrument.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from emu import messages as m

__all__ = [
    "CHANNEL_BANKS",
    "DEFAULT_WORDS",
    "FX_PARAMS",
    "PARAMS",
    "PARAM_BASE",
    "Param",
    "channel_bank",
    "channel_bank_offset",
    "channel_program_offset",
    "choices_for",
    "fx_params",
    "fx_params_for",
    "name_of",
    "offset_of",
    "param_at",
    "parse_dump",
    "set_name",
    "spell",
    "step_channel_preset",
    "values_for",
]


_PARAM_MANUAL = "Morpheus Operation Manual pp. 233-234, Midimap Data"

_NAME_WORDS = m.NAME_CHARS
_ASCII_FIRST = 32
_ASCII_LAST = 128


@dataclass(frozen=True)
class Param:
    """One Midimap parameter word, as the manual documents it.

    ``offset`` is the word's position (0-359) in a midimap body.
    ``low`` and ``high`` are inclusive, in the **signed** values the wire
    uses. ``choices`` names the enumerated values in the unit's own order;
    empty means a plain integer range. ``values`` is the wire value each entry
    of ``choices`` stands for, in the same order; empty means the choices are
    the contiguous integers ``low..high``. The manual is explicit (p.242,
    "Effect Types"): "The effect type number sent via SysEx are unique IDs.
    (they are not the index into the screens). Note that the A and B effect
    IDs do not overlap." ``note`` carries what the manual says that does not
    fit in the range.
    """

    offset: int
    label: str
    low: int
    high: int
    choices: tuple[str, ...] = ()
    values: tuple[int, ...] = ()
    note: str = ""


_PROGRAM_BANKS: tuple[str, ...] = (
    "RAM Presets",
    "ROM Presets",
    "RAM Hypers",
    "Card Presets",
    "Card Hypers",
)

#: The region each channel ``Ch. Bank`` word names, in word order.
#: Transcribed from the ``Ch. Bank`` row of the Midimap Data table (manual
#: p.232, offset ``base+1``, "0-4", whose choices are :data:`_PROGRAM_BANKS`):
#: 0 RAM Presets, 1 ROM Presets, 2 RAM Hypers, 3 Card Presets, 4 Card Hypers.
#: The ids are the region ids of :data:`emu.banks.REGIONS`.
CHANNEL_BANKS: tuple[str, ...] = (
    "P-RAM",
    "P-ROM",
    "H-RAM",
    "P-CARD",
    "H-CARD",
)

# The channel block geometry: sixteen blocks of twenty words from offset 12
# (manual p.232, "... for 16 channels (20 parms each)"; see _CHANNEL_BLOCK).
_CHANNELS_PER_MIDIMAP = 16
_CHANNEL_STRIDE = 20
_CHANNEL_FIRST_OFFSET = 12

#: Presets in one preset bank; the eight-bit width a ``Ch. Program`` word has.
_PRESETS_PER_BANK = 128

#: The combined-index range the five preset banks span (0-639).
_COMBINED_PRESETS = len(CHANNEL_BANKS) * _PRESETS_PER_BANK

_MIX_BUS: tuple[str, ...] = (
    "Preset",
    "Main",
    "Sub1",
    "FX A",
    "FX B",
)

_OFF_ON: tuple[str, ...] = ("Off", "On")

_FX_BUS: tuple[str, ...] = ("Main", "Sub1", "Sub2")

# Effect type names as the manual lists them (effects section, pp. 42 and 53):
# "A" effects (p. 42) include the reverbs and the rest; "B" effects (p. 53)
# are the B processor's own set. "No Effect" is the first entry of each, the
# silent/empty processor. The manual's grouped shorthand (Small Rooms 1 & 2,
# Halls 1, 2 & 3, ...) expands to the individual effect types the unit
# enumerates; the names and their order follow the manual's lists.
_FX_A_NAMES: tuple[str, ...] = (
    "No Effect",
    "Room",
    "Warm Room",
    "Small Room 1",
    "Small Room 2",
    "Hall 1",
    "Hall 2",
    "Hall 3",
    "Chamber 1",
    "Chamber 2",
    "Plate 1",
    "Plate 2",
    "Early Reflections 1",
    "Early Reflections 2",
    "Early Reflections 3",
    "Early Reflections 4",
    "Reverse Early Reflections",
    "Rain",
    "Shimmer",
    "Stereo Flanger",
    "Phaser",
    "Stereo Chorus",
    "Delay",
    "Cross Delay",
    "Echo",
)

_FX_B_NAMES: tuple[str, ...] = (
    "No Effect",
    "Fuzz",
    "Fuzz Lite",
    "Stereo Flanger",
    "Phaser",
    "Stereo Chorus",
    "Delay",
    "Cross Delay",
    "Ring Modulate",
)

# A-effect parameter ranges, transcribed from the effect programming instruc-
# tions (manual pp. 42-52): (label, low, high, choices). Choices stay empty
# for every effect parameter (none of them is enumerated on the wire).
_FX_A_PARAMS: tuple[tuple[tuple[str, int, int, tuple[str, ...]], ...], ...] = (
    (),  # No Effect
    (("Decay Time", 50, 250, ()),),  # Room
    (("Decay Time", 50, 250, ()),),  # Warm Room
    (("Decay Time", 10, 128, ()),),  # Small Room 1
    (("Decay Time", 10, 128, ()),),  # Small Room 2
    (("Decay Time", 100, 255, ()),),  # Hall 1
    (("Decay Time", 100, 255, ()),),  # Hall 2
    (("Decay Time", 100, 255, ()),),  # Hall 3
    (("Decay Time", 50, 200, ()),),  # Chamber 1
    (("Decay Time", 50, 200, ()),),  # Chamber 2
    (("Decay Time", 80, 200, ()),),  # Plate 1
    (("Decay Time", 80, 250, ()),),  # Plate 2
    (("Ambience", 0, 100, ()),),  # Early Reflections 1
    (("Ambience", 0, 100, ()),),  # Early Reflections 2
    (("Ambience", 0, 100, ()),),  # Early Reflections 3
    (("Ambience", 0, 100, ()),),  # Early Reflections 4
    (("Ambience", 0, 100, ()),),  # Reverse Early Reflections
    (("Decay Time", 100, 255, ()),),  # Rain
    (("Decay Time", 50, 250, ()),),  # Shimmer
    (  # Stereo Flanger
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Delay", 1, 255, ()),
        ("Feedback", -127, 127, ()),
    ),
    (  # Phaser
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Freq", 1, 255, ()),
        ("Feedback", 0, 127, ()),
    ),
    (  # Stereo Chorus
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Delay", 1, 255, ()),
        ("Feedback", -127, 127, ()),
    ),
    (  # Delay
        ("L Delay Time", 1, 255, ()),
        ("L Tap Level", 0, 127, ()),
        ("R Delay Time", 1, 255, ()),
        ("R Tap Level", 0, 127, ()),
    ),
    (  # Cross Delay
        ("R Delay Time", 1, 255, ()),
        ("R Tap Level", 0, 127, ()),
        ("L Delay Time", 1, 255, ()),
        ("L Tap Level", 0, 127, ()),
    ),
    (  # Echo
        ("L Delay Time", 1, 255, ()),
        ("L Tap Level", 0, 127, ()),
        ("R Delay Time", 0, 255, ()),
        ("R Tap Level", 0, 127, ()),
        ("Feedback", 0, 255, ()),
    ),
)

_FX_B_PARAMS: tuple[tuple[tuple[str, int, int, tuple[str, ...]], ...], ...] = (
    (),  # No Effect
    (  # Fuzz
        ("Input Filter", 0, 255, ()),
        ("Output Filter", 0, 255, ()),
        ("Output Volume", 0, 127, ()),
    ),
    (  # Fuzz Lite
        ("Input Filter", 0, 255, ()),
        ("Output Filter", 0, 255, ()),
    ),
    (  # Stereo Flanger
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Delay", 1, 255, ()),
        ("Feedback", -127, 127, ()),
    ),
    (  # Phaser
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Freq", 1, 255, ()),
        ("Feedback", 0, 127, ()),
    ),
    (  # Stereo Chorus
        ("LFO Rate", 0, 255, ()),
        ("LFO Depth", 0, 255, ()),
        ("Min Delay", 1, 255, ()),
        ("Feedback", -127, 127, ()),
    ),
    (  # Delay
        ("L Delay Time", 1, 255, ()),
        ("L Tap Level", 0, 127, ()),
        ("R Delay Time", 1, 255, ()),
        ("R Tap Level", 0, 127, ()),
    ),
    (  # Cross Delay
        ("R Delay Time", 1, 255, ()),
        ("R Tap Level", 0, 127, ()),
        ("L Delay Time", 1, 255, ()),
        ("L Tap Level", 0, 127, ()),
    ),
    (),  # Ring Modulate: manual names no parameters
)

# The wire effect IDs (from the EFFECT LIST) that the unit actually stores for
# each UI index, kept here as facts for interpreting a stored midimap.
_FX_A_IDS: tuple[int, ...] = (
    0,
    1,
    2,
    16,
    17,
    7,
    8,
    18,
    5,
    6,
    3,
    4,
    19,
    20,
    21,
    22,
    24,
    23,
    25,
    11,
    13,
    12,
    9,
    10,
    14,
)

_FX_B_IDS: tuple[int, ...] = (128, 132, 138, 130, 133, 131, 134, 135, 129)

_FX_PARAM_FALLBACK: tuple[tuple[str, int, int, tuple[str, ...]], ...] = (
    ("Parm 1", -8192, 8191, ()),
)

FX_PARAMS: dict[object, tuple[tuple[str, int, int, tuple[str, ...]], ...]] = {}


def _register_fx_params_by_id(
    ids: Sequence[int],
    params: Sequence[Sequence[tuple[str, int, int, tuple[str, ...]]]],
) -> None:
    # Key by the unit's unique effect ID, NOT by screen index. A and B IDs
    # do not overlap, so a single dictionary keyed on the ID is unambiguous.
    for fx_id, param_tuple in zip(ids, params, strict=True):
        table = tuple(param_tuple)
        if not table:
            # Effects the manual gives no parameters ("No Effect", "Ring
            # Modulate") fall back to the honest generic parameter rather
            # than inventing names.
            table = _FX_PARAM_FALLBACK
        FX_PARAMS[fx_id] = table


_register_fx_params_by_id(_FX_A_IDS, _FX_A_PARAMS)
_register_fx_params_by_id(_FX_B_IDS, _FX_B_PARAMS)


def fx_params_for(
    type_value: int,
) -> tuple[tuple[str, int, int, tuple[str, ...]], ...]:
    "Parameters the given effect type defines, keyed by its unique ID."
    try:
        key = int(type_value)
    except (TypeError, ValueError):
        key = type_value
    if key in FX_PARAMS:
        return FX_PARAMS[key]
    return _FX_PARAM_FALLBACK


# Backwards-compatible thin alias: earlier callers (and tests) used this name.
# It no longer interprets an integer as a screen index; string names are still
# resolved to their unique effect id.
def fx_params(
    type_value: object,
) -> tuple[tuple[str, int, int, tuple[str, ...]], ...]:
    if isinstance(type_value, str):
        for ids, names in (
            (_FX_A_IDS, _FX_A_NAMES),
            (_FX_B_IDS, _FX_B_NAMES),
        ):
            if type_value in names:
                type_value = ids[names.index(type_value)]
    return fx_params_for(type_value)  # type: ignore[arg-type]


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


def _channel_base(channel: int) -> int:
    # Channel n (1..16) occupies the twenty words at 12 + (n-1)*20 .. +19
    # (manual p.232, "for 16 channels (20 parms each)"; see _CHANNEL_BLOCK).
    if not 1 <= channel <= _CHANNELS_PER_MIDIMAP:
        raise ValueError(
            f"channel {channel} is outside 1-{_CHANNELS_PER_MIDIMAP}"
        )
    return _CHANNEL_FIRST_OFFSET + (channel - 1) * _CHANNEL_STRIDE


def channel_program_offset(channel: int) -> int:
    """The midimap offset of ``channel``'s ``Ch. Program`` word.

    Channel ``n`` (1..16) occupies ``base .. base+19``, where
    ``base = 12 + (n-1)*20`` (manual p.232, "... for 16 channels (20 parms
    each)"; see :data:`_CHANNEL_BLOCK`). ``Ch. Program`` is the block's
    first word, ``base+0`` (0-127, the slot number). A channel outside
    1-16 is refused with a message naming the range.
    """
    return _channel_base(channel)


def channel_bank_offset(channel: int) -> int:
    """The midimap offset of ``channel``'s ``Ch. Bank`` word.

    That is ``base+1`` of the channel block whose ``base`` is
    :func:`channel_program_offset` returns; the word is the bank number
    0-4 (manual p.232, ``Ch. Bank`` "0-4"). A channel outside 1-16 is
    refused with a message naming the range.
    """
    return _channel_base(channel) + 1


def channel_bank(bank: int) -> str:
    """The region id a channel's ``Ch. Bank`` word (0-4) names.

    The five words name, in order, RAM Presets, ROM Presets, RAM Hypers,
    Card Presets and Card Hypers (manual p.232, ``Ch. Bank`` "0-4"; the
    same order as :data:`_PROGRAM_BANKS`). They are the region ids
    ``P-RAM``, ``P-ROM``, ``H-RAM``, ``P-CARD`` and ``H-CARD`` of
    :data:`emu.banks.REGIONS`. A word outside 0-4 is refused with a
    message naming the range.
    """
    if not 0 <= bank < len(CHANNEL_BANKS):
        raise ValueError(
            f"bank word {bank} is outside 0-{len(CHANNEL_BANKS) - 1}"
        )
    return CHANNEL_BANKS[bank]


def step_channel_preset(bank: int, number: int, delta: int) -> tuple[int, int]:
    """Step a channel's preset by ``delta``, rolling between banks.

    A channel's preset is the pair ``(bank, number)``: the ``Ch. Bank``
    word 0-4 (see :func:`channel_bank`) and the ``Ch. Program`` number
    0-127. Their combined index is ``bank*128 + number`` (0-639), the
    single number ``+`` and ``-`` walk. The program word is eight bits, so
    ``+`` at ``bank 1 / 127`` rolls into ``bank 2 / 0`` and ``-`` at
    ``bank 2 / 0`` rolls back to ``bank 1 / 127``. The combined index is
    clamped to ``0..639``, so the ends do not wrap past ``bank 4 / 127`` or
    below ``bank 0 / 0``. A bank outside 0-4 or a number outside 0-127 is
    refused with a message naming the range.
    """
    # Refuse through the same checks the pair helpers use.
    channel_bank(bank)
    if not 0 <= number < _PRESETS_PER_BANK:
        raise ValueError(f"preset number {number} is outside 0-127")
    combined = bank * _PRESETS_PER_BANK + number
    stepped = min(max(combined + delta, 0), _COMBINED_PRESETS - 1)
    return divmod(stepped, _PRESETS_PER_BANK)


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
                (),
                _PARAM_MANUAL,
            )
        )

# Global tail, offsets 332-359.
_entries.append(
    Param(332, "Prog Map", -1, 3, _PROG_MAP_CHOICES, (), _PARAM_MANUAL)
)
_entries.append(
    Param(
        333,
        "FX A Type",
        0,
        25,
        _FX_A_NAMES,
        _FX_A_IDS,
        _PARAM_MANUAL
        + "; EFFECTS TYPES (manual pp. 41-52; unique IDs manual p.242): "
        + '"The effect type number sent via SysEx are unique IDs. '
        + "(they are not the index into the screens). Note that the A and B "
        + 'effect IDs do not overlap." '
        + "base 0 = No Effect (manual's first A type is Room at 1)",
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
            (),
            _PARAM_MANUAL
            + "; one of ten effect parameter words "
            + "(see fx_params for the selected type)",
        )
    )
_entries.append(
    Param(
        344,
        "FX B Type",
        128,
        138,
        _FX_B_NAMES,
        _FX_B_IDS,
        _PARAM_MANUAL
        + "; EFFECT TYPES (manual p. 53; unique IDs manual p.242): "
        + '"The effect type number sent via SysEx are unique IDs. '
        + "(they are not the index into the screens). Note that the A and B "
        + 'effect IDs do not overlap." '
        + "base 0 = No Effect (IDs start at 128)",
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
            (),
            _PARAM_MANUAL + "; one of ten effect parameter words",
        )
    )
_entries.append(Param(355, "FX A Amt", 0, 100, (), (), _PARAM_MANUAL))
_entries.append(Param(356, "FX B Amt", 0, 100, (), (), _PARAM_MANUAL))
_entries.append(
    Param(
        357,
        "B->A Amt",
        0,
        101,
        (),
        (),
        _PARAM_MANUAL + "; 101 = B->A only",
    )
)
_entries.append(Param(358, "FX A Bus", 0, 2, _FX_BUS, (), _PARAM_MANUAL))
_entries.append(Param(359, "FX B Bus", 0, 2, _FX_BUS, (), _PARAM_MANUAL))

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
        if param.values:
            try:
                index = param.values.index(signed_value)
            except ValueError:
                index = -1
        else:
            index = signed_value - param.low
        if 0 <= index < len(param.choices):
            return param.choices[index]
    return str(signed_value)


def choices_for(param: Param) -> tuple[tuple[int, str], ...]:
    """Legal ``(value, label)`` pairs for a choices parameter.

    Returned in the manual's **screen order** (the order ``param.choices``
    holds), because that is the order the picker shows the entries; the
    underlying wire value may be non-contiguous and out of numeric order
    (manual p.242: effect type numbers are unique IDs, not screen indices).
    """
    if param.values:
        return tuple(
            (value, label)
            for value, label in zip(param.values, param.choices, strict=True)
        )
    return tuple(
        (param.low + index, label) for index, label in enumerate(param.choices)
    )


def values_for(param: Param) -> tuple[int, ...]:
    """The legal values of ``param``.

    For a ``values``-bearing choices parameter these are the unique IDs;
    otherwise the contiguous integers ``param.low..param.high``.
    """
    if param.values:
        return param.values
    return tuple(range(param.low, param.high + 1))


def name_of(words: Sequence[int]) -> str:
    """The twelve-character Midimap name held in ``words``' first twelve."""
    return m.decode_name(words)


_ASCII_SPACE = 32


def set_name(words: Sequence[int], text: str) -> list[int]:
    """Return a NEW word list with the first twelve words spelling ``text``.

    ``text`` is padded with spaces or truncated to twelve characters. Every
    character must lie in ASCII 32-127; a character outside that range is
    refused with a message naming the range. The input is never mutated.
    """
    if len(text) > _NAME_WORDS:
        text = text[:_NAME_WORDS]
    padded = text.ljust(_NAME_WORDS)
    # Validate every character before touching the copy.
    for char in padded:
        code = ord(char)
        if code < _ASCII_FIRST or code >= _ASCII_LAST:
            raise ValueError(f"{char!r} is outside ASCII 32-127")
    new = list(words)
    if len(new) < _NAME_WORDS:
        new.extend([_ASCII_SPACE] * (_NAME_WORDS - len(new)))
    for index, char in enumerate(padded):
        new[index] = ord(char)
    return new


#: The factory-default midimap's 360 words, captured from the unit's
#: internal ("RAM") midimap named ``Dry`` on 2026-10-18 (read_midimap(2);
#: indices 2 and 5-15 are the same map). ``DEL`` writes these values.
#: The twelve name characters are the unit's own ("Dry"), kept deliberately
#: -- see CLAUDE.md, "E-mu's content is not ours to redistribute".
DEFAULT_WORDS: tuple[int, ...] = (
    68,
    114,
    121,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    32,
    0,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    2,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    3,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    4,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    5,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    6,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    7,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    8,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    9,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    10,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    11,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    12,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    13,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    14,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    15,
    0,
    127,
    16376,
    16383,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    16383,
    0,
    0,
    0,
    102,
    48,
    0,
    16280,
    0,
    16288,
    0,
    33,
    128,
    0,
    0,
    1,
    16280,
    0,
    16264,
    0,
    0,
    16336,
    0,
    50,
    50,
    0,
    0,
    0,
)
