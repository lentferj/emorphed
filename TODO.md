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

**The bench first talked to a Morpheus on 2026-10-15**: version,
configuration, a preset read, a bank request and all three name-list
exchanges answered. The three tests that failed did so on a 2.0 s test
timeout, not a protocol problem; the replies arrive in 3.73 s / 2.52 s /
0.15 s and parse exactly. See "Bench run, 2026-10-15" below and the
2026-10-16 deep dive in `docs/RESOLUTION_NOTES.md`.

## Bench run, 2026-10-15 — first contact

A human ran `make test-hardware` on a powered-on Morpheus. Raw output kept
outside the checkout at `~/temp/hardware_run_vsl042.txt`. **5 passed, 3
failed**; nothing was written, nothing was selected, nothing played. The
three failures were a **bench defect**, not a protocol problem: the test
used a 2.0 s timeout where the streamed reply takes seconds (see the
2026-10-16 deep dive below).

**Answered (read-only, structural):**

* **Identity** — `Version Request F0 18 0C 07 0A F7` → reply, device ID
  **7**, body `02 31 30 33` (firmware read as 2.103).
* **Configuration** — 19 bytes returned:
  `00 03 07 72 01 7F 00 00 00 02 46 01 20 00 18 00 08 00`. What is fitted
  is not decodable from this output alone; recorded for the human.
* **One RAM preset read** — 566-byte frame, body 556 bytes, checksum `0x3c`
  recomputed as `0x3c`: **match**; 278 words re-decode. The preset read
  path is confirmed on the wire.
* **Bank request** — the unit *does* answer a whole-bank request: 44
  messages in the 40 s window, the last two clean 566-byte preset frames
  whose checksums match. The other 42 are 674 bytes, are **separate
  messages** (the 2026-10-16 deep dive counted them), and their framing
  is unexplained — see the bank-framing question under item 1. The
  merged-frames-per-rtmidi-message hypothesis this bullet once leaned on
  is **withdrawn**: the deep dive's run 1 shows 44 distinct messages.
* **Timing** — two preset requests `PRESET_GAP` (100 ms) apart were both
  answered; observed spacing **100.1 ms**, total 298.2 ms. First
  measurement in the read direction (item 3).

**The three name-list exchanges — corrected by the 2026-10-16 deep dive:**

* **All three name-list requests answered**, after a longer window than
  the test allowed: the replies arrive at **3.73 s** (`0x12` → `0x13`,
  5000 bytes, 384 names), **2.52 s** (`0x50` → `0x51`, 3336 bytes, 256
  names) and **0.15 s** (`0x52` → `0x53`, 424 bytes, 32 names), and parse
  exactly — every body is `2 + 13 * count` bytes and every name is twelve
  printable characters. The one test timeout (2.0 s) is what failed.

**Consequence:** this was a **bench defect, not a protocol problem.** The
three hardware tests failed on a 2.0 s timeout where the streamed reply
takes seconds; `bridge.names()` waits 40 s, so the app itself was never
affected and the browser, its `r`/`S` keys and the scan offer stand. The
test fix is the companion commit (`2356ba5`); the deep dive is
`docs/RESOLUTION_NOTES.md` §20.

**Cosmetic defect, fixed in the same wave:** the deep-dive captures open
with `"…: remembered, but no Version Request came back on '…' … Probing
every port (--scan does this on purpose)"` even though the port probed was
the remembered one. The remembered-port probe was using device ID 0
instead of the **remembered device ID (7)**, so the unit ignored the
probe and the launch fell back to the sweep — harmless (the sweep found
the unit) but a misleading line. Fixed by probing the remembered port
with the remembered device ID; fixed in `801afbf`.

## 1. The bridge has never talked to the instrument

**Status:** the identity, name and read probes are answered; the bank
framing is the open question.

`emu/bridge.py` is complete and unexercised. In order:

* `morphcli status` -- a Version Request is the smallest, safest probe
* `morphcli names` -- one message, every preset name; if this works the
  browser is essentially done
* `morphcli read` against a bank request, to see whether the reply arrives
  in one message or several

