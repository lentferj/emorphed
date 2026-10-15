# SPDX-License-Identifier: GPL-2.0-or-later
# mypy: ignore-errors
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
# ruff: noqa: PLR2004
#
# This file is part of emorphed.

"""``morphcli fav``, end to end."""

import pytest

from emorphed import cli
from emu.favorites import Favorites

USER_1 = "P-RAM:001"
USER_2 = "P-RAM:002"
USER_3 = "P-RAM:003"


def _argv(tmp_path, *argv):
    return ["--favorites", str(tmp_path / "favorites.db"), *argv]


def _args(tmp_path, *argv):
    return cli.build_parser().parse_args(_argv(tmp_path, *argv))


def _fav(args):
    return Favorites(args.favorites)


def _api(text):
    bank_id, number = text.split(":")
    return bank_id, int(number)


def _listed(capsys):
    lines = capsys.readouterr().out.splitlines()
    rows = []
    for line in lines:
        if not line.startswith("P-RAM"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) >= 2:
            rows.append(parts[1])
    return rows


class TestRate:
    def test_it_sets_the_rating_and_leaves_the_rest_alone(
        self, tmp_path
    ) -> None:
        args = _args(
            tmp_path, "fav", "--add", USER_1, "--rating", "4", "--tags", "lead"
        )
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--rate", USER_1, "2")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(*_api(USER_1))
            assert (found.rating, found.tags) == (2, "lead")

    def test_it_refuses_a_slot_that_is_not_a_favourite(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "--rate", USER_3, "3")
        with pytest.raises(SystemExit) as caught:
            cli._cmd_fav(None, args)
        assert "not a favourite" in str(caught.value)
        with _fav(args) as store:
            assert store.get(*_api(USER_3)) is None

    def test_a_rating_outside_zero_to_five_is_one_line_not_a_traceback(
        self, tmp_path
    ) -> None:
        args = _args(tmp_path, "fav", "--add", USER_1)
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--rate", USER_1, "9")
        with pytest.raises(SystemExit) as caught:
            cli._cmd_fav(None, args)
        assert "--rate wants 0-5" in str(caught.value)
        with _fav(args) as store:
            assert store.get(*_api(USER_1)).rating == 0


class TestAddIsNotAWipe:
    def test_re_adding_without_a_rating_keeps_it(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "--add", USER_1, "--rating", "5")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--add", USER_1)
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            assert store.get(*_api(USER_1)).rating == 5

    def test_re_adding_with_a_rating_replaces_only_that(
        self, tmp_path
    ) -> None:
        args = _args(
            tmp_path, "fav", "--add", USER_1, "--rating", "5", "--note", "top"
        )
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--add", USER_1, "--rating", "1")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(*_api(USER_1))
            assert (found.rating, found.note) == (1, "top")

    def test_add_rejects_a_rating_outside_zero_to_five(self, tmp_path) -> None:
        for bad in ("7", "-1"):
            args = _args(tmp_path, "fav", "--add", USER_1, "--rating", bad)
            with pytest.raises(SystemExit) as caught:
                cli._cmd_fav(None, args)
            assert "--rating wants 0-5" in str(caught.value)
        args = _args(tmp_path, "fav")
        with _fav(args) as store:
            assert store.get(*_api(USER_1)) is None


class TestRatingFilters:
    def _seeded(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "--add", USER_1, "--rating", "5")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--add", USER_2, "--rating", "3")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "--add", USER_3)
        cli._cmd_fav(None, args)
        return _args(tmp_path, "fav")

    def test_at_least_keeps_the_rated_and_up(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-at-least", "3"))
        assert _listed(capsys) == ["002", "001"]

    def test_exactly_zero_is_the_unrated_one(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-exactly", "0"))
        assert _listed(capsys) == ["003"]

    def test_nothing_matching_says_so_and_exits_zero(
        self, tmp_path, capsys
    ) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-exactly", "2"))
        assert "no favourites" in capsys.readouterr().err

    def test_it_stacks_on_a_tag_filter(self, tmp_path, capsys) -> None:
        args = _args(
            tmp_path, "fav", "--add", USER_1, "--rating", "5", "--tags", "lead"
        )
        cli._cmd_fav(None, args)
        args = _args(
            tmp_path, "fav", "--add", USER_2, "--rating", "5", "--tags", "pad"
        )
        cli._cmd_fav(None, args)
        args = _args(
            tmp_path, "fav", "--add", USER_3, "--rating", "1", "--tags", "lead"
        )
        cli._cmd_fav(None, args)
        cli._cmd_fav(
            None,
            _args(tmp_path, "fav", "--tag", "lead", "--rating-at-least", "3"),
        )
        assert _listed(capsys) == ["001"]

    def test_both_flags_together_is_a_usage_error(
        self, tmp_path, capsys
    ) -> None:
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(
                _argv(
                    tmp_path,
                    "fav",
                    "--rating-at-least",
                    "3",
                    "--rating-exactly",
                    "0",
                )
            )
        assert "not allowed with" in capsys.readouterr().err

    def test_the_column_shows_the_stars(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-exactly", "5"))
        out = capsys.readouterr().out
        assert "★★★★★" in out
