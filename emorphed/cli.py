# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# This file is part of emorphed.
#
# emorphed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# emorphed is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""``morphcli`` -- the Morpheus's memory, read-only except ``select``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Any, cast

from emu import backup as bk
from emu import banks, config, dumps
from emu import catalog as cat
from emu import favorites as favmod
from emu.device import Device
from vinsynlib import render
from vinsynlib.cli import (
    add_common_arguments,
    channel_of,
    make_parser,
    validate_common,
)

__all__ = ["build_parser", "main"]


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    return render.table(headers, rows, empty="(nothing)")


def _cmd_regions(_device: Device | None, _args: argparse.Namespace) -> None:
    rows = []
    for entry in banks.regions():
        rows.append(
            [
                entry.id,
                entry.label,
                entry.kind,
                f"{entry.first}-{entry.last}",
                str(entry.count),
                "yes" if entry.writable else "no",
                "card" if entry.needs_card else "",
            ]
        )
    print(
        _table(
            rows, ["id", "name", "kind", "indices", "n", "writable", "needs"]
        )
    )
    print(
        f"\n{banks.TOTAL_PRESETS} presets, plus hyperpresets and "
        f"midimaps.\nA preset *index* is what SysEx addresses; it is not "
        f"a program number.\nBank Select is Controller 32, with "
        f"Controller 0 held at zero."
    )


def _cmd_list(_device: Device | None, args: argparse.Namespace) -> None:
    entry = banks.region(args.region)
    catalog = cat.load(getattr(args, "catalog", None))
    rows = []
    for item in banks.slots(entry.id):
        rows.append(
            [
                f"{item.number:03d}",
                str(item.index),
                catalog.display_name(item.bank_id, item.number),
            ]
        )
    print(f"{entry.label} — {entry.count}\n")
    print(_table(rows, ["#", "index", "name"]))
    if entry.note:
        print(f"\n{entry.note}")


def _cmd_names(device: Device, args: argparse.Namespace) -> None:
    """Every name of one kind, in one exchange. Silent."""
    names = device.names(args.kind)
    rows = [[f"{n:03d}", text.rstrip()] for n, text in enumerate(names)]
    print(f"{len(names)} {args.kind}(s)\n")
    print(_table(rows, ["#", "name"]))


def _cmd_status(device: Device, _args: argparse.Namespace) -> None:
    """Ask the unit its version and what is fitted. Silent."""
    version = device.version()
    print(f"port            {device.description}")
    print(f"device ID       {device.device_id}")
    print(f"version bytes   {' '.join(f'{b:02X}' for b in version)}")
    try:
        config_bytes = device.configuration()
        print(f"configuration   {' '.join(f'{b:02X}' for b in config_bytes)}")
    except Exception as exc:
        print(f"configuration   unavailable ({exc})")


