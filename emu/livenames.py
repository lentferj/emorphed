# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Names read off the unit, kept between runs.

A writable bank is the user's own work, and its printed list is
guaranteed to be wrong about it -- the catalog says what the factory
shipped, and a bank that has been saved into says something else
entirely. So for writable banks the hardware is the only authority,
and reading it is the only way to be right.

The problem is what happens next: those names live in
``Catalog._live``, which is a plain dict in a process that exits.
Every restart falls back to the printed list, so the browser
confidently shows the factory bank for a machine full of the user's
own patches, and re-reading fixes the screen for exactly as long as
the session lasts. Names that are expensive to get and true today
should not evaporate overnight.

So they are written here, in a per-project sidecar file, and read
back at startup -- which means the browser shows the right names
*immediately*, before anything has talked to the unit, and the
hardware read that follows only confirms them.

Deliberately not in the catalog file. That file is generated from the
manufacturer's own documentation, the printed-versus-live distinction
is the whole point of having two name sources, and a cache of one
instrument's current contents does not belong in a document
describing what the manual says. Overwriting one with the other would
destroy the disagreement the marker exists to show. Each project keeps
its own file -- and its own categories -- beside its own catalog.

Format is ``{"P-RAM:013": "..."}``, flat and keyed the same way
:class:`emu.catalog.Catalog` keys its live layer. A missing file is
normal and means nothing has been read yet; a corrupt one is worth a
warning rather than an exception, because names are a convenience and
refusing to open the browser over one would be the wrong trade.
"""

from __future__ import annotations

import os
from typing import Any

from emu.favorites import data_dir
from vinsynlib import livenames as _livenames
from vinsynlib.catalog import split_key
from vinsynlib.livenames import FILE_NAME, key

__all__ = ["FILE_NAME", "apply_to", "default_path", "key", "load", "save"]


def default_path() -> str:
    """Where the hardware-read names live, per platform.

    Beside the favourites database in emorphed's data directory. Overridable
    with ``--live-names`` on both front ends, for the same reason
    ``--favorites`` is: so the file can be pointed somewhere a ``git clean``
    will not reach, inspected, or thrown away.
    """
    return os.path.join(data_dir(), FILE_NAME)


def load(path: Any = None) -> dict[str, str]:
    """Previously-read names, keyed ``"BANK:NNN"``. Empty if there are none.

    A thin binding: the library's reader wants an explicit path, and both
    front ends default to the sidecar beside the favourites database, so
    the default is supplied here rather than at every call site. Everything
    else -- the lenient decode, the warning on a malformed cache, dropping
    entries that are not strings -- is the library's and lives in one place.
    """
    target = path if path is not None else default_path()
    return _livenames.load(str(target))


def apply_to(catalog: Any, path: Any = None) -> int:
    """Lay the stored names over ``catalog``. Returns how many were applied.

    Both front ends need this before they draw anything, and the parsing is
    the part worth sharing: a key that does not parse is skipped rather than
    guessed at, because a name attached to the wrong slot is worse than a
    missing one -- it is a plausible wrong answer.

    Kept here rather than delegated because the library's version records a
    *kind* alongside the name, and this instrument's catalog has none -- its
    banks are presets, not two kinds sharing one id. The key grammar is the
    library's all the same.
    """
    applied = 0
    for stored, name in load(path).items():
        try:
            bank_id, _kind, number = split_key(stored)
        except ValueError:
            continue
        if bank_id:
            catalog.set_live_name(bank_id, number, name)
            applied += 1
    return applied


def save(*args: Any, **kwargs: Any) -> None:
    """Write the live layer out. Best effort -- a cache is not required.

    The library merges rather than replaces, so a ``--live-names`` file that
    also holds something else keeps it, and writes through a temporary plus
    ``os.replace`` so a crash mid-write leaves the previous file intact.
    Only the default path is added here.

    Accepted call shapes, so callers and tests may pass the names and the
    path in either order: ``save(names, path)``, ``save(path, names)``,
    ``save(names)``, ``save(path=path, names=names)``.
    """
    names: dict[str, str] | None = kwargs.get("names")
    path: Any = kwargs.get("path")
    for arg in args:
        if isinstance(arg, dict):
            names = arg
        elif isinstance(arg, (str, os.PathLike)):
            path = arg
        elif arg is None:
            continue
    if names is None:
        names = {}
    target = path if path is not None else default_path()
    _livenames.save(str(target), names)
