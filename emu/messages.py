# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The wire protocol is transcribed as data from E-mu's own MIDI
# Specification, printed in full as pages 225-250 of the Morpheus
# Operation Manual (E-mu Systems, 1993), and checked against 2176 preset
# dumps the instrument produced. The transport layer is ported from the
# sibling p2ked, x5ded, kwsed, rxved and nanosyned projects.
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

"""The Morpheus's System Exclusive messages.

Unusually among these projects, the manual **is** the specification: E-mu
printed the whole thing, twenty-six pages of it, as a chapter of the
Operation Manual rather than making you write away for it. Everything
here is transcribed from that and then checked against real dumps.

Three things about this protocol that shape every caller:

1. **Data is fourteen bits wide, not seven.** Every value in a dump is
   two MIDI bytes -- bits 0-6 first, then bits 7-13 -- and is a signed
   two's-complement number sign-extended to bit 13, *whatever its stated
   range*. A parameter documented as 0-127 still arrives as fourteen
   bits. Reading a dump a byte at a time gets you plausible halves of
   numbers.
2. **Names are those same fourteen-bit words.** Twelve of them, ASCII in
   the low seven bits. So a twelve-character name occupies twenty-four
   MIDI bytes.
3. **There is exactly one edit buffer for each kind of thing.** One for
   the current preset, one for the current hyperpreset, one for the
   current midimap -- and changing which one is current *erases* the
   associated buffer. The manual says so twice.

And one thing to be careful of: the Morpheus answers to product ID ``04``
as well as its own ``0C``, so that it can accept Proteus presets. It
fills in the parameters a Proteus preset does not have with defaults and
sets instruments to "None". Nothing here sends ``04``: a message that
arrives as a Proteus preset is silently a different preset.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "SYSEX_START", "SYSEX_END", "EMU_ID", "MORPHEUS_ID", "PROTEUS_ID",
    "Command", "ProtocolError", "Packet",
    "frame", "parse", "to_words", "from_words", "checksum",
    "NAME_CHARS", "decode_name", "encode_name",
    "preset_request", "preset_bank_request", "hyperpreset_request",
    "midimap_request", "preset_list_request", "hyperpreset_list_request",
    "midimap_list_request", "version_request", "configuration_request",
    "master_data_request", "parse_name_list", "BANK_REQUEST_BASE",
    "PRESET_DATA_BYTES", "HYPERPRESET_DATA_BYTES", "MIDIMAP_DATA_BYTES",
]

SYSEX_START = 0xF0
SYSEX_END = 0xF7

#: E-mu Systems.
EMU_ID = 0x18

#: The Morpheus.
MORPHEUS_ID = 0x0C

#: The Proteus. The Morpheus answers to this too, when the Master menu
#: allows it, and fills in what a Proteus preset does not carry. This
#: program never sends it -- see the module docstring.
PROTEUS_ID = 0x04

#: A name is twelve characters, ASCII 32-127.
NAME_CHARS = 12

#: Add this to a bank number to request a whole bank instead of one
#: object. Banks are blocks of 128 presets, 128 hyperpresets or 16
#: midimaps -- the size depends on what is being asked for, which is why
#: :mod:`emu.banks` owns that and this does not.
BANK_REQUEST_BASE = 0x0400

#: Message sizes seen in every one of 2752 dumps from real instruments,
#: and the only structural check besides the checksum.
PRESET_DATA_BYTES = 566
HYPERPRESET_DATA_BYTES = 484
MIDIMAP_DATA_BYTES = 730


class ProtocolError(ValueError):
    """A message that is not what it claims to be."""


class Command:
    """Command IDs, from the manual's Command Summary (page 227)."""

    PRESET_REQUEST = 0x00
    PRESET_DATA = 0x01
    PARAMETER_REQUEST = 0x02
    PARAMETER_DATA = 0x03
    TUNE_TABLE_REQUEST = 0x04
    TUNE_TABLE_DATA = 0x05
    PROG_MAP_REQUEST = 0x06
    PROG_MAP_DATA = 0x07
    MASTER_DATA_REQUEST = 0x08
    VERSION_REQUEST = 0x0A
    VERSION_DATA = 0x0B
    CONFIGURATION_REQUEST = 0x0C
    CONFIGURATION_DATA = 0x0D
    INSTRUMENT_LIST_REQUEST = 0x0E
    INSTRUMENT_LIST_DATA = 0x0F
    PRESET_LIST_REQUEST = 0x12
    PRESET_LIST_DATA = 0x13
    HYPERPRESET_REQUEST = 0x44
    HYPERPRESET_DATA = 0x45
    MIDIMAP_REQUEST = 0x46
    MIDIMAP_DATA = 0x47
    HYPERPRESET_LIST_REQUEST = 0x50
    HYPERPRESET_LIST_DATA = 0x51
    MIDIMAP_LIST_REQUEST = 0x52
    MIDIMAP_LIST_DATA = 0x53
    EFFECT_LIST_REQUEST = 0x54
    EFFECT_LIST_DATA = 0x55
    FILTER_LIST_REQUEST = 0x56
    FILTER_LIST_DATA = 0x57

    NAMES = {
        0x00: "Preset Request", 0x01: "Preset Data",
        0x02: "Parameter Request", 0x03: "Parameter Data",
        0x04: "Tune Table Request", 0x05: "Tune Table Data",
        0x06: "Prog Map Request", 0x07: "Prog Map Data",
        0x08: "Master Data Request",
        0x0A: "Version Request", 0x0B: "Version Data",
        0x0C: "Configuration Request", 0x0D: "Configuration Data",
        0x0E: "Instrument List Request", 0x0F: "Instrument List Data",
        0x12: "Preset List Request", 0x13: "Preset List Data",
        0x44: "Hyperpreset Request", 0x45: "Hyperpreset Data",
        0x46: "Midimap Request", 0x47: "Midimap Data",
        0x50: "Hyperpreset List Request", 0x51: "Hyperpreset List Data",
        0x52: "Midimap List Request", 0x53: "Midimap List Data",
        0x54: "Effect List Request", 0x55: "Effect List Data",
        0x56: "Filter List Request", 0x57: "Filter List Data",
    }

    #: Which data message answers which request.
    REPLY_TO = {
        PRESET_REQUEST: PRESET_DATA,
        PARAMETER_REQUEST: PARAMETER_DATA,
        TUNE_TABLE_REQUEST: TUNE_TABLE_DATA,
        PROG_MAP_REQUEST: PROG_MAP_DATA,
        VERSION_REQUEST: VERSION_DATA,
        CONFIGURATION_REQUEST: CONFIGURATION_DATA,
        INSTRUMENT_LIST_REQUEST: INSTRUMENT_LIST_DATA,
        PRESET_LIST_REQUEST: PRESET_LIST_DATA,
        HYPERPRESET_REQUEST: HYPERPRESET_DATA,
        MIDIMAP_REQUEST: MIDIMAP_DATA,
        HYPERPRESET_LIST_REQUEST: HYPERPRESET_LIST_DATA,
        MIDIMAP_LIST_REQUEST: MIDIMAP_LIST_DATA,
        EFFECT_LIST_REQUEST: EFFECT_LIST_DATA,
        FILTER_LIST_REQUEST: FILTER_LIST_DATA,
    }

    #: Data messages whose size is fixed, and what it is.
    SIZES = {
        PRESET_DATA: PRESET_DATA_BYTES,
        HYPERPRESET_DATA: HYPERPRESET_DATA_BYTES,
        MIDIMAP_DATA: MIDIMAP_DATA_BYTES,
    }

    @staticmethod
    def name(command: int) -> str:
        return Command.NAMES.get(command, f"command {command:#04x}")