def _cmd_select(device: Device, args: argparse.Namespace) -> int:
    """Select a preset. **This makes the unit play.**"""
    try:
        target = banks.slot(args.region, args.number)
    except LookupError as exc:
        raise SystemExit(f"error: {exc}")
    if not args.yes:
        print(
            f"about to select {target.display} on MIDI channel "
            f"{device.channel + 1}."
        )
        print("This changes what the instrument is playing.")
        if input("proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("nothing sent")
            return 1
    device.select(target)
    print(
        f"selected {target.display} — Bank Select 32 = "
        f"{banks.bank_of(target.kind, target.index)}, Program Change "
        f"{target.program_change}"
    )
    print(
        "(that program number reaches this preset only while the "
        "default Program Map is in force)"
    )
    return 0


def _cmd_read(_device: Device | None, args: argparse.Namespace) -> None:
    """Read a .syx dump. No hardware."""
    library = dumps.read_file(args.file)
    print(f"{args.file}: {library.summary()}")
    for line in library.corrupt[:10]:
        print(f"  !! {line}")
    if len(library.corrupt) > 10:
        # Saying "and 30 more" matters: ten lines followed by a table of
        # the survivors reads as "mostly fine" when it is not.
        print(f"  !! ...and {len(library.corrupt) - 10} more")
    names = library.names(args.kind)
    if names:
        rows = [
            [f"{n:03d}", text.rstrip()] for n, text in sorted(names.items())
        ]
        print()
        print(_table(rows, ["#", "name"]))


def _favorites(args: argparse.Namespace) -> favmod.Favorites:
    return favmod.Favorites(getattr(args, "favorites", None))


def _catalog(args: argparse.Namespace) -> cat.Catalog:
    return cat.load(getattr(args, "catalog", None))


def _parse_slot(text: str) -> tuple[str, int]:
    for separator in (":", "/", " "):
        if separator in text:
            bank_id, _, number = text.partition(separator)
            try:
                return bank_id.strip(), int(number)
            except ValueError:
                break
    raise SystemExit(
        f"error: {text!r} is not a slot; "
        "write it as REGION:NUMBER, e.g. P-RAM:001"
    )


def _rating_stars(value: object, flag: str) -> int:
    try:
        stars = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        raise SystemExit(f"error: {flag} wants 0-5, not {value!r}")
    if not 0 <= stars <= 5:
        raise SystemExit(f"error: {flag} wants 0-5, not {stars}")
    return int(stars)


def _rated(args: argparse.Namespace, rows: list[Any]) -> list[Any]:
    if getattr(args, "rating_at_least", None) is not None:
        stars = _rating_stars(args.rating_at_least, "--rating-at-least")
        return [row for row in rows if row.rating >= stars]
    if getattr(args, "rating_exactly", None) is not None:
        stars = _rating_stars(args.rating_exactly, "--rating-exactly")
        return [row for row in rows if row.rating == stars]
    return rows


def _cmd_fav(_device: Device | None, args: argparse.Namespace) -> None:  # noqa: PLR0915
    from vinsynlib.favorites import rating_cell

    favorites = _favorites(args)
    catalog = _catalog(args)
    try:
        if args.add:
            bank_id, number = _parse_slot(args.add)
            name = (
                catalog.display_name(bank_id, number)
                if hasattr(catalog, "display_name")
                else (catalog.name(bank_id, number) or "")
            )
            existing = favorites.get(bank_id, number)
            if existing is None:
                rating, tags, note = 0, "", ""
            else:
                rating = existing.rating
                tags = existing.tags
                note = existing.note
            if getattr(args, "rating", None) is not None:
                rating = _rating_stars(args.rating, "--rating")
            if getattr(args, "tags", None) is not None:
                tags = args.tags
            if getattr(args, "note", None) is not None:
                note = args.note
            favorites.add(
                bank_id, number, name=name, rating=rating, tags=tags, note=note
            )
            print(f"added {bank_id} {number:03d}")
            return
        if args.rate:
            bank_id, number = _parse_slot(args.rate[0])
            if favorites.get(bank_id, number) is None:
                raise SystemExit(
                    f"error: {bank_id} {number:03d} is not a favourite; "
                    f"add it first"
                )
            stars = _rating_stars(args.rate[1], "--rate")
            favorites.set_rating(bank_id, number, stars)
            print(f"rated {bank_id} {number:03d} {stars}")
            return
        if args.remove:
            bank_id, number = _parse_slot(args.remove)
            if favorites.remove(bank_id, number):
                print(f"removed {bank_id} {number:03d}")
            else:
                print(
                    f"{bank_id} {number:03d} was not a favourite",
                    file=sys.stderr,
                )
            return
        if getattr(args, "tag", None):
            rows = favorites.with_tag(args.tag)
        elif getattr(args, "search", None):
            rows = favorites.search(args.search)
        else:
            rows = favorites.all(order=args.order)
        rows = _rated(args, rows)
        if not rows:
            print("no favourites", file=sys.stderr)
            return
        table = []
        for fav in rows:
            try:
                slot = banks.slot(fav.bank_id, fav.number)
                wire = [
                    str(getattr(slot, "msb", "?")),
                    str(getattr(slot, "lsb", "?")),
                    str(getattr(slot, "program_change", "?")),
                ]
            except LookupError:
                wire = ["?", "?", "?"]
            table.append(
                [
                    fav.bank_id,
                    f"{fav.number:03d}",
                    fav.name
                    or (
                        catalog.display_name(fav.bank_id, fav.number)
                        if hasattr(catalog, "display_name")
                        else (catalog.name(fav.bank_id, fav.number) or "")
                    ),
                    *wire,
                    rating_cell(fav.rating),
                    fav.tags,
                    fav.note,
                ]
            )
        print(
            _table(
                table,
                [
                    "bank",
                    "#",
                    "name",
                    "MSB",
                    "LSB",
                    "PC",
                    "rating",
                    "tags",
                    "note",
                ],
            )
        )
    finally:
        favorites.close()


def _cmd_tags(_device: Device | None, args: argparse.Namespace) -> None:
    favorites = _favorites(args)
    try:
        counts = favorites.tags()
    finally:
        favorites.close()
    if not counts:
        print("no tags", file=sys.stderr)
        return
    print(
        _table([[tag, str(n)] for tag, n in counts.items()], ["tag", "count"])
    )


def _cmd_ports(_device: Device | None, _args: argparse.Namespace) -> None:

    from vinsynlib import midi

    try:
        ins, outs = midi.list_ports()
    except midi.MidiUnavailable as exc:
        raise SystemExit(f"error: {exc}")
    print(
        midi.render_ports(
            ins, outs, likely=[], likely_label="looks like an E-mu"
        )
    )


def _backup_dir(args: argparse.Namespace) -> str:
    return args.dir or bk.default_dir()


def _cmd_backup_list(_device: Device | None, args: argparse.Namespace) -> None:
    import json

    directory = _backup_dir(args)
    rows = bk.list_backups(args.dir)
    if getattr(args, "json", False):
        payload = {
            "directory": directory,
            "backups": [
                {
                    "id": backup.id,
                    "kind": backup.kind,
                    "slot": backup.slot,
                    "name": backup.name,
                    "saved": _when(backup.saved),
                    "device_id": backup.device_id,
                    "source": backup.source,
                    "error": backup.error,
                }
                for backup in rows
            ],
        }
        print(json.dumps(payload, indent=2))
        return
    if not rows:
        print(f"no backups in {directory}")
        return
    print(f"{directory}\n")
    table_rows = []
    for backup in rows:
        if backup.error is not None:
            table_rows.append([backup.id, "", "", "", backup.error])
            continue
        table_rows.append(
            [
                backup.id,
                backup.kind,
                backup.name,
                _when(backup.saved),
                backup.device_id,
            ]
        )
    print(_table(table_rows, ["id", "kind", "name", "saved", "device"]))


def _when(saved: float) -> str:
    import time as _time

    if not saved:
        return ""
    return _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(saved))


