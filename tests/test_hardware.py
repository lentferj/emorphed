# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Tests against a real E-mu Morpheus. **Opt-in: see :mod:`tests.conftest`.**

Everything else in this suite runs against :mod:`emorphed.demo`, which is
the point of it -- the suite is fast, needs no hardware, and passes on a
machine with no MIDI stack at all. That is also its limit: a demo device
agrees with whatever emorphed believes, so every offset below the API
surface was only ever checked against emorphed's own transcription of
E-mu's documents, and the bridge has never talked to the instrument.

This file is the other half. It asks the machine, and the machine's answer
is the one that cannot be transcribed wrong:

* **Read-only, structural.** Frame shapes, counts, checksums, parsing. The
  list replies are streamed and take seconds, which is why the timeouts are
  the bank class.
* **Printed observations** for the bench questions in TODO.md items 1-4 and
  9, recorded rather than asserted -- the manual guarantees structure, not
  the unit's particular contents.

**What these tests deliberately do not do.** They never assert on a preset,
hyperpreset or midimap *name* (E-mu's ROM contents are not this project's
to redistribute). They never *select* a preset -- that changes what plays,
and it stays behind its own confirmation in the app. The card-select
question (TODO 9) is listed here as a manual bench step only; this suite
prints which card regions emorphed's map knows about and stops, because
selecting would make the unit play.

The bank request test (U4) writes one full frame per distinct frame length
to the directory named by ``EMORPHED_BANK_CAPTURE`` (default
``/tmp/opencode``) as raw ``.syx`` bytes, so the 674-byte framing question
(TODO item 1) now has a capture step a human can run: set the variable (or
use the default) and run ``make test-hardware``. The default directory is
outside the checkout on purpose -- raw captures never live in the repo.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from emu import banks
from emu import bridge as b
from emu import messages as m

#: A streamed list reply: 3.7 s measured for 128 preset names
#: (5000 B) at MIDI DIN speed; the 2.0 s request timeout was the
#: bug, not the protocol.
LIST_TIMEOUT = b.BANK_TIMEOUT


def _collect(
    unit: b.MorpheusBridge,
    outgoing: bytes,
    wanted: int,
    *,
    timeout: float,
    inactivity: float = 0.5,
) -> list[bytes]:
    """Send ``outgoing`` and gather every reply with command ``wanted``.

    The instrument may answer a large request with one SysEx or with several
    spaced in time; this collects until nothing arrives for ``inactivity``
    seconds or ``timeout`` elapses. Returns the raw frame bytes, so callers
    can check things parse() strips (the trailing checksum, the frame size).
    """
    unit._drain()
    unit._out.send_message(list(outgoing))
    deadline = time.time() + timeout
    frames: list[bytes] = []
    last = time.time()
    while time.time() < deadline:
        message = unit._in.get_message()
        if message is None:
            if frames and (time.time() - last) >= inactivity:
                break
            time.sleep(0.002)
            continue
        data = bytes(message[0])
        packet = m.parse(data)
        if (
            packet is None
            or packet.command != wanted
            or packet.device != unit.device_id
        ):
            continue
        frames.append(data)
        last = time.time()
    return frames


def frames_in(blob: bytes) -> list[bytes]:
    """Split a blob at every F0 (a message may carry several frames)."""
    starts = [i for i, byte in enumerate(blob) if byte == m.SYSEX_START]
    if not starts:
        return []
    out: list[bytes] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(blob)
        out.append(blob[start:end])
    return out


def _capture_one_frame_per_length(
    frames: list[bytes], capture_dir: Path
) -> list[tuple[Path, int]]:
    """Write one full frame per distinct length.

    Return (path, length) pairs.
    """
    seen: set[int] = set()
    captured: list[tuple[Path, int]] = []
    for frame in frames:
        if len(frame) in seen:
            continue
        seen.add(len(frame))
        path = capture_dir / f"bank_frame_{len(frame)}.syx"
        path.write_bytes(frame)
        captured.append((path, len(frame)))
    return captured


class TestHardwareIdentity:
    def test_version_round_trips_with_the_device_id(
        self, unit: b.MorpheusBridge
    ) -> None:
        """A Version Request is the smallest, safest probe."""
        outgoing = m.version_request(device=unit.device_id)
        # Frame shape of the request: F0 18 0C <id> 0A F7.
        assert len(outgoing) == 6  # noqa: PLR2004
        assert outgoing[0] == m.SYSEX_START and outgoing[-1] == m.SYSEX_END

        packet = unit.request(outgoing, m.Command.VERSION_DATA)
        assert packet.command == m.Command.VERSION_DATA
        # The reply carries this unit's device ID, not a broadcast.
        assert packet.device == unit.device_id
        returned = unit.version()
        assert returned == list(packet.body)

        print(
            f"\nversion: request {len(outgoing)} bytes, reply "
            f"{sum(1 for _ in packet.body) + 10} bytes (body "
            f"{len(packet.body)}), device id {packet.device}, body "
            + " ".join(f"{value:02X}" for value in returned)
        )


