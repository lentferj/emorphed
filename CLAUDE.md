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

- **emorphed writes midimap parameters, and nothing else.** Preset Data is
  never sent; a preset is only read, selected or backed up. The midimap
  parameter write path is the sole exception, and it is gated (below).
- **The hardware suite stays read-only.** Its vocabulary is information
  requests, name requests, data reads, and the Bank Select / Program Change
  pair from `select_messages`. `select` is the only sound-maker and the
  hardware suite does not select. The one write exception is
  `TestHardwareStore` (TODO item 6): a human-run bench step that stores
  midimap 0 to itself and puts it back -- no agent runs it.
- **Only one session drives a unit at a time.** Develop and test
  synthetically: `--demo` constructs no bridge and opens no ports.
- **`PRESET_GAP` is a guess** and is labelled as one. Do not quote it as a
  measurement (TODO item 3).

## Writing is fenced (TODO 6)

The one write path is **midimap parameters** (2048-2407). It is fenced, and
each rule below is a rule, not a suggestion:

- **The gate is locked by default.** `w` arms it; `--allow-write` arms only
  the *start* state, not every write. A locked gate refuses rather than
  sends, and the refusal is said in the interface, not swallowed.
- **Back up before the first write.** The first write reads the whole
  midimap into the backup envelope (`emu/backup.py`, kind/block "midimap");
  a failed backup is announced and the parameter write still proceeds --
  only the STORE refuses without a successful backup this session.
- **Every write is read back.** A parameter read *is* documented: the unit
  answers a Parameter Request (0x02) with the parameter's live value, so the
  read-back is one small frame, not a whole 730-byte dump. **Only an agreed
  read-back is logged**; a value that did not take is reported and not
  recorded for undo.
- **The store is named and confirmed.** Sending a whole midimap to a
  location is the one destructive step: it erases what is there (manual
  p.36). `s` opens a browser of the midimaps -- RAM 0-15 and card 16-31, by
  name -- and goes **arm-then-fire** from the chosen location: say what is
  erased, wait for a confirmation. It is refused outright without a
  successful backup this session. **`del` in the editor is the same store**
  aimed at the open location, carrying the captured factory default
  (``mm.DEFAULT_WORDS``, the unit's internal map named ``Dry`` -- not
  ``M00``, which is an ordinary user map): back up, confirm, store, read
  back. **`del` in the browser** aims the same reset at the midimap row
  under the cursor.
- **Scratch versus stored.** A parameter write edits the unit's **scratch**
  midimap: the value it is using right now, live, not permanent. Only a
  **store** makes an edit part of a stored location, and loading a stored map
  into the current location reloads the scratch map from it. Never describe a
  parameter write as saved. **A scratch edit is lost on a power cycle until
  it is stored** -- the editor carries an unstored marker until a store
  lands (manual p.233). The editor's `r` re-reads the **scratch**, not the
  stored dump, because that is where a write lands: the manual's sentence
  (p.232) is "The scratch map is accessed by requesting MASTER settings or
  individual parameter requests," and there is no scratch *dump* message, so a
  re-read is **360 Parameter Requests** -- one per parameter, offsets 0-359.
  Say the cost in the interface; a value that stays silent keeps what is on
  screen rather than becoming a zero.
- **Say it when you are assuming.** The current-midimap index comes from
  `bridge.current_midimap`, which only **selecting** a midimap sets; a midimap
  read (0x46/0x47) does **not** make a map current on the unit. When nothing
  has selected one this session the index is **assumed** (0) and the editor
  must say "assumed" rather than present a guess as the live map.
- **Never invent a parameter name.** The effect types and their parameters are
  transcribed from the manual (FX A: 25 types, FX B: 9). Where the manual does
  not break a type down -- "Ring Modulate" and "No Effect" -- the editor shows
  generic parameters; it does not name one it cannot cite.
- **One session drives the unit.** The write path is human-attended on
  hardware: the bench that proves it (`tools/bench_midimap_write.py`) refuses
  without `--yes` and a TTY, and no agent runs it. Develop and test
  synthetically (`--demo` opens no ports).
- The midimap editor's rows are collapsed to one summary row per channel by
  default; they expand on Enter and collapse again. `c` toggles all channels
  open/closed. Each channel's selected preset appears by name, and `+`/`-` steps
  through presets rolling across bank boundaries.

Preset writes remain **not offered** -- a preset is read, selected or backed
up, never written -- and there is still no `restore` command.

## E-mu's content is not ours to redistribute

**Never commit preset, instrument, hyperpreset or midimap names** — not in
code, docs, test fixtures, example output, screenshots, or filenames.

- `emu/data/catalog.json` is **gitignored**. `tools/extract_catalog.py`
  regenerates it from the user's own files (a Cakewalk `.ins` or a
  plain-text name list). emorphed works without it.
- **Fixtures and demo data must be invented.** `emorphed/demo.py` generates
  names from a word pool chosen to be obviously not E-mu's, so a screenshot
  taken in demo mode cannot be mistaken for a real unit's contents.
- **Deliberate divergence (rule 4):** the captured factory-default
  midimap's name (``Dry``) is committed in `emu/midimap.py` as
  `DEFAULT_WORDS`, so `DEL` produces the real factory map. This is the
  only place an E-mu midimap name appears in the repository, and it is
  kept because the default must be the unit's own map, not a guess. No
  other captured names are committed.
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