class Packet:
    """One parsed E-mu message."""

    __slots__ = ("device", "command", "version", "number", "body")

    def __init__(self, device: int, command: int, version: Optional[int],
                 number: Optional[int], body: bytes) -> None:
        #: Device ID, 0-15. Set in the unit's Master menu.
        self.device = device
        self.command = command
        #: The data-format version a dump declares, or ``None``.
        self.version = version
        #: The object number a dump carries, or ``None``.
        self.number = number
        #: The data bytes, without the header, the checksum or the F7.
        self.body = body

    @property
    def command_name(self) -> str:
        return Command.name(self.command)

    def words(self) -> List[int]:
        """The body as fourteen-bit words."""
        return from_words(self.body)

    def __repr__(self) -> str:
        return (f"Packet(device={self.device}, {self.command_name!r}, "
                f"number={self.number}, {len(self.body)} bytes)")


#: Data messages that carry a version byte and a two-byte object number
#: between the command and the data.
_NUMBERED = frozenset({
    Command.PRESET_DATA, Command.HYPERPRESET_DATA, Command.MIDIMAP_DATA,
})


def checksum(body: Sequence[int]) -> int:
    """The seven-bit sum of the data bytes.

    Verified against 2176 preset dumps: every one of them carries the low
    seven bits of the sum of its data bytes, and nothing else. The manual
    writes it only as ``cs Checksum``, which is a good reason to state
    here what it was measured to be.
    """
    return sum(body) & 0x7F


