#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# Reads a name listing the user already owns -- a Cakewalk .ins file or a
# plain-text list -- and writes emu/data/catalog.json, which is gitignored.
# Nothing here is redistributed and nothing is fetched. emorphed runs without
# the file, showing numbers only.

"""Build emorphed's preset-name catalog from a user-supplied listing.

The ``.ins`` format is a Windows INI file in two halves. ``.Patch Names``
declares sections of ``<program change>=<name>``; ``.Instrument
Definitions`` declares, per instrument, ``Patch[<bank>]=<section name>``.
The plain-text form is one name per line under a prose heading that names
the bank (or, for a single-bank file, a heading-less list with ``--region``).

Usage::

    python3 tools/extract_catalog.py --ins ~/path/to/file.ins
    python3 tools/extract_catalog.py --from-text names.txt --region P-ROM
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any, TypeAlias

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emu import banks as emu_banks
from emu import catalog as emu_catalog

#: Short alias for the rows payload shape.
BankRows: TypeAlias = dict[str, list[dict[str, Any]]]

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "emu",
    "data",
    "catalog.json",
)

_SECTION = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_ENTRY = re.compile(r"^(?P<pc>\d+)\s*=\s*(?P<name>.*)$")
_PATCH_REF = re.compile(r"^Patch\[(?P<bank>\d+)\]\s*=\s*(?P<section>.+?)\s*$")

# Typographic characters a word processor substitutes, mapped back to the
# ASCII the instrument actually holds. A name on this machine is made of
# printable ASCII; leaving a curly apostrophe in place would make a name
# read as differing from the unit forever.
_TYPOGRAPHIC = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
}


def to_ascii(text: str) -> str:
    """Undo a word processor's substitutions, then drop anything left."""
    for fancy, plain in _TYPOGRAPHIC.items():
        text = text.replace(fancy, plain)
    return "".join(char for char in text if 32 <= ord(char) <= 126)  # noqa: PLR2004