Then `autodetect`, whose sweep over sixteen device IDs times every port.
**The cost note for this item — measured 2026-10-16** (bench host, ~41
ports): the full sweep is **41 ports × 16 device IDs × 0.4 s per probe**.
It asks the requested/remembered device ID first across the ports, then 0,
then the rest, so a device-7 unit is reached on the eighth ID pass in
**~2.2 min**; the worst case is **~4.4 min**. What changed with the
measurement: the sweep now probes the requested/remembered device ID across
the ports before falling back to 0 and the rest, the remembered port is
tried first (one Version Request), one progress line is printed per port,
and an elapsed summary follows the run. The fast path — the remembered port
and device ID — is measured at **0.09 s** (~0.1 s), so `--scan` is only for
when the port or the device ID has changed; `--port "<port>" --device-id 7`
(or `morphcli … status`) opens directly, remembers both, and makes the next
plain run instant. The README carries the one-paragraph version.

**Not blocked any more.** The bench talked to the unit on 2026-10-15:
Version Request, configuration, one preset read and a bank request all
answered.

* `names()` -- **ANSWERED 2026-10-16.** All three kinds arrive and parse
  exactly: preset **384 names** (reply at **3.73 s**, 5000 bytes),
  hyperpreset **256** (2.52 s, 3336 bytes) and midimap **32** (0.15 s,
  424 bytes); each body is `2 + 13 * count` bytes and every name is
  **twelve printable characters**. The 2026-10-15 failures were a **2.0 s
  test timeout**, not the unit -- `bridge.names()` waits 40 s and the app
  was never affected. The test fix is the companion commit (`2356ba5`). So
  "if this works the browser is essentially done" is an expectation again.
* the bank request is **open**, and is now its own question below.

**Bank framing (raised 2026-10-16).** A whole-bank request for bank 0 is
answered: **44 messages, 29440 bytes (~30 kB)**. Forty-two of them are
**674 bytes**, each carrying a full **556-byte preset body beginning at
offset 8**, with the object number stepping by three (**0, 3, 6, ...
123**) and **108 unexplained trailing bytes** before the checksum; the
trailing byte matches **no** recomputed checksum span. The last two are
clean **566-byte** frames at numbers **126** and **127**, checksums
matching. So the unit *does* answer a bank request, but the format is
unexplained and **the app does not use bank requests** -- `morphcli
read`/`backup` walk presets one at a time instead.

**No Universal Identity Reply (2026-10-16).** The family's connect policy in
`vinsynlib` is built around the Universal Identity Request (`F0 7E 7F 06 01
F7`): one broadcast to every port identifies the instrument in one round
trip. **The Morpheus does not answer it.** Broadcast device `0x7F` and device
`7` were both sent, and both were silent; as a control the E-mu Version
Request (`F0 18 0C 07 0A F7`) answered in **~6 ms**. So the family's identity
fast path is unavailable on this instrument, and identification has to go
through the Version Request at each device ID — a **documented divergence,
not an oversight**. It is also why `--scan` here is a per-port, per-ID
Version sweep rather than a single identity probe.

`autodetect` has now been measured — see the cost note at the top of this
item.

The bench is built (T9, `581c4ed`: `tests/test_hardware.py`,
`tests/conftest.py`, `make test-hardware`); a human ran it 2026-10-15
(see the bench section above). Its steps cover this item's probes: Version
round-trip **answered**, `names()` for all three kinds **answered** (the
2026-10-15 failures were the test's 2.0 s timeout, corrected by the
2026-10-16 deep dive in `docs/RESOLUTION_NOTES.md`), and `read_preset`
checksum recomputation **matched** (566-byte frame, 0x3c).

## 2. Two things in the manual disagree about the card

**Status:** resolved in favour of the data; worth confirming.

"256-319 CARD" against "banks are blocks of 128, bank numbers 0-2", and a
real dump holding 0-383. `banks.py` uses 384.

What would settle it beyond doubt: a Configuration Request on a unit with
and without a card fitted.

**Blocked on:** a card. The bench ran 2026-10-15 and printed the 19
configuration bytes (see the bench section above): enough for the record,
not enough to decode what is fitted, so the 320-vs-384 question is
unchanged by this run and the observation belongs to a card-fitted unit.
No code change is pending on this answer.

