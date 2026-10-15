# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""Names read off the unit, and what survives a restart.

The bug these exist for: ``Catalog._live`` was a plain dict in a process
that exits. Every restart fell back to the printed catalog, so the browser
showed the factory bank for a machine full of the user's own patches --
and re-reading fixed it for exactly as long as the session lasted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from emu import catalog as cat
from emu import livenames


class TestStore:
    def test_round_trips(self, tmp_path: Path) -> None:
        path = str(tmp_path / "live-names.json")
        livenames.save(
            {"P-RAM:013": "Invented!", "P-RAM:014": "Alpha Foo"}, path
        )
        assert livenames.load(path) == {
            "P-RAM:013": "Invented!",
            "P-RAM:014": "Alpha Foo",
        }

    def test_a_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        """Nothing read yet is the normal state of a fresh install."""
        assert livenames.load(str(tmp_path / "nope.json")) == {}

    def test_saving_merges_rather_than_replaces(self, tmp_path: Path) -> None:
        """Losing one bank because another could not be read would be poor."""
        path = str(tmp_path / "live-names.json")
        livenames.save({"H-RAM:001": "Kit"}, path)
        livenames.save({"P-RAM:013": "Invented!"}, path)
        stored = livenames.load(path)
        assert stored == {"H-RAM:001": "Kit", "P-RAM:013": "Invented!"}

    def test_a_bank_read_later_wins(self, tmp_path: Path) -> None:
        """The newest read of a slot replaces the older one, not both."""
        path = str(tmp_path / "live-names.json")
        livenames.save({"P-RAM:013": "Old Name"}, path)
        livenames.save({"P-RAM:013": "New Name"}, path)
        assert livenames.load(path) == {"P-RAM:013": "New Name"}

    def test_a_corrupt_file_is_survivable(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """A cache that can be rebuilt must not stop startup.

        The unit is right there; the names are a convenience. Refusing to
        open the browser over a malformed cache would trade a small problem
        for a large one.
        """
        path = tmp_path / "live-names.json"
        path.write_text("{not json at all", encoding="utf-8")
        assert livenames.load(str(path)) == {}
        assert "live-names.json" in capsys.readouterr().err

    def test_a_file_of_the_wrong_shape_is_ignored(
        self, tmp_path: Path
    ) -> None:
        """A hand-edit, or a version with a different layout."""
        path = tmp_path / "live-names.json"
        path.write_text(json.dumps(["P-RAM:013"]), encoding="utf-8")
        assert livenames.load(str(path)) == {}

    def test_non_string_entries_are_dropped(self, tmp_path: Path) -> None:
        path = tmp_path / "live-names.json"
        path.write_text(
            json.dumps({"P-RAM:013": "Fine", "P-RAM:014": 7, "bad": None}),
            encoding="utf-8",
        )
        assert livenames.load(str(path)) == {"P-RAM:013": "Fine"}

    def test_it_writes_its_own_directory(self, tmp_path: Path) -> None:
        """The data directory may not exist yet on a first run."""
        path = str(tmp_path / "deep" / "deeper" / "live-names.json")
        livenames.save({"P-RAM:013": "Invented!"}, path)
        assert livenames.load(path) == {"P-RAM:013": "Invented!"}

    def test_written_names_survive_a_reload(self, tmp_path: Path) -> None:
        """The whole point: a restart must not lose them."""
        path = str(tmp_path / "live-names.json")
        livenames.save({livenames.key("P-RAM", 1): "Invented!"}, path)

        # What main() does at startup, on a fresh process.
        catalog = cat.empty()
        applied = livenames.apply_to(catalog, path)

        assert applied == 1
        assert catalog.display_name("P-RAM", 1) == "Invented!"
        assert catalog.is_live("P-RAM", 1)

    def test_apply_to_skips_keys_that_do_not_parse(
        self, tmp_path: Path
    ) -> None:
        """A name on the wrong slot is worse than a missing one.

        It is a plausible wrong answer, and there is no marker for it: the
        ``*`` only fires on a disagreement, so a key like ``"P-RAM"`` or
        ``"P-RAM:x"`` would land silently on slot 0 and look like a real
        reading.
        """
        path = tmp_path / "live-names.json"
        path.write_text(
            json.dumps(
                {
                    "P-RAM:013": "Fine",
                    "P-RAM": "No number",
                    "P-RAM:x": "Not digits",
                }
            ),
            encoding="utf-8",
        )
        catalog = cat.empty()
        applied = livenames.apply_to(catalog, str(path))

        assert applied == 1
        assert catalog.display_name("P-RAM", 13) == "Fine"
        assert catalog.display_name("P-RAM", 0) == cat.UNNAMED

    def test_apply_to_reports_how_many(self, tmp_path: Path) -> None:
        path = str(tmp_path / "live-names.json")
        livenames.save(
            {livenames.key("P-RAM", n): f"P{n}" for n in (1, 2, 3)}, path
        )
        expected = 3
        assert livenames.apply_to(cat.empty(), path) == expected

    def test_stored_names_beat_the_printed_list(self, tmp_path: Path) -> None:
        """The disagreement is the point, so it must survive a restart too."""
        path = str(tmp_path / "live-names.json")
        livenames.save({livenames.key("P-RAM", 1): "Invented!"}, path)

        catalog = cat.Catalog([cat.Entry("P-RAM", 1, "Printed List")])
        livenames.apply_to(catalog, path)

        assert catalog.display_name("P-RAM", 1) == "Invented!"
        assert catalog.differs("P-RAM", 1), "the * marker depends on this"
        # And the printed name is still there to disagree with.
        assert catalog.name("P-RAM", 1) == "Printed List"

    def test_key_round_trips(self) -> None:
        assert livenames.key("P-RAM", 13) == "P-RAM:013"
        bank_id, _kind, number = cat.split_key(livenames.key("P-RAM", 13))
        assert (bank_id, number) == ("P-RAM", 13)

    def test_a_wrong_shaped_call_raises(self, tmp_path: Path) -> None:
        """No argument-order guessing: a malformed call fails where it is made.

        The old signature sniffed its arguments by type, so ``save(path)``
        merged an empty file and ``save("P-RAM:013")`` was mistaken for a
        path. With the two arguments declared, either mistake is a
        ``TypeError`` at the call site instead.
        """
        path = str(tmp_path / "live-names.json")
        with pytest.raises(TypeError):
            livenames.save(path)  # type: ignore[arg-type]
        assert not os.path.exists(path)

    def test_save_leaves_no_tmp_file(self, tmp_path: Path) -> None:
        path = str(tmp_path / "live-names.json")
        livenames.save({"P-RAM:001": "X"}, path)
        assert not os.path.exists(path + ".tmp")

    def test_save_swallows_oserror(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        # Make the directory unwritable by pointing at a file as parent.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        bad = str(blocker / "live-names.json")
        # Should not raise even though the parent cannot be created.
        livenames.save({"P-RAM:001": "X"}, bad)

    def test_default_path_is_beside_favourites(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        # default_path points into the emorphed data dir and ends with the
        # filename.
        assert livenames.default_path().endswith("live-names.json")
        assert "emorphed" in livenames.default_path()

    def test_load_default_does_not_raise(self) -> None:
        # Calling load() with no argument hands back a dict.
        assert isinstance(livenames.load(), dict)
