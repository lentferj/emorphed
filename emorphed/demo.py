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

"""A Morpheus that is not there.

**Every name here is invented**, from a word pool chosen to be obviously
not E-mu's, so that a screenshot taken in demo mode cannot be mistaken
for a real machine's contents. It opens no MIDI port and constructs no
bridge, so it is safe beside a session driving hardware.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from emu import banks
from emu import messages as m
from emu import midimap as mm

__all__ = ["DemoDevice", "demo_name"]

#: Deliberately not anybody's product names. The three-letter prefix
#: mimics the *shape* of this instrument's naming, which is a category
#: abbreviation and a colon, without borrowing any of its words.
_TAGS = ("Zzz", "Qrk", "Vlt", "Nmb", "Wob", "Pfft")
_HEADS = (
    "Tin",
    "Glass",
    "Chalk",
    "Copper",
    "Velvet",
    "Cork",
    "Willow",
    "Pewter",
    "Basalt",
    "Linen",
)
_TAILS = ("Bell", "Drone", "Wash", "Sweep", "Hum", "Comb", "Gust", "Loom")


def demo_name(region_id: str, number: int) -> str:
    seed = sum(ord(c) for c in region_id) * 7 + number * 13
    tag = _TAGS[seed % len(_TAGS)]
    head = _HEADS[(seed // len(_TAGS)) % len(_HEADS)]
    tail = _TAILS[(seed // 31) % len(_TAILS)]
    return f"{tag}:{head}{tail}"[: m.NAME_CHARS].ljust(m.NAME_CHARS)


#: The name the demo midimap carries. Twelve characters, invented, and
#: deliberately not anybody's product, so a screenshot of the editor cannot
#: be mistaken for a real unit's map.
_MIDIMAP_NAME = "Demo Midimap"


def _channel_word(channel: int, label: str) -> int:
    """The offset of ``label`` in channel ``channel`` (1-16).

    The manual lays sixteen identical twenty-word channel blocks end to end
    (manual p.232, "... for 16 channels (20 parms each)"), so the
    ``channel``-th occurrence of a label in :data:`emu.midimap.PARAMS` *is*
    that channel's word. Reading the offset off the table keeps this seed
    from carrying a second copy of the layout that could drift from it.
    """
    seen = 0
    for param in mm.PARAMS:
        if param.label == label:
            seen += 1
            if seen == channel:
                return param.offset
    raise ValueError(f"no {label!r} in channel {channel}")


def _choice_value(param: mm.Param, label: str) -> int:
    """The wire value a choices parameter gives ``label``.

    The value comes from the table's own pairing
    (:func:`emu.midimap.choices_for`), not from the label's screen position:
    an effect type's number is a unique ID, not an index (manual p.242).
    """
    for value, name in mm.choices_for(param):
        if name == label:
            return value
    raise ValueError(f"{label!r} is not a choice of {param.label}")


def _seed_midimap() -> list[int]:
    """A deterministic, plausible midimap for the demo unit.

    The editor used to open on ``[0] * 360`` -- every value zero and a name
    of ``????????????`` -- which reads as a broken screen rather than an
    empty map. This builds one worth looking at, and takes every value from
    the manual's own table so nothing here can drift from it: channel words
    by their label (:func:`_channel_word`), enumerated values by their name
    (:func:`_choice_value`), and the effect's parameter range from
    :func:`emu.midimap.fx_params_for`. Channels 1 and 2 carry different
    programs and volumes; channels 3-16 stay disabled; the A effect is a
    room reverb.
    """
    words = mm.set_name([0] * 360, _MIDIMAP_NAME)

    def put(channel: int, label: str, value: int) -> None:
        words[_channel_word(channel, label)] = value

    def choice(channel: int, label: str, name: str) -> int:
        return _choice_value(mm.param_at(_channel_word(channel, label)), name)

    # Channel 1: a RAM preset, loud, with the routing switches on.
    put(1, "Ch. Program", 0)
    put(1, "Ch. Bank", choice(1, "Ch. Bank", "RAM Presets"))
    put(1, "Ch. Volume", 100)
    put(1, "Ch. Pan", choice(1, "Ch. Pan", "0"))
    # Ch. Mix Bus is 0 here -- the table spells 0 "Main"; the manual's
    # "Preset" is -1 on the wire (signed values, CLAUDE.md).
    put(1, "Ch. Mix Bus", choice(1, "Ch. Mix Bus", "Main"))
    put(1, "Ch. Enable", 1)
    put(1, "Ch. ProgChg Enbl", 1)
    put(1, "Ch. BankChg Enbl", 1)
    put(1, "Ch. VolCtl Enbl", 1)

    # Channel 2: a different program and volume, so its summary row does
    # not read the same as channel 1's.
    put(2, "Ch. Program", 1)
    put(2, "Ch. Bank", choice(2, "Ch. Bank", "RAM Presets"))
    put(2, "Ch. Volume", 90)
    put(2, "Ch. Pan", choice(2, "Ch. Pan", "0"))
    put(2, "Ch. Mix Bus", choice(2, "Ch. Mix Bus", "Main"))
    put(2, "Ch. Enable", 1)
    put(2, "Ch. ProgChg Enbl", 1)

    # Channels 3-16 keep the zero map they started as: disabled, which is
    # what "at most" wants and why the seed starts from zero.

    # Global / Effects: a room reverb on the A processor, its first
    # parameter at the middle of the range the manual gives that type.
    fx_a_type = mm.offset_of("FX A Type")
    type_value = _choice_value(mm.param_at(fx_a_type), "Room")
    words[fx_a_type] = type_value
    fx_a_params = mm.fx_params_for(type_value)
    if fx_a_params:
        _label, low, high, _choices = fx_a_params[0]
        words[mm.offset_of("FX A Parm Vals")] = (low + high) // 2

    return words


class DemoDevice:
    """Answers the subset of the protocol emorphed speaks."""

    def __init__(
        self,
        *,
        latency: float = 0.0,
        device_id: int = 0,
        channel: int = 0,
        card: bool = False,
    ) -> None:
        self.description = "demo (no MIDI ports opened)"
        self.device_id = device_id
        self.channel = channel
        self.timeout = 1.0
        self.latency = latency
        #: Whether a card is pretended to be fitted. Off by default,
        #: because a request for a card region is ignored outright when
        #: there is none and a demo that always had one would hide that.
        self.card = card
        self.port: str | None = None
        self.recv_port: str | None = None
        self.selected: banks.Slot | None = None
        self.selected_log: list[tuple[banks.Slot, int]] = []
        self.selected_midimaps: list[int] = []
        self.current_midimap: int | None = None
        #: Parameter requests observed, in order: param. Mirrors the
        #: scratch read's round trips so tests can count them.
        self.parameter_reads: list[int] = []
        #: Midimap parameter writes observed, in order: (param, value).
        self.parameter_writes: list[tuple[int, int]] = []
        #: Midimap stores observed, in order: (index, words).
        self.midimap_stores: list[tuple[int, list[int]]] = []
        #: Midimap *reads* (command 0x46 dump) observed, in order: index.
        #: A parameter round trip never touches this, so a test can prove
        #: "no stored dump happened" by checking it stayed empty.
        self.midimap_reads: list[int] = []
        #: The *scratch* midimap edits land in: a parameter write (command
        #: 0x03) edits this, so the live read (command 0x02,
        #: :meth:`read_parameter`) sees the new value. It starts as a
        #: plausible map, not a wall of zeroes (:func:`_seed_midimap`), so
        #: the editor has something worth showing.
        seed = _seed_midimap()
        self._midimap: list[int] = list(seed)
        #: The *stored* midimap a command 0x46/0x47 dump returns. A
        #: parameter write does NOT touch this, so ``read_midimap`` keeps
        #: reporting the previously stored map -- the scratch/stored
        #: distinction the manual draws on p.232. It starts as the same
        #: seed, as loading a stored map into the current one does.
        self._stored_midimap: list[int] = list(seed)
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _tick(self) -> None:
        if self._closed:
            raise RuntimeError(
                "this demo device is closed; a real bridge would be a "
                "closed port and would fail less clearly"
            )
        if self.latency:
            time.sleep(self.latency)

    # --- reading ------------------------------------------------------------

    def version(self, *, timeout: float | None = None) -> list[int]:
        self._tick()
        return [1, 0, 0]

    def configuration(self, *, timeout: float | None = None) -> list[int]:
        self._tick()
        return [1 if self.card else 0]

    def _regions(self, kind: str) -> Iterator[banks.Region]:
        for region in banks.regions(kind):
            if region.needs_card and not self.card:
                continue
            yield region

    def names(
        self, kind: str = banks.Kind.PRESET, *, timeout: float | None = None
    ) -> list[str]:
        self._tick()
        out: list[str] = []
        for region in self._regions(kind):
            for number in range(region.count):
                out.append(demo_name(region.id, number))
        return out

    def read_preset(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]:
        self._tick()
        for region in self._regions(banks.Kind.PRESET):
            if region.first <= index <= region.last:
                name = demo_name(region.id, index - region.first)
                # 278 words, the real record length, so a caller that
                # slices one gets the right shape
                words = m.encode_name(name) + [0] * (278 - m.NAME_CHARS)
                return words
        raise TimeoutError(
            f"no preset {index}: a request for a card region is ignored "
            f"outright when no card is fitted"
        )

    # --- the one thing that makes a sound ----------------------------------

    def select(self, target: banks.Slot) -> None:
        """Select a preset. **This changes what the unit is playing.**"""
        self._tick()
        banks.select_messages(target, self.channel)  # same refusals
        self.selected = target
        self.selected_log.append((target, self.channel))

    # --- selecting a midimap over SysEx ------------------------------

    def select_midimap(self, number: int) -> None:
        """Make a midimap current. **This changes what plays.**"""
        self._tick()
        if not 0 <= number <= 31:  # noqa: PLR2004
            raise m.ProtocolError(
                f"midimap {number} is outside 0-31 (16 RAM + 16 card)"
            )
        self.selected_midimaps.append(number)
        self.current_midimap = number

    # --- midimap reading and parameter writes -------------------------

    def read_midimap(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]:
        self._tick()
        if not 0 <= index <= 31:  # noqa: PLR2004
            raise m.ProtocolError(
                f"midimap {index} is outside 0-31 (16 RAM + 16 card)"
            )
        if index >= 16 and not self.card:  # noqa: PLR2004
            raise TimeoutError(
                f"midimap {index}: no card fitted, so the request is "
                f"ignored outright"
            )
        self.midimap_reads.append(index)
        return list(self._stored_midimap)

    def write_parameter(
        self, param: int, value: int, *, timeout: float | None = None
    ) -> None:
        self._tick()
        _low = mm.PARAM_BASE
        _high = mm.PARAM_BASE + len(mm.PARAMS) - 1
        if not _low <= param <= _high:
            raise m.ProtocolError(
                f"param {param} is outside the midimap parameter range "
                f"{_low}-{_high} (manual pp. 249-250)"
            )
        if not -0x2000 <= value <= 0x3FFF:  # noqa: PLR2004
            raise m.ProtocolError(
                f"value {value} is outside the fourteen-bit range 0-0x3FFF "
                f"(16383)"
            )
        offset = param - 2048
        self._midimap[offset] = value
        self.parameter_writes.append((param, value))

    def read_parameter(self, param: int) -> int | None:
        self._tick()
        self.parameter_reads.append(param)
        offset = param - 2048
        if not 0 <= offset < len(self._midimap):
            return None
        return self._midimap[offset]

    def read_scratch_params(self) -> list[int | None]:
        self._tick()
        out: list[int | None] = []
        for offset in range(len(self._midimap)):
            # Answer from the scratch map, via read_parameter, so a
            # synthetic test counting read_parameter calls sees 360.
            out.append(self.read_parameter(mm.PARAM_BASE + offset))
        return out

    def send_midimap(
        self, index: int, words: Any, *, timeout: float | None = None
    ) -> None:
        self._tick()
        if not 0 <= index <= 31:  # noqa: PLR2004
            raise m.ProtocolError(
                f"midimap {index} is outside 0-31 (16 RAM + 16 card)"
            )
        if len(words) != 360:  # noqa: PLR2004
            raise m.ProtocolError(
                f"a midimap body is 360 words; got {len(words)}"
            )
        # Validate every word fits the fourteen-bit (signed) range, the same
        # check the wire framing applies, so a bad map is refused here too.
        m.to_words(words)
        stored = list(words)
        self.midimap_stores.append((index, stored))
        #: A store makes this map the live (scratch) map when its location
        #: is the current one, so both sides move together.
        self._stored_midimap = list(stored)
        self._midimap = list(stored)
