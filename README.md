<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors -->

# emorphed

A terminal browser for the **E-mu Morpheus** — its presets, hyperpresets
and midimaps, and the Z-plane machine's awkward habit of numbering
everything three different ways.

Sibling to [rxved](../rxved), [kwsed](../kwsed), [p2ked](../p2ked),
[x5ded](../x5ded), [nanosyned](../nanosyned) and
[ensqsqed](../ensqsqed), and it follows their conventions.

## What makes this one different

**The manual is the specification.** E-mu printed all twenty-six pages of
the MIDI spec as a chapter of the Operation Manual instead of making you
write away for it, which is the opposite of the SQ-R next door.

**One message gets every name.** `Preset List Request` returns all of
them, in the order the instrument shows them. None of the sibling
instruments can do that.

**Data is fourteen bits wide.** Every value is two MIDI bytes, low seven
first, signed two's complement sign-extended to bit 13 — *whatever* the
parameter's documented range. Read a dump a byte at a time and you get
plausible halves of numbers.

**Bank Select is Controller 32**, with Controller 0 held at zero:
`Bn 00 00 20 bb Cn pp`. That is the opposite way round from
[nanosyned](../nanosyned)'s instrument, which ignores 32 entirely.

**A preset index is not a program number.** The index is what SysEx
addresses; a Program Map decides what program change reaches it. The code
keeps them apart and says so when it assumes.

## Memory

| region | indices | n | |
|---|---|---|---|
| Presets RAM | 0–127 | 128 | writable |
| Presets ROM | 128–255 | 128 | |
| Presets card | 256–383 | 128 | card only |
| Hyperpresets RAM | 0–127 | 128 | writable |
| Hyperpresets card | 128–255 | 128 | card only |
| Midimaps RAM | 0–15 | 16 | writable |
| Midimaps card | 16–31 | 16 | card only |

## Running it

```
python -m emorphed.cli regions          # the memory map
python -m emorphed.cli --demo names     # every name, in one exchange
python -m emorphed.cli read dump.syx    # read a .syx, verify checksums
python -m emorphed.cli status           # ask the unit who it is
```

`read` checks every dump's checksum, so it can tell you a file is
*damaged* rather than only that it is the wrong length.

## Licence

GPL-2.0-or-later. AI assistance was used; see `DISCLAIMER.md`.
