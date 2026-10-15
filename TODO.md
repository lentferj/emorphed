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

The bench is built (T9, `581c4ed`: `tests/test_hardware.py`,
`tests/conftest.py`, `make test-hardware`) and awaits a human run; no agent
drives the unit. Its steps would answer this item's listed probes: a Version
Request round-trip, `names()` for all three kinds, and `read_preset`
checksum recomputation.<|end|><|start|><|start|>assistant to=edit<|channel|>analysis <|constrain|>xml<|message|><rfl:parameter name="path">
/home/lentferj/git-repos/emorphed/TODO.md

## 2. Two things in the manual disagree about the card

**Status:** resolved in favour of the data; worth confirming.

"256-319 CARD" against "banks are blocks of 128, bank numbers 0-2", and a
real dump holding 0-383. `banks.py` uses 384.

What would settle it beyond doubt: a Configuration Request on a unit with
and without a card fitted.

**Blocked on:** item 1, and a card.

The bench is built (T9) and awaits a human run; its configuration request
prints the RAM sizes and card presence and settles the 256–319 vs 384
question observationally. No code change is pending on this answer.

## 3. `PRESET_GAP` is a guess

**Status:** open, blocked on wanting to measure it.

The manual warns that sending presets to the unit needs roughly 100 ms
between them or the input buffer clogs, and offers a SysEx Packet Delay
setting for the reverse. This program only reads, so the number is used
defensively when walking presets one at a time. It has not been measured
in the read direction.

The bench is built (T9) and awaits a human run; its spacing probe sends two
preset requests `PRESET_GAP` apart and prints the measured gap tolerance.
`PRESET_GAP` stays labelled a guess until that run.

## 4. Hyperpresets and midimaps are read but not browsed

**Status:** closed in T8 (`eab7d11`).

The right pane now cycles across **preset → hyperpreset → midimap** on
`k`. All three kinds are read in their own free name request (one exchange
per kind, silent) and land in the right regions; names from the live read
win over the catalog and persist through the same sidecar path. Display
numbers follow `emu/banks.py` per kind; the card flag and writable flag are
shown. `enter` selects presets only — hyperpresets and midimaps are refused
with a plain sentence in `notify_status(..., refused=True)` styling, because
no Program Change reaches a midimap at all. `tests/test_app.py` covers the
cycle, the three reads landing in the right regions, the refusal sentence,
and cursor silence.

What remains, if anything: none tracked here. Whether a midimap can ever
be selected by SysEx (not a Program Change) is a separate, unstarted
decision and stays out of the browser.

## 5. The browser — DONE 2026-09-20

Two panes, the sibling shape: regions left, that region's contents
right. Favourites with tags and notes, the `F` cycle, search, channel
keys, and a device screen.

What is specific to this instrument: `r` reads **every name of a kind in
one message**, which no sibling can do, and files the flat reply back
across the regions it spans -- a short reply is reported as "no card
fitted", which is what it means. Enter refuses hyperpresets and midimaps
before sending, since no program change reaches a midimap at all. The
slot pane shows the SysEx *index* beside the displayed number, and the
status line says the program number it used is the one that works under
the default Program Map. `d` sets the SysEx device ID, which this
instrument has in addition to a MIDI channel and which the siblings do
not need.

Textual is a real dependency again rather than the extra ER-8 made it.

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

---

# External code review — GLM-5.3-Flash (2026-09-20)

**Status:** findings only, no code changed. A full read of `emu/`,
`emorphed/`, `tests/`, `docs/` and the project metadata; the test suite was
run (30 passed). Everything below was verified at its site first-hand. What
is already known and documented — the bridge never having talked to the
unit (item 1), `PRESET_GAP` being a guess (item 3), the 256-319/384 manual
contradiction (item 2) — is not repeated here as a finding. The README's
sibling-convention framing is taken as given.

*Every finding below was re-verified at its site before being acted on.
All nine held. Two of them were worse than reported: ER-1's rot is in
three projects, not one, and the test ER-3 asked for immediately found a
real bug in six.*

