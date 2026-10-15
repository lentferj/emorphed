# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# The wire protocol is transcribed as data from E-mu's own MIDI
# Specification, printed in full as pages 225-250 of the Morpheus
# Operation Manual (E-mu Systems, 1993), and checked against 2176 preset
# dumps the instrument produced. The transport layer is ported from the
# sibling p2ked, x5ded, kwsed, rxved and nanosyned projects.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)

"""The favourites store, the config and the catalog. All invented data.

These three modules are ported from the sibling projects and carry this
family's most subtle behaviour -- the upsert that preserves ``added``,
the soft delete, the LIKE escaping, the TOML quoting. None of it was
pinned here until an outside review pointed out that the largest module
in the project had no test at all.
"""

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from emu import config
from emu.favorites import Favorites


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Favorites]:
    with Favorites(str(tmp_path / "f.db")) as db:
        yield db


class TestTheSlotIsTheIdentity:
    def test_a_favourite_survives_a_rename(self, store: Favorites) -> None:
        store.add("P-RAM", 7, name="Invented One")
        store.add("P-RAM", 7, name="Renamed Entirely")
        assert len(store) == 1
        fav = store.get("P-RAM", 7)
        assert fav is not None
        assert fav.name == "Renamed Entirely"

    def test_the_added_date_is_preserved_across_an_edit(
        self, store: Favorites
    ) -> None:
        first = store.add("P-RAM", 7, name="Invented")
        again = store.add("P-RAM", 7, name="Invented", rating=4)
        assert again.added == first.added, (
            "re-adding is an edit, not a re-acquisition; the date is the "
            "one ordering the user cannot reconstruct"
        )

    def test_regions_are_separate_spaces(self, store: Favorites) -> None:
        """P-RAM 5 and P-ROM 5 are different slots with the same number."""
        store.add("P-RAM", 5, name="In RAM")
        store.add("P-ROM", 5, name="In ROM")
        assert len(store) == 2
        fav = store.get("P-ROM", 5)
        assert fav is not None
        assert fav.name == "In ROM"


class TestUnfavouritingKeepsWhatTheUserTyped:
    """`f` in a browser unfavourites without asking, so a rating, tags, a
    note and the original date must survive it."""

    def test_a_toggle_cycle_keeps_everything(self, store: Favorites) -> None:
        store.add(
            "P-RAM", 5, name="Invented", rating=4, tags="a, b", note="hello"
        )
        before = store.get("P-RAM", 5)
        assert before is not None

        assert store.toggle("P-RAM", 5) is False
        assert store.get("P-RAM", 5) is None
        assert store.toggle("P-RAM", 5) is True

        after = store.get("P-RAM", 5)
        assert after is not None
        assert (after.rating, after.tags, after.note) == (4, "a, b", "hello")
        assert after.added == before.added

    def test_an_unfavourited_slot_is_not_a_favourite_by_any_route(
        self, store: Favorites
    ) -> None:
        store.add("P-RAM", 5, name="Invented", rating=3)
        store.remove("P-RAM", 5)
        assert len(store) == 0
        assert store.keys() == set()
        assert store.all() == []
        assert store.search("Invented") == []
        assert "P-RAM:005" not in store

    def test_what_is_still_held_can_be_seen(self, store: Favorites) -> None:
        store.add("P-RAM", 5, name="Invented", rating=3)
        store.remove("P-RAM", 5)
        assert [f.rating for f in store.dormant()] == [3]

    def test_forget_really_deletes(self, store: Favorites) -> None:
        store.add("P-RAM", 5, name="Invented", rating=3)
        store.remove("P-RAM", 5)
        assert store.forget("P-RAM", 5) is True
        assert store.dormant() == []

    def test_a_v1_database_upgrades_without_losing_rows(
        self, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "old.db")
        db = sqlite3.connect(path)
        db.executescript(
            """
            CREATE TABLE favorites (
                bank_id TEXT NOT NULL, number INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                rating INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                added REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (bank_id, number));
            """
        )
        db.execute(
            "INSERT INTO favorites (bank_id, number, name, rating) "
            "VALUES ('P-RAM', 7, 'Invented', 5)"
        )
        db.execute("PRAGMA user_version = 1")
        db.commit()
        db.close()

        with Favorites(path) as store:
            kept = store.get("P-RAM", 7)
            assert kept is not None, "an existing row must stay a favourite"
            assert kept.rating == 5


