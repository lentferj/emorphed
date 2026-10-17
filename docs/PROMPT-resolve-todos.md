<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — resolve the open TODO items

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).
This file turns every OPEN / UNRESOLVED line in `TODO.md` and
`docs/RESOLUTION_NOTES.md` into **atomic tasks**. Work **one task per agent**,
in the order the coordinator hands them to you. Do not wander into another
task's files.

The family conventions are in `CLAUDE.md`; read it first. The sibling
projects `../rxved`, `../p2ked`, `../kwsed`, `../x5ded`, `../nanosyned`,
`../ensqsqed` and `../vinsynlib` are **read-only references** — copy their
shapes, never edit them.

---

## Iron rules (violating any of these fails the task)

1. **No hardware. Act like it.** `MorpheusBridge` is instantiated against
   `emorphed/demo.py` and fakes only. Nothing you write may open a MIDI port
   or run `make test-hardware`. The hardware tests you edit must **collect**
   (`--collect-only`) but you never execute them. If a fact needs the real
   unit, it is **bench-gated**: you build the harness and print the
   observation; the human runs it. (CLAUDE.md, "There is no hardware.")
2. **Never invent a byte, a timeout, a size, a page number or a name.** Cite
   the manual section, the sibling, or an existing captured observation.
   Unknown facts become printed observations or TODO lines — never
   assertions.
3. **`make check` must be green before you end**, for the scope you touched.
   Run the targeted tests with coverage off to avoid races with other
   agents: `.venv/bin/python -m pytest <file> -q -o addopts=""` then
   `.venv/bin/ruff check`, `.venv/bin/ruff format --check`,
   `.venv/bin/mypy --strict emorphed emu tests`.
4. **The venv only.** Everything runs inside `.venv/` (`bin/python`,
   `bin/pytest`, `bin/ruff`, `bin/mypy`). vinsynlib 0.4.2 is installed; do
   not touch it.
5. **No E-mu / MidiQuest / third-party names in the repo.** Fixtures and
   docs use invented word pools (`emorphed/demo.py`). A format note
   *describes* structure; it does not paste a bank's identity strings or a
   slot's name. `emu/data/catalog.json` is gitignored.
6. **Line style:** ruff line length 79, GPL-2.0-or-later SPDX header on every
   new `.py`, mypy **strict**. Match the surrounding diction (docstrings cite
   the manual and the siblings; status lines are plain sentences).
7. **Do not commit and never push.** Leave your changes in the working tree;
   the coordinator commits. Report files touched, tests added, verify-command
   tail.

---

## The open items, and what can actually be resolved

| item | TODO.md | status | offline? |
|---|---|---|---|
| 1 bank framing (674-byte frames) | `:78`, `:120-129` | open, bench-gated for *resolution* | harness only |
| 2 card 320-vs-384 | `:153-167` | open, needs a card | harness only |
| 3 `PRESET_GAP` is a guess | `:169-186` | open, one observation | harness only |
| 6 midimap **store** unverified | `:226-316` | open, destructive | split (tests offline, proof bench) |
| 7 MidiQuest `.sqs` unread | `:318-326` | open | **yes** (document + scope) |
| ER-F1 `load_channel` bool | `:569-595` | open (stale — guard already in vinsynlib) | **yes** (ledger) |
| stale `RESOLUTION_NOTES` §22 line | `RESOLUTION_NOTES.md:623-625` | contradicting §22:515-536 | **yes** (ledger) |
| edisyn observations | `TODO.md:537-548` | "worth doing" | **yes** (notes) |
| untracked `docs/PROMPT-emorphed-parity.md` | referenced `TODO.md:685` | untracked, stale in places | **yes** (commit + note) |

**Nothing in this programme touches the hardware.** Items 1, 2, 3 and the
store half of 6 are made **bench-ready** here and resolved by a later human
run; the tasks call that out honestly.

---

# The tasks

## U1 · The store read-back is checked, not discarded

**Files:** `emorphed/app.py`, `tests/test_app.py`.
**Current fact:** `_store_midimap_worker` (`app.py:856-872`) sends the map and
calls `self.device.read_midimap(loc)` but throws the result away (`_ =`), then
always reports `"stored to M{loc:02d}"` — success is claimed without checking.