class TestHardwareConfiguration:
    def test_configuration_is_well_formed_and_prints_what_is_fitted(
        self, unit: b.MorpheusBridge
    ) -> None:
        config = unit.configuration()
        assert isinstance(config, list)
        assert len(config) > 0
        assert all(0 <= value <= 0x7F for value in config)  # noqa: PLR2004

        # Printed observations, not assertions: the Configuration byte layout
        # is not established in docs (TODO item 2).
        print(
            "\nconfiguration bytes: "
            + " ".join(f"{value:02X}" for value in config)
        )
        print(
            "regions emorphed maps (index-vs-display-number rule, 0.4.2-era): "
            + ", ".join(
                f"{region.id}={region.count}" for region in banks.REGIONS
            )
        )
        print(
            f"preset address span: {banks.TOTAL_PRESETS} indices "
            "(manual says 256-319 card = 320; banks-of-128 says 0-383 = 384)"
        )

        # The card question, TODO 9: no select, no Program Change. Just say
        # which regions in emorphed's map are card-backed, record them, stop.
        print("card-backed regions emorphed knows about:")
        for region in banks.REGIONS:
            if region.needs_card:
                print(
                    f"  {region.id} ({region.label}): indices "
                    f"{region.first}-{region.last}, {region.count} of them, "
                    f"writable={region.writable}"
                )
        print(
            "MANUAL BENCH STEP (TODO 9, do not automate): select a card "
            "preset first with CC32 bank 2, then bank 3, and see which "
            "arrives. This suite sends no Bank Select and no Program Change."
        )


class TestHardwareNames:
    @pytest.mark.parametrize("kind", list(banks.Kind.ALL))
    def test_names_one_exchange_per_kind(
        self, unit: b.MorpheusBridge, kind: str
    ) -> None:
        request = {
            banks.Kind.PRESET: m.preset_list_request,
            banks.Kind.HYPERPRESET: m.hyperpreset_list_request,
            banks.Kind.MIDIMAP: m.midimap_list_request,
        }[kind]
        reply_command = banks.Kind.LIST_REPLY[kind]
        outgoing = request(device=unit.device_id)
        packet = unit.request(outgoing, reply_command, timeout=LIST_TIMEOUT)

        # The reply opens with a fourteen-bit count; the parsed list is
        # structural only -- no names are asserted on.
        assert len(packet.body) >= 2  # noqa: PLR2004
        count_word = packet.body[0] | (packet.body[1] << 7)
        names = m.parse_name_list(packet)

        assert len(names) == count_word, (
            f"{kind}: parse_name_list returned {len(names)} names but the "
            f"reply word said {count_word}"
        )
        for name in names:
            assert len(name) == m.NAME_CHARS, (
                f"{kind}: name {name!r} is {len(name)} chars, not "
                f"{m.NAME_CHARS}"
            )
            assert all(32 <= ord(char) < 127 for char in name), (  # noqa: PLR2004
                f"{kind}: name {name!r} is not all ASCII 32-127"
            )

        mapped_total = sum(r.count for r in banks.regions(kind))
        card_total = sum(r.count for r in banks.regions(kind) if r.needs_card)
        assert (
            count_word == mapped_total
            or (mapped_total - count_word) == card_total
        ), (
            f"{kind}: count word {count_word}, mapped total {mapped_total}, "
            f"card total {card_total}"
        )
        if count_word != mapped_total:
            print("no card fitted")

        print(
            f"\nnames({kind}): request {len(outgoing)} bytes, "
            f"{len(names)} names, count word {count_word}"
        )


class TestHardwarePresetRead:
    def test_one_ram_preset_is_a_566_byte_frame_with_a_good_checksum(
        self, unit: b.MorpheusBridge
    ) -> None:
        index = 0
        outgoing = m.preset_request(index, device=unit.device_id)
        frames = _collect(
            unit, outgoing, m.Command.PRESET_DATA, timeout=unit.timeout
        )
        assert frames, "no preset reply came back"
        frame = frames[0]

        # Frame shape: 566 bytes total for a Preset Data message.
        assert len(frame) == m.PRESET_DATA_BYTES

        packet = m.parse(frame)
        assert packet is not None
        assert packet.command == m.Command.PRESET_DATA
        assert packet.number == index

        # Checksum status for the audit trail: recompute over the data bytes
        # and compare with the trailing byte the unit sent.
        computed = m.checksum(packet.body)
        sent = frame[-2]  # frame[-1] is F7
        assert sent == computed, (
            f"preset {index}: sent checksum {sent:#04x}, recomputed "
            f"{computed:#04x}"
        )

        # Words re-decode from the body byte pairs.
        words = packet.words()
        assert words == m.from_words(packet.body)
        assert len(words) == (m.PRESET_DATA_BYTES - 10) // 2

        print(
            f"\nread_preset({index}): frame {len(frame)} bytes, body "
            f"{len(packet.body)} bytes, checksum sent {sent:#04x} recomputed "
            f"{computed:#04x} (match), {len(words)} words re-decode"
        )


