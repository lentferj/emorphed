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


# The five documented bank numbers, each with the object that is *supposed*
# to sit inside it -- a hypothesis from the manual's program-number table
# and the edisyn cross-check, NOT an assumption: the sources disagree about
# bank 2 (manual: card; edisyn: the card is bank 3), which is the whole
# reason this tool exists. The pc is the offset *within* the bank (0 = first
# object of that bank); ``index`` is the object's own global number, used
# for labelling. The operator's ears decide which label is true.
_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(0, 0, Kind.PRESET, 0, "bank 0 (hypothesis: RAM presets)"),
    Candidate(1, 0, Kind.PRESET, 128, "bank 1 (hypothesis: ROM presets)"),
    Candidate(
        2,
        0,
        Kind.HYPERPRESET,
        0,
        "bank 2 (hypothesis: RAM hyperpresets -- edisyn says the card)",
    ),
    Candidate(
        3,
        0,
        Kind.PRESET,
        256,
        "bank 3 (hypothesis: card presets -- manual says the card is bank 2)",
    ),
    Candidate(
        4, 0, Kind.HYPERPRESET, 128, "bank 4 (hypothesis: card hyperpresets)"
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
    parser.add_argument(
        "--sweep-channels",
        action="store_true",
        help="find which MIDI channel the unit answers a Program Change on, "
        "and stop: then run the bank candidates again with --channel N",
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

        if getattr(args, "sweep_channels", False):
            return _sweep_channels(bridge, preset_names, channel)

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


def _sweep_channels(
    bridge: Any, preset_names: Sequence[str], start: int
) -> int:
    """Which channel does the unit actually take a Program Change on?

    The 2026-10-16 first run sent Bank Select + PC on one channel and every
    candidate was ignored -- which says nothing about the bank numbers and
    everything about the channel the unit listens on (its MIDI mode and the
    current Midimap's MIDI Enables both gate it). This asks channel by
    channel, playing RAM preset 0 each time, until the operator says the
    preset changed. Order starts at the configured channel, so the common
    case is answered first.
    """
    first = preset_names[0] if preset_names else "the first RAM preset"
    order = [start] + [c for c in range(16) if c != start]
    for channel in order:
        data = bank_select_bytes(0, 0, channel)
        messages = select_byte_messages(0, 0, channel)
        print()
        print(
            f"channel {channel + 1}: sending "
            + " ".join(f"{b:02X}" for b in data)
        )
        for message in messages:
            bridge._out.send_message(list(message))
        try:
            answer = (
                input(f"    did it change to {first!r}? [y/N] ")
                .strip()
                .lower()
            )
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            print(
                f"\nchannel {channel + 1} answers a Program Change. Re-run "
                f"the bank candidates with: --channel {channel + 1}"
            )
            return 0
    print(
        "\nno channel changed the preset. Check the unit's MIDI mode "
        "(Omni listens to all; Poly/Multi use one channel) and the current "
        "Midimap's MIDI Enables and Program-to-Channel Assign."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