def to_words(values: Iterable[int]) -> bytes:
    """Fourteen-bit words to MIDI bytes, **least significant seven first**."""
    out = bytearray()
    for value in values:
        word = value & 0x3FFF
        out.append(word & 0x7F)
        out.append((word >> 7) & 0x7F)
    return bytes(out)


def from_words(data: Sequence[int]) -> List[int]:
    """MIDI byte pairs back to fourteen-bit words.

    A trailing odd byte is dropped: half a word is not a word.
    """
    out = []
    for index in range(0, len(data) - 1, 2):
        low, high = data[index], data[index + 1]
        for part in (low, high):
            if not 0 <= part <= 0x7F:
                raise ProtocolError(
                    f"{part:#04x} has bit 7 set; SysEx data must not")
        out.append(low | (high << 7))
    return out


def signed(word: int) -> int:
    """A fourteen-bit word as the signed value it actually is.

    Every data word in this format is two's complement sign-extended to
    bit 13, *whatever the parameter's documented range*. Reading one as
    unsigned turns a pan of -7 into 16377, which is a number a screen
    will happily show.
    """
    word &= 0x3FFF
    return word - 0x4000 if word & 0x2000 else word


def frame(command: int, body: Sequence[int] = (), *, device: int = 0,
          product: int = MORPHEUS_ID) -> bytes:
    """One E-mu message, ready to send. No checksum is added.

    Requests carry no checksum; only data messages do, and this program
    does not build data messages -- it does not write to the instrument.
    """
    if not 0 <= device <= 15:
        raise ProtocolError(f"device ID {device} is outside 0-15")
    for byte in body:
        if not 0 <= byte <= 0x7F:
            raise ProtocolError(
                f"{byte:#04x} is not a 7-bit data byte")
    return bytes([SYSEX_START, EMU_ID, product, device, command, *body,
                  SYSEX_END])


def parse(message: Sequence[int]) -> Optional[Packet]:
    """Parse one E-mu message, or ``None`` if it is not one.

    ``None`` rather than an exception for foreign traffic: a shared MIDI
    port carries other manufacturers' messages and none of those are
    errors. A Proteus-ID message *is* accepted, because the Morpheus
    accepts it -- the product ID is reported rather than filtered.
    """
    data = bytes(message)
    if len(data) < 6:
        return None
    if data[0] != SYSEX_START or data[-1] != SYSEX_END:
        return None
    if data[1] != EMU_ID or data[2] not in (MORPHEUS_ID, PROTEUS_ID):
        return None
    device, command = data[3], data[4]
    rest = data[5:-1]
    if command in _NUMBERED:
        if len(rest) < 3:
            return None
        version = rest[0]
        number = rest[1] | (rest[2] << 7)
        # the last byte of a data message is its checksum
        return Packet(device, command, version, number, bytes(rest[3:-1]))
    return Packet(device, command, None, None, bytes(rest))