## ER-1 — `catalog.py` described a different instrument — FIXED

**Confirmed, and worse than reported.** The module was ported with `sed`,
which renamed identifiers and left every word of the prose alone: the X5
family, `p2k/data/catalog.json`, "all hundred at once", 640 presets,
Korg's patch list, a 2026-09-12 session that belongs to another project,
and a reference to an `app.py` that does not exist.

**The same rot is in `nanosyned` and `ensqsqed`**, which came off the
same `sed`. All three docstrings are rewritten for their own instrument,
and each now says what a catalog is actually *for* there -- which differs:
here the unit hands over every name in one exchange, so a catalog is for
working away from it; in nanosyned four of five banks can come from
nowhere else.

`tools/` being empty is now TODO item 8.

## ER-2 — checksum handling is asymmetric — DOCUMENTED, still a bench question

**Confirmed.** `parse` strips the trailing byte only for the three
numbered data messages. Whether an unnumbered reply carries a checksum at
all is asserted nowhere, and the review is right that the fixtures bake
in the assumption that it does not.

Not guessed at. `Packet.body` now says in its docstring exactly what is
stripped, what is not, and why -- and item 1 gains the bench step. The
alternative was to strip uniformly on a hunch, which would silently eat a
real data byte from every Version reply if the hunch were wrong.

## ER-3 — the largest modules had no tests — FIXED, and it found a bug

**Confirmed.** `tests/test_protocol.py` imported three modules; `favorites`
(601 lines), `config` and `catalog` had none.

`tests/test_store.py` now covers the behaviours the review named: the
upsert preserving `added`, the `active` soft delete and the v1 migration,
`toggle`'s restore-on-re-add, `_merge` keeping tags across a rating edit,
LIKE escaping, `refresh_names`' change count, TOML quoting, and the
catalog's disagreement reporting.

**One of those tests failed on the first run.** `load_device_id` accepted
TOML `device_id = true` as device 1, because `isinstance(True, int)`. That
guard was written for p2ked weeks ago and never propagated: **six of the
seven projects were missing it.** All six are fixed, rxved with its own
range because its device ID is the panel number 17-32, where 1 is not
merely wrong but impossible.

The two docstrings citing `--favorites` and "the browser" are reworded.

## ER-4 — `banks.py` contradicted itself in its own front matter — FIXED

**Confirmed.** The docstring table said 256-319 while the code eleven
lines below argued for 256-383 and the tests, README and RESOLUTION_NOTES
agreed with the code. The table now says 383.

## ER-5 — the catalog keyed names on `program_change` — FIXED

**Confirmed, and the reasoning is right.** This project makes the
index-versus-program-number distinction a headline and then named the
catalog's key after the assumption. Renamed to `number`, matching
`Slot.number`, with a comment saying why the other name would have
enshrined it.

## ER-6 — `--recv-port` was accepted and never remembered — FIXED

**Confirmed**: the pair existed, was exported, and had no caller. `main`
now saves it when it differs from the output port and offers it back when
`--recv-port` is not given.

## ER-7 — a missing file gave a traceback — FIXED

**Confirmed.** `OSError` is now caught with the rest, with a comment
saying why `read` in particular needs it.

## ER-8 — `textual` was a hard dependency for a program with no TUI — FIXED

**Confirmed**: required unconditionally, imported nowhere. Moved to an
optional `[tui]` extra, to come back as a dependency when item 5 lands.

## ER-9 — minor — ALL FIXED

* `signed` is exported.
* `to_words` raises instead of masking, matching `from_words` and
  `encode_name`. A value past the range was silently becoming a different,
  entirely plausible value on the wire -- the exact failure this module is
  written to avoid.
* `banks.bank_request` delegates the preset case to
  `messages.preset_bank_request`.
* `DemoDevice._tick` raises after `close()`.
* `morphcli read` says how many corrupt dumps it did not list.

## What was checked and found sound

