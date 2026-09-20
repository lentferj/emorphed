<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors -->

# Resolution notes

How each thing was established. `TODO.md` says what is open.

## 1. The manual is the specification, and that is unusual

E-mu printed the whole MIDI specification — twenty-six pages, every
command, every data layout — as chapter 11 of the Operation Manual. No
writing away, no separate document, and it extracts as text because the
PDF has real fonts rather than being a scan.

Set against the rest of this collection: the Korg X5D has a MIDI
implementation chart and then the index; the Alesis NanoSynth has one
line; the Ensoniq SQ-R's manual gives a postal address and a three-week
wait. E-mu simply printed it.

The German edition was not needed and was not used.

## 2. Fourteen bits, and what it costs to forget

Every data word is two MIDI bytes — bits 0–6 first, then bits 7–13 — and
is *signed two's complement sign-extended to bit 13*, the manual says,
"regardless of the parameter's value range". So a pan documented as ±7
still arrives as fourteen bits, and reading it unsigned turns −7 into
16377.

`messages.signed` exists for that and is tested with that number.

## 3. The checksum, measured

The manual gives it as one line in each data-message layout: `cs
Checksum`. What it actually is: **the low seven bits of the sum of the
data bytes**.

Verified against every preset dump in the collection — 2176 of them,
plus 512 hyperpresets and 64 midimaps — and all 2752 match. That is why
`dumps.read_bytes` can report a file as *damaged* rather than only as
the wrong length, which none of the sibling readers can do.

## 4. Where the manual contradicts itself

The Preset Request paragraph, page 228:

> Preset numbers are: 0-127 RAM, 128-255 ROM, 256-319 CARD. Values
> 0x0400+ the bank number (0-2) represent request for banks. (Banks are
> blocks of 128 presets.)

Those two sentences disagree. The first gives 320 presets; the second
gives three banks of 128, which is 384. A full dump from the owner's own
instrument holds presets 0–383, contiguous, every checksum good.

Resolved in favour of 384: two statements against one, and the two are
the ones that can be checked. `banks.py` says so at the point of the
decision rather than in a commit message nobody will read again.

## 5. A preset index is not a program number

The Preset Request's first line: "Uses preset index values (not the same
as program numbers)." A Program Map sits between the two, and for a
preset in ROM or on a card there may be no program number at all until a
map gives it one.

So `banks.Slot` carries `index` — what SysEx addresses — and exposes
`program_change` as a documented *assumption*, true only while the
default map is in force. `morphcli select` prints that caveat every time
rather than claiming to have selected something.

This is the same family of trap as the sibling rxved's, where the
manual counts programs from 1 and MIDI from 0, and the sibling
ensqsqed's, where a program change *is* the bank select. Three
instruments, three different ways for a number not to mean what it says.

## 6. Bank Select is Controller 32 here

The manual's MIDI table gives the sequence literally:

```
Bank Select    Bn 00 00 20 bb Cn pp
```

Controller 0 set to zero, Controller 32 carrying the bank, then the
program change. The sibling nanosyned's instrument is the exact
opposite: its manual says it ignores Controller 32 entirely and only
Controller 0 works.

Neither is wrong. A helper that sent both "to be safe" would be lying
about one of them, which is why each project spells out its own.

## 7. One message gets every name

`Preset List Request` (0x12) returns every preset name in one reply, in
the order the instrument shows them, twelve ASCII characters each with a
null terminator. There are equivalents for hyperpresets and midimaps.

No other instrument in this collection can do this. The Wavestation
needs a whole-bank dump and the names decoded out of it; the NanoSynth
needs 128 separate requests; the X5D needs one bulk dump per bank. Here
it is one message out and one back.

**A caught error in the manual:** the Preset List Data section's byte
table gives its own command ID as `0F`, which is Instrument List Data's
ID and is what the block above it uses. The Command Summary table on
page 227 says `13`. The summary is right and the detail block is a
copy-paste slip; `Command.PRESET_LIST_DATA` is `0x13`. Worth knowing,
because a browser built on the detail block would wait forever for a
reply that had already arrived under another number.

## 8. Edisyn was not used

A copy of Edisyn with Morpheus support is on this machine. Edisyn is
Apache-2.0 and this project is GPL-2.0, which are incompatible in that
direction, so none of its code was read into this project. E-mu's own
specification is complete and was sufficient — it is cited in every
docstring that depends on it.

## 9. Rules carried in from the sibling projects

Arrived with the ported code: workers do MIDI and nothing else, because
the favourites store is SQLite and refuses cross-thread use; `_busy` is
set on the thread that checks it; favourites act on the row's own bank;
TOML values are escaped so a port name with a quote cannot poison the
config; a bad catalog row is skipped rather than fatal; `config.toml` is
disposable and gitignored while the favourites store lives in the
platform data directory; and the manufacturer's names are never
committed.
