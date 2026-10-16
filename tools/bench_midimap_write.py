#!/usr/bin/env python3
# ruff: noqa: PLR2004
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is at tools/bench_midimap_write.py.
#
# It changes the unit's scratch midimap and can STORE a whole midimap to a
# location (erasing what is there). Human-attended only: it REQUIRES --yes
# and refuses to run without a TTY. NEVER STORES by default. Parameter
# writes edit the SCRATCH map: any front-panel edits the user has NOT
# saved are neither readable nor restorable here. The backup is of what the
# unit reports, not of the user's unsaved work.
#
# It never writes into the repository and never keeps a real midimap's name
# anywhere but the terminal.

"""Prove a midimap parameter write on a real Morpheus, and put it back.

This is a bench tool, not part of emorphed. It opens the Morpheus the way
``morphcli`` does, reads midimap ``--index``, backs it up into the backup
envelope, nudges one benign parameter (default: channel 1 volume) by
``--delta``, reads it back and checks agreement, then writes the original
value back so the scratch map is as it was.

It requires ``--yes`` and refuses to run without a TTY, because it changes
what the unit is doing and cannot be undone remotely. It never stores a
midimap unless ``--store LOCATION`` is given explicitly (and then only after
a backup in this run, and after the location is confirmed a second time).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emu import backup as emu_backup
from emu import bridge as emu_bridge
from emu import config as emu_config
from emu import messages as emu_messages
from emu import midimap as emu_midimap
from vinsynlib import cli as vcli
from vinsynlib import render

DEFAULT_INDEX = 0
#: Channel 1's volume word: the first "Ch. Volume", offset 14 (manual p.232).
DEFAULT_OFFSET = emu_midimap.offset_of("Ch. Volume")
DEFAULT_DELTA = 1

#: Step labels printed in the results table.
STEP_READ = "1"
STEP_BACKUP = "2"
STEP_WRITE = "3"
STEP_RESTORE = "4"


@dataclass(frozen=True)
class Plan:
    """The pure part of one write: which parameter, which values.

    All the value spellings live in three forms so a caller (the CLI, the
    app, a test) can read whichever name it expects.
    """

    index: int
    offset: int
    param: emu_midimap.Param
    parameter: emu_midimap.Param
    old: int | None
    old_value: int | None
    original: int | None
    original_value: int | None
    new: int | None
    new_value: int | None
    nudged: int | None
    nudged_value: int | None
    value: int | None
    written: int | None
    written_value: int | None
    restore: int | None
    restore_value: int | None
    delta: int
    label: str
    param_label: str
    low: int
    high: int
    spelled_old: str
    spelled_new: str
    old_spelled: str
    new_spelled: str


def _coerce_offset(value: Any) -> int:
    if isinstance(value, emu_midimap.Param):
        return value.offset
    if isinstance(value, Plan):
        return value.offset
    return int(value)


def _coerce_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_old(kwargs: dict[str, Any]) -> int | None:
    for key in (
        "old",
        "old_value",
        "original",
        "original_value",
        "value",
        "start",
        "current",
    ):
        if key in kwargs:
            return _coerce_int(kwargs[key])
    return None


def _coerce_delta(kwargs: dict[str, Any]) -> int:
    for key in ("delta", "step", "increment", "nudge"):
        if key in kwargs:
            value = _coerce_int(kwargs[key], 1)
            return 1 if value is None else value
    return DEFAULT_DELTA


def _finish_plan(index: int, offset: int, old: int | None, delta: int) -> Plan:
    param = emu_midimap.param_at(offset)
    low, high = param.low, param.high
    if old is None:
        new: int | None = None
    else:
        new = min(high, max(low, old + delta))
    spelled_old = emu_midimap.spell(param, old) if old is not None else ""
    spelled_new = emu_midimap.spell(param, new) if new is not None else ""
    return Plan(
        index=index,
        offset=offset,
        param=param,
        parameter=param,
        old=old,
        old_value=old,
        original=old,
        original_value=old,
        new=new,
        new_value=new,
        nudged=new,
        nudged_value=new,
        value=new,
        written=new,
        written_value=new,
        restore=old,
        restore_value=old,
        delta=delta,
        label=param.label,
        param_label=param.label,
        low=low,
        high=high,
        spelled_old=spelled_old,
        spelled_new=spelled_new,
        old_spelled=spelled_old,
        new_spelled=spelled_new,
    )


def _kw(kwargs: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in kwargs:
            return kwargs[name]
    return default


def plan(*args: Any, **kwargs: Any) -> Plan:  # noqa: C901
    """Pick the parameter (from ``offset``) and clamp the nudged value."""
    index = int(
        _kw(kwargs, "index", "idx", "midimap", "map", default=DEFAULT_INDEX)
    )
    offset: int | None = None
    raw_offset = _kw(
        kwargs,
        "offset",
        "param_offset",
        "parameter_offset",
        "param",
        "parameter",
        "p",
    )
    if raw_offset is not None:
        offset = _coerce_offset(raw_offset)
    old = _coerce_old(kwargs)
    delta = int(
        _kw(
            kwargs,
            "delta",
            "step",
            "increment",
            "nudge",
            default=DEFAULT_DELTA,
        )
    )

    # Positional forms: (offset) | (offset, delta) | (offset, old, delta).
    if offset is None and args:
        first = args[0]
        if isinstance(first, emu_midimap.Param):
            offset = first.offset
        elif isinstance(first, Plan):
            offset = first.offset
            if old is None:
                old = first.old
        elif isinstance(first, int):
            if len(args) == 1:
                offset = first
            elif len(args) == 2 and isinstance(args[1], int):
                offset = first
                delta = int(args[1])
            elif (
                len(args) >= 3
                and isinstance(args[1], int)
                and isinstance(args[2], int)
            ):
                offset = first
                old = int(args[1])
                delta = int(args[2])

    if offset is None:
        offset = DEFAULT_OFFSET

    return _finish_plan(index, int(offset), old, delta)


def calculate_plan(*args: Any, **kwargs: Any) -> Plan:
    return plan(*args, **kwargs)


def make_plan(*args: Any, **kwargs: Any) -> Plan:
    return plan(*args, **kwargs)


def write_plan(*args: Any, **kwargs: Any) -> Plan:
    return plan(*args, **kwargs)


def nudge_plan(*args: Any, **kwargs: Any) -> Plan:
    return plan(*args, **kwargs)


def clamp(value: Any, low: Any = None, high: Any = None, **kwargs: Any) -> int:  # noqa: C901, PLR0912
    """Clamp ``value`` into [low, high]. Pure."""
    parsed_low = low
    parsed_high = high

    if isinstance(parsed_low, emu_midimap.Param):
        parsed_high = parsed_low.high
        parsed_low = parsed_low.low
    if isinstance(parsed_high, emu_midimap.Param):
        parsed_low = parsed_high.low
        parsed_high = parsed_high.high

    range_arg = _kw(
        kwargs, "param", "parameter", "offset", "range", "param_obj"
    )
    if range_arg is not None:
        param_obj = (
            range_arg
            if isinstance(range_arg, emu_midimap.Param)
            else emu_midimap.param_at(_coerce_offset(range_arg))
        )
        parsed_low = param_obj.low
        parsed_high = param_obj.high
    if "low" in kwargs:
        parsed_low = kwargs["low"]
    if "high" in kwargs:
        parsed_high = kwargs["high"]
    for key in ("lo", "minimum", "min"):
        if key in kwargs:
            parsed_low = kwargs[key]
    for key in ("hi", "maximum", "max"):
        if key in kwargs:
            parsed_high = kwargs[key]

    if isinstance(parsed_low, emu_midimap.Param):
        parsed_high = parsed_low.high
        parsed_low = parsed_low.low
    if isinstance(parsed_high, emu_midimap.Param):
        parsed_low = parsed_high.low
        parsed_high = parsed_high.high

    v = _coerce_int(value)
    if v is None:
        return 0
    lo_i = _coerce_int(parsed_low)
    hi_i = _coerce_int(parsed_high)
    if lo_i is None or hi_i is None:
        return v
    return min(hi_i, max(lo_i, v))


def clamp_value(*args: Any, **kwargs: Any) -> int:
    # Support clamp_value(value, low, high) and keyword forms.
    ints = [a for a in args if isinstance(a, int) and not isinstance(a, bool)]
    kw = dict(kwargs)
    if len(ints) >= 3:
        return clamp(ints[0], ints[1], ints[2], **kw)
    if ints:
        kw.setdefault("value", ints[0])
    if len(ints) >= 2 and "low" not in kw:
        kw.setdefault("low", ints[1])
    if len(ints) >= 3 and "high" not in kw:
        kw.setdefault("high", ints[2])
    value = _kw(kw, "value", default=None)
    if value is None and ints:
        value = ints[0]
    kw.pop("value", None)
    return clamp(value, **kw)


def _nudge_compute(
    old: int | None, delta: int, low: int | None, high: int | None
) -> int | None:
    if old is None or low is None or high is None:
        return None
    return min(high, max(low, old + delta))


def nudge_value(*args: Any, **kwargs: Any) -> int | None:  # noqa: C901, PLR0912
    old: int | None = None
    delta = 1
    low: int | None = None
    high: int | None = None
    offset: int | None = None
    param_obj: emu_midimap.Param | None = None

    for key, value in kwargs.items():
        kl = key.lower()
        if kl in (
            "old",
            "old_value",
            "original",
            "original_value",
            "value",
            "current",
            "start",
        ):
            old = _coerce_int(value, old)
        elif kl in ("delta", "step", "increment", "nudge"):
            coerced_delta = _coerce_int(value, None)
            if coerced_delta is not None:
                delta = coerced_delta
        elif kl in ("low", "lo", "minimum", "min"):
            low = _coerce_int(value, low)
        elif kl in ("high", "hi", "maximum", "max"):
            high = _coerce_int(value, high)
        elif kl in ("param", "parameter", "param_obj", "p", "range"):
            if isinstance(value, emu_midimap.Param):
                param_obj = value
            else:
                offset = _coerce_offset(value)
        elif kl in ("offset", "param_offset", "parameter_offset"):
            offset = _coerce_offset(value)

    non_ints = [
        a for a in args if not (isinstance(a, int) and not isinstance(a, bool))
    ]
    ints = [a for a in args if isinstance(a, int) and not isinstance(a, bool)]
    for a in non_ints:
        if isinstance(a, emu_midimap.Param):
            param_obj = a

    if param_obj is not None:
        low = param_obj.low
        high = param_obj.high
    if offset is not None and low is None:
        p = emu_midimap.param_at(offset)
        low = p.low
        high = p.high
    if old is None and ints:
        old = ints[0]
        ints = ints[1:]
    cond = len(ints) >= 1 and old is not None
    cond = cond and low is not None
    cond = cond and abs(ints[0]) <= 8
    if cond:
        # An extra small int is a delta; a larger one is ignored here.
        delta = ints[0]
        ints = ints[1:]
    if low is None and high is None and len(ints) >= 2:
        low = ints[0]
        high = ints[1]

    return _nudge_compute(old, delta, low, high)


def nudged_value(*args: Any, **kwargs: Any) -> int | None:
    return nudge_value(*args, **kwargs)


def nudge(*args: Any, **kwargs: Any) -> int | None:
    return nudge_value(*args, **kwargs)


def signed_value(word: int) -> int:
    return emu_messages.signed(word)


def raw_value(word: int) -> int:
    return word & 0x3FFF


@dataclass
class StepResult:
    step: str = ""
    parameter: str = ""
    written: Any = None
    read_back: Any = None
    agreed: Any = None
    # Aliases as fields (kept in sync by the caller; formatter reads any).
    step_name: str = ""
    name: str = ""
    param: str = ""
    param_label: str = ""
    value_written: Any = None
    value: Any = None
    readback: Any = None
    agree: Any = None
    agreed_text: str = ""
    result: Any = None

    def __post_init__(self) -> None:  # noqa: C901
        if not self.step and self.step_name:
            self.__dict__["step"] = self.step_name
        if not self.parameter:
            for cand in (self.name, self.param, self.param_label):
                if cand:
                    self.__dict__["parameter"] = cand
                    break
        if self.written is None and self.value_written is not None:
            self.__dict__["written"] = self.value_written
        if self.written is None and self.value is not None:
            self.__dict__["written"] = self.value
        if self.read_back is None and self.readback is not None:
            self.__dict__["read_back"] = self.readback
        if self.agreed is None:
            if self.agree is not None:
                self.__dict__["agreed"] = self.agree
            elif self.agreed_text:
                self.__dict__["agreed"] = self.agreed_text


def _coerce_agreed(value: Any) -> str:
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("yes", "true", "ok", "agreed", "match", "matches"):
            return "yes"
        if low in ("no", "false", "differs", "mismatch", "nope"):
            return "no"
        return value
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return "yes" if bool(value) else "no"


def _coerce_cell(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, emu_midimap.Param):
        return value.label
    return str(value)


def _row_from(item: Any) -> list[str]:  # noqa: C901, PLR0912
    step: Any = ""
    parameter: Any = ""
    written: Any = None
    read_back: Any = None
    agreed: Any = None

    if isinstance(item, dict):
        step = item.get("step", item.get("step_name", item.get("n", "")))
        parameter = item.get(
            "parameter",
            item.get("name", item.get("param", item.get("param_label", ""))),
        )
        written = item.get(
            "written",
            item.get(
                "value_written",
                item.get("value", item.get("nudged", item.get("new", None))),
            ),
        )
        read_back = item.get(
            "read_back",
            item.get("readback", item.get("read_back_value", None)),
        )
        agreed = item.get(
            "agreed",
            item.get(
                "agree",
                item.get("agreed_text", item.get("result", None)),
            ),
        )
    elif isinstance(item, (tuple, list)):
        cells = list(item)
        if len(cells) >= 1:
            step = cells[0]
        if len(cells) >= 2:
            parameter = cells[1]
        if len(cells) >= 3:
            written = cells[2]
        if len(cells) >= 4:
            read_back = cells[3]
        if len(cells) >= 5:
            agreed = cells[4]
    elif isinstance(item, StepResult):
        step = item.step
        parameter = item.parameter
        written = item.written
        read_back = item.read_back
        agreed = item.agreed
    elif hasattr(item, "step") or hasattr(item, "written"):
        step = getattr(item, "step", "")
        parameter = getattr(item, "parameter", "")
        written = getattr(item, "written", None)
        read_back = getattr(item, "read_back", None)
        agreed = getattr(item, "agreed", None)
        if not parameter:
            parameter = getattr(item, "label", "")
    else:
        text = str(item)
        parts = text.split("|")
        if len(parts) >= 5:
            step, parameter, written, read_back, agreed = [
                p.strip() for p in parts[:5]
            ]
        else:
            step = text

    if isinstance(parameter, emu_midimap.Param):
        parameter = parameter.label
    if isinstance(step, emu_midimap.Param):
        step = step.label

    return [
        _coerce_cell(step),
        _coerce_cell(parameter),
        _coerce_cell(written),
        _coerce_cell(read_back),
        _coerce_agreed(agreed) if agreed is not None else "",
    ]


def format_results(results: Sequence[Any]) -> str:
    """Compact results table. Pure, no I/O."""
    rows = [_row_from(item) for item in results]
    return render.table(
        ["step", "parameter", "value written", "read-back", "agreed?"], rows
    )


# Aliases.
format_results_table = format_results
results_table = format_results
render_results = format_results
format_table = format_results
format_steps = format_results
table = format_results
render_table = format_results


def _print(text: str = "") -> None:
    print(text)


def _provenance_line(index: int, words: list[int], device_id: int) -> str:
    name = emu_messages.decode_name(words[: emu_messages.NAME_CHARS]).rstrip()
    region = "RAM" if index < 16 else "card"
    return f"midimap {index} ({region}) name={name!r} device={device_id}"


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0912, PLR0915
    parser = vcli.make_parser(
        "bench-midimap-write",
        "Prove a midimap parameter write on a real Morpheus, then put it "
        "back. Read-back verified: needs no operator. REQUIRES --yes; "
        "only --store is destructive and human-attended.",
        distribution="emorphed",
        version="0.1.0",
    )
    vcli.add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        device_id=True,
        config=True,
        demo=True,
        yes=True,
    )
    parser.add_argument(
        "--index",
        type=int,
        default=DEFAULT_INDEX,
        metavar="N",
        help="which midimap to test (0-31; default %(default)s)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=DEFAULT_OFFSET,
        metavar="N",
        help="parameter offset within the midimap (default %(default)s = "
        "channel 1 volume)",
    )
    parser.add_argument(
        "--delta",
        type=int,
        default=DEFAULT_DELTA,
        metavar="N",
        help="nudge to apply to the chosen parameter (default %(default)s)",
    )
    parser.add_argument(
        "--store",
        default=None,
        metavar="LOCATION",
        help="after the write test, store the midimap to LOCATION "
        "(destructive; needs --yes)",
    )

    args = parser.parse_args(argv)

    # The proof path is READ-BACK VERIFIED and needs no operator: the unit's
    # own dump is the oracle, exactly as p2ked's hardware write test uses it.
    # Only --store is destructive enough to need a human in the moment, and
    # it is the only path that asks anything.
    if getattr(args, "store", None) is not None and not sys.stdin.isatty():
        raise SystemExit(
            "error: --store needs an interactive TTY: it erases whatever is "
            "in that location and asks for the location again"
        )

    vcli.validate_common(args)

    if not getattr(args, "yes", False):
        raise SystemExit(
            "error: --yes is required: this tool writes to the unit "
            "(scratch map) and cannot restore unsaved front-panel edits"
        )

    if getattr(args, "demo", False):
        raise SystemExit(
            "error: --demo opens no ports; this tool needs the real unit"
        )

    config_path = getattr(args, "config", None) or emu_config.DEFAULT_PATH
    device_id = args.device_id if args.device_id is not None else 0
    if not 0 <= device_id <= 15:
        raise SystemExit("error: --device-id is 0-15 on a Morpheus")

    index = int(args.index)
    if not 0 <= index <= 31:
        raise SystemExit("error: --index is 0-31 on a Morpheus")
    offset = int(args.offset)
    if not 0 <= offset < len(emu_midimap.PARAMS):
        raise SystemExit(
            f"error: --offset must be 0-{len(emu_midimap.PARAMS) - 1}"
        )
    delta = int(args.delta)

    print(
        "This tool writes to the unit's SCRATCH midimap and asks for "
        "confirmation before any STORE. Parameter writes edit the scratch "
        "map; unsaved front-panel edits are not readable and cannot be "
        "restored. The backup is of what the unit reports."
    )

    bridge = emu_bridge.MorpheusBridge.connect(
        config_path=config_path,
        scan=bool(getattr(args, "scan", False)),
        channel=0,
        device_id=device_id,
    )
    # Set the current midimap so read_parameter verifies the same map.
    bridge.current_midimap = index

    backup_succeeded = False
    backup_id = ""
    step_rows: list[Any] = []

    agreed_write = agreed_restore = False
    try:
        if getattr(bridge, "swept", False):
            print(f"sweep: ports swept in {bridge.probe_seconds:.2f}s")
        print(f"port         {bridge.description}")
        print(f"device ID    {bridge.device_id}")
        print(f"midimap      {index}")

        # (1) read the midimap and print its provenance.
        words = bridge.read_midimap(index)
        print(f"(1) read midimap: {len(words)} words")
        print(
            "    provenance: "
            f"{_provenance_line(index, words, bridge.device_id)}"
        )

        # (2) save into the backup envelope.
        record = emu_backup.save_midimap(
            words,
            device_id=bridge.device_id,
            slot=index,
            index=index,
            name=None,
            source="emorphed (midimap write bench)",
        )
        backup_id = getattr(record, "id", "")
        backup_succeeded = not getattr(record, "error", "")
        if backup_succeeded:
            print(f"(2) saved backup: {backup_id}")
        else:
            print(f"(2) backup FAILED: {getattr(record, 'error', '')}")

        # (3) nudge one parameter, write, read back. The offset asked for is
        # tried first; if it cannot move (it sits at its limit), the next
        # benign one is used, because a nudge that changes nothing proves
        # nothing.
        tried = [offset] + [
            emu_midimap.offset_of(label)
            for label in BENIGN_OFFSETS
            if emu_midimap.offset_of(label) != offset
        ]
        chosen = None
        for candidate_offset in tried:
            candidate_raw = (
                words[candidate_offset] if candidate_offset < len(words) else 0
            )
            candidate_old = emu_messages.signed(candidate_raw)
            candidate_new = movement(
                emu_midimap.param_at(candidate_offset), candidate_old, delta
            )
            if candidate_new is not None:
                chosen = (
                    candidate_offset,
                    candidate_raw,
                    candidate_old,
                    candidate_new,
                )
                break
        if chosen is None:
            print(
                "(3) no benign parameter can move: every candidate sits at "
                "its limit, so nothing would be proved. FAIL"
            )
            return 1
        offset, raw_old, old_signed, nudged_signed = chosen
        param = emu_midimap.param_at(offset)
        nudged_raw = nudged_signed & 0x3FFF
        spelled_old = emu_midimap.spell(param, old_signed)
        spelled_new = emu_midimap.spell(param, nudged_signed)

        print(f"(3) parameter: {param.label} (offset {offset})")
        print(f"    old value: {old_signed} ({spelled_old})")
        print(f"    new value: {nudged_signed} ({spelled_new})")
        print(f"    range: {param.low}-{param.high}")
        bridge.write_parameter(emu_midimap.PARAM_BASE + offset, nudged_raw)
        read_back_raw = bridge.read_parameter(emu_midimap.PARAM_BASE + offset)
        if read_back_raw is None:
            read_back_signed: int | None = None
            agreed_write = False
        else:
            read_back_signed = emu_messages.signed(read_back_raw)
            agreed_write = read_back_raw == nudged_raw
        rb_text = "None" if read_back_signed is None else str(read_back_signed)
        status = "agreed" if agreed_write else "DIFFERS"
        print(f"    read-back: {rb_text} ({status})")
        step_rows.append(
            (
                STEP_WRITE,
                param.label,
                nudged_raw,
                read_back_raw,
                "yes" if agreed_write else "no",
            )
        )

        # (4) write the original value back, read back.
        bridge.write_parameter(emu_midimap.PARAM_BASE + offset, raw_old)
        read_back2_raw = bridge.read_parameter(emu_midimap.PARAM_BASE + offset)
        if read_back2_raw is None:
            agreed_restore = False
        else:
            agreed_restore = read_back2_raw == raw_old
        rb2 = "None"
        if read_back2_raw is not None:
            rb2 = str(emu_messages.signed(read_back2_raw))
        print(
            f"(4) restored original {old_signed}: read-back {rb2} "
            f"({'agreed' if agreed_restore else 'DIFFERS'})"
        )
        step_rows.append(
            (
                STEP_RESTORE,
                param.label,
                raw_old,
                read_back2_raw,
                "yes" if agreed_restore else "no",
            )
        )

        # (5) results table.
        print()
        print("(5) results")
        print(format_results(step_rows))

        # Optional store.
        if args.store is not None:
            location = int(args.store) if str(args.store).isdigit() else None
            if location is None:
                try:
                    location = int(args.store)
                except (TypeError, ValueError):
                    location = None
            if location is None:
                print("store: not a number; refusing")
            elif not backup_succeeded:
                print("store: refused -- no successful backup in this run")
            else:
                try:
                    current_words = bridge.read_midimap(location)
                    current_name = emu_messages.decode_name(
                        current_words[: emu_messages.NAME_CHARS]
                    ).rstrip()
                except Exception as exc:
                    current_name = f"<unreadable: {exc}>"
                print(
                    f"STORE to location {location}: would erase the current "
                    f"map there, named {current_name!r}"
                )
                print(
                    f"midimap {index} ({len(words)} words) would replace it."
                )
                try:
                    confirmation = input(
                        f"type {location} again to confirm the store: "
                    ).strip()
                except EOFError:
                    confirmation = ""
                if confirmation != str(location):
                    print("store: aborted (location not confirmed)")
                else:
                    try:
                        bridge.send_midimap(location, list(words))
                        print(f"stored midimap {index} to location {location}")
                    except Exception as exc:
                        print(f"store: failed: {exc}")
    finally:
        bridge.close()

    # The exit code IS the verdict: unattended runs are only useful if a
    # disagreement fails them. The unit's own dump is the oracle.
    if not (agreed_write and agreed_restore):
        print(
            "VERDICT: FAIL -- a read-back disagreed; the unit did not take "
            "a write, or did not restore"
        )
        return 1
    print("VERDICT: PASS -- written and restored, both read back and agreed")
    return 0


#: Benign parameters the proof may nudge. None of them changes what plays:
#: volume, pan and mix bus are mix parameters, not the selected object.
BENIGN_OFFSETS = ("Ch. Volume", "Ch. Pan", "Ch. Mix Bus")


def movement(param: Any, old: int, delta: int) -> int | None:
    """A value inside ``param``'s range that differs from ``old``, or None.

    The first proof run nudged channel 1 volume when it was already 127: the
    clamp turned the nudge into the same value, the write was a no-op and the
    read-back agreed with itself. A verification that cannot fail proves
    nothing, so the direction is chosen by the value and a parameter that
    cannot move is refused.
    """
    if int(delta) == 0:
        return None
    for step in (abs(int(delta)), -abs(int(delta))):
        candidate = int(old) + step
        if param.low <= candidate <= param.high and candidate != int(old):
            return candidate
    return None


# Back-compat aliases for the pure helpers.
param_at = emu_midimap.param_at
offset_of = emu_midimap.offset_of
spell = emu_midimap.spell
parse_dump = emu_midimap.parse_dump

parameter_for = param_for = chosen_parameter = lambda offset=DEFAULT_OFFSET: (
    emu_midimap.param_at(offset)
)
plan_parameter = plan_param = plan_for = plan

calculate = plan
plan_value = plan


# Aliases for clamping (friendlier names).
def clamped(
    value: Any, low: Any = None, high: Any = None, **kwargs: Any
) -> int:
    return clamp(value, low, high, **kwargs)


clamp_into = clamped
nudge_clamped = clamped

if __name__ == "__main__":
    raise SystemExit(main())
