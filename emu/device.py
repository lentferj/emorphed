# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The device interface, ported from the sibling projects: what emorphed asks
# of a device, real or invented, so neither the CLI nor the browser needs to
# know which one it is holding.
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

"""The interface both devices answer to.

``DemoDevice`` and ``MorpheusBridge`` both satisfy this structurally. The
commands and the browser are written against it, so a command that needs a
real unit can be told so by the caller passing one, and the offline commands
are passed ``None`` and never touch it.
"""

from __future__ import annotations

from typing import Any, Protocol

from emu import banks

__all__ = ["Device"]


class Device(Protocol):
    """What emorphed asks of a device, real or invented."""

    description: str
    device_id: int
    channel: int
    port: str | None
    recv_port: str | None

    def close(self) -> None: ...

    def version(self) -> list[int]: ...

    def configuration(self) -> list[int]: ...

    def names(self, kind: str) -> list[str]: ...

    def select(self, target: banks.Slot) -> None: ...

    def select_midimap(self, number: int) -> None: ...

    def read_midimap(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]: ...

    def write_parameter(
        self, param: int, value: int, *, timeout: float | None = None
    ) -> None: ...

    def send_midimap(
        self, index: int, words: Any, *, timeout: float | None = None
    ) -> None: ...

    def read_parameter(self, param: int) -> int | None:
        # Live scratch-map value via Parameter Request (0x02); NOT the
        # stored midimap dump. See emu.bridge.MorpheusBridge.read_parameter.
        ...