class TestHardwareBankRequest:
    def test_preset_bank_request_records_checksum_status_per_frame(
        self, unit: b.MorpheusBridge
    ) -> None:
        # Full-bank read: 128 presets, the 40 s timeout class.
        outgoing = m.preset_bank_request(0, device=unit.device_id)
        blobs = _collect(
            unit,
            outgoing,
            m.Command.PRESET_DATA,
            timeout=b.BANK_TIMEOUT,
            inactivity=3.0,
        )

        # A single rtmidi message may carry several F0 frames; split them.
        frames: list[bytes] = []
        for blob in blobs:
            frames.extend(frames_in(blob))

        # How many frames of each length.
        length_counts: dict[int, int] = {}
        for frame in frames:
            length_counts[len(frame)] = length_counts.get(len(frame), 0) + 1

        # The number field's stride across the bank.
        numbers: list[int] = []
        for frame in frames:
            packet = m.parse(frame)
            if packet is not None and packet.number is not None:
                numbers.append(packet.number)
        diffs = sorted(
            {numbers[i + 1] - numbers[i] for i in range(len(numbers) - 1)}
        )

        # Checksums verified only for single frames of a known size.
        known_lengths = set(m.Command.SIZES.values())
        checked = 0
        matched = 0
        for frame in frames:
            if len(frame) in known_lengths:
                packet = m.parse(frame)
                if packet is not None:
                    checked += 1
                    if frame[-2] == m.checksum(packet.body):
                        matched += 1

        lengths_summary = ", ".join(
            f"{length}x{count}"
            for length, count in sorted(length_counts.items())
        )
        print(
            f"\npreset_bank_request(0): {len(frames)} frame(s); "
            f"lengths: {lengths_summary}; number stride: {diffs}; "
            f"checksums {matched}/{checked} on known-size frames"
        )
        # Capture one full frame per distinct length as raw SysEx bytes, so
        # the 674-byte framing can be analysed later. No decoding, no
        # assertion about the framing.
        capture_dir = Path(
            os.environ.get("EMORPHED_BANK_CAPTURE", "/tmp/opencode")  # noqa: S108
        )
        capture_dir.mkdir(parents=True, exist_ok=True)
        captured = _capture_one_frame_per_length(frames, capture_dir)
        for path, length in captured:
            print(f"captured bank frame: {path} ({length} bytes)")

        # Recorded, not asserted: the reply/absence resolves TODO item 1's
        # bank-request question. The 674-byte framing is an open question
        # and is recorded here, not decided.


class TestHardwareTiming:
    def test_two_spaced_preset_requests_are_both_answered(
        self, unit: b.MorpheusBridge
    ) -> None:
        gap = b.PRESET_GAP

        first = unit.read_preset(0)
        start = time.perf_counter()
        time.sleep(gap)
        after_sleep = time.perf_counter()
        second = unit.read_preset(0)
        end = time.perf_counter()

        assert first and second
        print(
            f"\ntiming: requested gap {gap * 1000:.1f} ms between two "
            f"preset requests; observed spacing "
            f"{(after_sleep - start) * 1000:.1f} ms; first reply "
            f"{len(first)} words, second {len(second)} words; total "
            f"{(end - start) * 1000:.1f} ms. PRESET_GAP (TODO 3) is a "
            "guess until this is recorded."
        )

    def test_gap_sweep_reports_the_largest_answered_gap(
        self, unit: b.MorpheusBridge
    ) -> None:
        gaps = (0.0, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25)

        # Warm read: exercise the path once before measuring.
        unit.read_preset(0, timeout=b.DEFAULT_TIMEOUT)

        answered: list[float] = []
        first_unanswered: float | None = None
        for gap in gaps:
            try:
                first = unit.read_preset(0, timeout=b.DEFAULT_TIMEOUT)
                time.sleep(gap)
                second = unit.read_preset(0, timeout=b.DEFAULT_TIMEOUT)
                ok = bool(first) and bool(second)
            except Exception:
                ok = False
            if ok:
                answered.append(gap)
                print(
                    f"\ngap sweep: gap {gap * 1000:.1f} ms answered "
                    f"({len(first)} + {len(second)} words)"
                )
                continue
            first_unanswered = gap
            print(f"\ngap sweep: gap {gap * 1000:.1f} ms NOT answered")
            break

        largest = answered[-1] if answered else None
        largest_ms = largest * 1000 if largest is not None else 0.0
        first_ms = (
            first_unanswered * 1000 if first_unanswered is not None else -1.0
        )
        print(
            f"\ngap sweep: largest answered gap {largest_ms:.1f} ms; "
            f"first unanswered {first_ms:.1f} ms. "
            "PRESET_GAP (TODO 3) stays a guess until recorded."
        )
