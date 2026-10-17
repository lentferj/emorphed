# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure tests for emorphed/edit.py and midimap data framing."""

from __future__ import annotations

import pytest

from emorphed import edit as E
from emorphed.demo import DemoDevice
from emu import messages as m


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