def _cmd_backup_save(device: Device, args: argparse.Namespace) -> None:
    import time as _time

    from emu import bridge as _bridge

    if not getattr(args, "yes", False):
        raise SystemExit(
            "error: reading a whole RAM region needs --yes (128 requests)"
        )
    entry = banks.region(args.region)
    if entry.kind != banks.Kind.PRESET:
        raise SystemExit(
            f"error: {entry.id} is not a preset region; preset backups only"
        )
    directory = _backup_dir(args)
    total = entry.count
    done = 0
    print(f"reading {entry.label} ({total})...", file=sys.stderr)
    device_any = cast(Any, device)
    for slot in banks.slots(entry.id):
        if done > 0:
            _time.sleep(_bridge.PRESET_GAP)
        words = device_any.read_preset(slot.index)
        bk.save_preset(
            words,
            device_id=device.device_id,
            slot=slot.index,
            source="emorphed (backup save)",
            directory=args.dir,
        )
        done += 1
        print(
            render.progress("preset", done, total),
            end="",
            file=sys.stderr,
            flush=True,
        )
    print("", file=sys.stderr)
    print(f"saved {done} preset(s) to {directory}")


def _cmd_backup(_device: Device | None, args: argparse.Namespace) -> None:
    if args.backup_command == "list":
        _cmd_backup_list(_device, args)
    elif args.backup_command == "save":
        _cmd_backup_save(cast(Device, _device), args)
    else:
        raise SystemExit(
            f"error: unknown backup command {args.backup_command!r}"
        )


def _offline(args: argparse.Namespace) -> bool:
    if args.command in OFFLINE:
        return True
    is_backup_list = (
        args.command == "backup"
        and getattr(args, "backup_command", None) == "list"
    )
    return is_backup_list


