# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# ruff: noqa: PLR2004
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Synthetic checks for the midimap write bench tool (no MIDI, no input)."""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

import pytest

from emu import midimap as mm

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "bench_midimap_write.py")


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("bench_midimap_write", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _tool()


def test_plan_picks_parameter_via_midimap_and_clamps() -> None:
    param = mm.param_at(14)  # Ch. Volume, 0-127
    # A normal nudge.
    plan = bench.plan(offset=14, old_value=100, delta=3)
    assert plan.param is param
    assert plan.parameter is param
    assert plan.label == "Ch. Volume"
    assert plan.old_value == 100
    assert plan.new_value == 103
    assert plan.nudged_value == 103
    # At the top of the range, a further nudge stays put.
    top = param.high
    plan_top = bench.plan(offset=14, old_value=top, delta=5)
    assert plan_top.new_value == top
    assert plan_top.nudged == top
    # clamp helper agrees.
    assert bench.clamp(top + 5, low=param.low, high=param.high) == top
    assert bench.nudge_value(old=top, delta=5, param=param) == top


def test_restore_value_is_always_original() -> None:
    for old in (0, 5, 100, 127):
        plan = bench.plan(offset=14, old_value=old, delta=7)
        assert plan.restore_value == old
        assert plan.original_value == old
        assert plan.old_value == old


def test_results_table_format_is_stable() -> None:
    rows = [
        (bench.STEP_WRITE, "Ch. Volume", 103, 103, "yes"),
        (bench.STEP_RESTORE, "Ch. Volume", 100, 100, "yes"),
    ]
    out = bench.format_results(rows)
    assert out == (
        "step |  parameter | value written | read-back | agreed?\n"
        "---- | ---------- | ------------- | --------- | -------\n"
        "   3 | Ch. Volume |           103 |       103 |     yes\n"
        "   4 | Ch. Volume |           100 |       100 |     yes"
    )


def test_refuses_without_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit):
        bench.main([])


def test_refuses_store_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the destructive store needs a human in the moment.

    The proof path is read-back verified -- the unit's dump is the oracle --
    so it runs unattended, the way p2ked's hardware write test does.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as caught:
        bench.main(["--yes", "--store", "3"])
    assert "--store needs an interactive TTY" in str(caught.value)


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as caught:
        bench.main(["--help"])
    assert caught.value.code == 0


def test_a_store_that_disagrees_fails_the_verdict() -> None:
    """The store is the destructive step; agreement is part of the verdict."""
    assert bench.exit_code(True, True) == 0
    assert (
        bench.exit_code(True, True, store_attempted=True, store_agreed=True)
        == 0
    )
    assert (
        bench.exit_code(True, True, store_attempted=True, store_agreed=False)
        == 1
    )
    # attempted with no result recorded is not a pass
    assert (
        bench.exit_code(True, True, store_attempted=True, store_agreed=None)
        == 1
    )
    assert bench.exit_code(True, False) == 1
    assert bench.exit_code(False, True) == 1


def test_count_agreeing_words() -> None:
    assert bench.count_agreeing_words([1, 2, 3], [1, 9, 3]) == 2
    assert bench.count_agreeing_words([1, 2], [1, 2, 3]) == 2
    assert bench.count_agreeing_words([], []) == 0


def testAliases_and_plan_at_top() -> None:
    # alias family should agree
    assert bench.make_plan(offset=14, old_value=1, delta=1).new_value == 2
    assert bench.calculate_plan(offset=14, old_value=1, delta=1).new_value == 2
    assert bench.nudge(127, 1, param=mm.param_at(14)) == 127
    assert bench.clamped(200, mm.param_at(14)) == 127


def test_movement_refuses_a_parameter_that_cannot_move() -> None:
    """The first run nudged volume 127 -> 127: a no-op that 'agreed'.

    A verification that cannot fail proves nothing, so the chooser picks the
    direction from the value and refuses a parameter at its limit.
    """

    volume = mm.param_at(mm.offset_of("Ch. Volume"))  # 0-127
    assert bench.movement(volume, 10, 1) == 11
    assert bench.movement(volume, 127, 1) == 126, "should step down at the top"
    assert bench.movement(volume, 0, -1) == 1, "should step up at the bottom"
    assert bench.movement(volume, 5, 0) is None
    assert bench.BENIGN_OFFSETS == ("Ch. Volume", "Ch. Pan", "Ch. Mix Bus")