Steps:
1. In `_store_midimap_worker`, keep the read-back and compare it with the
   words sent: `stored = list(self.device.read_midimap(loc))`; count the
   agreeing words. On full agreement, say so in the status line
   (`"stored to M{loc:02d} (read back {n}/{n} words agree)"`). On
   disagreement, **do not claim success**: report the disagreement and
   `refused=True`, with the count. Guard the read-back so a bridge error
   becomes the failure path (never an unhandled exception in the worker).
2. Add the synthetic store tests that are missing today (every existing
   store test only asserts that a store did **not** happen):
   - `_store_confirmed(loc, words, True)` runs the worker and the
     `DemoDevice` records exactly one `send_midimap`; the status line names
     the location.
   - a read-back that disagrees is reported as a refusal and does **not**
     claim success (monkeypatch the demo `read_midimap` to return a changed
     word).
   - `_store_confirmed(loc, words, False)` and `None` send nothing.
   - the location prompt refuses a non-number and an out-of-range value
     (`0-31`) before any screen is pushed.
3. Model the new tests on the existing `TestStartingTheMidimapEditor` /
   store-fence tests in `tests/test_app.py` (`:709-768`) and the
   `DemoDevice` store surface in `tests/test_midimapedit.py:108-113`.

**Verify:** `.venv/bin/python -m pytest tests/test_app.py -q -o addopts=""`;
`ruff check`; `ruff format --check`; `mypy --strict emorphed emu tests`.

---

## U2 · The midimap half of the backup envelope is tested

**Files:** `tests/test_backup.py`.
**Current fact:** `emu/backup.py` has `save_midimap`, `load_midimap`,
`KIND_MIDIMAP`, `BLOCK_MIDIMAP`, `MidimapBytes` (`:88-89`, `:127-145`,
`:249-290`, `:380-385`) and **no test references any of them**.

Steps:
1. Add a class `TestTheMidimapEnvelope` alongside the preset tests:
   - `save_midimap` round-trips a 360-word map through `load_midimap`
     (compare word-for-word); the record's `kind` and `slot` are the
     midimap ones.
   - saving twice never overwrites (two distinct files, `list_backups` shows
     two).
   - `load(..., kind="midimap")` returns `MidimapBytes`; a preset `id` asked
     for as kind `"midimap"` is refused.
   - a backup whose kind is `"preset"` is refused for `load_midimap`.
2. Use the module's existing helpers (`vbk.save` for hand-built envelopes,
   `DemoDevice` for the words). Model the shape on `../p2ked/tests/
   test_backup.py` and the preset tests already in this file.

**Verify:** `.venv/bin/python -m pytest tests/test_backup.py -q -o addopts=""`;
`ruff check`; `ruff format --check`; `mypy --strict emorphed emu tests`.

---

## U3 · A parameter change is undone by `z`

**Files:** `tests/test_app.py`.
**Current fact:** `_undo_master_edits` has a `ParamChange` branch
(`app.py:907-909`) that restores the old value through `_apply_parameter`,
but no test exercises it (only the busy-refusal and the `NameChange` branch
are covered).

Steps:
1. Add a test: open the midimap editor, arm the gate, nudge a parameter
   (demo device), assert the write; press `z`; assert the **previous** value
   is written back through the same gate and read back in agreement.
2. Reuse the existing helpers in `tests/test_app.py`
   (`_capture`, `_settle`, the editor-open + `move_cursor(row=1, column=2)`
   pattern at `:729-731`, and the name-undo test at `:957-974` as the
   model).

**Verify:** `.venv/bin/python -m pytest tests/test_app.py -q -o addopts=""`;
`ruff check`; `ruff format --check`; `mypy --strict emorphed emu tests`.

---

## U4 · The bench can capture the whole 674-byte bank frame

**Files:** `tests/test_hardware.py`.
**Current fact:** `test_preset_bank_request_records_checksum_status_per_frame`
(`:267-324`) prints a summary (lengths, number stride, checksum tally) but
keeps **no raw bytes**, so the 674-byte framing cannot be analysed later.
This is the reason TODO item 1 is still open. Offline evidence available: the
recon shows only ~120-byte hex fragments survive outside the checkout.

Steps:
1. In the bank test, for each **distinct frame length** that survives
   `frames_in`, write one full frame as a `.syx` file into the directory
   named by the environment variable `EMORPHED_BANK_CAPTURE` (default
   `/tmp/opencode`), and print every written path and its frame length. The
   file is raw SysEx bytes; no decoding, no assertion about the framing.
