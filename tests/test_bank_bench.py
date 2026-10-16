# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Synthetic checks for the bank-number bench tool (no MIDI, no input)."""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "bench_bank_numbers.py")


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("bench_bank_numbers", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _tool()


def test_candidate_set_covers_banks_and_card() -> None:
    cands = bench.candidates()
    assert {c.ll for c in cands} == {0, 1, 2, 3, 4}
    assert any(c.index == 256 for c in cands), "card's first preset missing"  # noqa: PLR2004
    # one probe per documented bank number
    assert len({c.ll for c in cands}) == 5  # noqa: PLR2004


def test_bytes_are_documented_bank_select() -> None:
    msgs = bench.select_byte_messages(2, 7, 3)
    assert msgs == [
        bytes([0xB3, 0x00, 0x00]),
        bytes([0xB3, 0x20, 0x02]),
        bytes([0xC3, 0x07]),
    ]
    flat = bench.bank_select_bytes(2, 7, 3)
    assert flat == bytes([0xB3, 0x00, 0x00, 0xB3, 0x20, 0x02, 0xC3, 0x07])
    # alias agreement
    assert bench.bytes_for(1, 0, 0) == bench.cc_pc_bytes(1, 0, 0)


def test_results_table_format_is_stable() -> None:
    cand = bench.Candidate(3, 0, bench.Kind.PRESET, 256, "card")
    result = bench.BenchResult(
        cand, bench.bank_select_bytes(3, 0, 0), "card piano"
    )
    out = bench.format_results([result])
    assert out == (
        "                  candidate |              bytes sent |      heard\n"
        "--------------------------- | ----------------------- | ----------\n"
        "ll=3 pc=0 preset 256 (card) | B0 00 00 B0 20 03 C0 00 | card piano"
    )


def test_refuses_without_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit):
        bench.main([])


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as caught:
        bench.main(["--help"])
    assert caught.value.code == 0
