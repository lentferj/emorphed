# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""Synthetic tests for :mod:`emu.midimap`."""

from __future__ import annotations

import pytest

from emu import midimap


def test_count_and_shape() -> None:
    assert len(midimap.PARAMS) == 360  # noqa: PLR2004
    for param in midimap.PARAMS:
        assert param.low <= param.high
        assert param.label != ""


def test_offsets_unique_and_contiguous() -> None:
    offsets = [p.offset for p in midimap.PARAMS]
    assert sorted(offsets) == list(range(360))
    assert len(set(offsets)) == 360  # noqa: PLR2004


def test_param_base() -> None:
    assert midimap.PARAM_BASE == 2048  # noqa: PLR2004


def test_spot_name_block() -> None:
    # manual p.232: "0 Midimap Name 12 chars, ASCII 32-127"
    p = midimap.param_at(0)
    assert p.label == "Midimap Name"
    assert p.low == 32  # noqa: PLR2004
    assert p.high == 127  # noqa: PLR2004


def test_spot_channel_program() -> None:
    # manual p.232: offset 12 "Ch. Program" See PROGRAM NUMBERS
    p = midimap.param_at(12)
    assert p.label == "Ch. Program"
    assert p.low == 0
    assert p.high == 127  # noqa: PLR2004


def test_spot_channel_bank() -> None:
    # manual p.232: offset 13 "Ch. Bank" 0-4
    p = midimap.param_at(13)
    assert p.label == "Ch. Bank"
    assert p.low == 0
    assert p.high == 4  # noqa: PLR2004


def test_spot_channel_volume() -> None:
    # manual p.232: offset 14 "Ch. Volume" 0-127
    p = midimap.param_at(14)
    assert p.label == "Ch. Volume"
    assert p.low == 0
    assert p.high == 127  # noqa: PLR2004


def test_spot_channel_pan() -> None:
    # manual p.232: offset 15 "Ch. Pan" +-7, -8 = Preset
    p = midimap.param_at(15)
    assert p.label == "Ch. Pan"
    assert p.low == -8  # noqa: PLR2004
    assert p.high == 7  # noqa: PLR2004


def test_spot_channel_mix_bus() -> None:
    # manual p.232: offset 16 "Ch. Mix Bus" -1 = preset, 0-3 ...
    p = midimap.param_at(16)
    assert p.label == "Ch. Mix Bus"
    assert p.low == -1
    assert p.high == 3  # noqa: PLR2004


def test_spot_first_channel_tail() -> None:
    # manual p.232: offset 31 last word of one 20-word channel block
    p = midimap.param_at(31)
    assert p.label == "Ch. Ftsw. 3 Enbl"


def test_spot_last_channel_first() -> None:
    # channel 16 starts at 12 + 15*20 = 312 (manual: 16 channels, 20 parms)
    p = midimap.param_at(312)
    assert p.label == "Ch. Program"


def test_spot_last_channel_last() -> None:
    p = midimap.param_at(331)
    assert p.label == "Ch. Ftsw. 3 Enbl"


def test_spot_prog_map_tail() -> None:
    # manual p.233: offset 332 "Prog Map" -1 for None, 0-3
    p = midimap.param_at(332)
    assert p.label == "Prog Map"
    assert p.low == -1
    assert p.high == 3  # noqa: PLR2004


def test_spot_fx_a_type_tail() -> None:
    # manual p.233: offset 333 "FX A Type" See EFFECTS TYPES
    p = midimap.param_at(333)
    assert p.label == "FX A Type"


def test_spot_fx_b_type_tail() -> None:
    # manual p.233: offset 344 "FX B Type" See EFFECTS TYPES chart
    p = midimap.param_at(344)
    assert p.label == "FX B Type"


def test_spot_fx_a_amt_tail() -> None:
    # manual p.233: offset 355 "FX A Amt" 0-100%
    p = midimap.param_at(355)
    assert p.label == "FX A Amt"
    assert p.low == 0
    assert p.high == 100  # noqa: PLR2004


def test_spot_fx_b_bus_tail() -> None:
    # manual p.233: offset 359 "FX B Bus" 0-2, Main, Sub1, Sub2
    p = midimap.param_at(359)
    assert p.label == "FX B Bus"
    assert p.low == 0
    assert p.high == 2  # noqa: PLR2004


def test_offset_of() -> None:
    assert midimap.offset_of("Ch. Volume") == 14  # noqa: PLR2004
    assert midimap.offset_of("Midimap Name") == 0


def test_parse_dump_round_trip() -> None:
    words = list(range(360))
    result = midimap.parse_dump(words)
    assert result == {i: i for i in range(360)}


def test_parse_dump_refuses_short() -> None:
    with pytest.raises(ValueError):
        midimap.parse_dump(list(range(359)))