## 3. `PRESET_GAP` is a guess

**Status:** open — first measurement taken 2026-10-15 (one observation).

The manual warns that sending presets to the unit needs roughly 100 ms
between them or the input buffer clogs, and offers a SysEx Packet Delay
setting for the reverse. This program only reads, so the number is used
defensively when walking presets one at a time. It has not been measured
in the read direction.

The bench ran 2026-10-15: two preset requests `PRESET_GAP` (100 ms) apart
were **both answered**, observed spacing **100.1 ms**, total 298.2 ms.
That is one observation on one unit, not a tolerance curve — the number
stays labelled a guess in the code until a sweep says how far it can be
pushed, but the read direction is no longer unmeasured. That unit reads a
preset in about **0.2 s** (a single 566-byte frame; the 2026-10-16 deep
dive saw the first reply at 0.198 s), so the 100.1 ms spacing sat inside a
fast, complete read — the observation stands.

## 4. Hyperpresets and midimaps are read but not browsed

**Status:** closed in T8 (`eab7d11`).

The right pane now cycles across **preset → hyperpreset → midimap** on
`k`. All three kinds are read in their own free name request (one exchange
per kind, silent) and land in the right regions; names from the live read
win over the catalog and persist through the same sidecar path. Display
numbers follow `emu/banks.py` per kind; the card flag and writable flag are
shown. `enter` selects presets **and hyperpresets** — a Program Change does
reach a hyperpreset, with Bank Select bank 2 (RAM) or bank 4 (card), per the
2026-10-16 measurement in item 9. A midimap is not refused outright: it has
no Program Change, so it is made current over System Exclusive behind a
confirmation (`a6e4c74`), which switches the unit to Multi mode and changes
what plays. `tests/test_app.py` covers the cycle, the three reads landing in
the right regions, and cursor silence.

What remains, if anything: none tracked here.

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

## 6. Midimap parameters can be edited; presets still cannot

**Status:** open — a gated midimap-parameter write path exists; preset
writes do not, and the fence is still the point.

It is no longer nothing. A midimap's own parameters (2048-2407, the
manual's "Midimap Vers. 1 Parms") can now be edited through a **gated**
path: `m` opens the editor, `w` arms the gate (locked by default;
`--allow-write` arms only the start state), the first write backs the
whole midimap up (`emu/backup.py`, kind/block "midimap"); a failed backup
is announced and the parameter write still proceeds, and only the STORE
refuses without a successful backup this session. Every write is read back
and **only an agreed
read-back is logged**, and `z`/`Z` undo through the UndoLog. The store --
sending a whole `0x47` dump to a location -- is the one destructive step
and is **arm-then-fire**: it names the location, states that it erases
what is there, needs a confirmation, and is refused outright without a
successful backup this session (manual p.36).

**Presets still cannot be written.** Preset Data sent *to* the unit would
replace a preset, and nothing in emorphed sends it; presets are read,
selected and backed up only. `morphcli` has no write command and there is
still no `restore`.

The distinction the fence rests on: a parameter write edits the unit's
**scratch** midimap (live, not permanent); only a **store** makes an edit
part of a stored location, and a store erases what was there.

Note that only RAM regions are writable at all, and that the unit has one
edit buffer per kind which is erased by changing which object is current
-- so a write path must not assume the buffer it filled is still there.

**What remains open:**

* **The store is unverified on hardware.** Nothing has been written to a
  real unit; the whole path is synthetic until the bench runs.
* **The human-attended write bench** (`tools/bench_midimap_write.py`) has
  not been run: back up a midimap, change one benign parameter (a channel
  volume), read it back and verify, restore the backup. It refuses without
  `--yes` and a TTY, and no agent runs it.

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

## ER-2 — checksum handling is asymmetric — RESOLVED 2026-10-16

**Confirmed.** `parse` strips the trailing byte only for the three
numbered data messages. Whether an unnumbered reply carries a checksum at
all is asserted nowhere, and the review is right that the fixtures bake
in the assumption that it does not.

