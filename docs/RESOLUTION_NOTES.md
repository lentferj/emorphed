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

## 10. Adopted vinsynlib 0.4.2's frame, build line and work gate (T1, T2, T5)

**Task T1** (`dd33a6b`) pins `vinsynlib>=0.4.2` and `entry.MINIMUM = (0, 4,
2)`. The floor is justified by `build.build_of`, `ui.report.ReportScreen`
and undo's `plan`/`settle`; the gate stays stdlib-only (rule 1 of the
prompt). Verified by `tests/test_entry.py` and the sanity import
`vinsynlib.ui.report.ReportScreen`.

**Task T2** (`26d8ce0`) retires emorphed's local `ReportScreen`/`PromptScreen`
and takes `vinsynlib.ui.report.ReportScreen` (a subclass adding `enter` as a
closer, copied from rxved's three-line subclass) and `vinsynlib.ui.prompt.
PromptScreen`. The body is a `VerticalScroll`, so device info, search
results and help scroll. `_build_line()` uses `vinsynlib.build.build_of` for
`(("emorphed", __file__), ("vinsynlib", None))` and is prepended by the
help report and the device report. `make_parser` gained
`distribution="emorphed"` so `--version` is one implementation. `BusyGate`
replaced the `_busy` flag / `RLock` pair, and `QUIET_BRIDGE_ERRORS` was
folded into `_BRIDGE_ERRORS`. Verified by `tests/test_report.py` (subclass
of the library frame, escape/q/enter close, scroll body, `_build_line`
agreeing with `build_of("vinsynlib")`) and `tests/test_app.py` /
`tests/test_conformance.py`.

**Task T5** (`9738de7`) makes `UndoLog(gate_hook=self._undo_gate)` the
first object in `__init__`, because a watcher can fire before the constructor
finishes (p2ked, `p2k/app.py:353`). Favourites, rating and tags/notes flip on
the main thread (SQLite is local); undo sends the *previous* value back.
`V` (`rating_filter`) pushes `vinsynlib.ui.modals.RatingFilterScreen`; escape
returns unchanged, `x`+enter clears; state parked via
`emu/config.py`'s `load_ui_int`/`load_ui_bool`/`save_ui_state` under
`rating_stars` and `rating_at_least`. Verified by `tests/test_app.py` and
`tests/test_favorites.py`. Live names are loaded from the sidecar before the
first frame (`rxved/app.py:2970-2974` order) and persisted after a
successful read via
`favorites.refresh_names` from the main thread.

Sources: rxved (`rxved/screens.py:20-43, 240-303`, `app.py:2756`, `:66`,
`:2999-3021`, `:2970-2974`), p2ked (`p2k/app.py:88-91`, `:353`,
`:1449-1748`), the library's `ui/modals.py`, `undo.py`, `build.py`,
`ui/work.py`, `ui/report.py`.

## 11. Catalog on the library's grammar (T3)

**Task T3** (`c5af02d`): `emu/catalog.py` keeps its public API but keys
become `vinsynlib.catalog.make_key` (`"P-RAM:013"`), `UNNAMED = "--"` is the
printed placeholder, `split_key` reads keys back. Printed (generated) vs
live (read off the unit) layers kept apart, live wins, `differs` flags a
disagreement with `*`. `load(path=None)` reads `emu/data/catalog.json` with
the family's leniency — missing file returns `Catalog.empty()`; bad rows are
counted to stderr, never fatal. The Morpheus rows carry no `kind`; keys are
`make_key(bank_id, number)`. The catalog test class was split out of
`tests/test_store.py` into `tests/test_catalog.py`. Verified by
`tests/test_catalog.py` and `tests/test_store.py`, with
`tests/test_config_paths.py` unchanged (`devchecks.foreign_imports` clean).

Sources: p2ked (`p2k/catalog.py`), rxved (`xv/catalog.py:61`). Manual §§ as
previously recorded (the key grammar and UNNAMED come from the library, not
from the manual).

## 12. Live names survive the session (T4, T5)

**Task T4** (`75bbbf9`) binds `emu/livenames.py` to `vinsynlib.livenames`
(`FILE_NAME`, `key`, `load`, `save`, `apply_to`), supplying the default path
beside the favourites DB via `favorites.data_dir`. `default_path()`,
`load`, `save`, `apply_to` are thin bindings that only supply the path and
emorphed's own docstring — the sidecar is separate from the catalog file so
that a `git clean` in a checkout cannot take the user's read-off names.
`--live-names` overrides the default path (rxved naming). Tests:
`tests/test_livenames.py` (15 tests, `tmp_path` stores): missing loads empty,
corrupt warns and loads the readable subset, `apply_to` sets live names and
skips unparseable keys, save writes atomically and never raises on `OSError`,
key round-trip. No app wiring in T4; T5 does that (see §10).

Sources: rxved (`rxved/livenames.py`, 119 lines), the library's
`livenames.py`.

## 13. Scan offer and screen (T7)

**Task T7** (`423619e`): `emorphed/scan.py` defines `ScanOffer = str`
(`"scan" | "later" | "never"`), `ScanOfferScreen` (`y`/`n`/`d`, escape ==
later, "never" persisted via `config.save_ui_state("scan_offer_dismissed",
True)`) and `ScanScreen` (progress line + Cancel; cancel is a
`threading.Event`; mount-safe before compose). Both screens are MIDI-free;
the app drives the wire. The offer fires when the catalog is empty and not
dismissed and not demo (`_maybe_offer_scan`, p2ked shape). `S` reads all
three kinds with the free name requests (one exchange per kind, silent),
applies to the catalog, persists live names and announces the count; progress
on the shared `ScanScreen`; the cancel event checked between kinds. The
Morpheus has no per-bank scan that plays — documented in the screen's honest
text (rxved's honesty standard, `rxved/scan.py:63`): no sound accompanies a
name read here either. Verified by `tests/test_scan.py`
(offer answers, persistence of "never", mount-safe progress, cancel honoured
between requests, no MIDI from the screens).

Sources: p2ked (`p2k/scan.py`, 184 lines), rxved (`rxved/scan.py:74-212`).

## 14. Kind views: hyperpresets and midimaps become browsable (T8)

**Task T8** closes TODO item 4 (`eab7d11`): a key (`k`) cycles the right
pane across preset → hyperpreset → midimap. `names(kind)` already reads all
three in one exchange each; the browser now has the views and the catalog
keys (`catalog.make_key(bank_id, number, kind=…)`). Hyperpreset and midimap
regions per `emu/banks.py` (H-RAM/H-CARD, M-RAM/M-CARD 16+16); display
numbers follow the index-vs-number rule per kind; card and writable flags
shown; names from the live read win over the catalog and persist through the
sidecar. `enter` selects presets only — hyperpresets and midimaps refused
with `notify_status(..., refused=True)`. The refusal follows the family's
styling. Verified by `tests/test_app.py` (cycle, three name reads landing
in the right regions, refusal sentence on `enter`, cursor silence) and
`tests/test_conformance.py` (`keys.legend(...)` extras include the new key).

Sources: emorphed's existing preset table machinery;
p2ked's "kinds-of-containers are fixed tables" rule (`p2k/roms.py`).

## 15. Hyperpresets and midimaps enter/quota (no write path) — the backup envelope (T6)

**Task T6** (`9101b7d`), the family's CLI and the backup envelope.
`emu/backup.py`: `from vinsynlib import backup as _backup` + `FORMAT`;
`Backup(_backup.Backup)` record; `APP_NAME`, `KIND = "preset"`,
`BLOCK = "preset"`; `default_dir()` = `<data_dir>/backups`;
`save_preset(words, …)` takes the preset's own bytes from `messages` (never a
re-description); `list_backups(dir)`; `load(id)` refuses wrong kind/missing
block. Pure stdlib + our messages module. **No restore** is offered: the
Morpheus write path does not exist; `load` exists and `restore` is
explicitly not offered, docstring naming the TODO-6 design decision
(arm-then-fire, parked). `morphcli backup save <region>` reads a whole RAM
region (128 requests with `PRESET_GAP`, behind `--yes` per the family sweep
convention) with `render.progress`; `backup list` (offline, newest first,
corrupt listed with `error`). `morphcli fav` carries `--add/--remove/--rate/
--tags/--note/--tag/--search/--rating-at-least/--rating-exactly/--order`
(rxved's surface, `rating_cell` glyphs in list output); `morphcli tags`
(counts); `morphcli ports` (via `vinsynlib.midi.list_ports`/`render_ports`,
imported inside the command body so non-MIDI commands never pay for rtmidi).
Tables/progress from `vinsynlib.render` (`table`, `progress`); `spec.flag_help`
for emorphed-specific flag help. Verified by `tests/test_backup.py`
(round-trip, never-overwrite names, refuse-wrong-kind) and
`tests/test_cli_favorites.py` (12 tests, demo-device-driven so every command
runs without hardware).

Sources: p2ked (`p2k/backup.py`, 250 lines), rxved (`rxved/cli.py:39-41`,
`:1186-1221`).

## 16. Hardware suite (T9) — the bench is built, and was run 2026-10-15

**Task T9** (`581c4ed`): `tests/conftest.py` adds `pytest_addoption("--hardware")`
and the env twin `EMORPHED_HARDWARE=1`, plus a session-scoped `bridge`
fixture — `MorpheusBridge.connect()` (remembered ports first); on failure
retry once with `connect(scan=True)`; failing that, `pytest.skip` with the
named-causes list (powered off, port renumbered, busy session, Rx Exclusive
off / Master Exclusive off). Close in `finally`. `tests/test_hardware.py`
is read-only and asserts only manual-guaranteed facts, printing observations:
`version()` frame shape and device id in reply; `configuration()` structural
sanity plus a printed observation of RAM sizes for TODO item 2 and card
presence; one `names(kind)` exchange per kind (12 ASCII chars in 32–127,
count matches the reply's word — structural, no name values asserted); one
`read_preset` from a RAM slot (566-byte frame, checksum recomputed from the
data bytes agrees — ER-2's bench step — words re-decode); one
`preset_bank_request` exchange (full-bank read on the 40 s timeout class,
checksum status of every frame printed, reply/absence resolving TODO item 1's
bank-request question); a timing probe of two preset requests spaced
`PRESET_GAP` apart (prints the measured gap tolerance for TODO item 3); the
card question printed, not selected — selecting would move the machine and is
left as a manual bench step (TODO item 9). `Makefile` gains `test-hardware`:
`pytest tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s`.
No agent runs it. Verified by collection only:
`.venv/bin/pytest tests/test_hardware.py --hardware --collect-only -q`
(collection succeeds; no device traffic) plus `make lint typecheck` and a
green `pytest tests/ -q`.

Sources: rxved/p2ked `tests/conftest.py`, p2ked's probe style at
`tests/test_hardware.py:194`. Manual: identity, configuration, name-list and
preset data message layouts (Operation Manual, MIDI chapter).

## 17. Catalog extraction tool (T10)

**Task T10** (`5af2160`): `tools/extract_catalog.py` builds
`emu/data/catalog.json` (gitignored) from a user-supplied name listing — a
Cakewalk `.ins` as the primary source, or a plain-text preset list via
`--from-text`. Region targeting via `--region P-ROM` etc.; rows land via
`catalog.make_key`; the tool never invents a name. Guards: duplicate display
numbers refused, control characters and unprintables refused, names survive a
re-read (p2ked's guards, `p2k/tools/extract_catalog.py:51-120`). Tests on
invented fixtures only (`tests/fixtures/invented.ins`); no network, no local
file presence required. Verified by `tests/test_extract.py` and
`python tools/extract_catalog.py --help`.

Sources: p2ked (`p2k/tools/extract_catalog.py`, 414 lines), rxved
(`rxved/tools/extract_catalog.py` guard philosophy). Manual: not applicable
— the names are the user's own files' (rule 4).

## 18. Documentation (T11)

**Task T11** (this commit) adds `CLAUDE.md` (family conventions in
emorphed's facts: index vs display number; device IDs 0–15 with the
panel-number distinction; workers/MIDI rule; no hardware and "act like it";
the fenced write park, TODO 6; never commit E-mu names; the two-file ledger;
no pushes without approval) and rewrites `README.md`, `TODO.md` and this
file. `README.md` now covers the new surface: favourites with undo
(`z`/`Z`), rating filter (`V`), live names kept between sessions
(`--live-names`), backup envelope (`morphcli backup save|list`, read-only),
scan (`S`, `ScanOfferScreen`), new CLI commands (`fav`, `tags`, `ports`,
`backup`), and `make test-hardware` for the bench. Honest limits stay
truthful: no write path and no `restore`. CLI surface spell-checked against
`morphcli --help` and `emorphed --help` (console scripts per `pyproject.toml`:
`emorphed`, `morphcli`).

## 19. The bench run, and what it found (2026-10-15)

**Source: this run, not a document.** A human ran `make test-hardware` on a
powered-on Morpheus (`tests/test_hardware.py` via `tests/conftest.py`'s
`--hardware` gate). The raw output is kept outside the checkout at
`~/temp/hardware_run_vsl042.txt`. Result: **5 passed, 3 failed**. The suite
is read-only by construction: no Bank Select, no Program Change, no write
of any kind; what it sent was Version, Configuration, Preset, Hyperpreset,
Midimap, Preset-Bank and Preset List requests only.

**Answered:**

* Version: request `F0 18 0C 07 0A F7` → reply with device ID 7 and body
  `02 31 30 33` (firmware read as 2.103). The bridge's request/reply
  matching works against a real unit.
* A RAM preset read returned the expected **566-byte frame** (body 556),
  and the recomputed checksum `0x3c` equals the byte on the wire — the
  first confirmation of §3's measurement against hardware rather than
  against dumps.
* A preset **bank request is answered** (44 messages within the 40 s
  window); the last two are clean 566-byte preset frames whose checksums
  match. So "does a whole-bank request answer at all" is now yes.
* `PRESET_GAP` timing: two preset requests 100 ms apart were both answered;
  observed spacing **100.1 ms**, total 298.2 ms. One observation, one unit
  (TODO item 3) — the constant stays labelled a guess in the code, but the
  read direction now has a data point.
* Configuration returned 19 bytes
  (`00 03 07 72 01 7F 00 00 00 02 46 01 20 00 18 00 08 00`); recorded as
  printed, not decoded. It does not by itself settle TODO item 2 (320 vs
  384) — that needs a card-fitted unit and a decoded response.

**"Not answered" — corrected 2026-10-16:**

* **All three name-list requests answered.** The 2026-10-15 result was a
  **bench defect, not the protocol**: the three hardware tests asked for a
  streamed list reply on a **2.0 s** timeout. A raw re-run with the
  timeouts the protocol needs (the deep dive, §20) shows every one replies
  and parses — `0x12`→`0x13` at 3.73 s (5000 B, 384 names), `0x50`→`0x51`
  at 2.52 s (3336 B, 256 names), `0x52`→`0x53` at 0.15 s (424 B, 32
  names). §7's "one message gets every name" stands.
* The bank request's 42 non-final messages were **674 bytes with the
  object number stepping 0, 3, 6, … and a recomputed checksum that does
  not match** the last byte. The deep dive (§20) shows they are **separate
  messages**, not concatenated frames, each carrying one preset's 556-byte
  body at offset 8 with 108 unexplained trailing bytes. The bank framing
  stays the open question, recorded in TODO item 1.

**What this changes in the code: the test's timeout only.** The 2.0 s
timeout was the defect and is corrected in the companion commit
(`2356ba5`); no parser or framing change follows. The hardware file is
still opted in, so `make check` was never affected.

## 20. The deep dive: list replies work, the bank framing is the open question (2026-10-16)

**Source: this run, not a document.** A read-only probe of the same unit
(device ID 7) with the timeouts the protocol actually needs, captured
without a command filter — three raw logs kept outside the checkout at
`~/temp/diag_morpheus_run1.txt` (arrival times and sizes),
`~/temp/diag_morpheus_run2.txt` (the list payloads parse; the bank frame
structure) and `~/temp/diag_morpheus_run3.txt` (which presets the bank
frames contain). Nothing was written, selected or played.

**The 2026-10-15 "name-list requests did not answer" was a bench defect,
not a protocol finding.** Given a 40 s window the replies arrive and parse
exactly:

| request | reply | arrives | size | names |
| --- | --- | --- | --- | --- |
| `0x12` preset list | `0x13` | **3.73 s** | 5000 B | **384** |
| `0x50` hyperpreset list | `0x51` | **2.52 s** | 3336 B | **256** |
| `0x52` midimap list | `0x53` | **0.15 s** | 424 B | **32** |

Each body is `2 + 13 * count` bytes (run 2: 4994 = 2 + 13×384, 3330 =
2 + 13×256, 418 = 2 + 13×32, all `match=True`), and every name is exactly
**twelve printable characters** (`name lengths [12]`). The three
`test-hardware` tests failed on a **2.0 s test timeout**; `bridge.names()`
waits **40 s** (`BANK_TIMEOUT`, also the run's "bank timeout: 40.0"), so
the app was never affected. This settles §7 and TODO item 1's `names()`
probe: the one-message-gets-every-name mechanism works on hardware.

**ER-2 is settled in the other direction: unnumbered replies carry no
checksum.** Run 2 reads the last byte of every list body as `0` — the last
name's `0x00` terminator, not a checksum — and run 1 shows the Version
reply's trailing byte as `0x33` (`'3'`, the last character of the
firmware string). `messages.parse` strips nothing for unnumbered messages,
which the hardware run confirms is correct. The `MISMATCH` lines in the
2026-10-15 log were the *test* comparing a whole-blob tail against the
first frame's checksum, not the parser disagreeing with the unit.

**The bank request is answered but its framing is unexplained.** Bank 0
returns **44 messages, 29440 bytes (~30 kB)**. Forty-two are **674
bytes**, each a full **556-byte preset body beginning at offset 8** (run
2: `preset 0 body[:512] found at offset 8`; run 3 confirms the first
frames carry the presets 0/3/6/9/12/15 read separately) with the object
number stepping by three (**0, 3, 6, … 123**) and **108 unexplained
bytes** between the body and the checksum (674 = 8 header + 556 body +
108 + 2); the trailing byte matches **no** recomputed checksum span: run
2 recomputes four spans over a 674-byte frame (664 B, 667 B and 556 B
twice) and **none** equals the byte on the wire (`0x71`). The last two
messages are clean **566-byte** frames at numbers **126** and **127**
whose checksums match. So the format is neither the plain preset frame nor
a fixed-size bank cell; it is **open**, and the app does not use bank
requests.

**What this changes in the code: nothing but the test.** No parser or
framing change follows from any of it. The 2.0 s timeout is the defect and
is corrected in the companion commit (`2356ba5`). The remembered-device-ID
probe defect (`emu/bridge.py`) is fixed in `801afbf`: the
remembered port is now probed with the remembered device ID, so the
misleading "Probing every port" line no longer appears when the
remembered port is the right one.

## 21. The Bank Select mapping is measured — the card is bank 3 (2026-10-16)

**Source: this run, not a document.** A human ran
`tools/bench_bank_numbers.py --yes` on a powered-on Morpheus. The tool
sends Bank Select + Program Change and asks the operator what was heard; it
**plays the unit**, is human-attended only, and refuses to run without a
TTY. The raw record is kept outside the checkout at
`~/temp/bench_bank_run.txt`. Five probes, each Bank Select bank `ll` with
Program Change 0 on the unit's channel (display 7 = wire `0xB6`):

| ll | PC | the tool expected | the operator heard | reaches |
| --- | --- | --- | --- | --- |
| 0 | 0 | RAM preset 0 | "nothing, but the preset is correct" | presets, RAM (0-127) |
| 1 | 0 | ROM preset 128 | "nothing, but preset is correct" | presets, ROM (128-255) |
| 2 | 0 | hyperpreset 0 | `000-2` | hyperpresets, RAM (0-127) |
| 3 | 0 | card preset 256 | "preset correct, but `000-3`" | presets, card (256-383) |
| 4 | 0 | hyperpreset 128 | `000-4` | hyperpresets, card (128-255) |

The unit's display is `NNN-B` = the object within the bank, then the bank
number. The measured table is therefore fixed: **P-RAM 0, P-ROM 1, H-RAM 2,
P-CARD 3, H-CARD 4.** Nothing here is arithmetic.

**Two numberings, and the manual keeps them on different pages.** The Preset
Request text (p.228) says "Values 0x0400 + the bank number (0-2)" for
presets -- RAM/ROM/CARD. That is the **SysEx REQUEST** numbering and belongs
to the request side only. The **Bank Select** numbering the wire actually
uses is the p.159 box, "ll = Bank number (00-04)", the five rows above.
Reading "bank 2" as a Bank Select byte is the bug the measurement caught: in
the browser a `P-CARD` slot sent `ll=2` and reached the **hyperpresets**
instead of the card presets. The companion commit (`2762c6e`) replaces the
old `index // 128` arithmetic in `select_messages` with the fixed
`BANK_SELECT` table (`emu/banks.py`) and renames the old `bank_of` to the
request-side `request_bank`.

**The edisyn cross-check is now confirmed, not merely suspected.** edisyn's
Morpheus implementation (`EmuMorpheus.java:1262`, "because the card's actual
bank is bank 3") bumps the card to 3 on the CC0/CC32 pair. The review
recorded it as an open discrepancy (TODO item 9) because that class also
covers the UltraProteus and the comment did not say which machine it was
proven on. **This run confirms it for the Morpheus: the card is bank 3.**
Its `CARD 384-511` dump comment is a separate, **dump-side** axis
(`bank * 128 + number` with the card at bank 2); that is not the Bank Select
axis and was not what the tool tested. The instrument's numberings stay
distinct.

**Why preset and hyperpreset share the program space.** Manual p.31,
"Preset/Hyper to MIDI Channel Assign": a Midimap assigns a preset **or** a
hyperpreset (program) per MIDI channel, which is why a Program Change
reaches a hyperpreset at all and why the two kinds are interleaved across
the five Bank Select banks. A midimap is not a program: p.159 is explicit
that System Exclusive is the only way to make one current -- which is what
`select_messages` refuses, and what the browser's midimap path sends over
SysEx behind a confirmation (`a6e4c74`).

**One tool bug before the measurement.** The first 2026-10-16 run of the
same tool measured nothing: it read the **stored** MIDI channel (the unit
keeps it zero-based, 6 for display 7) and subtracted one, so it addressed
the wrong channel and heard silence. The human-answered record above is from
the corrected tool. Stored channels are not display channels -- a useful
warning, since the stored value is zero-based and the display is not.
