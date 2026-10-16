# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The transport is ported from the sibling p2ked, x5ded, kwsed, rxved and
# nanosyned projects. The protocol it carries is E-mu's.
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

"""Talking to a Morpheus.

**Nothing in this module has been run against a Morpheus.** The
instrument was not patched into the MIDI bay while it was written. Every
message it sends is transcribed from E-mu's published specification and
checked against real dumps, which is enough to write it honestly and not
enough to call it tested. `DISCLAIMER.md` says the same thing and TODO
item 1 tracks it.

Two things from the manual that the code has to respect:

* **Device ID.** Every message carries one, 0-15, set in the unit's
  Master menu. A request with the wrong ID is answered with silence, and
  silence is the same answer as a wrong cable, so `autodetect` sweeps IDs
  rather than assuming 0.
* **Pacing.** The manual warns that sending preset data in one chunk
  will clog the input buffer unless roughly 100 ms separates each preset,
  and the unit has a SysEx Packet Delay setting for the other direction.
  This program only reads, so the warning applies to it only in that a
  reply to a bank request is large and arrives slowly.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from emu import banks
from emu import config as cfg
from emu import messages as m
from vinsynlib import midi

__all__ = [
    "BANK_TIMEOUT",
    "DEFAULT_TIMEOUT",
    "PRESET_GAP",
    "PROBE_TIMEOUT",
    "DeviceError",
    "MorpheusBridge",
    "likely_ports",
    "list_ports",
]


class DeviceError(midi.DeviceError):
    """Something about the connection, not about the music.

    The library's class, so a probe that finds nothing is recognised by
    :func:`vinsynlib.midi.open_remembered_or_swept` and the sweep it falls
    back to happens -- with an announcement, rather than as a launch that
    quietly takes the slow path.
    """


DEFAULT_TIMEOUT = 2.0
PROBE_TIMEOUT = 0.4
#: A bank reply is 128 dumps of 566 bytes -- 72 kB at MIDI's 3125 bytes a
#: second is twenty-three seconds, so this is not generous, it is
#: arithmetic.
BANK_TIMEOUT = 40.0

#: Between one preset request and the next, when walking a bank one at a
#: time. The manual asks for roughly 100 ms between presets in the other
#: direction; this is the same number used defensively, and it is a
#: **guess** in this direction. Measuring it is a TODO item.
PRESET_GAP = 0.100


def _rtmidi() -> Any:
    try:
        import rtmidi
    except ImportError as exc:  # pragma: no cover
        raise DeviceError(
            "python-rtmidi is not installed, so no MIDI port can be "
            "opened. emorphed still runs with --demo, which opens none."
        ) from exc
    return rtmidi


def list_ports() -> tuple[list[str], list[str]]:
    rtmidi = _rtmidi()
    midi_in, midi_out = rtmidi.MidiIn(), rtmidi.MidiOut()
    try:
        return list(midi_in.get_ports()), list(midi_out.get_ports())
    finally:
        midi_in.delete()
        midi_out.delete()


def likely_ports() -> list[str]:
    """Ports whose name suggests the instrument. Only an ordering."""
    _, outs = list_ports()
    wanted = ("morpheus", "e-mu", "emu", "ultraproteus")
    return [p for p in outs if any(w in p.lower() for w in wanted)]


class MorpheusBridge:
    """One open pair of ports, and the requests this program makes."""

    def __init__(
        self,
        midi_in: Any,
        midi_out: Any,
        *,
        device_id: int = 0,
        channel: int = 0,
        description: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._in = midi_in
        self._out = midi_out
        #: The SysEx device ID, 0-15. Not the MIDI channel; the Morpheus
        #: has both and they are set in different places.
        self.device_id = device_id
        self.channel = channel
        self.description = description
        self.timeout = timeout
        self.port: str | None = None
        self.recv_port: str | None = None
        try:
            self._in.ignore_types(sysex=False, timing=True, active_sense=True)
        except AttributeError:  # a test double
            pass

    @classmethod
    def open(
        cls,
        port: str,
        *,
        recv_port: str | None = None,
        device_id: int = 0,
        channel: int = 0,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> MorpheusBridge:
        rtmidi = _rtmidi()
        ins, outs = list_ports()
        listen = recv_port or port
        if port not in outs:
            raise DeviceError(f"no output port named {port!r}; have {outs}")
        if listen not in ins:
            raise DeviceError(f"no input port named {listen!r}; have {ins}")
        midi_out, midi_in = rtmidi.MidiOut(), rtmidi.MidiIn()
        try:
            midi_out.open_port(outs.index(port))
            midi_in.open_port(ins.index(listen))
        except Exception:
            for client in (midi_in, midi_out):
                try:
                    client.close_port()
                    client.delete()
                except Exception:
                    pass
            raise
        bridge = cls(
            midi_in,
            midi_out,
            device_id=device_id,
            channel=channel,
            description=f"{port} -> {listen}",
            timeout=timeout,
        )
        bridge.port = port
        bridge.recv_port = listen
        return bridge

    def close(self) -> None:
        for client in (self._in, self._out):
            try:
                client.close_port()
                client.delete()
            except Exception:
                pass

    def __enter__(self) -> MorpheusBridge:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # --- the wire -----------------------------------------------------------

    def _drain(self) -> None:
        while self._in.get_message() is not None:
            pass

    def request(
        self, outgoing: bytes, wanted: int, *, timeout: float | None = None
    ) -> m.Packet:
        """Send a request and wait for the reply that answers it.

        ``wanted`` is the command of the **reply**. A request echoed back
        by a soft thru -- which the sibling projects all met -- parses as
        a perfectly good E-mu message, and only the command tells the two
        apart.
        """
        self._drain()
        self._out.send_message(list(outgoing))
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        while time.time() < deadline:
            message = self._in.get_message()
            if message is None:
                time.sleep(0.002)
                continue
            packet = m.parse(message[0])
            if packet is None or packet.command != wanted:
                continue
            if packet.device != self.device_id:
                continue
            return packet
        raise TimeoutError(self._silence_means(wanted))

    def _silence_means(self, wanted: int) -> str:
        """Why nothing came back. Never picks one reason."""
        return (
            f"no {m.Command.name(wanted)} came back. The unit does not "
            f"refuse a request it cannot serve, it simply says nothing, so "
            f"this means one of: powered off, the wrong port, a chain that "
            f"does not carry replies back, the wrong SysEx device ID "
            f"(emorphed is using {self.device_id}), or -- for a card "
            f"region -- no card fitted, which the manual says is ignored "
            f"outright."
        )

    # --- reading, all of it silent -----------------------------------------

    def version(self, *, timeout: float | None = None) -> list[int]:
        """The unit's software version. Silent."""
        packet = self.request(
            m.version_request(device=self.device_id),
            m.Command.VERSION_DATA,
            timeout=timeout,
        )
        return list(packet.body)

    def configuration(self, *, timeout: float | None = None) -> list[int]:
        """What is fitted. Silent."""
        packet = self.request(
            m.configuration_request(device=self.device_id),
            m.Command.CONFIGURATION_DATA,
            timeout=timeout,
        )
        return list(packet.body)

    def names(
        self, kind: str = banks.Kind.PRESET, *, timeout: float | None = None
    ) -> list[str]:
        """Every name of one kind, in one exchange. Silent.

        The best thing in this protocol: one message out, every name
        back, in the order the instrument shows them. None of the sibling
        instruments can do this.
        """
        request = {
            banks.Kind.PRESET: m.preset_list_request,
            banks.Kind.HYPERPRESET: m.hyperpreset_list_request,
            banks.Kind.MIDIMAP: m.midimap_list_request,
        }[kind]
        packet = self.request(
            request(device=self.device_id),
            banks.Kind.LIST_REPLY[kind],
            timeout=BANK_TIMEOUT if timeout is None else timeout,
        )
        return m.parse_name_list(packet)

    def read_preset(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]:
        """One preset, as fourteen-bit words. Silent."""
        packet = self.request(
            m.preset_request(index, device=self.device_id),
            m.Command.PRESET_DATA,
            timeout=timeout,
        )
        if packet.number != index:
            raise TimeoutError(
                f"asked for preset {index} and got {packet.number}; a late "
                f"reply to an earlier request"
            )
        return packet.words()

    # --- the one thing that makes a sound ----------------------------------

    def select(self, target: banks.Slot) -> None:
        """Select a preset. **This changes what the unit is playing.**

        Bank Select then Program Change, in the manual's order, always
        both. Note that the program number is only what reaches this
        preset when the default Program Map is in force -- see
        :attr:`banks.Slot.program_change`.
        """
        for message in banks.select_messages(target, self.channel):
            self._out.send_message(list(message))

    # --- discovery ----------------------------------------------------------

    @classmethod
    def connect(
        cls,
        *,
        config_path: str = cfg.DEFAULT_PATH,
        remembered: tuple[str, str] | None = None,
        scan: bool = False,
        channel: int = 0,
        device_id: int = 0,
        on_try: Callable[[str], None] | None = None,
    ) -> MorpheusBridge:
        """Open the unit, sweeping every port only when that is necessary.

        **The normal path is one Version Request, to the port remembered in
        ``config_path``.** That is not only an optimisation.
        :meth:`autodetect` sweeps every output port on the machine at every
        one of the sixteen SysEx device IDs, which on a studio box with
        thirty ports takes seconds and pings every piece of hardware on the
        chain -- and once the answer is known there is nothing left to learn
        from asking again.

        So: use the remembered port if there is one, sweep if there is not,
        and sweep on request. ``scan=True`` is what ``--scan`` reaches,
        which is what is needed after the unit moves to another port --
        USB re-enumeration renumbers ALSA clients out from under a saved
        name.

        A remembered port that does not answer falls back to the sweep, but
        **it says so first**. The guess is gone, and the announcement is
        what keeps the fallback from looking like the fast path having
        worked -- which is how a slow launch quietly becomes the normal one.
        What the sweep then finds is written back, so the launch after this
        one is fast again.

        The policy itself is :func:`vinsynlib.midi.open_remembered_or_swept`,
        written and tested once for the whole family; this is the Morpheus's
        half of it, which is what a Version Request on a named port means
        and where the answer is filed.

        ``remembered`` defaults to what ``config_path`` holds. It is a
        parameter so a caller can pass a pair it has already read, and so a
        test can say what the file says without writing one.
        """
        remembered = (
            remembered
            if remembered is not None
            else cfg.load_port_pair(config_path)
        )

        # The remembered port belongs to whatever unit answered there last
        # time, and that unit is identified by its SysEx device ID. Probing
        # it with a different (usually the default, 0) ID silences the one
        # unit that is actually there, so use the ID remembered alongside it.
        # Only when nothing has been remembered yet does the probe fall back
        # to the caller's/default ID, exactly as before.
        remembered_device_id = device_id
        if remembered is not None:
            loaded = cfg.load_device_id(config_path)
            if loaded is not None:
                remembered_device_id = loaded

        def probe(send: str, recv: str) -> MorpheusBridge:
            """One round trip to the named port. Raises if nothing answers."""
            try:
                bridge = cls.open(
                    send,
                    recv_port=recv,
                    device_id=remembered_device_id,
                    channel=channel,
                    timeout=PROBE_TIMEOUT,
                )
            except Exception as exc:
                raise DeviceError(str(exc)) from exc
            try:
                bridge.version(timeout=PROBE_TIMEOUT)
            except Exception as exc:
                bridge.close()
                raise DeviceError(
                    f"no Version Request came back on {send!r}: {exc}"
                ) from exc
            # The discovery timeout must not become the session's: every
            # later request that does not name its own would run at the
            # probe's value rather than the working one.
            bridge.timeout = DEFAULT_TIMEOUT
            return bridge

        def remember(bridge: MorpheusBridge) -> None:
            if bridge.port and bridge.recv_port:
                cfg.save_ports(bridge.port, bridge.recv_port, config_path)

        return midi.open_remembered_or_swept(
            probe=probe,
            sweep=lambda try_hook: cls.autodetect(
                timeout=PROBE_TIMEOUT, on_try=try_hook
            ),
            remembered=remembered,
            scan=scan,
            remember=remember,
            on_try=on_try,
        )

    @classmethod
    def autodetect(
        cls,
        *,
        timeout: float = PROBE_TIMEOUT,
        on_try: Callable[[str], None] | None = None,
    ) -> MorpheusBridge:
        """Find a Morpheus by asking each port, and each device ID, who it is.

        Sixteen device IDs times every port is a lot of probing, so the
        sweep asks ID 0 on every port first and only then widens: a unit
        left on the default is found quickly, and one that is not is
        still found.
        """
        hinted = likely_ports()
        _, outs = list_ports()
        candidates = hinted + [p for p in outs if p not in hinted]
        candidates = [p for p in candidates if "Midi Through" not in p]

        for device_id in (0, *range(1, 16)):
            for port in candidates:
                if on_try is not None:
                    on_try(f"{port} (device {device_id})")
                try:
                    bridge = cls.open(
                        port, device_id=device_id, timeout=timeout
                    )
                except Exception:
                    continue
                try:
                    bridge.version(timeout=timeout)
                except Exception:
                    bridge.close()
                    continue
                bridge.timeout = DEFAULT_TIMEOUT
                return bridge
        raise DeviceError(
            "no Morpheus answered a Version Request on any port at any "
            "device ID. Check the cable, that the unit is on, and that the "
            "chain carries its replies back to this computer as well as "
            "carrying requests out."
        )