def test_spell_range() -> None:
    param = midimap.param_at(14)  # Ch. Volume 0-127
    assert midimap.spell(param, 100) == "100"


def test_spell_signed_range() -> None:
    param = midimap.param_at(15)  # Ch. Pan, -8..+7 (preset at -8)
    assert midimap.spell(param, -4) == "-4"
    assert midimap.spell(param, 4) == "+4"


def test_spell_choices() -> None:
    param = midimap.param_at(17)  # Ch. Enable, Off/On
    assert midimap.spell(param, 0) == "Off"
    assert midimap.spell(param, 1) == "On"


def test_spell_name_block() -> None:
    param = midimap.param_at(0)
    assert midimap.spell(param, ord("A")) == "A"


def test_fx_a_type_choices() -> None:
    # manual p. 42: 25 "A" effects including "No Effect", base 0 first type
    p = midimap.param_at(333)
    assert p.label == "FX A Type"
    assert p.choices
    assert len(p.choices) == 25  # noqa: PLR2004


def test_fx_b_type_choices() -> None:
    # manual p. 53: 9 "B" effects including "No Effect"
    p = midimap.param_at(344)
    assert p.label == "FX B Type"
    assert p.choices
    assert len(p.choices) == 9  # noqa: PLR2004


def test_fx_params_spells_types() -> None:
    # at least three manual effect types (manual pp. 42-52): keyed by unique
    # effect ID, not by screen index.
    assert midimap.fx_params_for(1)[0][0] == "Decay Time"
    assert any(p[0] == "Ambience" for p in midimap.fx_params_for(19))
    assert any(p[0] == "LFO Rate" for p in midimap.fx_params_for(11))


def test_fx_params_fallback() -> None:
    # a value nobody documented falls back to the honest generic parameter
    params = midimap.fx_params_for(100000)
    assert params == (("Parm 1", -8192, 8191, ()),)


def test_name_helpers_roundtrip() -> None:
    words = [32] * 12
    name = "TestName1234"
    new = midimap.set_name(words, name)
    assert midimap.name_of(new) == name
    assert words == [32] * 12  # input unmutated


def test_name_helpers_pad_and_truncate() -> None:
    padded = midimap.set_name([], "Hi")
    assert midimap.name_of(padded) == "Hi          "
    truncated = midimap.set_name([32] * 12, "A" * 20)
    assert midimap.name_of(truncated) == "A" * 12


def test_name_helpers_refuse_bad_char() -> None:
    with pytest.raises(ValueError, match="32-127"):
        midimap.set_name([32] * 12, "Bad\x01")


def test_fx_ids_match_names_and_ranges() -> None:
    # manual p.242: unique IDs, not screen indices.
    for offset, ids, names in (
        (333, midimap._FX_A_IDS, midimap._FX_A_NAMES),
        (344, midimap._FX_B_IDS, midimap._FX_B_NAMES),
    ):
        p = midimap.param_at(offset)
        assert len(ids) == len(names)
        assert set(ids).issubset(range(p.low, p.high + 1))
        assert p.values == ids
        assert p.choices == names


def test_spell_fx_a_id_is_not_index() -> None:
    # manual p.242, "Effect Types": "The effect type number sent via SysEx
    # are unique IDs. (they are not the index into the screens)."
    # ID 3 names the effect whose ID is 3, not the third screen entry.
    p = midimap.param_at(333)
    assert midimap.spell(p, 3) == "Plate 1"


def test_spell_fx_b_first_id() -> None:
    p = midimap.param_at(344)
    assert midimap.spell(p, 128) == "No Effect"


def test_spell_unknown_fx_id_is_number() -> None:
    # ID 15 is deliberately absent from the A ID set (the gap at 15).
    p = midimap.param_at(333)
    assert midimap.spell(p, 15) == "15"


def test_choices_for_and_values_for() -> None:
    p = midimap.param_at(333)
    assert midimap.values_for(p) == midimap._FX_A_IDS
    assert midimap.choices_for(p) == tuple(
        zip(midimap._FX_A_IDS, midimap._FX_A_NAMES, strict=True)
    )


def test_picker_round_trips() -> None:
    p = midimap.param_at(333)
    for value, label in midimap.choices_for(p):
        assert midimap.spell(p, value) == label


def test_fx_params_for_collisions() -> None:
    assert midimap.fx_params_for(1) is not midimap.fx_params_for(129)
    assert midimap.fx_params_for(1) != midimap.fx_params_for(129)


def test_fx_params_fallback_for_effectless_types() -> None:
    # manual: "No Effect" (both processors) and "Ring Modulate" have no
    # documented parameters, so the honest generic fallback is used.
    fallback = (("Parm 1", -8192, 8191, ()),)
    assert midimap.fx_params_for(0) == fallback
    assert midimap.fx_params_for(128) == fallback
    assert midimap.fx_params_for(129) == fallback