def split_bank(bank: int) -> tuple[int, int]:
    """A Cakewalk bank number to ``(msb, lsb)``.

    ``bank = msb * 128 + lsb``. Doing it the other way round gives an MSB
    of 0-127 and an LSB of 0-1 for every ROM, which looks like data rather
    than like a mistake.
    """
    if not 0 <= bank <= 128 * 128 - 1:
        raise ValueError(f"bank {bank} is outside 0-16383")
    return (bank // 128, bank % 128)


def read_sections(path: str) -> dict[str, dict[int, str]]:
    """``{section name: {program change: preset name}}``."""
    sections: dict[str, dict[int, str]] = {}
    current: dict[int, str] | None = None
    with open(path, encoding="latin-1") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line or line.startswith(";"):
                continue
            found = _SECTION.match(line)
            if found:
                current = sections.setdefault(found.group("name"), {})
                continue
            if current is None:
                continue
            entry = _ENTRY.match(line)
            if entry:
                current[int(entry.group("pc"))] = entry.group("name").strip()
    return sections


def read_bank_refs(path: str) -> dict[int, str]:
    """``{bank number: section name}`` from ``.Instrument Definitions``."""
    refs: dict[int, str] = {}
    with open(path, encoding="latin-1") as handle:
        in_defs = False
        for raw in handle:
            line = raw.strip()
            if line.startswith(".Instrument Definitions"):
                in_defs = True
                continue
            if not in_defs:
                continue
            found = _PATCH_REF.match(line)
            if not found:
                continue
            refs[int(found.group("bank"))] = found.group("section")
    return refs


def _region_from_section(section: str) -> str | None:
    for region_id in emu_banks.region_ids():
        if re.search(r"\b" + re.escape(region_id) + r"\b", section):
            return region_id
    return None


def read_ins(path: str, region_override: str | None = None) -> BankRows:
    """Names from a Cakewalk ``.ins`` file, keyed by region id."""
    sections = read_sections(path)
    refs = read_bank_refs(path)
    out: BankRows = {}

    if region_override is not None:
        try:
            emu_banks.region(region_override)
        except LookupError:
            raise SystemExit(
                f"error: no such region {region_override!r}"
            ) from None

    for _bank_number, section in sorted(refs.items()):
        region_id: str | None
        if region_override is not None:
            region_id = region_override
        else:
            region_id = _region_from_section(section)
            if region_id is None:
                continue
        rows = sections.get(section)
        if not rows:
            continue
        target = out.setdefault(region_id, [])
        have = {row["n"] for row in target}
        for program_change, name in sorted(rows.items()):
            if program_change in have:
                continue
            cleaned = to_ascii(name)
            if not cleaned:
                continue
            target.append({"n": int(program_change), "name": cleaned})
            have.add(int(program_change))
        target.sort(key=lambda row: int(row["n"]))
    return out


def _line_region(line: str) -> str | None:
    for region_id in emu_banks.region_ids():
        if re.search(
            r"\b" + re.escape(region_id) + r"\b", line, re.IGNORECASE
        ):
            return region_id
    return None


def read_text(path: str, region_override: str | None = None) -> BankRows:
    """Names from a plain-text list -- one name per line, under a heading."""
    out: BankRows = {}
    if region_override is not None:
        try:
            emu_banks.region(region_override)
        except LookupError:
            raise SystemExit(
                f"error: no such region {region_override!r}"
            ) from None

    current: str | None = region_override
    counters: dict[str, int] = {}
    if current is not None:
        counters[current] = 0

    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            found_region = _line_region(line)
            if found_region is not None:
                current = found_region
                counters[current] = 0
                continue

            # A short prose heading with no region id is still a heading,
            # not a name. Without --region there is no target for it, so it
            # is skipped (and anything under it with no region stays out).
            if (
                region_override is None
                and current is None
                and (":" in line or line.lower().endswith("bank"))
                and len(line.split()) <= 8  # noqa: PLR2004
            ):
                continue

            if current is None:
                continue
            rows = out.setdefault(current, [])
            number = counters.get(current, 0)
            rows.append({"n": int(number), "name": line})
            counters[current] = number + 1
    for rows in out.values():
        rows.sort(key=lambda row: int(row["n"]))
    return out


def merge_sources(
    banks_out: BankRows,
    found: BankRows,
) -> None:
    for region_id, rows in found.items():
        target = banks_out.setdefault(region_id, [])
        have = {int(row["n"]) for row in target}
        for row in rows:
            number = int(row["n"])
            if number in have:
                continue
            target.append({"n": number, "name": str(row["name"])})
            have.add(number)
        target.sort(key=lambda row: int(row["n"]))


def check_no_duplicates(banks_out: BankRows) -> None:
    """Refuse a catalog where one slot is named twice."""
    for bank_id, rows in sorted(banks_out.items()):
        seen: dict[int, int] = {}
        for position, row in enumerate(rows):
            number = int(row["n"])
            if number in seen:
                raise SystemExit(
                    f"error: {bank_id} names slot {number:03d} twice, at "
                    f"rows {seen[number]} and {position}. One of the two "
                    f"names would be lost. Fix the reader that produced "
                    f"this bank rather than dropping a row."
                )
            seen[number] = position


def _has_control_chars(name: str) -> bool:
    return any(not (32 <= ord(char) <= 126) for char in name)  # noqa: PLR2004


def check_printable(banks_out: BankRows) -> None:
    """Refuse names with control or unprintable characters."""
    for bank_id, rows in sorted(banks_out.items()):
        for position, row in enumerate(rows):
            name = row["name"]
            if not isinstance(name, str) or _has_control_chars(name):
                raise SystemExit(
                    f"error: {bank_id} slot {int(row['n']):03d} name "
                    f"holds an unprintable or control character at row "
                    f"{position}; a Morpheus name is printable ASCII."
                )


# Aliases for the same guard, in case a caller uses another name.
check_printable_names = check_printable
check_control_chars = check_printable
reject_unprintable = check_printable


def verify_survives(path: str) -> None:
    """The written rows must come back after a load."""
    catalog = emu_catalog.load(path)
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    banks_in = payload.get("banks", {})
    if not isinstance(banks_in, dict):
        raise SystemExit(f"error: {path} did not round-trip: bad banks object")
    expected_total = sum(
        len(rows) for rows in banks_in.values() if isinstance(rows, list)
    )
    loaded_total = len(catalog)
    if loaded_total != expected_total:
        raise SystemExit(
            f"error: {path} did not survive re-reading: wrote "
            f"{expected_total} name(s), loaded {loaded_total}"
        )
    # Names must also match, not just the count.
    for bank_id, rows in banks_in.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            number = int(row["n"]) if "n" in row else int(row["pc"]) - 1
            name = str(row["name"])
            if catalog.display_name(bank_id, number) != name:
                raise SystemExit(
                    f"error: {path} did not survive re-reading: "
                    f"{bank_id}:{number:03d} changed"
                )


def preserve_existing(banks_out: BankRows, output: str) -> bool:  # noqa: C901
    """Carry forward banks this run did not produce."""
    if not os.path.exists(output):
        return False
    try:
        with open(output, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return False
    existing_banks = payload.get("banks", {})
    if not isinstance(existing_banks, dict):
        return False
    merged = False
    for bank_id, rows in existing_banks.items():
        if not isinstance(rows, list):
            continue
        target = banks_out.setdefault(str(bank_id), [])
        have = {
            int(row["n"])
            for row in target
            if isinstance(row, dict) and "n" in row
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                if "n" in row:
                    number = int(row["n"])
                elif "pc" in row:
                    number = int(row["pc"]) - 1  # wire to display edge
                else:
                    continue
                name = str(row["name"])
            except (KeyError, TypeError, ValueError):
                continue
            if number in have:
                continue
            target.append({"n": number, "name": name})
            have.add(number)
            merged = True
        target.sort(key=lambda row: int(row["n"]))
    return merged


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ins",
        action="append",
        default=None,
        metavar="FILE",
        help="a Cakewalk .ins file (repeatable)",
    )
    parser.add_argument(
        "--from-text",
        dest="from_text",
        action="append",
        default=None,
        metavar="FILE",
        help="a plain-text preset list (repeatable)",
    )
    parser.add_argument(
        "--region",
        action="append",
        default=None,
        metavar="REGION",
        help="target region for a bank-less file, e.g. P-ROM (repeatable)",
    )
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    ins_paths = args.ins or []
    text_paths = args.from_text or []
    if not ins_paths and not text_paths:
        parser.error("give at least one --ins or --from-text source")

    missing = [
        path for path in (ins_paths + text_paths) if not os.path.exists(path)
    ]
    if missing:
        raise SystemExit("error: no such file: " + ", ".join(missing))

    region_flags: list[str] = args.region or []

    banks_out: BankRows = {}
    sources: list[str] = []

    # Pair regions to sources, oldest-first; a single flag covers all of them.
    def region_for(index: int) -> str | None:
        if not region_flags:
            return None
        if len(region_flags) == 1:
            return region_flags[0]
        if index < len(region_flags):
            return region_flags[index]
        return region_flags[0]

    for i, path in enumerate(ins_paths):
        found = read_ins(path, region_for(i) if region_flags else None)
        merge_sources(banks_out, found)
        sources.append(os.path.basename(path))

    # Re-index region flags for text sources, continuing after the .ins ones.
    offset = len(ins_paths)
    for j, path in enumerate(text_paths):
        idx = offset + j
        found = read_text(path, region_for(idx) if region_flags else None)
        merge_sources(banks_out, found)
        sources.append(os.path.basename(path))

    check_no_duplicates(banks_out)
    check_printable(banks_out)

    merged = preserve_existing(banks_out, args.output)
    if merged:
        sources.append("existing catalog")

    payload: dict[str, Any] = {
        "source": "; ".join(sources),
        "generated": datetime.date.today().isoformat(),
        "note": (
            "Generated locally by tools/extract_catalog.py from the user's "
            "own listing. Not distributed with emorphed."
        ),
        "banks": banks_out,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    verify_survives(args.output)

    total = sum(len(rows) for rows in banks_out.values())
    print(f"wrote {args.output}: {total} names across {len(banks_out)} banks")
    for bank_id in sorted(banks_out):
        print(f"  {bank_id:<8} {len(banks_out[bank_id]):>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
