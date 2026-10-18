#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
#
# Read one stored midimap from a Morpheus and print it as a ready-to-paste
# ``DEFAULT_WORDS = (...)`` tuple. Read-only: it sends no data to the unit
# and writes nothing to disk. The twelve-character name is printed first, so
# the capture can be checked before it is pasted anywhere.
#
# Usage::
#
#     python3 tools/read_midimap.py --index 2
#

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emu import bridge as emu_bridge
from emu import config as emu_config
from emu import midimap as emu_midimap
from vinsynlib import cli as vcli


def format_tuple(words: Sequence[int]) -> str:
    """Render ``words`` as a ready-to-paste ``DEFAULT_WORDS = (...)`` line."""
    body = ", ".join(str(int(word)) for word in words)
    if body:
        body = body + ","
    return f"DEFAULT_WORDS = ({body})"


def main(argv: list[str] | None = None) -> int:
    parser = vcli.make_parser(
        "read-midimap",
        "Read one stored midimap (command 0x46/0x47) from a Morpheus and "
        "print its name and 360 words as a ready-to-paste tuple. Read-only: "
        "no writes, no selection, no sound.",
        distribution="emorphed",
        version="0.1.0",
    )
    vcli.add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        device_id=True,
        config=True,
        demo=True,
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        metavar="N",
        help="which stored midimap to read (0-31; default %(default)s)",
    )

    args = parser.parse_args(argv)
    vcli.validate_common(args)

    if getattr(args, "demo", False):
        raise SystemExit(
            "error: --demo opens no ports; this tool needs the real unit"
        )

    config_path = getattr(args, "config", None) or emu_config.DEFAULT_PATH
    device_id = args.device_id if args.device_id is not None else 0
    if not 0 <= device_id <= 15:  # noqa: PLR2004
        raise SystemExit("error: --device-id is 0-15 on a Morpheus")

    index = int(args.index)
    if not 0 <= index <= 31:  # noqa: PLR2004
        raise SystemExit("error: --index is 0-31 on a Morpheus")

    bridge = emu_bridge.MorpheusBridge.connect(
        config_path=config_path,
        scan=bool(getattr(args, "scan", False)),
        channel=0,
        device_id=device_id,
    )
    try:
        if getattr(bridge, "swept", False):
            print(f"sweep: ports swept in {bridge.probe_seconds:.2f}s")
        print(f"port         {bridge.description}")
        print(f"device ID    {bridge.device_id}")
        words = bridge.read_midimap(index)
        name = emu_midimap.name_of(words)
        print(f"index        {index}")
        print(f"name         {name!r}")
        print(f"words        {len(words)}")
        print(format_tuple(words))
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
