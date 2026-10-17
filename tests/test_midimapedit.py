# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure tests for emorphed/edit.py, midimap data framing, and the demo
midimap seed."""

from __future__ import annotations

import pytest

from emorphed import edit as E
from emorphed.demo import DemoDevice, _seed_midimap
from emu import messages as m
from emu import midimap as mm

#: The largest fourteen-bit word a midimap body carries.
_WORD_MAX = 0x3FFF


def test_gate_locked_refuses_allow() -> None:
    editor = E.MidimapEditor()
    assert editor.allow(14, 10) is not None
    assert (
        editor.gate.refuse() == "the write gate is locked; press w to arm it"
    )


def test_arm_then_allows() -> None:
    editor = E.MidimapEditor()
    editor.gate.toggle()
    assert editor.gate.armed is True
    assert editor.allow(14, 10) is None


def test_value_outside_range_refused_with_range() -> None:
    editor = E.MidimapEditor()
    editor.gate.toggle()
    refusal = editor.allow(14, 999)  # Ch. Volume 0-127
    assert refusal is not None
    assert "0-127" in refusal
    # choices too: offset 13 Ch. Bank 0-4
    refusal2 = editor.allow(13, 9)
    assert refusal2 is not None
    assert "0-4" in refusal2


def test_unknown_offset_refused() -> None:
    editor = E.MidimapEditor()
    editor.gate.toggle()
    assert editor.allow(10_000, 1) is not None


def test_finish_matching_logs_and_returns_true() -> None:
    editor = E.MidimapEditor()
    editor.gate.toggle()
    # ensure allowed
    assert editor.allow(14, 7) is None
    ok, sentence = editor.finish(14, 7, 7)
    assert ok is True
    assert len(editor.log) == 1
    assert " -> " in sentence
    # a mismatch does not log
    before = len(editor.log)
    ok2, msg = editor.finish(14, 7, 9)
    assert ok2 is False
    assert len(editor.log) == before
    assert "reports" in msg or "still" in msg


def test_take_consumes_and_newest_first() -> None:
    log = E.EditLog()
    log.push(E.Edit(1, 0, 1))
    log.push(E.Edit(2, 0, 2))
    got = log.take(2)
    assert [e.offset for e in got] == [2, 1]
    assert len(log) == 0
    assert log.take(1) == []


def test_undo_plan_newest_first() -> None:
    editor = E.MidimapEditor()
    editor.gate.toggle()
    editor.log.push(E.Edit(1, 10, 20))
    editor.log.push(E.Edit(2, 30, 40))
    plan = editor.undo_plan(2)
    assert [e.offset for e in plan] == [2, 1]
    assert len(editor.log) == 0


def test_undo_report_voice() -> None:
    editor = E.MidimapEditor()
    assert editor.undo_report(0, 0) == "nothing to undo"
    assert editor.undo_report(3, 0) == "undid 3"
    assert editor.undo_report(2, 1) == "undid 2; 1 failed"
    assert editor.undo_report(0, 2) == "undo failed: 2"


def test_midimap_data_roundtrip() -> None:
    words = [i % 1000 for i in range(360)]
    frame = m.midimap_data(words, number=3)
    assert len(frame) == m.MIDIMAP_DATA_BYTES
    pkt = m.parse(frame)
    assert pkt is not None
    assert pkt.number == 3  # noqa: PLR2004
    assert pkt.words() == words


def test_edit_gate_toggle_describe() -> None:
    g = E.EditGate()
    assert g.armed is False
    assert "locked" in g.describe()
    g.toggle()
    assert g.armed is True
    assert g.refuse() is None


def test_demo_send_midimap() -> None:
    words = [5] * 360
    dev = DemoDevice()
    dev.send_midimap(2, words)
    assert dev.midimap_stores[-1] == (2, words)
    assert dev.read_midimap(2) == words


def test_demo_send_midimap_word_count() -> None:
    dev = DemoDevice()
    short = [5] * 359
    with pytest.raises(m.ProtocolError):
        dev.send_midimap(2, short)
    # a 360-word map still stores and reads back
    words = [7] * 360
    dev.send_midimap(2, words)
    assert dev.midimap_stores[-1] == (2, words)
    assert dev.read_midimap(2) == words


# --- the demo midimap seed (D1) ------------------------------------------


def test_demo_read_midimap_returns_the_seed() -> None:
    assert DemoDevice().read_midimap(0) == _seed_midimap()


def test_seed_is_a_deterministic_360_word_map() -> None:
    seed = _seed_midimap()
    assert len(seed) == 360  # noqa: PLR2004
    assert seed == _seed_midimap()
    assert all(0 <= word <= _WORD_MAX for word in seed)


def test_seed_name_is_the_invented_twelve_characters() -> None:
    name = mm.name_of(_seed_midimap())
    assert name == "Demo Midimap"
    assert len(name) == 12  # noqa: PLR2004
    assert all(32 <= ord(char) < 128 for char in name)  # noqa: PLR2004


def test_seed_channel_one_holds_the_expected_values() -> None:
    seed = _seed_midimap()
    # These offsets are the manual's (midimap.PARAMS): channel 1 runs from
    # offset 12, and the first twenty words are one channel block.
    assert mm.param_at(12).label == "Ch. Program"
    assert seed[12] == 0  # Ch. Program
    assert seed[13] == 0  # Ch. Bank, RAM Presets
    assert seed[14] == 100  # noqa: PLR2004  # Ch. Volume
    assert seed[15] == 0  # Ch. Pan, "0"
    assert seed[16] == 0  # Ch. Mix Bus, Main
    assert seed[17] == 1  # Ch. Enable
    assert seed[18] == 1  # Ch. ProgChg Enbl
    assert seed[19] == 1  # Ch. BankChg Enbl
    assert seed[20] == 1  # Ch. VolCtl Enbl


def test_seed_channel_two_differs_from_channel_one() -> None:
    seed = _seed_midimap()
    # Channel 2 starts one twenty-word block later, at offset 32.
    assert mm.param_at(32).label == "Ch. Program"
    assert seed[32] == 1  # Ch. Program
    assert seed[34] == 90  # noqa: PLR2004  # Ch. Volume
    assert seed[37] == 1  # Ch. Enable
    assert (seed[32], seed[34]) != (seed[12], seed[14])


def test_seed_leaves_channels_three_to_sixteen_disabled() -> None:
    seed = _seed_midimap()
    for channel in range(3, 17):
        base = 12 + (channel - 1) * 20
        assert mm.param_at(base + 5).label == "Ch. Enable"
        assert seed[base : base + 20] == [0] * 20


def test_seed_sets_a_named_fx_a_type_and_one_of_its_params() -> None:
    seed = _seed_midimap()
    fx_type = mm.param_at(333)
    assert fx_type.label == "FX A Type"
    assert mm.spell(fx_type, seed[333]) == "Room"
    params = mm.fx_params_for(seed[333])
    assert params, "the seeded effect type defines a parameter"
    label, low, high, _choices = params[0]
    assert label == "Decay Time"  # the manual's name for Room's parameter
    first_param = mm.offset_of("FX A Parm Vals")
    assert first_param == 334  # noqa: PLR2004
    assert low <= seed[first_param] <= high
    assert seed[first_param] != 0


def test_demo_read_parameter_answers_the_seed() -> None:
    dev = DemoDevice()
    seed = _seed_midimap()
    for offset in (12, 13, 14, 15, 16, 17, 32, 34, 333, 334):
        assert dev.read_parameter(mm.PARAM_BASE + offset) == seed[offset]


def test_demo_scratch_and_stored_both_start_as_the_seed() -> None:
    dev = DemoDevice()
    seed = _seed_midimap()
    assert dev.read_midimap(0) == seed
    # The scratch map is what a parameter read answers from, and it starts
    # from the same seed as the stored dump.
    assert dev.read_scratch_params() == seed
