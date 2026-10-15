# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The catalog: keys from the library, printed vs live kept apart."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emu import catalog as cat


def test_unnamed_placeholder_is_the_librarys() -> None:
    assert cat.UNNAMED == "--"


def test_make_key_and_split_key_round_trip() -> None:
    assert cat.make_key("P-RAM", 13) == "P-RAM:013"
    assert cat.split_key("P-RAM:013") == ("P-RAM", "", 13)
    assert cat.split_key(cat.make_key("P-RAM", 13)) == ("P-RAM", "", 13)


def test_split_key_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        cat.split_key("NOPE")
    with pytest.raises(ValueError):
        cat.split_key("P-RAM:ooh")


def test_entry_key_uses_make_key() -> None:
    assert cat.Entry("P-ROM", 5, "Invented").key == "P-ROM:005"


def test_a_name_is_found_by_region_and_number() -> None:
    c = cat.Catalog([cat.Entry("P-ROM", 5, "Invented")])
    assert c.name("P-ROM", 5) == "Invented"
    assert c.name("P-RAM", 5) is None, "regions are separate spaces"


def test_a_live_name_wins_and_the_difference_is_visible() -> None:
    c = cat.Catalog([cat.Entry("P-RAM", 5, "Printed")])
    c.set_live_name("P-RAM", 5, "Saved Over")
    assert c.display_name("P-RAM", 5) == "Saved Over"
    assert c.is_live("P-RAM", 5)
    assert c.differs("P-RAM", 5)


def test_display_name_falls_back_to_unnamed() -> None:
    c = cat.empty()
    assert c.display_name("P-RAM", 5) == cat.UNNAMED


def test_search_carries_the_disagreement() -> None:
    c = cat.Catalog([cat.Entry("P-RAM", 5, "Printed")])
    c.set_live_name("P-RAM", 5, "Saved Over")
    assert c.search("saved") == [("P-RAM", 5, "Saved Over", True)]


def test_search_is_case_insensitive() -> None:
    c = cat.Catalog([cat.Entry("P-RAM", 5, "Invented Name")])
    assert c.search("INV") == [("P-RAM", 5, "Invented Name", False)]


def test_differs_needs_both_sources() -> None:
    c = cat.Catalog([cat.Entry("P-RAM", 5, "Printed")])
    assert not c.differs("P-RAM", 5)
    c.set_live_name("P-RAM", 5, "Printed")
    assert not c.differs("P-RAM", 5)
    c.set_live_name("P-RAM", 5, "Other")
    assert c.differs("P-RAM", 5)


def test_one_bad_row_does_not_cost_the_others(tmp_path: Path) -> None:
    path = str(tmp_path / "cat.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "banks": {
                    "P-RAM": [
                        {"pc": "not a number", "name": "Bad"},
                        {"pc": 1, "name": "Invented"},
                    ]
                }
            },
            handle,
        )
    assert len(cat.load(path)) == 1
    assert cat.load(path).name("P-RAM", 2) == "Invented"


def test_load_missing_is_empty(tmp_path: Path) -> None:
    assert not cat.load(str(tmp_path / "absent.json"))
    assert not cat.load(None)


def test_load_missing_default_path_is_empty() -> None:
    assert isinstance(cat.load(), cat.Catalog)


def test_dump_round_trips(tmp_path: Path) -> None:
    path = str(tmp_path / "out" / "catalog.json")
    entries = [cat.Entry("P-ROM", 5, "Invented")]
    c = cat.Catalog(entries, source="s", generated="g")
    cat.dump(c, path)
    back = cat.load(path)
    assert back.name("P-ROM", 5) == "Invented"
    assert back.source == "s"


def test_entry() -> None:
    c = cat.Catalog([cat.Entry("P-ROM", 5, "Invented")])
    assert c.entry("P-ROM", 5) is not None
    assert c.entry("P-ROM", 6) is None
    assert c.has("P-ROM")
    assert not c.has("P-RAM")


def test_disagreement_wording() -> None:
    c = cat.Catalog([cat.Entry("P-RAM", 5, "Printed")])
    c.set_live_name("P-RAM", 5, "Other")
    assert c.disagreement("P-RAM", 5, False) == (
        "the printed list is wrong; the unit is right"
    )
    assert c.disagreement("P-RAM", 5, True) == "saved over the factory preset"
    assert c.disagreement("P-RAM", 9) is None


def test_len_bool() -> None:
    assert len(cat.empty()) == 0
    assert not cat.empty()
    entries = [cat.Entry("P-RAM", 1, "A"), cat.Entry("P-RAM", 2, "B")]
    c = cat.Catalog(entries)
    assert len(c) == len(entries)
    assert bool(c)