2. Keep the test asserting nothing about the 674-byte structure (it is a
   recorded observation). Update the module docstring so it says the framing
   question now has a **capture step** a human can run.
3. The default directory is outside the checkout on purpose (raw captures
   never live in the repo); say so in the docstring.

**Verify:** `.venv/bin/python -m pytest tests/test_hardware.py --hardware
--collect-only -q` (collection succeeds, **no device traffic**);
`ruff check`; `ruff format --check`; `mypy --strict emorphed emu tests`.

---

## U5 · `PRESET_GAP` gets a read-only tolerance sweep

**Files:** `tests/test_hardware.py`.
**Current fact:** `test_two_spaced_preset_requests_are_both_answered`
(`:327-348`) measures **one** gap (`PRESET_GAP` = 0.1 s). TODO item 3 asks
how far the gap can be pushed, in the read direction.

Steps:
1. Add `TestHardwareTiming::test_gap_sweep_reports_the_largest_answered_gap`
   (opt-in like the rest): read preset 0; then, for a small ascending list of
   gaps — `(0.0, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25)` — send two spaced
   preset requests and record whether both were answered. Print the largest
   gap still answered and the first that was not.
2. Read-only: **no writes**, no selection, no Program Change. Bound the whole
   sweep so a silent unit fails fast (use `bridge.DEFAULT_TIMEOUT` per read
   and stop at the first unanswered gap).
3. Do not change `bridge.PRESET_GAP` from a test; the number stays labelled a
   guess in the code until a human records the sweep (TODO item 3).

**Verify:** `.venv/bin/python -m pytest tests/test_hardware.py --hardware
--collect-only -q`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

## U6 · The write bench covers the store, or says it cannot

**Files:** `tools/bench_midimap_write.py`, `tests/test_midimap_bench.py`.
**Current fact:** the bench proves the **parameter** write only; its `--store`
block (`:833-873`) prints a failure but does **not** affect the exit verdict,
and it never reads the stored map back. TODO item 6's store half is unproven.

Steps:
1. When `--store` is given: after `bridge.send_midimap(location, words)`, read
   the stored map back (`bridge.read_midimap(location)`) and compare it to the
   words sent. Fold the store result into the **exit verdict** — a store that
   was attempted and did not read back agreeing is a failure.
2. Keep every fence: `--store` still needs a TTY and `--yes`; the location is
   still retyped; the tool still refuses `--demo`. Update the header/help so
   it states the store is now read back and part of the verdict.
3. Add synthetic tests to `tests/test_midimap_bench.py`: the store branch
   refuses without `--yes`/TTY (extend the existing ones), and the verdict
   helper treats a store disagreement as failure (test the pure helper, not
   `main`).

**Verify:** `.venv/bin/python -m pytest tests/test_midimap_bench.py -q
-o addopts=""`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

## U7 · The MidiQuest `.sqs` container is documented and scoped

**Files:** `docs/SQS_NOTES.md` (new), `TODO.md` (item 7 only).
**Current fact:** TODO item 7 is six lines and names nothing. Recon found
**41 real `.sqs` samples under `~/Dokumente/`** (none committed, none in any
sibling), and the siblings describe it as an IFF-style chunked file.

Steps:
1. Write `docs/SQS_NOTES.md` (GPL SPDX header) recording **structure only**,
   truthfully sourced:
   - big-endian IFF-style `LIST`/`FORM` typed `BANK`, with chunks seen in
     order `CHNL, SHDR, FILE, TRAN, RECV, [AUDI,] XTRA, [BDEF, TDEF,] MPIN,
     MPOT, BODY` (some files also `COMM`/`FIND`/`NAME`);
   - ASCII identity strings survive in the clear in the identity area while
     `SHDR`/`BODY` payloads are high-entropy (measured ≈5.5–7.2 bits/byte),
     i.e. compressed and/or obfuscated, **not** raw SysEx;
   - where this was observed (the sample directories, **read-only**) and that
     **no sample, name or identity string is committed**.
   Read a couple of the samples to confirm (or correct) the chunk vocabulary;
   do not copy any content into the doc.
2. Scope item 7 explicitly in the note: the **container is documented**; the
   `BODY` decode is a separate research task, and **no decoder ships**.
3. Update `TODO.md` item 7 to point at `docs/SQS_NOTES.md` and state what
   remains (the compressed body), replacing the six-line stub.

**Verify:** `ruff check`/`format --check` are unaffected (Markdown);
`grep -RIn "" docs/SQS_NOTES.md` shows no committed name string;
`.venv/bin/python -m pytest tests/ -q -o addopts=""` still green.

