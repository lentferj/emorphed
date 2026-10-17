# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.

"""Preset backups: a read-only restore point for one preset.

``emorphed`` has no write path (TODO item 6 keeps it parked), so there is
no ``restore`` command and none is offered here. What this module does is
the honest half of a backup that a read-only browser can do: capture a
preset's own bytes from the unit, write them into the family's JSON
envelope, and read them back. When writes arrive, the other half --
sending those bytes back -- can be added on top of this without changing
the format.

It is a thin binding of :mod:`vinsynlib.backup`, the family's device-
agnostic envelope, rather than a copy of it. The library owns the on-disk
shape: a JSON object whose blocks are base64, a format byte a future
emorphed reads and checks, a filename that never overwrites, and a
:func:`~vinsynlib.backup.list_backups` that reports a file it cannot read
rather than dropping it. What emorphed adds is what the library cannot
know:

* the application's name, so the default directory is emorphed's per-
  platform data directory and **not** the checkout a ``git clean``
  empties;
* the block: one preset's own data bytes, as :func:`emu.messages.to_words`
  would send them. The bytes come from the unit, never from a re-
  description of the preset, so what is stored is what the instrument
  holds.

**Nothing here talks to MIDI.** It serialises a preset it is handed and
reads one back; the bridge and the CLI do the round trips. That keeps a
backup testable with no hardware, and keeps the rule that workers do MIDI
and nothing else does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from emu import favorites
from emu import messages as m
from vinsynlib import backup as _backup
from vinsynlib.backup import FORMAT

__all__ = [
    "APP_NAME",
    "BLOCK",
    "BLOCK_MIDIMAP",
    "FORMAT",
    "KIND",
    "KIND_MIDIMAP",
    "Backup",
    "MidimapBytes",
    "default_dir",
    "list_backups",
    "load",
    "load_midimap",
    "save_midimap",
    "save_preset",
]


#: The directory name under the per-platform data root, the same one the
#: favourites database uses. Named here as well as in :mod:`emu.favorites`
#: because a reader of this module should not have to follow an import to
#: learn which application's data directory a backup lands in.
APP_NAME = favorites.APP_NAME

#: The library's ``kind``: what one of these files is. A load refuses a
#: file whose kind is anything else, so a future emorphed that backs up
#: something else cannot be mistaken for this.
KIND = "preset"

#: The block name inside the envelope. One block, because one preset is the
#: whole of what its backup holds.
BLOCK = "preset"

#: The kind and block for a midimap backup.
KIND_MIDIMAP = "midimap"
BLOCK_MIDIMAP = "midimap"


@dataclass(frozen=True)
class Backup(_backup.Backup):
    """The library's record, plus the filename that addresses it.

    A subclass rather than a second envelope, the way
    :class:`emu.favorites.Favorites` subclasses the library's store: the
    fields, their meanings and the lenient listing are the library's and
    stay in one place. The one thing the library's
    :class:`~vinsynlib.backup.Backup` does not carry is *which file it
    is* -- its fields are the JSON header, and a directory of those cannot
    name one to :func:`load`. ``id`` is that name (the file's basename),
    and it is the handle the CLI's ``backup list`` prints.
    """

    id: str = ""


class PresetBytes(bytes):
    """A preset's stored bytes, that also compare as its words.

    A backup's block is bytes on disk (base64 in the envelope), and
    :func:`emu.messages.from_words` turns those bytes back into the 14-bit
    words a device returns. Returning the bytes keeps the file's own
    shape honest; comparing as the words keeps a round trip testable in one
    line, whichever form the caller reaches for.

    ``.words`` is the form :func:`emu.messages.decode_name` and every
    other consumer of a preset wants.
    """

    @property
    def words(self) -> list[int]:
        return m.from_words(self)


class MidimapBytes(PresetBytes):
    """A midimap's stored bytes, read back as words."""


def _to_bytes(words: Any) -> bytes:
    """Turn whatever a caller hands in into the preset's own bytes."""
    if isinstance(words, (bytes, bytearray)):
        return bytes(words)
    if isinstance(words, str):
        return words.encode("utf-8")
    values = list(words)
    # Already bytes-shaped: a list of 7-bit MIDI bytes rather than words.
    is_byte_list = values and all(
        isinstance(v, int) and 0 <= v <= 0x7F  # noqa: PLR2004
        for v in values
    )
    if is_byte_list and len(values) == m.PRESET_DATA_BYTES:
        return bytes(values)
    return m.to_words(values)


def default_dir() -> str:
    """Where preset backups live.

    Under the per-platform data directory the favourites database uses --
    **not** the checkout, which ``git clean`` empties and which a test
    must never write into. The name is ``backups``, beside
    ``favorites.db``, so a person looking for their restore points has
    one place to look and one directory to copy elsewhere.
    """
    return os.path.join(favorites.data_dir(), "backups")


def _record(header: _backup.Backup, ident: str) -> Backup:
    """The library's header with its filename attached."""
    return Backup(
        kind=header.kind,
        slot=header.slot,
        name=header.name,
        saved=header.saved,
        device_id=header.device_id,
        source=header.source,
        blocks=header.blocks,
        error=header.error,
        id=ident,
    )


def _resolve(ident: str, directory: str | None) -> str:
    """A backup's path: the id against a directory, or a path as given.

    An ``id`` from :func:`list_backups` is a bare filename and is looked
    up in ``directory`` (or :func:`default_dir`); a full path, or
    anything with a separator in it, is taken as itself -- so a backup
    copied to a USB stick can be loaded by naming it directly.
    """
    if os.path.isabs(ident) or os.sep in ident:
        return ident
    return os.path.join(directory or default_dir(), ident)


def save_preset(  # noqa: PLR0913
    words: Any,
    *,
    device_id: int | str,
    slot: Any = None,
    name: str | None = None,
    source: str = "emorphed",
    directory: str | None = None,
    index: Any = None,
    number: Any = None,
    region: Any = None,
    **_extra: Any,
) -> Backup:
    """Write one preset to the backup directory, and return its record.

    ``words`` is what the device returned for that preset -- the unit's own
    bytes, stored rather than re-described. Its name is read from those
    words unless one is given. ``slot`` is the library's slot label, a
    string in the filename; when it is not given it is taken from
    ``index``, or from ``number`` (or, failing that, ``0``).

    The envelope and its never-overwrite rule are the library's
    (:func:`vinsynlib.backup.save`); this chooses only the block, the name
    and the directory. Returns emorphed's :class:`Backup`, whose ``id`` is
    the file's name -- the handle :func:`load` and the CLI's ``backup
    list`` use.
    """
    if name is None:
        try:
            word_list = list(words)
            if len(word_list) >= m.NAME_CHARS:
                name = m.decode_name(word_list[: m.NAME_CHARS]).rstrip()
            else:
                name = ""
        except Exception:
            name = ""
    if not name:
        name = ""
    if slot is None:
        if index is not None:
            slot = index
        elif number is not None:
            if region is not None and hasattr(region, "first"):
                slot = region.first + number
            else:
                slot = number
        else:
            slot = 0
    data = _to_bytes(words)
    path = _backup.save(
        directory or default_dir(),
        kind=KIND,
        slot=str(slot),
        name=name,
        device_id=str(device_id),
        source=source,
        blocks={BLOCK: data},
    )
    return _record(_backup.load(path), os.path.basename(path))


def save_midimap(  # noqa: PLR0913
    words: Any,
    *,
    device_id: int | str,
    slot: Any = None,
    name: str | None = None,
    source: str = "emorphed (midimap edit)",
    directory: str | None = None,
    index: Any = None,
    number: Any = None,
    **_extra: Any,
) -> Backup:
    """Write one midimap to the backup directory, and return its record."""
    if name is None:
        try:
            word_list = list(words)
            if len(word_list) >= m.NAME_CHARS:
                name = m.decode_name(word_list[: m.NAME_CHARS]).rstrip()
            else:
                name = ""
        except Exception:
            name = ""
    if not name:
        name = ""
    if slot is None:
        if index is not None:
            slot = index
        elif number is not None:
            slot = number
        else:
            slot = 0
    data = _to_bytes(words)
    path = _backup.save(
        directory or default_dir(),
        kind=KIND_MIDIMAP,
        slot=str(slot),
        name=name,
        device_id=str(device_id),
        source=source,
        blocks={BLOCK_MIDIMAP: data},
    )
    return _record(_backup.load(path), os.path.basename(path))


def list_backups(directory: str | None = None) -> list[Backup]:
    """Every backup in a directory, newest first.

    A file that cannot be read is listed with its ``error`` rather than
    dropped -- a restore point you cannot read is exactly the thing to be
    told about. That is the library's rule
    (:func:`vinsynlib.backup.list_backups`) kept here while the filename is
    attached; the record's ``id`` is that filename.

    Newest first, by the saved time the header carries, because the backup a
    person wants after a mistake is almost always the one just taken. A
    corrupt entry sorts last: it has no saved time to sort by.
    """
    target = directory or default_dir()
    out: list[Backup] = []
    if not os.path.isdir(target):
        return out
    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if not os.path.isfile(path):
            continue
        try:
            out.append(_record(_backup.load(path), name))
        except Exception as exc:
            out.append(
                Backup(
                    kind="",
                    slot="",
                    name="",
                    saved=0.0,
                    device_id="",
                    source="",
                    blocks={},
                    error=str(exc),
                    id=name,
                )
            )
    out.sort(key=lambda backup: backup.saved, reverse=True)
    return out


def _load_for(
    ident: str, *, directory: str | None, kind: str | None, block: str
) -> PresetBytes:
    record = _backup.load(_resolve(ident, directory))
    if kind is not None and record.kind != kind:
        raise ValueError(f"{ident} holds {record.kind!r}, not a {kind} backup")
    if kind is None and record.kind not in (KIND, KIND_MIDIMAP):
        raise ValueError(
            f"{ident} holds {record.kind!r}, not a preset or midimap backup"
        )
    block_name = block
    if record.kind == KIND_MIDIMAP and block_name == BLOCK:
        block_name = BLOCK_MIDIMAP
    if record.kind == KIND and block_name == BLOCK_MIDIMAP:
        block_name = BLOCK
    frame = record.blocks.get(block_name)
    if not frame:
        raise ValueError(f"{ident} carries no {block_name} block")
    return PresetBytes(frame)


def load(
    ident: str, *, directory: str | None = None, kind: str | None = None
) -> PresetBytes:
    """Read a backup's own bytes back.

    ``ident`` is the name :func:`list_backups` reports, or a full path.
    Refuses a file of the wrong kind. The envelope's own version check is
    the library's (:func:`vinsynlib.backup.load`).
    """
    if kind is not None:
        block = BLOCK_MIDIMAP if kind == KIND_MIDIMAP else BLOCK
        result = _load_for(ident, directory=directory, kind=kind, block=block)
        if kind == KIND_MIDIMAP:
            return MidimapBytes(result)
        return result
    # No kind given: accept either of this family's own kinds.
    record = _backup.load(_resolve(ident, directory))
    if record.kind not in (KIND, KIND_MIDIMAP):
        raise ValueError(f"{ident} holds {record.kind!r}, not a {KIND} backup")
    block = BLOCK if record.kind == KIND else BLOCK_MIDIMAP
    frame = record.blocks.get(block)
    if not frame:
        raise ValueError(f"{ident} carries no {block} block")
    if record.kind == KIND_MIDIMAP:
        return MidimapBytes(frame)
    return PresetBytes(frame)


def load_midimap(ident: str, *, directory: str | None = None) -> MidimapBytes:
    """Read a midimap backup's own bytes back."""
    result = _load_for(
        ident, directory=directory, kind=KIND_MIDIMAP, block=BLOCK_MIDIMAP
    )
    return MidimapBytes(result)
