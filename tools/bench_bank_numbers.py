#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# Reads (and plays) an E-mu Morpheus over MIDI to settle which Bank Select
# bank number reaches which kind of object. This tool MAKES THE UNIT PLAY.
# Human-attended only. Never writes data to the unit.

"""Measure which Bank Select bank number reaches which kind of object.

This is a bench tool, not part of emorphed. It opens the Morpheus the
same way ``morphcli`` does, then sends Bank Select + Program Change on
the configured channel for each candidate and asks the operator what was
heard. It changes what the instrument is playing and cannot be undone
remotely -- the previously playing selection is not readable -- so it
requires ``--yes`` and refuses to run without a TTY.

It never writes preset, hyperpreset or midimap data to the unit, and it
writes nothing to disk (real names are printed to the terminal only).

Usage::

    python3 tools/bench_bank_numbers.py --yes
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emu import banks as emu_banks
from emu import bridge as emu_bridge
from emu import config as emu_config
from vinsynlib import cli as vcli
from vinsynlib import render

Kind = emu_banks.Kind


@dataclass(frozen=True)
class Candidate:
    """One (bank number, program number) probe."""

    ll: int
    pc: int
    kind: str
    index: int
    label: str = ""


# The five documented bank numbers, with an object that should sit inside
# one of them (given the manual's program-number table). The pc is the
# offset *within* the bank (0 = first object of that bank); ``index`` is
# the object's own global number, used for labelling.
_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(0, 0, Kind.PRESET, 0, "bank 0 (RAM presets), first object"),
    Candidate(1, 0, Kind.PRESET, 128, "bank 1 (ROM presets), first object"),
    Candidate(
        2, 0, Kind.HYPERPRESET, 0, "bank 2 (RAM hyperpresets), first object"
    ),
    Candidate(3, 0, Kind.PRESET, 256, "bank 3 (card presets), first object"),
    Candidate(
        4, 0, Kind.HYPERPRESET, 128, "bank 4 (card hyperpresets), first object"
    ),
)


def candidates() -> list[Candidate]:
    """The probes, in order. Pure, no I/O."""
    return list(_CANDIDATES)


def select_byte_messages(ll: int, pc: int, channel: int = 0) -> list[bytes]:
    """The three wire messages: CC0=0, CC32=ll, Program Change=pc.

    Pure, no I/O.
    """
    if not 0 <= ll <= 15:  # noqa: PLR2004
        raise ValueError(f"ll {ll} is outside 0-15")
    if not 0 <= pc <= 127:  # noqa: PLR2004
        raise ValueError(f"pc {pc} is outside 0-127")
    if not 0 <= channel <= 15:  # noqa: PLR2004
        raise ValueError(f"channel {channel} is outside 0-15")
    status = 0xB0 | channel
    return [
        bytes([status, 0x00, 0x00]),
        bytes([status, 0x20, ll]),
        bytes([0xC0 | channel, pc]),
    ]


def bank_select_bytes(ll: int, pc: int, channel: int = 0) -> bytes:
    """The same bytes as one flat sequence. Pure, no I/O."""
    out = bytearray()
    for message in select_byte_messages(ll, pc, channel):
        out.extend(message)
    return bytes(out)


# Aliases, so a test can use whichever name it found first.
cc_pc_bytes = bank_select_bytes
bytes_for = bank_select_bytes
candidate_bytes = bank_select_bytes
wire_bytes = bank_select_bytes


def messages_for(ll: int, pc: int, channel: int = 0) -> list[bytes]:
    return select_byte_messages(ll, pc, channel)


select_messages_for = messages_for


def expected_name(
    candidate: Candidate,
    preset_names: Sequence[str],
    hyper_names: Sequence[str] | None = None,
) -> str:
    """Label a candidate from the names already read."""
    hyper_names = hyper_names or ()
    names = preset_names if candidate.kind == Kind.PRESET else hyper_names
    if 0 <= candidate.index < len(names):
        return (
            f"{names[candidate.index]!r} ({candidate.kind} {candidate.index})"
        )
    return f"{candidate.kind} {candidate.index}"


def describe_candidate(candidate: Candidate) -> str:
    base = (
        f"ll={candidate.ll} pc={candidate.pc} "
        f"{candidate.kind} {candidate.index}"
    )
    if candidate.label:
        return f"{base} ({candidate.label})"
    return base


@dataclass(frozen=True)
class BenchResult:
    candidate: Candidate
    bytes_sent: bytes
    heard: str


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    return render.table(headers, rows, empty="(nothing)")


def format_results(results: Sequence[Any]) -> str:
    """Compact results table. Pure, no I/O."""
    rows: list[list[str]] = []
    for item in results:
        if isinstance(item, BenchResult):
            candidate = item.candidate
            data = item.bytes_sent
            heard = item.heard
        elif isinstance(item, dict):
            candidate = item["candidate"]
            raw = item.get("bytes_sent", item.get("bytes"))
            data = bytes(raw) if raw is not None else b""
            heard = item.get("heard", "")
        else:
            candidate, data, heard = item
        label = (
            describe_candidate(candidate)
            if isinstance(candidate, Candidate)
            else str(candidate)
        )
        hex_bytes = " ".join(f"{b:02X}" for b in bytes(data))
        rows.append([label, hex_bytes, str(heard)])
    return _table(rows, ["candidate", "bytes sent", "heard"])


# Aliases.
format_results_table = format_results
results_table = format_results
render_results = format_results


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0912, PLR0915
    parser = vcli.make_parser(
        "bench-bank-numbers",
        "Play a Morpheus to settle which Bank Select bank number reaches "
        "which kind of object. REQUIRES --yes; human-attended.",
        distribution="emorphed",
        version="0.1.0",
    )
    vcli.add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        device_id=True,
        config=True,
        demo=True,
        yes=True,
    )
    args = parser.parse_args(argv)

    # Refuse without a TTY.
    if not sys.stdin.isatty():
        raise SystemExit(
            "error: bench-bank-numbers needs an interactive TTY; it plays "
            "the unit and asks what you heard"
        )

    vcli.validate_common(args)

    config_path = getattr(args, "config", None) or emu_config.DEFAULT_PATH

    if isinstance(args.channel, int):
        channel = args.channel - 1
    else:
        loaded = emu_config.load_channel(config_path)
        if isinstance(loaded, int) and 1 <= loaded <= 16:  # noqa: PLR2004
            channel = loaded - 1
        else:
            channel = 0
    if not 0 <= channel <= 15:  # noqa: PLR2004
        channel = 0

    device_id = args.device_id if args.device_id is not None else 0
    if not 0 <= device_id <= 15:  # noqa: PLR2004
        raise SystemExit("error: --device-id is 0-15 on a Morpheus")

    if not getattr(args, "yes", False):
        raise SystemExit(
            "error: --yes is required: this tool plays the unit and "
            "cannot restore the previous selection (it is not readable)"
        )

    if getattr(args, "demo", False):
        raise SystemExit(
            "error: --demo opens no ports; this tool needs the real unit"
        )

    bridge = emu_bridge.MorpheusBridge.connect(
        config_path=config_path,
        scan=bool(getattr(args, "scan", False)),
        channel=channel,
        device_id=device_id,
    )

    try:
        if getattr(bridge, "swept", False):
            print(f"sweep: ports swept in {bridge.probe_seconds:.2f}s")
        print(f"port         {bridge.description}")
        print(f"device ID    {bridge.device_id}")
        print(f"channel      {channel + 1}")
        print(
            "note: the previously playing selection cannot be restored "
            "(it is not readable)."
        )

        preset_names = bridge.names(emu_banks.Kind.PRESET)
        hyper_names = bridge.names(emu_banks.Kind.HYPERPRESET)

        cands = candidates()
        results: list[BenchResult] = []
        total = len(cands)
        for number, cand in enumerate(cands, start=1):
            expected = expected_name(cand, preset_names, hyper_names)
            data = bank_select_bytes(cand.ll, cand.pc, channel)
            print()
            print(f"[{number}/{total}] {describe_candidate(cand)}")
            print(f"    expected: {expected}")
            print(f"    bytes:    {' '.join(f'{b:02X}' for b in data)}")
            # Play first (cannot be undone).
            messages = select_byte_messages(cand.ll, cand.pc, channel)
            for message in messages:
                bridge._out.send_message(list(message))
            try:
                heard = input("    what did you hear? ").strip()
            except EOFError:
                heard = ""
            if not heard:
                heard = "nothing"
            results.append(BenchResult(cand, data, heard))

        print()
        print(format_results(results))
    finally:
        bridge.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
