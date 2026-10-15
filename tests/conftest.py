# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""The ``--hardware`` option, and the unit fixture for the file that uses it.

**Nothing here runs unless you ask for it.** CLAUDE.md's hardware rule is
that only one session drives a unit at a time, so the suite that talks to
a real E-mu Morpheus is opt-in twice over: the ``--hardware`` flag, and the
machine actually answering. ``make check`` -- and CI, which runs it -- never
passes the flag, so ``tests/test_hardware.py`` skips there by design rather
than by accident. The environment variable covers the case of a unit
plugged into a runner nobody meant to address.

A skip is a skip, not a pass. ``-rs`` names the reason, so "the unit was
off" and "the offsets are wrong" never look like the same green.
"""

import os
from collections.abc import Iterator

import pytest

from emu import bridge as b

#: Why the option is spelled out rather than folded into ``-m hardware``.
HELP = (
    "run the tests that need a real E-mu Morpheus on a MIDI port. They open "
    "the ports, so only one session may use them at a time. Without this "
    "flag they skip."
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("hardware", "tests against a real E-mu Morpheus")
    group.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help=HELP,
    )


def _asked_for_hardware(config: pytest.Config) -> bool:
    """The flag, or the environment variable that says the same thing."""
    return bool(config.getoption("hardware")) or bool(
        os.environ.get("EMORPHED_HARDWARE")
    )


@pytest.fixture(scope="session")
def unit(request: pytest.FixtureRequest) -> Iterator[b.MorpheusBridge]:
    """A live :class:`emu.bridge.MorpheusBridge`, or a skip saying why not.

    Session-scoped on purpose: one connection, one set of ports, held for
    the whole run rather than opened and closed per test -- the bridge learns
    the device ID and the port once.

    A failure to connect is a skip, never a failure. The reason lists every
    cause the manual gives rather than picking one, because this unit
    answers a request it cannot serve with silence and a timeout cannot say
    which of them it was: the unit may be powered off, on another port (USB
    renumbers them), busy with another session, or have "Master Exclusive"
    off. The skip never diagnoses a single cause, because the silence does
    not.
    """
    if not _asked_for_hardware(request.config):
        pytest.skip(
            "hardware tests need --hardware (or EMORPHED_HARDWARE=1); the "
            "suite that talks to a real E-mu Morpheus is opt-in because only "
            "one session may drive the unit"
        )

    try:
        connection = b.MorpheusBridge.connect()
    except Exception as exc:
        # One retry, sweeping. The remembered port may have been renumbered
        # since it was saved; the sweep is the only way to find it again.
        try:
            connection = b.MorpheusBridge.connect(scan=True)
        except Exception as exc2:
            pytest.skip(
                f"no E-mu Morpheus answered ({exc2}; remembered-port failure "
                f"was {exc}). The unit may be powered off, on another port "
                "(USB renumbers them), busy with another session, or have "
                '"Master Exclusive" off -- a request it cannot serve is '
                "answered with silence, so a timeout does not say which."
            )
    try:
        yield connection
    finally:
        connection.close()