---

## U8 · The ledger is reconciled (ER-F1, the stale §22 line, edisyn notes)

**Files:** `TODO.md`, `docs/RESOLUTION_NOTES.md`.
**Do this task last, after U7**, so it owns the shared ledger files.

Steps:
1. **ER-F1** (`TODO.md:569-595`): the described bug **no longer exists in
   this checkout**. `emu/config.py` is a thin binding (`_settings =
   Settings(...)`, `:61-80`) and the bool guard now lives in
   `vinsynlib/config.py:438` (`load_channel`: `isinstance(value, bool) or not
   isinstance(value, int)`); `load_last_recv_port` is string-typed (`:464`)
   and cannot admit a bool; `tests/test_store.py::TestABoolIsNotANumber`
   (`:229-278`) walks every numeric loader and passes. Mark the item
   **resolved for emorphed**, say the guard moved to the shared library, and
   note the sibling-repo sweep is **out of this repository's scope** (Rule:
   do not edit siblings). Add the matching `docs/RESOLUTION_NOTES.md` entry.
2. **Stale line** `docs/RESOLUTION_NOTES.md:623-625` says the write bench
   "has not been run"; it ran 2026-10-16 (§22:515-536 says so). Correct it to
   say the **store** is the unrun half.
3. **edisyn observations** (`TODO.md:537-548`): record, as notes not code,
   that command `0x22` is absent from `Command.NAMES` (the manual does not
   confirm it — do **not** add a name yet), the nested Effect List structure,
   and the UltraProteus product ID `0x0C`.
4. Point items 1, 3 and 6 at the new bench steps (bank capture U4, gap sweep
   U5, store bench U6) so a human knows what to run; point item 7 at
   `docs/SQS_NOTES.md` (U7).
5. Re-read the whole of `TODO.md` and `docs/RESOLUTION_NOTES.md` and make the
   status lines agree with the code; leave genuinely bench-gated items open
   with an honest "bench-ready, run by a human" note.

**Verify:** `.venv/bin/python -m pytest tests/ -q -o addopts=""` green;
`grep -n "isinstance(value, int) and 0 <= value <= 15" TODO.md` returns
nothing; the §22 line no longer contradicts §22:515.

---

## U9 · The parity prompt is committed with a staleness note

**Files:** `docs/PROMPT-emorphed-parity.md` (add a short note near the top).
**Current fact:** the file is **untracked** although `TODO.md:685` references
it, and its parity contract is stale in three places (it says there is no
write path / no `--allow-write`, that the card bank is unresolved, and that
unnumbered replies' checksum is unknown — all since resolved).

Steps:
1. Add a short `> **Note (superseded in places).**` block under the title
   recording the three drifted facts and pointing at `TODO.md` /
   `docs/RESOLUTION_NOTES.md` for the current truth. Do not rewrite the task
   bodies — it is a historical record.
2. Leave it staged for the coordinator to commit (do not commit).

**Verify:** file renders; no broken relative links.

---

## Bench-gated: what a human must run (not this programme)

These are **not** resolvable offline; they are left as ready-to-run bench
steps, recorded in `TODO.md` by U8:

* **Item 1 (bank framing):** run `make test-hardware` with `U4` and send the
  captured `.syx` frames for analysis. Full raw bytes are the missing input.
* **Item 2 (card 320 vs 384):** needs a **card-fitted** unit; the
  configuration print plus the card regions observation.
* **Item 3 (`PRESET_GAP`):** run the `U5` sweep and record the largest
  answered gap.
* **Item 6 (store):** human-attended
  `tools/bench_midimap_write.py --store …` (TTY + `--yes`); `U6` makes it part
  of the verdict.

---

## Dependency graph

```
U1  U2  U3  U4  U5  U6   (wave 1, parallel — distinct files)
        U7 ──┐
             └── U8        (U8 owns TODO.md + RESOLUTION_NOTES.md; after U7)
U9                         (independent; docs/PROMPT-emorphed-parity.md)
```

`U1`/`U3` share `tests/test_app.py`; `U4`/`U5` share `tests/test_hardware.py`;
`U7`/`U8` share `TODO.md`. The coordinator serialises those pairs.

## Report format

End every task with: files touched, tests added (count), the tail of each
verify command, and any observation a human must bench-verify. The coordinator
commits; you never push.
