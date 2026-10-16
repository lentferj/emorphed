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
    ) -> None:
        self.answering = answering
        self.ports = ports if ports is not None else list(answering)
        self.opened: list[str] = []
        self.tried: list[str] = []
        self.swept = 0
        self.made: list[_FakeBridge] = []
        self.probes: list[tuple[str, int]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _Rig:
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
                port, recv_port or port, answers=bool(rig.answering.get(port))
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
            on_try: Callable[[str], None] | None = None,
        ) -> _FakeBridge:
            # Mirrors the real one's shape -- device ID 0 on every port
            # first, then widening -- so that the widening is exercised
            # rather than stubbed away.
            rig.swept += 1
            for device_id in (0, *range(1, 16)):
                for name in rig.ports:
                    if on_try is not None:
                        on_try(f"{name} (device {device_id})")
                    rig.tried.append(name)
                    if rig.answering.get(name):
                        bridge = fake_open(cls, name, device_id=device_id)
                        return bridge
            raise b.DeviceError("nothing answered")

        monkeypatch.setattr(
            b, "list_ports", lambda: (list(rig.ports), list(rig.ports))
        )
        monkeypatch.setattr(b, "likely_ports", lambda: [])
        monkeypatch.setattr(b.MorpheusBridge, "open", classmethod(fake_open))
        monkeypatch.setattr(
            b.MorpheusBridge, "autodetect", classmethod(fake_autodetect)
        )
        return rig

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

    def test_scan_does_not_probe_the_remembered_port_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--scan asks for the sweep, not for a check of the file and then
        the sweep."""
        path = _remembered(tmp_path)
        rig = _Rig(
            {OTHER_PORT: True}, ports=[MORPHEUS_PORT, OTHER_PORT]
        ).install(monkeypatch)

        b.MorpheusBridge.connect(config_path=path, scan=True)

        assert rig.opened == [OTHER_PORT], "the saved port was probed first"

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
