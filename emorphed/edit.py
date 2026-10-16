# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.

"""The edit rules for a midimap: a gate, a log, and what is known.

PURE rules only -- no Textual, no I/O, importable without a terminal. The
wire itself is the app's, on a worker, in the shape every other MIDI
operation in emorphed uses.

Two write routes, one gate. A parameter write (``write_parameter``, 0x03)
edits the **scratch** midimap: it changes the value the unit is using
right now but is not permanent. The **store** (``send_midimap``, 0x47)
writes a whole midimap to a location and erases what was there (manual
p.36); only that makes an edit stick, and loading a stored map into the
current location reloads the scratch map from it (manual p.232). Hence
this editor guards the safe route -- parameter writes one value at a time
with a read-back -- while the store stays a separate, fenced action that a
caller must take deliberately with a backup already in hand. A parameter
ID is never invented: the ranges and enumerations come from
:data:`emu.midimap.PARAMS`, and nothing here keeps a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from emu import midimap as mm

__all__ = ["Edit", "EditGate", "EditLog", "MidimapEditor"]


@dataclass
class Edit:
    """One recorded midimap edit."""

    offset: int
    old: int
    new: int
    old_spelled: str = ""
    new_spelled: str = ""

    @property
    def old_spell(self) -> str:
        return self.old_spelled

    @property
    def new_spell(self) -> str:
        return self.new_spelled

    @property
    def spelled(self) -> tuple[str, str]:
        return self.old_spelled, self.new_spelled


class EditGate:
    """Whether writes to the unit are allowed."""

    def __init__(self, *, armed: bool = False) -> None:
        self.armed = armed

    def toggle(self) -> bool:
        self.armed = not self.armed
        return self.armed

    def describe(self) -> str:
        return "write gate armed" if self.armed else "write gate locked"

    def refuse(self) -> str | None:
        """The refusal, or ``None`` when the gate is armed."""
        if self.armed:
            return None
        return "the write gate is locked; press w to arm it"


@dataclass
class EditLog:
    """What was sent, in order, so an edit can be reversed."""

    edits: list[Edit] = field(default_factory=list)

    def push(self, *args: Any, **kwargs: Any) -> None:
        if len(args) == 1 and isinstance(args[0], Edit) and not kwargs:
            self.edits.append(args[0])
            return
        if not args and "edit" in kwargs:
            self.edits.append(kwargs["edit"])
            return
        offset = kwargs.get("offset", args[0] if len(args) > 0 else None)
        old = kwargs.get("old", args[1] if len(args) > 1 else None)
        new = kwargs.get("new", args[2] if len(args) > 2 else None)  # noqa: PLR2004
        old_spelled = kwargs.get(
            "old_spelled",
            args[3] if len(args) > 3 else "",  # noqa: PLR2004
        )
        new_spelled = kwargs.get(
            "new_spelled",
            args[4] if len(args) > 4 else "",  # noqa: PLR2004
        )
        old_spelled = kwargs.get("old_spell", old_spelled) or old_spelled
        new_spelled = kwargs.get("new_spell", new_spelled) or new_spelled
        old_spelled = kwargs.get("spelled_old", old_spelled) or old_spelled
        new_spelled = kwargs.get("spelled_new", new_spelled) or new_spelled
        self.edits.append(
            Edit(
                cast(int, offset),
                cast(int, old),
                cast(int, new),
                str(old_spelled or ""),
                str(new_spelled or ""),
            )
        )

    def take(self, n: int) -> list[Edit]:
        """The last ``n`` edits, newest first, and drop them."""
        if n <= 0:
            return []
        n = min(n, len(self.edits))
        if n <= 0:
            return []
        taken = list(reversed(self.edits[-n:]))
        del self.edits[-n:]
        return taken

    def __len__(self) -> int:
        return len(self.edits)


class MidimapEditor:
    """The rules around an edit, with no I/O in them."""

    def __init__(
        self,
        gate: EditGate | None = None,
        log: EditLog | None = None,
    ) -> None:
        self.gate = gate if gate is not None else EditGate()
        self.log = log if log is not None else EditLog()

    def allow(self, offset: int, value: int) -> str | None:
        if not self.gate.armed:
            return self.gate.refuse()
        try:
            param = mm.param_at(offset)
        except (ValueError, KeyError):
            return f"no midimap parameter at offset {offset}"
        if value < param.low or value > param.high:
            return (
                f"{param.label} must be {param.low}-{param.high}, "
                f"and {value} is not"
            )
        if param.choices:
            index = value - param.low
            if index < 0 or index >= len(param.choices):
                return (
                    f"{param.label} must be one of "
                    f"{', '.join(param.choices)}, and {value} is not"
                )
        return None

    def finish(
        self,
        offset: int,
        value: int,
        read_back: int,
        *,
        old: int | None = None,
    ) -> tuple[bool, str]:
        try:
            param = mm.param_at(offset)
        except (ValueError, KeyError):
            param = None
        if read_back != value:
            label = param.label if param is not None else f"offset {offset}"
            return False, (
                f"{label} did not take {value}: the unit still reports "
                f"{read_back!r}"
            )
        if old is None:
            old = value
        spelled_old = mm.spell(param, old) if param is not None else str(old)
        spelled_new = (
            mm.spell(param, value) if param is not None else str(value)
        )
        label = param.label if param is not None else f"offset {offset}"
        self.log.push(
            Edit(
                offset=offset,
                old=old,
                new=value,
                old_spelled=spelled_old,
                new_spelled=spelled_new,
            )
        )
        return True, f"{label}: {old} -> {value}"

    def undo_plan(self, n: int) -> list[Edit]:
        return self.log.take(n)

    def undo_report(self, applied: int, failed: int) -> str:
        if applied == 0 and failed == 0:
            return "nothing to undo"
        if failed and applied:
            return f"undid {applied}; {failed} failed"
        if failed and not applied:
            return f"undo failed: {failed}"
        return f"undid {applied}"