Not guessed at. `Packet.body` now says in its docstring exactly what is
stripped, what is not, and why -- and item 1 gains the bench step. The
alternative was to strip uniformly on a hunch, which would silently eat a
real data byte from every Version reply if the hunch were wrong.

**Resolved 2026-10-16 by the deep dive: unnumbered replies carry no
checksum.** A list reply's last body byte is the last name's `0x00`
terminator (preset, hyperpreset and midimap all parse with the last body
byte `0`), and a Version reply's last data byte is `'3'` (`0x33`) -- the
last character of the firmware string, not a checksum. `messages.parse`
strips nothing for unnumbered messages, which the hardware run confirms
is correct.

The `MISMATCH` lines in the 2026-10-15 log were the **test** comparing a
whole-blob tail against the first frame's checksum -- not the parser
disagreeing with the unit. Nothing is stripped differently.

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

**Settled 2026-10-16: it is right for the Morpheus too — the card is bank
3 on the wire (TODO item 9, measured).**

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

## 9. The card's bank number when *selecting* is 3, not 2

**Status:** RESOLVED 2026-10-16, by measurement on the unit.

`select_messages` used to send `bank_of(index) = index // 128`, which is 2
for every P-CARD preset. A hardware-proven implementation elsewhere bumped
the card to bank **3** on the Controller 0/32 pair while addressing the same
preset as bank 2 in *dumps*, which made this instrument's habit of numbering
things three different ways into a fourth. The bench settled it: the card
is **bank 3** for Bank Select.

**The measured mapping** (`tools/bench_bank_numbers.py --yes`, 2026-10-16;
the operator heard each object and named what it was):

| ll (Bank Select bank) | reaches |
| --- | --- |
| 0 | presets, RAM |
| 1 | presets, ROM |
| 2 | hyperpresets, RAM |
| 3 | presets, card |
| 4 | hyperpresets, card |

**Two numberings, and that is how the bug arose.** The manual's "0x0400 +
the bank number (0-2)" (p.228) is the **SysEx REQUEST** numbering --
presets, RAM/ROM/CARD. The Bank Select numbering the wire actually uses is
a different one: the p.159 box, "ll = Bank number (00-04)", the five rows
above. Reading "bank 2" off the request side and sending it as a Bank
Select byte is exactly the bug: `P-CARD` sent `ll=2`, which reached the
**hyperpresets**, not the card presets. It is fixed in the companion commit
`2762c6e` (the `BANK_SELECT` table in `emu/banks.py`, with `bank_of` renamed
to the request-side `request_bank`).

**Re-running it:** `tools/bench_bank_numbers.py --yes`, human-attended --
it **plays the unit** and cannot be undone remotely, so it refuses to run
without a TTY. The first run on 2026-10-16 measured nothing: the tool
mis-converted the stored channel (the unit keeps it zero-based, 6 for
display 7, and the tool subtracted one) -- a reminder that a stored channel
is not a display channel. That was fixed before the useful run.

**Blocked on:** nothing; the earlier 2026-10-15 bench had not driven the
select step (selecting moves the unit) and established no card number, so
it is superseded by this measurement.

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
  without a device; no agent ran it. A human ran it 2026-10-15 —
  5 passed, 3 failed, all three on a 2.0 s test timeout, not a protocol
  problem (the replies arrive in 3.73/2.52/0.15 s and parse; corrected by
  the 2026-10-16 deep dive); see the bench section above.
- **Bench follow-up (this commit)**: `TODO.md` and
  `docs/RESOLUTION_NOTES.md` record the 2026-10-15 run; no code changed.
- **T10 — extract tool** (`5af2160`): closes item 8 (see above).
- **T11 — docs** (this commit): `CLAUDE.md`, `TODO.md`,
  `docs/RESOLUTION_NOTES.md`, `README.md`.

Deliberate divergences recorded in
`docs/PROMPT-emorphed-parity.md` (parity contract): no category filter,
no preset write path (midimap *parameters* are gated behind
`--allow-write`; TODO item 6), no marked-list or screenshot capture,
favourites stays on `F`.
