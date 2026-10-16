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

"""How a launch finds the unit: the remembered port, and the sweep.

Ported in the same shape as the sibling x5ded's and rxved's
tests/test_connect.py. These exist because `MorpheusBridge.autodetect` swept
every MIDI port on the machine at every one of the sixteen SysEx device IDs
on every single launch, against a config.toml that had been recording the
answer since before the file existed -- it was written, and then ignored.

What is tested here is the *wiring*, not the policy: the policy itself is
`vinsynlib.midi.open_remembered_or_swept`, and its own tests live with it.
These prove that emorphed hands it the right probe, the right remembered
pair, and the right answer to --scan.

No hardware and no MIDI ports here: `open` and `autodetect` are stubbed with
what they would have found.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from emu import bridge as b
from emu import config as cfg

MORPHEUS_PORT = "Midi Out: E-mu MIDI 1 20:0"
OTHER_PORT = "Midi Out: Scarlett 18i8 USB MIDI 1 24:0"
SPLIT_IN = "Midi In: Something Else 1 30:0"


class _FakeBridge:
    """Stands in for an opened bridge. Closes are counted, not needed."""

    def __init__(self, port: str, recv: str, *, answers: bool) -> None:
        self.port = port
        self.recv_port = recv
        #: False models a port that stays silent, which on this protocol is
        #: indistinguishable from a unit that is off.
        self.answers = answers
        self.channel = 0
        self.device_id = 0
        self.timeout = b.DEFAULT_TIMEOUT
        self.closed = False
        #: Set by a real sweep; the fake sets them itself when it stands in
        #: for one, so assertions can tell a sweep from the fast path.
        self.swept = False
        self.probe_seconds = 0.0

    def version(self, *, timeout: float | None = None) -> list[int]:
        if not self.answers:
            raise TimeoutError("no VERSION_DATA came back")
        return [1, 2, 3]

    def close(self) -> None:
        self.closed = True


class _Rig:
    """Records what was opened, what answered, and whether a sweep happened.

    `answering` maps a port name to whether a Morpheus answers there. A port
    left out is never opened; one mapped to False is opened and stays silent,
    which is the case that has to be told apart from a hit.
    """

    def __init__(
        self,
        answering: dict[str, bool],
        *,
        ports: list[str] | None = None,
        answering_on_id: dict[tuple[str, int], bool] | None = None,
    ) -> None:
        self.answering = answering
        #: A more precise map: this port answers *only* on this device ID.
        #: Used for the case a unit is there but not on the ID on file.
        self.answering_on_id = answering_on_id or {}
        self.ports = ports if ports is not None else list(answering)
        self.opened: list[str] = []
        self.tried: list[str] = []
        self.swept = 0
        self.made: list[_FakeBridge] = []
        self.probes: list[tuple[str, int]] = []
        #: The (device_id, preferred_port) the sweep was called with.
        self.sweep_calls: list[tuple[int | None, str | None]] = []

    def install(
        self, monkeypatch: pytest.MonkeyPatch, *, stub_autodetect: bool = True
    ) -> _Rig:
        rig = self

        def fake_open(
            cls: Any,
            /,
            port: str,
            *,
            recv_port: str | None = None,
            device_id: int = 0,
            channel: int = 0,
            **rest: Any,
        ) -> _FakeBridge:
            # `rest` is `timeout=...`, which is a discovery timeout and is
            # deliberately dropped: the test that cares asserts on
            # bridge.timeout after the call rather than on what went in.
            rig.opened.append(port)
            bridge = _FakeBridge(
                port, recv_port or port, answers=rig.answers(port, device_id)
            )
            bridge.device_id = device_id
            bridge.channel = channel
            rig.made.append(bridge)
            rig.probes.append((port, device_id))
            return bridge

        def fake_autodetect(
            cls: Any,
            *,
            timeout: float = b.PROBE_TIMEOUT,
            device_id: int | None = None,
            preferred_port: str | None = None,
            on_try: Callable[[str], None] | None = None,
        ) -> _FakeBridge:
            # Mirrors the real one's order -- the ID we were given first on
            # every port, then 0, then the rest; ports remembered-first --
            # so the ordering is exercised rather than stubbed away.
            rig.swept += 1
            rig.sweep_calls.append((device_id, preferred_port))
            ids: list[int] = []
            if device_id is not None:
                ids.append(device_id)
            if 0 not in ids:
                ids.append(0)
            ids.extend(d for d in range(1, 16) if d not in ids)
            ports = [preferred_port] if preferred_port else []
            ports += [p for p in rig.ports if p not in ports]
            for name in ports:
                if on_try is not None:
                    on_try(f"{name} (device {', '.join(str(d) for d in ids)})")
                for device in ids:
                    rig.tried.append(name)
                    if rig.answers(name, device):
                        bridge = fake_open(cls, name, device_id=device)
                        bridge.swept = True
                        return bridge
            raise b.DeviceError("nothing answered")

        monkeypatch.setattr(
            b, "list_ports", lambda: (list(rig.ports), list(rig.ports))
        )
        monkeypatch.setattr(b, "likely_ports", lambda: [])
        monkeypatch.setattr(b.MorpheusBridge, "open", classmethod(fake_open))
        if stub_autodetect:
            monkeypatch.setattr(
                b.MorpheusBridge, "autodetect", classmethod(fake_autodetect)
            )
        return rig

    def answers(self, port: str, device: int) -> bool:
        """Whether a unit answers on this port at this device ID."""
        if (port, device) in self.answering_on_id:
            return self.answering_on_id[(port, device)]
        return bool(self.answering.get(port))

    def unclosed(self) -> list[str]:
        """Bridges that were opened and never closed."""
        return [x.port for x in self.made if not x.closed]


def _remembered(
    tmp_path: Path, send: str = MORPHEUS_PORT, recv: str = ""
) -> str:
    """A config.toml holding one remembered port pair."""
    path = str(tmp_path / "config.toml")
    cfg.save_ports(send, recv or send, path)
    return path


# --- the normal path: trust the config ---------------------------------------


class TestTheRememberedPort:
    def test_it_is_used_without_sweeping(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """One Version Request to the saved port, and nothing else.

        The whole point. `autodetect` sweeps every output port at every one
        of the sixteen device IDs, which on a box with thirty ports takes
        seconds and pings everything on the chain once per launch.
        """
        path = _remembered(tmp_path)
        rig = _Rig({MORPHEUS_PORT: True, OTHER_PORT: False}).install(
            monkeypatch
        )

        b.MorpheusBridge.connect(config_path=path)

        assert rig.swept == 0, "swept every port when the answer was on file"
        assert rig.opened == [MORPHEUS_PORT]

    def test_the_remembered_pair_is_both_halves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The input port is remembered too, so a unit on a separate
        interface does not fall back to probing the output name."""
        path = str(tmp_path / "config.toml")
        cfg.save_ports(OTHER_PORT, SPLIT_IN, path)
        _Rig({OTHER_PORT: True}).install(monkeypatch)

        bridge = b.MorpheusBridge.connect(config_path=path)

        assert bridge.recv_port == SPLIT_IN

    def test_the_session_timeout_is_not_the_probe_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A short discovery timeout must not become the working one.

        Otherwise every later request that does not name its own runs at the
        probe's value, and a slow but working connection looks like a timeout
        on every call.
        """
        path = _remembered(tmp_path)
        _Rig({MORPHEUS_PORT: True}).install(monkeypatch)

        bridge = b.MorpheusBridge.connect(config_path=path)

        assert bridge.timeout == b.DEFAULT_TIMEOUT
        assert bridge.timeout != b.PROBE_TIMEOUT

    def test_it_does_not_rewrite_the_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The file is this path's *input*.

        Rewriting it unchanged would make a plain launch mutate the thing it
        was asked to trust, and any later change to what is stored would be
        invisible in a diff.
        """
        path = _remembered(tmp_path)
        _Rig({MORPHEUS_PORT: True}).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path)

        assert cfg.load_last_port(path) == MORPHEUS_PORT

    def test_a_dead_remembered_port_leaves_nothing_open(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        rig = _Rig({MORPHEUS_PORT: False, OTHER_PORT: True}).install(
            monkeypatch
        )

        b.MorpheusBridge.connect(config_path=path)

        # The remembered one was closed on the way to falling back; the one
        # the sweep found is the caller's to close.
        assert rig.made[0].port == MORPHEUS_PORT
        assert rig.made[0].closed is True


# --- the fallback: sweep ----------------------------------------------------


class TestTheSweep:
    def test_it_runs_when_nothing_is_remembered(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")  # never written: a first run
        rig = _Rig({OTHER_PORT: True}).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path)

        assert rig.swept == 1
        assert OTHER_PORT in rig.tried

    def test_it_runs_when_asked_for(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--scan: what is needed after the unit moves to a renumbered port.

        The saved name still answers here -- something is behind it -- but
        the unit has moved, so the port that answers is the wrong one. That
        is the case a remembered port cannot see, and it is the whole reason
        the flag exists.
        """
        path = _remembered(tmp_path)
        # The saved name is still a port on this host -- it is what the unit
        # was on -- and nothing answers there now, because the unit is
        # somewhere else. `ports` says it exists; `answering` says what is
        # behind it.
        rig = _Rig(
            {OTHER_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]
        ).install(monkeypatch)

        bridge = b.MorpheusBridge.connect(config_path=path, scan=True)

        assert rig.swept == 1
        assert bridge.port == OTHER_PORT, "opened the saved port anyway"

    def test_scan_sweeps_from_the_remembered_port(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--scan asks for the sweep, and the sweep still starts where the
        unit was last seen: the most likely port, and asking it first costs
        nothing. What --scan skips is the probe-and-trust fast path, not
        the port.
        """
        path = _remembered(tmp_path)
        rig = _Rig(
            {OTHER_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]
        ).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path, scan=True)

        assert rig.swept == 1
        assert rig.tried[0] == MORPHEUS_PORT, "the sweep skipped the file"
        # The only opens are the sweep's own: nothing took the
        # probe-and-trust fast path before it.
        assert rig.probes == [(OTHER_PORT, 0)]

    def test_a_dead_remembered_port_falls_back_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Not silently. A fallback that says nothing is indistinguishable
        from the fast path having worked, which is how a slow launch quietly
        becomes the normal one."""
        path = _remembered(tmp_path)
        rig = _Rig({MORPHEUS_PORT: False, OTHER_PORT: True}).install(
            monkeypatch
        )
        said: list[str] = []

        bridge = b.MorpheusBridge.connect(config_path=path, on_try=said.append)

        assert rig.swept == 1
        assert bridge.port == OTHER_PORT
        assert said[0] == f"{MORPHEUS_PORT} (remembered, did not answer)"

    def test_the_fast_path_says_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """One Version Request, and silence about it."""
        path = _remembered(tmp_path)
        _Rig({MORPHEUS_PORT: True}).install(monkeypatch)
        said: list[str] = []

        b.MorpheusBridge.connect(config_path=path, on_try=said.append)

        assert said == []

    def test_it_remembers_what_it_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The end the whole thing is for: one sweep, then never again."""
        path = str(tmp_path / "config.toml")
        _Rig({MORPHEUS_PORT: True}, ports=[OTHER_PORT, MORPHEUS_PORT]).install(
            monkeypatch
        )

        b.MorpheusBridge.connect(config_path=path)

        assert cfg.load_last_port(path) == MORPHEUS_PORT

    def test_the_next_launch_does_not_sweep(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "config.toml")
        first = _Rig({MORPHEUS_PORT: True}, ports=[OTHER_PORT, MORPHEUS_PORT])
        first.install(monkeypatch)
        b.MorpheusBridge.connect(config_path=path)
        assert first.swept == 1

        second = _Rig({MORPHEUS_PORT: True}, ports=[OTHER_PORT, MORPHEUS_PORT])
        second.install(monkeypatch)
        b.MorpheusBridge.connect(config_path=path)

        assert second.swept == 0
        assert second.opened == [MORPHEUS_PORT]

    def test_nothing_answered_is_the_sweeps_own_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The user needs the sweep's sentence, not the stale port's."""
        path = _remembered(tmp_path)
        _Rig({MORPHEUS_PORT: False, OTHER_PORT: False}).install(monkeypatch)

        with pytest.raises(b.DeviceError, match="nothing answered"):
            b.MorpheusBridge.connect(config_path=path)


# --- remembered device id ----------------------------------------------------


class TestRememberedDeviceId:
    def test_remembered_port_is_probed_with_remembered_device_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        cfg.save_device_id(7, path)
        rig = _Rig({MORPHEUS_PORT: True}).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path)

        assert rig.probes, "the remembered port was not probed"
        assert rig.probes[0] == (MORPHEUS_PORT, 7)

    def test_no_remembered_device_id_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        rig = _Rig({MORPHEUS_PORT: True}).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path)

        assert rig.probes, "the remembered port was not probed"
        assert rig.probes[0] == (MORPHEUS_PORT, 0)

    def test_a_dead_remembered_probe_falls_back_and_announces(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        cfg.save_device_id(7, path)
        rig = _Rig({MORPHEUS_PORT: False, OTHER_PORT: True}).install(
            monkeypatch
        )
        said: list[str] = []

        bridge = b.MorpheusBridge.connect(config_path=path, on_try=said.append)

        assert rig.swept == 1
        assert bridge.port == OTHER_PORT
        assert rig.probes[0] == (MORPHEUS_PORT, 7)
        assert said[0] == f"{MORPHEUS_PORT} (remembered, did not answer)"

    def test_scan_skips_the_remembered_probe(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        cfg.save_device_id(7, path)
        rig = _Rig(
            {OTHER_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]
        ).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path, scan=True)

        assert all(p[0] != MORPHEUS_PORT for p in rig.probes), (
            "the remembered port was probed under --scan"
        )
        assert rig.opened == [OTHER_PORT]


# --- the sweep's order: the point of the 2026-10-16 fix -----------------


class TestTheSweepsOrder:
    """A device-7 unit used to need eight passes over every port.

    The order is now: the ID we were given, then 0, then the rest; the
    remembered port first. `autodetect` is the real one here (not the
    stub), because the ordering is what is under test.
    """

    def test_the_remembered_id_leads_the_sweep(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _remembered(tmp_path)
        cfg.save_device_id(7, path)
        rig = _Rig(
            {OTHER_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]
        ).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path, scan=True)

        assert rig.sweep_calls == [(7, MORPHEUS_PORT)]

    def test_the_given_id_is_asked_first_across_ports(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        rig = _Rig(
            {MORPHEUS_PORT: True}, ports=[OTHER_PORT, MORPHEUS_PORT]
        ).install(monkeypatch, stub_autodetect=False)

        bridge = b.MorpheusBridge.autodetect(
            device_id=7, preferred_port=MORPHEUS_PORT
        )

        assert rig.probes[0] == (MORPHEUS_PORT, 7)
        assert bridge.port == MORPHEUS_PORT
        assert bridge.swept is True

    def test_the_preferred_port_is_tried_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        rig = _Rig(
            {MORPHEUS_PORT: True}, ports=[OTHER_PORT, MORPHEUS_PORT]
        ).install(monkeypatch, stub_autodetect=False)

        b.MorpheusBridge.autodetect(preferred_port=MORPHEUS_PORT)

        assert rig.opened[0] == MORPHEUS_PORT

    def test_zero_is_second_and_the_rest_follow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """With nothing given, a unit on the default is found in one step
        and the widening is still finite and in order."""
        rig = _Rig(
            {},
            ports=[MORPHEUS_PORT],
            answering_on_id={(MORPHEUS_PORT, 3): True},
        ).install(monkeypatch, stub_autodetect=False)

        b.MorpheusBridge.autodetect()

        assert [device for _port, device in rig.probes] == [0, 1, 2, 3]

    def test_one_line_per_port_names_the_ids(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A slow sweep says what it is doing without 656 lines."""
        _Rig({MORPHEUS_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]).install(
            monkeypatch, stub_autodetect=False
        )
        said: list[str] = []

        b.MorpheusBridge.autodetect(
            device_id=7, preferred_port=MORPHEUS_PORT, on_try=said.append
        )

        assert len(said) == 1, "more than one line for one port"
        assert said[0].startswith(f"{MORPHEUS_PORT} (device 7, 0, 1, 2")


class TestTheProbesShortlist:
    def test_zero_is_tried_after_a_dead_remembered_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A fresh install has no remembered ID and a unit on 0: the probe
        tries 7 (on file), then 0, and never sweeps."""
        path = _remembered(tmp_path)
        cfg.save_device_id(7, path)
        rig = _Rig({}, answering_on_id={(MORPHEUS_PORT, 0): True}).install(
            monkeypatch
        )

        bridge = b.MorpheusBridge.connect(config_path=path)

        assert rig.swept == 0
        assert rig.probes == [(MORPHEUS_PORT, 7), (MORPHEUS_PORT, 0)]
        assert bridge.port == MORPHEUS_PORT
        assert bridge.swept is False
