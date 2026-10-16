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

from emu import banks
from emu import messages as m

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
        #: Midimap parameter writes observed, in order: (param, value).
        self.parameter_writes: list[tuple[int, int]] = []
        #: The one mutable midimap this demo stands in for (360 words,
        #: one per midimap parameter index 0-359). A write lands here so
        #: the next read-back sees it.
        self._midimap: list[int] = [0] * 360
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
        return list(self._midimap)

    def write_parameter(
        self, param: int, value: int, *, timeout: float | None = None
    ) -> None:
        self._tick()
        if not 2048 <= param <= 2407:  # noqa: PLR2004
            raise m.ProtocolError(
                f"param {param} is outside the midimap parameter range "
                f"2048-2407 (manual p.264)"
            )
        if not 0 <= value <= 0x3FFF:  # noqa: PLR2004
            raise m.ProtocolError(
                f"value {value} is outside the fourteen-bit range 0-0x3FFF "
                f"(16383)"
            )
        offset = param - 2048
        self._midimap[offset] = value
        self.parameter_writes.append((param, value))

    def read_parameter(self, param: int) -> int | None:
        self._tick()
        offset = param - 2048
        if not 0 <= offset < len(self._midimap):
            return None
        return self._midimap[offset]