class TestAnnotationsSurviveEachOther:
    def test_setting_a_rating_keeps_the_tags_and_note(
        self, store: Favorites
    ) -> None:
        store.add("P-RAM", 1, name="Invented", tags="pad", note="keep me")
        store.set_rating("P-RAM", 1, 5)
        row = store.get("P-RAM", 1)
        assert row is not None
        assert (row.rating, row.tags, row.note) == (5, "pad", "keep me")

    def test_a_rating_has_a_range(self, store: Favorites) -> None:
        store.add("P-RAM", 1)
        with pytest.raises(ValueError, match="0-5"):
            store.set_rating("P-RAM", 1, 6)


class TestSearchWildcardsAreLiteral:
    """% and _ are LIKE wildcards, and a search for one must not match
    everything."""

    def test_a_percent_matches_only_a_percent(self, store: Favorites) -> None:
        store.add("P-RAM", 1, name="Invented One")
        store.add("P-RAM", 2, name="Ten % Off")
        assert [f.number for f in store.search("%")] == [2]

    def test_an_underscore_matches_only_an_underscore(
        self, store: Favorites
    ) -> None:
        store.add("P-RAM", 1, name="Invented One")
        store.add("P-RAM", 2, name="under_score")
        assert [f.number for f in store.search("_")] == [2]


class TestNamesCanBeRefreshed:
    def test_it_relabels_and_counts_what_changed(
        self, store: Favorites
    ) -> None:
        store.add("P-RAM", 0, name="")
        store.add("P-RAM", 1, name="Already Right")
        changed = store.refresh_names(
            lambda bank, number: "Already Right" if number else "From Unit"
        )
        assert changed == 1
        fav = store.get("P-RAM", 0)
        assert fav is not None
        assert fav.name == "From Unit"


class TestTheConfigIsWrittenSafely:
    """A quote in a port name once made the file unparsable for good."""

    def test_a_quoted_port_name_round_trips(self, tmp_path: Path) -> None:
        path = str(tmp_path / "config.toml")
        nasty = 'Odd "quoted"\tport\\with slash'
        config.save_last_port(nasty, path)
        assert config.load_last_port(path) == nasty

    def test_the_cache_heals(self, tmp_path: Path) -> None:
        path = str(tmp_path / "config.toml")
        config.save_last_port('has a " in it', path)
        config.save_last_port("a sane port", path)
        assert config.load_last_port(path) == "a sane port"

    def test_the_device_id_round_trips(self, tmp_path: Path) -> None:
        path = str(tmp_path / "config.toml")
        config.save_device_id(12, path)
        assert config.load_device_id(path) == 12

    def test_a_device_id_of_true_is_not_device_one(
        self, tmp_path: Path
    ) -> None:
        """isinstance(True, int) is True, and device 1 is a real device."""
        path = str(tmp_path / "config.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("device_id = true\n")
        assert config.load_device_id(path) is None

    def test_the_recv_port_round_trips(self, tmp_path: Path) -> None:
        """Wired into the CLI only after a review pointed out it was
        exported and never called."""
        path = str(tmp_path / "config.toml")
        config.save_last_recv_port("some input port", path)
        assert config.load_last_recv_port(path) == "some input port"


class TestABoolIsNotANumber:
    """`isinstance(True, int)` is True, and every range check passes for
    it. A hand-edited `channel = true` came back as `True`, and
    `0xC0 | True` is `0xC1` -- MIDI channel 2 when channel 1 was asked
    for. A wrong channel is not an error anywhere: the instrument plays
    nothing, or something else does.

    The device-ID guard was written first and this one was missed, one
    function away in the same file, in all seven projects. That is the
    reason this test walks *every* loader rather than naming two.
    """

    def _loaders(self) -> Iterator[tuple[str, Callable[..., Any]]]:

        import importlib

        module = importlib.import_module("emu.config")
        for name, fn in vars(module).items():
            if not name.startswith("load_") or not callable(fn):
                continue
            hints = getattr(fn, "__annotations__", {})
            if "int" in str(hints.get("return", "")):
                yield name, fn

    def test_there_are_numeric_loaders_to_check(self) -> None:
        assert list(self._loaders()), "the search matched nothing"

    def test_no_numeric_loader_accepts_true(self, tmp_path: Path) -> None:
        offenders = []
        for name, fn in self._loaders():
            key = name[len("load_") :]
            path = str(tmp_path / f"{key}.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"{key} = true\n")
            if fn(path) is not None:
                offenders.append(name)
        assert not offenders, f"{offenders} accept a TOML boolean as a number"

    def test_no_numeric_loader_accepts_an_absurd_value(
        self, tmp_path: Path
    ) -> None:
        offenders = []
        for name, fn in self._loaders():
            key = name[len("load_") :]
            path = str(tmp_path / f"{key}.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"{key} = 9999\n")
            if fn(path) is not None:
                offenders.append(name)
        assert not offenders, f"{offenders} accept an out-of-range number"