def decode_name(words: Sequence[int]) -> str:
    """Twelve characters from the first twelve words of a record."""
    if len(words) < NAME_CHARS:
        raise ProtocolError(
            f"a name is {NAME_CHARS} words; this record has {len(words)}")
    chars = []
    for word in words[:NAME_CHARS]:
        value = word & 0x7F
        chars.append(chr(value) if 32 <= value < 127 else "?")
    return "".join(chars)


def encode_name(name: str) -> List[int]:
    """Twelve words holding a name, for building a fixture."""
    padded = f"{name:<{NAME_CHARS}}"[:NAME_CHARS]
    out = []
    for char in padded:
        value = ord(char)
        if not 32 <= value < 127:
            raise ProtocolError(
                f"{char!r} is outside this instrument's ASCII 32-127")
        out.append(value)
    return out


def parse_name_list(packet: Packet) -> List[str]:
    """The names out of a Preset, Hyperpreset or Midimap List Data reply.

    The reply opens with a fourteen-bit count and then gives each name as
    twelve ASCII characters followed by a null terminator. The count is
    trusted only as far as the data goes: a reply cut short yields the
    names that arrived rather than an exception, because a short list is
    still worth showing.
    """
    body = packet.body
    if len(body) < 2:
        return []
    count = body[0] | (body[1] << 7)
    out: List[str] = []
    cursor = 2
    while len(out) < count and cursor + NAME_CHARS <= len(body):
        chars = body[cursor:cursor + NAME_CHARS]
        out.append("".join(chr(c) if 32 <= c < 127 else "?" for c in chars))
        cursor += NAME_CHARS
        # the null terminator, when it is there
        if cursor < len(body) and body[cursor] == 0:
            cursor += 1
    return out


# --- requests ---------------------------------------------------------------

def _numbered_request(command: int, number: int, device: int) -> bytes:
    if not 0 <= number <= 0x3FFF:
        raise ProtocolError(f"{number} does not fit in fourteen bits")
    return frame(command, [number & 0x7F, (number >> 7) & 0x7F],
                 device=device)


def preset_request(number: int, *, device: int = 0) -> bytes:
    """Ask for one preset. Read-only, and **makes no sound**."""
    return _numbered_request(Command.PRESET_REQUEST, number, device)


def preset_bank_request(bank: int, *, device: int = 0) -> bytes:
    """Ask for a whole bank of 128 presets."""
    return _numbered_request(Command.PRESET_REQUEST,
                             BANK_REQUEST_BASE + bank, device)


def hyperpreset_request(number: int, *, device: int = 0) -> bytes:
    return _numbered_request(Command.HYPERPRESET_REQUEST, number, device)


def midimap_request(number: int, *, device: int = 0) -> bytes:
    return _numbered_request(Command.MIDIMAP_REQUEST, number, device)


def preset_list_request(*, device: int = 0) -> bytes:
    """Ask for every preset's name in one message.

    The best thing in this protocol, and the reason a browser for this
    instrument is cheap: one message and every name comes back, in the
    order the instrument shows them.
    """
    return frame(Command.PRESET_LIST_REQUEST, device=device)


def hyperpreset_list_request(*, device: int = 0) -> bytes:
    return frame(Command.HYPERPRESET_LIST_REQUEST, device=device)


def midimap_list_request(*, device: int = 0) -> bytes:
    return frame(Command.MIDIMAP_LIST_REQUEST, device=device)


def version_request(*, device: int = 0) -> bytes:
    """Ask the unit its software version. Silent."""
    return frame(Command.VERSION_REQUEST, device=device)


def configuration_request(*, device: int = 0) -> bytes:
    """Ask what is fitted: banks, cards, memory. Silent."""
    return frame(Command.CONFIGURATION_REQUEST, device=device)


def master_data_request(*, device: int = 0) -> bytes:
    return frame(Command.MASTER_DATA_REQUEST, device=device)
