# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
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

"""Reading ``.syx`` files, and checking that what is in them is intact.

A Morpheus bank file is one message per object, back to back: 128 preset
dumps, or 128 hyperpresets, or 16 midimaps, or all of those in sequence.
Every one carries a checksum, so unlike most of the sibling instruments
this one can say whether a file is *damaged* rather than only whether it
is the right length.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emu import banks
from emu import messages as m

__all__ = ["Library", "read_bytes", "read_file", "split_sysex"]


@dataclass
class Library:
    """Whatever a file turned out to hold, by kind and number."""

    presets: dict[int, list[int]] = field(default_factory=dict)
    hyperpresets: dict[int, list[int]] = field(default_factory=dict)
    midimaps: dict[int, list[int]] = field(default_factory=dict)
    #: Dumps whose checksum did not match, by (kind, number). Kept rather
    #: than dropped: a caller may still want to look at one, and silence
    #: about a bad checksum would waste the only integrity check this
    #: format offers.
    corrupt: list[str] = field(default_factory=list)
    other: dict[int, int] = field(default_factory=dict)
    foreign: int = 0
    device: int | None = None
    #: True if any message arrived under the Proteus product ID.
    proteus_ids: int = 0

    def of(self, kind: str) -> dict[int, list[int]]:
        return {
            banks.Kind.PRESET: self.presets,
            banks.Kind.HYPERPRESET: self.hyperpresets,
            banks.Kind.MIDIMAP: self.midimaps,
        }[kind]

    def names(self, kind: str = banks.Kind.PRESET) -> dict[int, str]:
        out = {}
        for number, words in sorted(self.of(kind).items()):
            try:
                out[number] = m.decode_name(words)
            except m.ProtocolError:
                continue
        return out

    def summary(self) -> str:
        parts = []
        for kind in banks.Kind.ALL:
            held = self.of(kind)
            if held:
                parts.append(f"{len(held)} {kind}(s)")
        if self.device is not None:
            parts.append(f"device ID {self.device}")
        if self.proteus_ids:
            parts.append(f"{self.proteus_ids} under the Proteus product ID")
        if self.corrupt:
            parts.append(f"{len(self.corrupt)} FAILED CHECKSUM")
        if self.other:
            parts.append(
                ", ".join(
                    f"{n}x {m.Command.name(c)}"
                    for c, n in sorted(self.other.items())
                )
            )
        if self.foreign:
            parts.append(f"{self.foreign} foreign message(s)")
        return ", ".join(parts) or "nothing this program recognises"


def split_sysex(raw: bytes) -> list[bytes]:
    """Every complete SysEx message in a blob.

    A trailing ``F0`` with no ``F7`` is dropped: that is what a transfer
    cut short looks like, and the messages before it are still good.
    """
    out, cursor = [], 0
    while True:
        start = raw.find(b"\xf0", cursor)
        if start < 0:
            break
        end = raw.find(b"\xf7", start)
        if end < 0:
            break
        out.append(raw[start : end + 1])
        cursor = end + 1
    return out


_KIND_OF = {
    m.Command.PRESET_DATA: banks.Kind.PRESET,
    m.Command.HYPERPRESET_DATA: banks.Kind.HYPERPRESET,
    m.Command.MIDIMAP_DATA: banks.Kind.MIDIMAP,
}


def read_bytes(raw: bytes) -> Library:
    library = Library()
    for message in split_sysex(raw):
        packet = m.parse(message)
        if packet is None:
            library.foreign += 1
            continue
        if library.device is None:
            library.device = packet.device
        if message[2] == m.PROTEUS_ID:
            library.proteus_ids += 1
        kind = _KIND_OF.get(packet.command)
        if kind is None:
            library.other[packet.command] = (
                library.other.get(packet.command, 0) + 1
            )
            continue
        expected = m.Command.SIZES.get(packet.command)
        if expected is not None and len(message) != expected:
            library.corrupt.append(
                f"{kind} {packet.number}: {len(message)} bytes, not {expected}"
            )
            continue
        if m.checksum(packet.body) != message[-2]:
            library.corrupt.append(
                f"{kind} {packet.number}: checksum "
                f"{message[-2]:#04x}, computed "
                f"{m.checksum(packet.body):#04x}"
            )
            continue
        if packet.number is None:
            continue
        library.of(kind)[packet.number] = packet.words()
    return library


def read_file(path: str) -> Library:
    with open(path, "rb") as handle:
        return read_bytes(handle.read())
