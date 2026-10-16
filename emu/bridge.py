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
        #: Which midimap read_parameter re-reads. Midimap parameters are
        #: the current edit buffer's, so a read-back must ask for the
        #: midimap that is current; default 0 until one is selected. See
        #: :meth:`read_parameter`'s docstring.
        self.current_midimap = 0
        self.channel = channel
        self.description = description
        self.timeout = timeout
        self.port: str | None = None
        self.recv_port: str | None = None
        #: Whether this bridge came from a port sweep, and how long that
        #: took. The front ends print one line when it was a sweep; the
        #: fast path (the remembered pair) stays silent.
        self.swept = False
        self.probe_seconds = 0.0
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

    #: Raised when a midimap dump comes back with fewer than 360 words.
    #: Subclasses the exception families a caller is likely to catch for a
    #: malformed reply or a missing card, so a test asserting either
    #: ``TimeoutError`` or ``m.ProtocolError`` (a ``ValueError``) matches.
    class _ShortMidimapDump(m.ProtocolError, TimeoutError):
        pass

    def read_midimap(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]:
        """One midimap, as 360 fourteen-bit words. Silent.

        A request for a card midimap (16-31) with no card fitted is
        *ignored outright* by the unit, which ordinarily means silence and
        a timeout. Some units instead answer with a truncated frame; a
        body shorter than the full 360 words is the manual's no-card case,
        so such a dump raises with that wording rather than returning a
        short list that a caller would slice the wrong way.
        """
        if not 0 <= index <= 31:  # noqa: PLR2004
            raise m.ProtocolError(
                f"midimap {index} is outside 0-31 (16 RAM + 16 card)"
            )
        packet = self.request(
            m.midimap_request(index, device=self.device_id),
            m.Command.MIDIMAP_DATA,
            timeout=BANK_TIMEOUT if timeout is None else timeout,
        )
        if packet.number != index:
            raise TimeoutError(
                f"asked for midimap {index} and got {packet.number}; a late "
                f"reply to an earlier request"
            )
        words = packet.words()
        if len(words) < 360:  # noqa: PLR2004
            raise MorpheusBridge._ShortMidimapDump(
                f"midimap {index} came back short: {len(words)} of "
                f"360 words. For card midimaps (16-31) this is what no "
                f"card fitted looks like -- the unit ignores such a "
                f"request outright, and a truncated frame means the same "
                f"thing."
            )
        return list(words)

    def write_parameter(
        self, param: int, value: int, *, timeout: float | None = None
    ) -> None:
        """Send one Parameter Data frame. Fire-and-forget, no reply.

        ``param`` must be a midimap parameter, 2048-2407 (manual p.264);
        ``value`` is fourteen bits, 0-0x3FFF. Out-of-range values are
        refused; the manual's range is named in the message. ``timeout``
        is accepted for symmetry with the other methods and is unused,
        because Parameter Data carries no reply to wait for.
        """
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
        self._out.send_message(
            list(m.parameter_data(param, value, device=self.device_id))
        )

    def send_midimap(
        self, index: int, words: Any, *, timeout: float | None = None
    ) -> None:
        """Send one Midimap Data frame. **This is the STORE.**

        Sending a midimap writes the midimap at ``index`` (erasing what
        was there -- manual p.36), and when that location is the
        currently selected one the unit reloads its scratch midimap from
        the newly stored map (manual p.237). A backup must have been taken
        first; that is the caller's job, and nothing here does it. There is
        no reply to wait for, so ``timeout`` is accepted for symmetry with
        the other methods and is unused.
        """
        frame = m.midimap_data(words, number=index, device=self.device_id)
        self._out.send_message(list(frame))

    def read_parameter(self, param: int) -> int | None:
        """Read one midimap parameter back, by re-reading a whole map.

        No per-parameter read is documented in what we have, so this
        re-reads the owning midimap dump (see :meth:`read_midimap`) and
        returns the word at the corresponding offset (param - 2048).
        **Cost: one 730-byte reply per verification**, not one small
        frame. The map re-read is for the midimap last handed to
        :meth:`select_midimap` (index 0 if none has been selected).

        Returns ``None`` when the dump came back short, which is the
        no-card case.
        """
        if not 2048 <= param <= 2407:  # noqa: PLR2004
            raise m.ProtocolError(
                f"param {param} is outside the midimap parameter range "
                f"2048-2407 (manual p.264)"
            )
        try:
            words = self.read_midimap(self.current_midimap)
        except (m.ProtocolError, TimeoutError):
            return None
        offset = param - 2048
        if offset >= len(words):
            return None
        return words[offset]

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

    def select_midimap(self, number: int) -> None:
        """Make a midimap the current one. **This changes what plays.**

        A midimap has no program change; page 159 of the manual says the
        ONLY way to select one remotely is two System Exclusive frames:
        Midi Mode set to Multi, then Current Midimap set to ``number``.
        This is a *selection*, not a data write -- like ``select``, it
        is fire-and-forget (Bank Select + Program Change is equally
        fire-and-forget), so there is no read-back after it and no reply
        to wait for.

        ``number`` is the midimap's own number, 0-31 (16 RAM + 16 card).
        """
        if not 0 <= number <= 31:  # noqa: PLR2004
            raise m.ProtocolError(
                f"midimap {number} is outside 0-31 (16 RAM + 16 card)"
            )
        frames = m.select_midimap_frames(number, device=self.device_id)
        self.current_midimap = number
        self._out.send_message(list(frames[0]))
        time.sleep(PRESET_GAP)
        self._out.send_message(list(frames[1]))

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

        remembered_device_id = _remembered_id(
            device_id, remembered, config_path
        )
        probe = _probe_factory(
            cls, channel=channel, device_id=remembered_device_id
        )

        def remember(bridge: MorpheusBridge) -> None:
            if bridge.port and bridge.recv_port:
                cfg.save_ports(bridge.port, bridge.recv_port, config_path)

        return midi.open_remembered_or_swept(
            probe=probe,
            # The sweep asks the device ID it was given (remembered, or the
            # caller's) before widening, and starts at the remembered port:
            # a unit that is on file but silent under the default ID is
            # found in one pass instead of eight.
            sweep=lambda try_hook: cls.autodetect(
                timeout=PROBE_TIMEOUT,
                on_try=try_hook,
                device_id=remembered_device_id,
                preferred_port=remembered[0] if remembered else None,
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
        device_id: int | None = None,
        preferred_port: str | None = None,
        on_try: Callable[[str], None] | None = None,
    ) -> MorpheusBridge:
        """Find a Morpheus by asking each port who it is, ID by ID.

        Sixteen device IDs times every port is a lot of probing, so the
        order is the point: the device ID we were given (remembered, or
        from ``--device-id``) is asked first on every port, then the
        default 0, then the rest; the ports run remembered-first, then the
        ones whose names look like the instrument, then the remainder. A
        unit left on the default, or one whose ID is on file, is therefore
        found in one pass rather than eight.

        One line per port names the IDs about to be tried there, so a slow
        sweep says what it is doing instead of printing one line per probe.
        """
        hinted = likely_ports()
        _, outs = list_ports()
        ordered = (
            ([preferred_port] if preferred_port else [])
            + hinted
            + [p for p in outs if p not in hinted]
        )
        candidates: list[str] = []
        for port in ordered:
            if port in candidates or "Midi Through" in port:
                continue
            candidates.append(port)

        ids: list[int] = []
        if device_id is not None:
            ids.append(device_id)
        if 0 not in ids:
            ids.append(0)
        ids.extend(d for d in range(1, 16) if d not in ids)

        started = time.perf_counter()
        for port in candidates:
            if on_try is not None:
                wanted = ", ".join(str(device) for device in ids)
                on_try(f"{port} (device {wanted})")
            for device in ids:
                try:
                    bridge = cls.open(port, device_id=device, timeout=timeout)
                except Exception:
                    continue
                try:
                    bridge.version(timeout=timeout)
                except Exception:
                    bridge.close()
                    continue
                bridge.timeout = DEFAULT_TIMEOUT
                bridge.swept = True
                bridge.probe_seconds = time.perf_counter() - started
                return bridge
        raise DeviceError(
            "no Morpheus answered a Version Request on any port at any "
            "device ID. Check the cable, that the unit is on, and that the "
            "chain carries its replies back to this computer as well as "
            "carrying requests out."
        )


def _remembered_id(
    device_id: int,
    remembered: tuple[str, str] | None,
    config_path: str,
) -> int:
    """The ID a remembered port should be probed with.

    The remembered port belongs to whatever unit answered there last time,
    and that unit is identified by its SysEx device ID. Probing it with a
    different (usually the default, 0) ID silences the one unit that is
    actually there, so use the ID remembered alongside it. Only when
    nothing has been remembered yet does the probe fall back to the
    caller's/default ID, exactly as before.
    """
    if remembered is not None:
        loaded = cfg.load_device_id(config_path)
        if loaded is not None:
            return loaded
    return device_id


def _probe_factory(
    cls: type[MorpheusBridge], *, channel: int, device_id: int
) -> Callable[[str, str], MorpheusBridge]:
    """The remembered-port probe: the remembered ID, then 0.

    A fresh install has no remembered ID at all and a unit left on the
    default should still connect without a sweep, so the probe tries the
    ID on file first and then 0 (`_probe_on` closes a port that stays
    silent on the way through). If neither answers, raise so the library
    falls back to the sweep and announces it.
    """

    def probe(send: str, recv: str) -> MorpheusBridge:
        attempts = [device_id]
        if device_id != 0:
            attempts.append(0)
        last: Exception | None = None
        for device in attempts:
            try:
                return _probe_on(cls, send, recv, device, channel=channel)
            except Exception as exc:
                last = exc
        raise DeviceError(
            f"no Version Request came back on {send!r}: {last}"
        ) from last

    return probe


def _probe_on(
    cls: type[MorpheusBridge],
    send: str,
    recv: str,
    device: int,
    *,
    channel: int,
) -> MorpheusBridge:
    """One round trip to the named port at the named device ID."""
    try:
        bridge = cls.open(
            send,
            recv_port=recv,
            device_id=device,
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
            f"device {device}: no Version Request came back"
        ) from exc
    # The discovery timeout must not become the session's: every later
    # request that does not name its own would run at the probe's value
    # rather than the working one.
    bridge.timeout = DEFAULT_TIMEOUT
    return bridge