For the record, since this is the part a future reviewer would redo:
the 2176 + 512 + 64 = 2752 figure across README, TODO and
RESOLUTION_NOTES §3 is internally consistent (preset + hyperpreset +
midimap dumps), not a doc drift; `PRESET_DATA_BYTES = 566` is the total
message length including `F0`/`F7` and the fixture test agrees;
`dumps.read_bytes`' corrupt-vs-kept policy (bad checksums kept and
*reported*, not dropped) is right for a format whose one integrity check
would otherwise be wasted; the `active` soft-delete migration,
`_LockedConnection`'s lock-and-fetch-everything contract, the XDG
`data_dir` fallback chain, `_toml_string`'s escaping rationale, and
`autodetect`'s ID-0-first sweep order are all sound designs worth keeping
exactly as they are.

## Cross-check against edisyn's Morpheus implementation (GLM-5.3-Flash, 2026-09-20)

`~/git-repos/edisyn` ships a hardware-proven Morpheus implementation
(`edisyn/synth/emumorpheus/`, Java, since 2020). It is **Apache-2.0** and
emorphed is **GPL-2.0-or-later** — different licences, so nothing was
copied or quoted into emorphed and nothing below is a patch: the protocol
FACTS below were read off that implementation and recorded here for the
bench to verify at item 1. Every one of them is checkable without reading
any of edisyn again.

**Agreements — the protocol core is now independently corroborated:**

* All three data sizes match exactly, and edisyn's arithmetic (`recognize`
  asserts `length == 10 + NUM_PARAMETERS * 2`) shows the ten bytes are
  `F0 18 0C id cmd version NNlo NNhi checksum F7` — the same shape
  emorphed's `Command.SIZES` encode: preset 10 + 278×2 = **566**,
  hyperpreset 10 + 237×2 = **484**, midimap 10 + 360×2 = **730**. All three
  agree.
* Checksum: edisyn computes it over the **data bytes only** (name + words,
  *excluding* the version byte and the object number) and places it before
  the `F7` — the same scope `dumps.read_bytes` assumes. Its comment is
  also corroboration from the other direction: "The manuals do NOT say how
  to calculate the checksum. But it appears to be simply the sum of the
  parameter bytes" — the same gap RESOLUTION_NOTES §3 fills by measurement.
