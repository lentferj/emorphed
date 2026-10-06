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

from emu import banks, config, dumps
from emu import catalog as cat
from emu.device import Device
from vinsynlib.cli import (
    add_common_arguments,
    channel_of,
    make_parser,
    validate_common,
)

__all__ = ["build_parser", "main"]


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    if not rows:
        return "(nothing)"
    widths = [
        max(len(str(r[i])) for r in (*rows, headers))
        for i in range(len(headers))
    ]
    out = [
        "  ".join(str(h).ljust(w) for h, w in zip(headers, widths)).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        out.append(
            "  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip()
        )
    return "\n".join(out)


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


OFFLINE = {"regions", "list", "read"}


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser(
        "morphcli",
        "Browse an E-mu Morpheus. Read-only except `select`.",
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
    return parser


COMMANDS: dict[str, Callable[..., int | None]] = {
    "regions": _cmd_regions,
    "list": _cmd_list,
    "names": _cmd_names,
    "status": _cmd_status,
    "select": _cmd_select,
    "read": _cmd_read,
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
    if args.command not in OFFLINE:
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
                            f"  probing {n}...", file=sys.stderr
                        ),
                    )
                device = bridge
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