OFFLINE = {"regions", "list", "read", "fav", "tags", "ports"}


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser(
        "morphcli",
        "Browse an E-mu Morpheus. Read-only except `select`.",
        distribution="emorphed",
    )
    add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        device_id=True,
        catalog=True,
        config=True,
        demo=True,
        yes=True,
        favorites=True,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("regions", help="the memory map")
    sp = sub.add_parser("list", help="every slot in a region")
    sp.add_argument("region", choices=banks.region_ids())
    sp = sub.add_parser("names", help="read every name (silent)")
    sp.add_argument(
        "kind",
        nargs="?",
        default=banks.Kind.PRESET,
        choices=list(banks.Kind.ALL),
    )
    sub.add_parser("status", help="ask the unit who it is (silent)")
    sp = sub.add_parser("select", help="select a preset ON THE UNIT")
    sp.add_argument("region", choices=banks.region_ids(banks.Kind.PRESET))
    sp.add_argument("number", type=int)
    sp = sub.add_parser("read", help="read a .syx dump (no hardware)")
    sp.add_argument("file")
    sp.add_argument(
        "kind",
        nargs="?",
        default=banks.Kind.PRESET,
        choices=list(banks.Kind.ALL),
    )

    sp = sub.add_parser("fav", help="the favourites database")
    sp.add_argument("--add", metavar="REGION:N")
    sp.add_argument("--remove", metavar="REGION:N")
    sp.add_argument("--rating", type=int, default=None)
    sp.add_argument(
        "--rate",
        nargs=2,
        metavar=("REGION:N", "0-5"),
        help="rate a favourite you already have",
    )
    sp.add_argument("--tags", default=None)
    sp.add_argument("--note", default=None)
    sp.add_argument("--tag", default=None, help="favourites with this tag")
    sp.add_argument("--search", default=None)
    ratings = sp.add_mutually_exclusive_group()
    ratings.add_argument(
        "--rating-at-least", type=int, default=None, metavar="0-5"
    )
    ratings.add_argument(
        "--rating-exactly", type=int, default=None, metavar="0-5"
    )
    sp.add_argument(
        "--order", default="added", choices=["added", "rating", "bank", "name"]
    )

    sub.add_parser("tags", help="tags in use, with counts")

    sub.add_parser("ports", help="MIDI ports on this host")

    sp = sub.add_parser("backup", help="preset backups: list, save")
    bsub = sp.add_subparsers(dest="backup_command", required=True)
    bp = bsub.add_parser("list", help="backups on disk")
    bp.add_argument("--dir", help="backup directory")
    bp.add_argument("--json", action="store_true")
    bp = bsub.add_parser("save", help="read a RAM region's presets to backups")
    bp.add_argument("region", choices=banks.region_ids(banks.Kind.PRESET))
    bp.add_argument("--dir", help="backup directory (default: the data dir)")
    bp.add_argument("--yes", action="store_true")

    return parser


COMMANDS: dict[str, Callable[..., int | None]] = {
    "regions": _cmd_regions,
    "list": _cmd_list,
    "names": _cmd_names,
    "status": _cmd_status,
    "select": _cmd_select,
    "read": _cmd_read,
    "fav": _cmd_fav,
    "tags": _cmd_tags,
    "ports": _cmd_ports,
    "backup": _cmd_backup,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = getattr(args, "config", None) or config.DEFAULT_PATH
    validate_common(args)
    # channel_of subtracts one: --channel is 1-16 on every command line in
    # this family and 0-15 on the wire. The trailing `or 0` covers only the
    # case where neither the option nor the cache had one; it cannot turn a
    # real channel 0 into anything else.
    channel = channel_of(args, default=config.load_channel(config_path)) or 0
    device_id = (
        args.device_id
        if args.device_id is not None
        else (config.load_device_id(config_path) or 0)
    )
    # The family's check is against a byte, because that is what a SysEx
    # device ID is in most of these protocols. A Morpheus only answers to
    # the low sixteen of them.
    if not 0 <= device_id <= 15:
        raise SystemExit("error: --device-id is 0-15 on a Morpheus")

    device: Device | None = None
    if not _offline(args):
        if args.demo:
            from emorphed.demo import DemoDevice

            device = DemoDevice(device_id=device_id, channel=channel)
        else:
            from emu import bridge as b

            try:
                if args.port:
                    bridge = b.MorpheusBridge.open(
                        args.port,
                        recv_port=(
                            args.recv_port
                            or config.load_last_recv_port(config_path)
                        ),
                        device_id=device_id,
                        channel=channel,
                    )
                else:
                    # One Version Request to the remembered port; the sweep
                    # only when there is nothing remembered, when the
                    # remembered port no longer answers, or on --scan.
                    bridge = b.MorpheusBridge.connect(
                        config_path=config_path,
                        channel=channel,
                        device_id=device_id,
                        scan=args.scan,
                        on_try=lambda n: print(
                            f"  probing {n}", file=sys.stderr
                        ),
                    )
                device = bridge
                if getattr(bridge, "swept", False):
                    print(
                        f"swept for {bridge.probe_seconds:.1f} s; found "
                        f"{bridge.port} (device {bridge.device_id})",
                        file=sys.stderr,
                    )
                try:
                    if bridge.port:
                        config.save_last_port(bridge.port, config_path)
                        config.save_device_id(bridge.device_id, config_path)
                    recv = bridge.recv_port
                    if recv and recv != bridge.port:
                        config.save_last_recv_port(recv, config_path)
                except OSError:
                    pass
            except Exception as exc:
                raise SystemExit(f"error: {exc}")

    try:
        result = COMMANDS[args.command](device, args)
    except (
        LookupError,
        TimeoutError,
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        # OSError because `read` is the one command that opens a path the
        # user typed. Its whole pitch is telling them a file is damaged
        # rather than wrong; a missing one deserves the same sentence.
        raise SystemExit(f"error: {exc}")
    finally:
        if device is not None:
            device.close()
    return result or 0


if __name__ == "__main__":
    raise SystemExit(main())
