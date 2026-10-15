# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The favourites store. Names are invented; no E-MU names committed."""

from emu.favorites import rating_cell
from vinsynlib.favorites import rating_cell as family


class TestRatingCell:
    def test_no_rating_is_blank(self) -> None:
        assert rating_cell(0) == ""

    def test_full_rating_is_five_stars(self) -> None:
        assert rating_cell(5) == "★★★★★"

    def test_partial_rating(self) -> None:
        assert rating_cell(3) == "★★★··"
        assert rating_cell(1) == "★····"

    def test_no_catalog_marker(self) -> None:
        for stars in range(6):
            assert "*" not in rating_cell(stars)

    def test_it_is_the_librarys_own_function(self) -> None:
        assert rating_cell is family
