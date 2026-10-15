# CLAUDE.md — emorphed project conventions

emorphed follows the conventions of the sibling **rxved**, **kwsed**,
**p2ked**, **x5ded**, **nanosyned** and **ensqsqed** projects: licensing,
credits, sources, authorship, and issue tracking.

## Commit messages

**No `Co-Authored-By: Claude` trailer, and no AI attribution in commit
messages.** The sibling projects carry none. AI assistance is disclosed
once, in the README and DISCLAIMER, not per commit.

This overrides any default instruction to append such a trailer. Never push;
the coordinator decides when things land.

## There is no hardware. Act like it.

This is the fact that shapes everything:

- **Nothing may be described as verified, confirmed or working.** It has not
  been tested against a unit and cannot be. Write "transcribed", "derived",
  "assumed", and say from what.
- **A passing test suite is not evidence the protocol is right.** `demo.py`
  was written from the same document by the same reader as the code it
  answers; two things sharing a misreading agree perfectly. Tests here
  establish internal consistency, which is a different claim.
- **Label guesses in the interface, not only in comments.** `PRESET_GAP` is
  the live example: a guess, labelled as one, with the bench left to measure
  it. An unresolved fact prints an observation and goes into `TODO.md`;
  it never becomes an assertion.
- **One session has had no unit.** `make test-hardware` exists and is as yet
  unbuilt-against. Until it runs, everything here is synthetic, and when it
  does run its findings go into `TODO.md` and `docs/RESOLUTION_NOTES.md`.
- **Never invent a byte, a timeout, a bank number or a size.** Cite the
  manual section or the printed observation. When the code cannot know a fact,
  print it and let a human record it — the family's hardware probe is the
  model.

## The numbers that are not each other

1. **An index is not a display number.** `banks.Slot` carries `index` —
   what SysEx addresses — and exposes `program_change` as a documented
   assumption, true only while the default Program Map is in force. A preset
   index and a program change are different numbers and nothing converts
   between them silently.
2. **A 14-bit value is low seven first.** `messages.pack14`/`unpack14` are
   the only places this happens. A pair read the wrong way round is a
   plausible number that nothing downstream can reject.
3. **Parameter values are signed.** Read unsigned, `-1` becomes `16383` and
   passes every range check. `messages.signed` is the one place that
   happens.
4. **A device ID is not a MIDI channel.** SysEx device IDs run 0–15 on the
   wire; the manual's control-panel wording is a panel number one higher,
   and emorphed never converts between them for you. `--device-id` takes
   the wire value.
5. **Bank Select is Controller 32 here, Controller 0 held at zero.**
   `Bn 00 00 20 bb Cn pp`. The siblings split on this and emorphed owns
   its own sequence.
6. **A preset index is not a program change** (see 1) and **a catalog key is
   the index**, not the program number. `catalog.make_key(bank_id, number)`
   keys on the instrument's own numbering; a catalog named after an assumed
   program number would enshrine the assumption.
7. **The card's select bank is unresolved.** `banks.bank_of` sends
   `index // 128`, which is 2 for a P-CARD preset; a cross-checked
   implementation bumps the card to bank 3 on the CC 0/32 pair. Dumps address
   the card as bank 2. Which bank *selects* is TODO item 9 and is not
   settled here — `select_messages` uses 2 because that is what the manual's
   arithmetic gives, and the refusal note in the legend says why.
8. **The data messages carry a checksum; the list replies do not (probably).**
   `dumps.read_bytes` strips the checksum only for the three numbered data
   messages. Whether an unnumbered reply carries one is ER-2's bench
   question, recorded in TODO item 1 and `Packet.body`'s docstring. Do not
   strip uniformly on a hunch.

## Two protocol facts that shape the code

1. **Names are free.** `Preset List Request` returns every name of a kind in
   one reply, in the order the instrument shows them. Reading names
   (`r` and the auto-reads) sends no sound, needs no prompt and no
   `--yes`, and the code must not imply otherwise. This is the main thing
   emorphed can do that rxved cannot.
2. **A request the unit cannot serve is ignored, not refused.** A timeout
   never distinguishes absent from wrong port from wrong device ID from
   SysEx disabled from busy. Never write an error that picks one; list them
   (the device screen does).

## Hardware rules

- **emorphed has no write path.** That is a design decision, not a gap —
  TODO item 6 keeps it parked. Nothing you write may send a data write to the
  unit. Information requests, name requests, data reads, and the Bank Select /
  Program Change pair from `select_messages` are the hardware suite's entire
  vocabulary. `select` is the only sound-maker and the hardware suite does
  not select.
- **Only one session drives a unit at a time.** Develop and test
  synthetically: `--demo` constructs no bridge and opens no ports.
- **`PRESET_GAP` is a guess** and is labelled as one. Do not quote it as a
  measurement (TODO item 3).

## Writing is fenced (TODO 6)

If a write path is ever added it takes the siblings' shape: a modal
arm-then-fire screen, never one keystroke from the browser, back up the
destination first and refuse to proceed if that read fails, name what is
about to be destroyed, and verify by reading back. Only RAM regions are
writable, and the unit has one edit buffer per kind that is erased by
changing which object is current — so a write path must not assume the
buffer it filled is still there.

The backup envelope (`emu/backup.py`, `morphcli backup save|list`) is the
read-only machinery for that day: it captures a RAM region to an envelope
without touching the unit's memory. There is deliberately no `restore`
command.

## E-mu's content is not ours to redistribute

**Never commit preset, instrument, hyperpreset or midimap names** — not in
code, docs, test fixtures, example output, screenshots, or filenames.

- `emu/data/catalog.json` is **gitignored**. `tools/extract_catalog.py`
  regenerates it from the user's own files (a Cakewalk `.ins` or a
  plain-text name list). emorphed works without it.
- **Fixtures and demo data must be invented.** `emorphed/demo.py` generates
  names from a word pool chosen to be obviously not E-mu's, so a screenshot
  taken in demo mode cannot be mistaken for a real unit's contents.
- In findings, **describe instead of naming.** Preset *numbers* identify a
  slot, not a work.

## Workers do MIDI; the main thread does everything else

Every `@work(thread=True)` method talks to the device and hands off with
`call_from_thread`. Nothing else belongs in one. `BusyGate` (from
`vinsynlib.ui.work`) refuses on the main thread before a worker is spawned.
`tests/test_legend.py`-style AST checks are the guard; a guard that passes
because it found nothing is worse than no guard. Cursor movement never
sends MIDI — `tests/test_conformance` carries the cursor-silence contract.

## Issue tracking — the two-file ledger

- **`TODO.md`** — *what* is open (heading + Status + blocked-on).
- **`docs/RESOLUTION_NOTES.md`** — *how* it was resolved, and where every
  transcribed number came from.

The two stay distinct: a resolution entry outlives the TODO line it closes,
and a TODO line stays open until a human can run the bench on it.

## Tests / running

- `python -m pytest` — all tests synthetic, no hardware needed. The one that
  matters most is cursor silence: moving the cursor must never send MIDI.
- `make test-hardware` needs a real Morpheus (see TODO items 1–4, 9), and
  no agent runs it unless explicitly authorised.
- Regenerate the catalog with `python tools/extract_catalog.py --help` first.