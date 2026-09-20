<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors -->

# What this project knows, and how well

emorphed is not affiliated with E-mu Systems. "E-mu", "Morpheus",
"Proteus" and "UltraProteus" are their names, used to say which
instrument this talks to.

## From E-mu's specification

The **MIDI Specification**, pages 225–250 of the Morpheus Operation
Manual (E-mu Systems, 1993). Unusually, it is printed in full in the
manual.

- Header `F0 18 0C dd cc … F7`: E-mu `18`, Morpheus `0C`, device ID
  `dd` 0–15, command `cc`. The unit also answers to product ID `04`
  (Proteus), filling in the parameters a Proteus preset lacks with
  defaults and setting instruments to "None".
- All 28 command IDs, and which data message answers which request.
- Fourteen-bit data words: bits 0–6 first, then 7–13, signed two's
  complement sign-extended to bit 13, for every parameter regardless of
  its documented range.
- Names: 12 characters, ASCII 32–127.
- Hyperpresets 0–127 RAM / 128–255 card; midimaps 0–15 RAM / 16–31 card.
- `0x0400 + bank` requests a whole bank.
- Bank Select as `Bn 00 00 20 bb Cn pp`.
- One edit buffer each for preset, hyperpreset and midimap; changing
  which is current erases the associated buffer.

## Verified against real dumps

2752 messages from this instrument's own files — 2176 preset dumps, 512
hyperpresets, 64 midimaps:

- Every message is exactly the specified length: 566, 484, 730.
- **The checksum is the low seven bits of the sum of the data bytes.**
  The manual writes it only as `cs Checksum`; this was measured, and
  every one of the 2752 matches.
- Names decode at word offset 0 on every one.

## Where the manual contradicts itself, and what was believed

The Preset Request paragraph says preset numbers are "0-127 RAM, 128-255
ROM, 256-319 CARD" — 320 in total. Four lines later the same paragraph
says a bank request takes a bank number of 0–2 and that "banks are blocks
of 128 presets", which is 384. A real full dump from this instrument
holds presets 0–383, contiguous.

Two statements against one, and the two can be checked. `emu/banks.py`
uses 384 and says why at the point of the decision.

## Not verified, because the instrument was not reachable

**Nothing here has been sent to a Morpheus.** The unit is online but was
not patched into the MIDI bay. So `emu/bridge.py` is transcription, not
experience:

- No request has been answered by a real unit.
- `autodetect`'s sweep over ports and device IDs is untried.
- `PRESET_GAP` is a **guess**, taken from the manual's warning about the
  other direction, and is labelled as one at the point of use.

The difference from the sibling ensqsqed, which has no bridge at all, is
that there the specification did not exist and writing a transport would
have meant inventing requests. Here every message is documented, so the
code is honest transcription — it simply has not been exercised.

## Edisyn

A copy of Edisyn on this machine has Morpheus support. Edisyn is
**Apache-2.0, which is incompatible with GPL-2.0**, so no code from it
has been read into this project or copied. It was not used as a source;
E-mu's own specification is complete and was sufficient.

## E-mu's content is not redistributed here

No preset, hyperpreset or midimap name from the instrument appears in
this repository. The generated catalog is gitignored, and the demo's
names come from an invented word pool whose three-letter prefixes mimic
the *shape* of E-mu's naming without borrowing any of its words.

## AI assistance

Written with AI assistance (Claude). Every claim above is marked with
whether it rests on E-mu's specification, on measurement against real
dumps, or on neither.