* Word order (low seven first) and the sign rule (`val >= 8192` →
  `val - 16384`, i.e. two's complement to bit 13) are identical to
  `messages.to_words`/`messages.signed`. Names are 12 × 14-bit words in
  dumps. Command IDs for preset/hyperpreset/midimap request-and-data pairs
  (0x00/0x01, 0x44/0x45, 0x46/0x47) and the version byte on the data
  messages all agree.
* edisyn does **not** validate incoming checksums and does not use the
  bank request, the List Requests, or the Version/Configuration Requests —
  so emorphed's read path is *stronger* there, and those parts stay
  manual-only (item 1 still has to confirm them on hardware).

**One real discrepancy found — the card's bank number when SELECTING:**

edisyn's patch-select (its `changePatch`) sends the bank as a 14-bit
controller pair on CC 0 (MSB) + CC 32 (LSB) — the same wire shape as the
manual's `Bn 00 00 20 bb Cn pp`, so emorphed's `select_messages` format is
confirmed — but for the card it bumps the bank: the comment says the card's
actual bank is **bank 3**, not 2. emorphed sends
`bank_of(index) = index // 128` = **2** for every P-CARD preset. If edisyn
is right, selecting a card preset in emorphed lands one bank off.

This does not contradict the 256-383 dump resolution — edisyn's *dump*
addressing is also `bank * 128 + number` with the card at bank 2 — it
reveals a THIRD numbering: the CC/PC bank select value, where the card
sits at 3. Which is exactly this instrument's "numbered three different
ways" habit, and it refines item 2: the manual's "256-319" and "banks
0-2" sentences disagree about count, but the *select* bank may disagree
with both. The planned bench test gains a step: select a card preset and
see whether bank 2 or bank 3 reaches it.

Caveat worth keeping: edisyn's class covers the **UltraProteus** in the
same file, so the bump could in principle be an UltraProteus-ism applied
unconditionally. Its comment does not say which machine it was proven on.
That is the bench's question, not the review's.

**Secondary observations:**

* edisyn reads Instrument/Filter List Data replies as a 14-bit count then
  entries of (14-bit index, 12 **raw** bytes) — names in list replies are
  raw bytes, matching `parse_name_list`'s reading, and it consumes no
  checksum and (commented out) no terminator in those replies. Weak
  corroboration for ER-2's suspicion that unnumbered data replies carry no
  checksum — weak because it reads to end-of-file and ignores trailing
  bytes either way. The Effect List is nested (name, then a 14-bit count,
  then 11-character subnames and 14-bit values) — a richer structure than
  `parse_name_list` handles, which is fine for now but worth a line in the
  protocol notes if the browser ever lists effects.
* edisyn sends a command **0x22** (a preset-write variant, unused in its
  current flow) that is not in `Command.NAMES`. Harmless for a read-only
  program — such a message would land in `Library.other` — but worth
  adding to the table once the manual confirms it, since `morphcli read`
  currently prints it as "command 0x22".
* edisyn sends product ID `0x0C` for the **UltraProteus as well** —
  suggesting the UltraProteus also answers to the Morpheus ID (or that its
  UltraProteus support assumed it). Low priority for emorphed, but it
  means the "answers to 04 as well" story may have a sibling case.
* No pacing anywhere in edisyn's Morpheus code — it writes one preset at
  a time on user action, so it never had to measure the gap. TODO item 3
  remains open and unmeasured from both directions.

## 8. `tools/extract_catalog.py` does not exist

**Status:** closed in T10 (`5af2160`).

The tool now exists. It builds `emu/data/catalog.json` (gitignored) from a
user-supplied name listing: a Cakewalk `.ins` as the primary source, or a
plain-text preset list (one name per line, prose heading per bank) via
`--from-text`. Rows land via `catalog.make_key`; a gap is a gap (UNNAMED
placeholder or omitted, never invented). Guards refuse duplicate display
numbers, control characters and unprintables, and round-trip the parsed
name.

Run line:

    python tools/extract_catalog.py --help

Tests: `tests/test_extract.py`, on invented fixtures only — no network, no
local file presence required.

## ER-F1 — the bool sweep stopped at `device_id`; `load_channel` has the same bug (external review follow-up — GLM-5.3-Flash, 2026-09-20)

**Status:** open, verified live in six projects.

The ER-3 fix added the correct bool guard to `load_device_id` — verified
live: a hand-edited `device_id = true` now comes back as `None` in both
this project and ensqsqed, with the comment naming why
(`isinstance(True, int)` is True).

**`load_channel`, one function away in the same file, was not swept.** It
still reads `isinstance(value, int) and 0 <= value <= 15`, which passes for
`True`: `channel = true` in TOML returns `True`, every downstream range
check passes (`0 <= True <= 15` is true), and the wire effect is real —
`select_messages(slot, True)` emits status `0xC1`, which is **MIDI channel
2**, not channel 1. Verified live against this checkout, and the same
unfixed form is in `ensqsqed/sq/config.py`, `kwsed/kws/config.py:129`,
`p2ked/p2k/config.py:130`, `x5ded/x5/config.py:129` and
`nanosyned/nano/config.py:130`. rxved carries its channel logic in its
bridge with its own panel-number range and needs the same check in its own
terms.

The failure mode is the one the new `load_device_id` comment itself
describes — a hand-edited value taking a plausible wrong form — one
function from where it was just fixed. The sweep that propagated the
device-ID guard to six projects should run for the channel loader too;
`load_last_recv_port`'s `and value` truthiness check is of the same shape
and worth a glance while there.

**Status:** open, noticed by the review under ER-1.

`.gitignore` and `catalog.load`'s warning both point at it and `tools/`
is empty. The same shape as nanosyned's: `--syx` for what a dump can
supply, `--manual` for the regions it cannot.

It matters less here than in the siblings, because this instrument hands
over every preset name in one exchange. It matters at all because two
regions need a card fitted and a card is not always in.

## 9. The card's bank number when *selecting* may be 3, not 2

**Status:** open, a bench question, raised by the edisyn cross-check.

`select_messages` sends `bank_of(index) = index // 128`, which is 2 for
every P-CARD preset. A hardware-proven implementation elsewhere bumps the
card to bank **3** on the Controller 0/32 pair while addressing the same
preset as bank 2 in *dumps* -- which would make this instrument's habit
of numbering things three different ways into a fourth.

If that is right, selecting a card preset from emorphed lands one bank
off. If it is an UltraProteus-ism applied unconditionally, it is right to
ignore. Nothing here can tell without a Morpheus and a card.

**The bench step:** select a card preset with bank 2, then with bank 3,
and see which one arrives.

**Blocked on:** item 1, and a card.

The bench (T9) is built and awaits a human run. It does not drive the
select-based settle itself — selecting moves the unit — so that step stays
a listed manual bench step rather than an automated test. The bench records
the configuration-reported card regions for the human's note.

---

## Adopted in this wave (T1–T11)

vinsynlib 0.4.2 surface adoption. One entry per task; the features each
task shipped.

- **T1 — Stand on 0.4.2** (`dd33a6b`): `vinsynlib>=0.4.2`,
  `entry.MINIMUM = (0, 4, 2)`, `SOURCE = "vinsynlib>=0.4.2"`. Entry gate
  covered by `tests/test_entry.py`.
- **T2 — screens and working rules** (`26d8ce0`): `emorphed/screens.py`
  re-exports `ReportScreen` (frame, scrollable body) and `PromptScreen`;
  `BusyGate`/`QUIET_BRIDGE_ERRORS` from `vinsynlib.ui.work`;
  `_build_line()` via `build.build_of`.
- **T3 — catalog on the library** (`c5af02d`): keys via `catalog.make_key`,
  `UNNAMED = "--"`, printed-vs-live discipline intact;
  `tests/test_catalog.py`.
- **T4/T5 — live names** (`75bbbf9`): sidecar `live-names.json` beside the
  favourites DB; loaded at startup before the first frame; persisted after a
  successful read; `--live-names` override. `tests/test_livenames.py`.
- **T5 — undo and rating filter** (`9738de7`): `UndoLog(gate_hook=...)` made
  first in `__init__`; `z`/`Z` restore previous values; `V` rating filter via
  `vinsynlib.ui.modals.RatingFilterScreen` (remembered as `rating_stars` /
  `rating_at_least`).
- **T6 — CLI and backup envelope** (`9101b7d`): `morphcli fav`, `tags`,
  `ports`, `backup save|list` (read-only; no `restore` — TODO 6 design
  decision). `emu/backup.py`, `tests/test_backup.py`,
  `tests/test_cli_favorites.py`. `render` tables/progress, `spec.flag_help`.
- **T7 — scan** (`423619e`): `emorphed/scan.py` (`ScanOfferScreen` y/n/d,
  mount-safe `ScanScreen` progress + cancel), `_maybe_offer_scan`, `S`
  reads all three kinds, progress on the shared `ScanScreen`, cancel checked
  between kinds. Honest text: no per-bank play on the Morpheus.
- **T8 — kind views** (`eab7d11`): closes item 4 (see above).
- **T9 — hardware suite** (`581c4ed`): `tests/conftest.py`,
  `tests/test_hardware.py`, `make test-hardware`. Collection succeeds
  without a device; no agent runs it.
- **T10 — extract tool** (`5af2160`): closes item 8 (see above).
- **T11 — docs** (this commit): `CLAUDE.md`, `TODO.md`,
  `docs/RESOLUTION_NOTES.md`, `README.md`.

Deliberate divergences recorded in
`docs/PROMPT-emorphed-parity.md` (parity contract): no category filter,
no write path / `--allow-write`, no marked-list or screenshot capture,
favourites stays on `F`.
