<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors -->

# TODO

What is open. *How* anything was resolved goes in
`docs/RESOLUTION_NOTES.md`.

## Status, 2026-09-20 (first session)

Protocol transcribed from E-mu's specification and checked against 2752
real messages: header, commands, sizes, fourteen-bit words, names and
checksum all agree. Library, bridge and CLI written. 30 tests, all
synthetic.

**Nothing has been sent to a Morpheus** -- it is online but not patched
into the MIDI bay.

## 1. The bridge has never talked to the instrument

**Status:** open, and the first thing to do at the bench.

`emu/bridge.py` is complete and unexercised. In order:

* `morphcli status` -- a Version Request is the smallest, safest probe
* `morphcli names` -- one message, every preset name; if this works the
  browser is essentially done
* `morphcli read` against a bank request, to see whether a 72 kB reply
  arrives in one message or several

Then `autodetect`, whose sweep over sixteen device IDs times every port
has never been run and may well be too slow to be pleasant.

**Blocked on:** the Morpheus being patched in.

## 2. Two things in the manual disagree about the card

**Status:** resolved in favour of the data; worth confirming.

"256-319 CARD" against "banks are blocks of 128, bank numbers 0-2", and a
real dump holding 0-383. `banks.py` uses 384.

What would settle it beyond doubt: a Configuration Request on a unit with
and without a card fitted.

**Blocked on:** item 1, and a card.

## 3. `PRESET_GAP` is a guess

**Status:** open, blocked on wanting to measure it.

The manual warns that sending presets to the unit needs roughly 100 ms
between them or the input buffer clogs, and offers a SysEx Packet Delay
setting for the reverse. This program only reads, so the number is used
defensively when walking presets one at a time. It has not been measured
in the read direction.

## 4. Hyperpresets and midimaps are read but not browsed

**Status:** open.

`morphcli names hyperpreset` and `names midimap` work, and dumps of both
parse. The browser does not have a pane for them.

A hyperpreset stacks up to 16 zones of presets; a midimap assigns a
preset to each of 16 channels and **cannot be selected with a program
change at all** -- SysEx is the only way. That last fact is the strongest
argument for giving them a pane, since the front panel is the only other
route.

## 5. There is no TUI yet

**Status:** open.

`morphcli` does the reading. The Textual browser the siblings have --
two panes, favourites, tags, notes, the F cycle -- is not written. The
shared modules it needs are ported and working.

Should follow item 1, so `⏎` has something real to send to.

## 6. Nothing writes, and adding a write is a decision

**Status:** open, and the fence is the point.

The protocol can write: Preset Data sent *to* the unit replaces a preset,
and there are parameter-value commands that edit the current one.

If that is ever added it takes the siblings' shape: a modal arm-then-fire
screen, never one keystroke from the browser, back up the destination
first and refuse to proceed if that read fails, say what is about to be
destroyed **by name**, and verify by reading back.

Note that only RAM regions are writable at all, and that the unit has one
edit buffer per kind which is erased by changing which object is current
-- so a write path must not assume the buffer it filled is still there.

## 7. The MidiQuest `.sqs` format is unread — shared across the projects

**Status:** open, and not specific to this instrument.

The same chunked MidiQuest bank format turns up in every instrument's
folder in this collection. Decoding it once would serve rxved, kwsed,
p2ked, x5ded, nanosyned, ensqsqed and this one alike.

**Blocked on:** nothing but the decoding.
