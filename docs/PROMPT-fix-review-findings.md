<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — fix every finding from the branch review (MiMo-V2.6-Flash)

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).
A code review of the resolve-TODO wave (commits `5dffb16`…`ce80cac`) found
the issues below. Fix **every one, no matter how small**. One agent = one
file-group; the groups are chosen so no two agents touch the same file.

The family conventions are in `CLAUDE.md`; read it first. Siblings
(`../rxved`, `../p2ked`, `../vinsynlib`, …) are read-only references.

## Iron rules

1. **No hardware.** No MIDI ports, no `make test-hardware`, no `--hardware`.
   Tests run against `emorphed/demo.py` and fakes only.
2. **Never invent a byte, timeout, size or name.** Cite the manual, the
   sibling, or an existing observation.
3. **Targeted tests only**, coverage off, to avoid clobbering parallel
   agents: `.venv/bin/python -m pytest <file> -q -o addopts=""
   -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.** Leave changes in the working tree; the
   coordinator commits.
5. Keep the family diction: docstrings cite the decision; status lines are
   plain sentences.

## How the findings were located

Quotes and line numbers are from the reviewed commit. Line numbers may have
drifted by one or two; **anchor on the quoted code, not the number.**

---

# Group A — browser write/store correctness

**Files (owned by this group):** `emorphed/app.py`, `tests/test_app.py`.

## A1 · (HIGH, correctness) A parameter undo re-logs an inverse record

**Finding.** `_undo_master_edits` undoes a parameter by calling the same entry
point a user edit uses (`app.py:936-938`):

```python
elif isinstance(change, ParamChange):
    params += 1
    self._apply_parameter(change.offset, change.old)
```

`_parameter_edited` then pushes a fresh record on success (`app.py:778-779`):

```python
if ok:
    self._push_change(ParamChange(offset, old_val, value))
```

Because `vinsynlib.undo.UndoLog.plan` **consumes** the taken records
(`del self._log[-clamped:]`), the undo removes one record and adds another, so
`z` toggles the value forever and `Z` right after a `z` re-applies the change
that was just undone. Every other change type avoids this: favourites/ratings/
tags call the store directly, and the name path passes `record=False`
(`app.py:608`).

**Fix.** Thread a `record` flag through the parameter path, mirroring the name
path:
- `_apply_parameter(self, offset, value, *, record: bool = True)`
- `_apply_parameter_worker(self, offset, value, record: bool = True)`
- `_parameter_edited(..., *, record: bool = True)` and guard the push:
  `if ok and record: self._push_change(...)`.
- Call site `app.py:534` (the editor callback) keeps the default.
- The undo branch becomes
  `self._apply_parameter(change.offset, change.old, record=False)`.

Do **not** change the `_current_midimap_words[offset] = value` update on a
successful restore — the screen must reflect the restored value.

## A2 · (HIGH, test) Pin the undo semantics A1 fixes

**File:** `tests/test_app.py`, class `TestMidimapParamUndo`
(around `:972-1003`).

The existing test stops after one `z`. Extend it (or add a second test) so the
bug A1 fixes could not return:
- after the `z`, assert the change log is **empty**
  (`app._changes == []` — same view the "nothing to undo" path uses), i.e. the
  undo did not re-log;
- a second `z` writes nothing more (the demo's `parameter_writes` count does
  not grow) and says "nothing to undo";
- a `z` followed by `Z` does **not** re-apply the value (the final read value
  equals the original, not the nudged one).

## A3 · (HIGH, correctness) A name write that disagreed is still logged for undo and still updates the screen

**Finding.** `_write_midimap_name_worker` (`app.py:637-648`) computes
`agreed = read_back == expected`, but then unconditionally updates
`_current_midimap_words` and (when `record`) pushes the `NameChange`:

```python
new_text = mm.name_of(new_words)
if getattr(self, "_current_midimap_words", None) is not None:
    for off in range(12):
        self._current_midimap_words[off] = new_words[off]
if record:
    self._push_change(NameChange(old_text, new_text))
```

`CLAUDE.md` (Writing is fenced) and `TODO.md` item 6 both say *only an agreed
read-back is logged*, and the parameter path obeys this (`app.py:778-779`,
`:788-789`). The name path does not, so a disagreement logs a name the unit
did not take and paints it on screen.

**Fix.** Guard both by `agreed`:

```python
if agreed and getattr(self, "_current_midimap_words", None) is not None:
    ...
if record and agreed:
    self._push_change(NameChange(old_text, new_text))
```

Leave `_finish_name_write`'s disagreement sentence unchanged (it already
reports `read-back disagreed (n/12)`); the point is that nothing is recorded
and nothing on screen changes when the unit did not take the write.

## A4 · (HIGH, test) Pin the name-write disagreement path

**File:** `tests/test_app.py`, class `TestMidimapNameWrite` (around
`:1065-1160`).

Add a test that monkeypatches `DemoDevice.read_parameter` to return a wrong
value once, arms the gate, applies a name, and asserts:
- the status/say text reports `read-back disagreed`;
- the change log is **empty** (nothing recorded for undo);
- the 12 on-screen words (`app._current_midimap_words[:12]`) are **unchanged**.

Model it on the existing name-write tests in that class.

## A5 · (MEDIUM, correctness) The store verdict counts an empty agreement as full success

**Finding.** `_store_midimap_worker` (`app.py:873-884`) computes

```python
full = stored is not None and len(stored_list) == total and agreed == total
```

With `words == []`, `total == 0` and `full` is vacuously `True`, so the app
prints `stored to M03 (read back 0/0 words agree)`. A real unit would refuse
the send (`messages.midimap_data` requires 360 words), but the demo does not
(see C1), so the synthetic surface can report a success the wire cannot.

**Fix.** Require a non-empty map:

```python
full = (
    stored is not None
    and total > 0
    and len(stored_list) == total
    and agreed == total
)
```

## A6 · (MEDIUM, correctness) `_store_midimap` does MIDI on the main thread

**Finding.** `_store_midimap` (`app.py:811-816`) falls back to a blocking
device read on the UI thread:

```python
words = list(getattr(self, "_current_midimap_words", []))
if not words:
    try:
        words = list(self.device.read_midimap(index))
    except Exception:
        words = []
```

`read_midimap` can wait `BANK_TIMEOUT` (40 s) and is not covered by the busy
gate or the exchange claim — a violation of `CLAUDE.md`: "Workers do MIDI; the
main thread does everything else."

**Fix.** Move the fallback read into `_store_midimap_worker`, which already
runs on a worker thread inside `self._busy_gate`:
- In `_store_midimap`, keep the cheap index calculation (it touches only
  attributes, not the wire) and pass it through:
  `lambda confirmed: self._store_confirmed(loc, words, confirmed, index=index)`.
- `_store_confirmed(self, loc, words, confirmed, *, index: int | None = None)`
  forwards `index` to the worker.
- `_store_midimap_worker(self, loc, words, index: int | None = None)`: inside
  the busy gate, `if not words: words = list(self.device.read_midimap(index or 0))`
  before sending.
- The existing 3-argument test calls (`tests/test_app.py:866, 896, 917, 929`)
  pass non-empty `words`, so `index` stays `None` and is unused — they keep
  working unchanged.

## A7 · (LOW, correctness) The disagreement sentence contradicts itself on a length mismatch

**Finding.** When the read-back is a different length, `full`/`store_agreed`
are `False` while `agreed == total`, so the app prints
`read-back disagreed (360/360 words agree)`.

**Fix.** In `_store_midimap_worker`, branch on the length first:

```python
if stored is None or total == 0 or len(stored_list) != total:
    sentence = (f"store to M{loc:02d}: read-back was "
                f"{len(stored_list)} words, not {total}")
    ... refused=True
else:
    agreed = ...
    if agreed == total: success sentence
    else: f"read-back disagreed ({agreed}/{total} words agree)"
```

## A8 · (LOW, style) The new store tests are in the wrong class

**File:** `tests/test_app.py`.

The six store tests (`:857-969`) were appended to
`TestStartupSaysWhereTheNamesCameFrom` (declared `:803`), whose subject is the
startup status line. Move them into `TestMidimapAppWriteGateAndStore`
(declared around `:675`) — the class U1 named as their model. Pure move; do not
change any assertion.

**Verify (group A):** `.venv/bin/python -m pytest tests/test_app.py -q
-o addopts="" -p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# Group B — bench tool

**Files (owned by this group):** `tools/bench_midimap_write.py`,
`tests/test_midimap_bench.py`.

## B1 · (HIGH, correctness) `--store` never range-checks its location

**Finding.** `tools/bench_midimap_write.py:864`:

```python
location = int(args.store) if str(args.store).isdigit() else None
```

`--index` *is* checked (`:706-708`, `if not 0 <= index <= 31:
raise SystemExit(...)`), and the app's prompt refuses out-of-range before any
screen (`emorphed/app.py:828-830`). But `--store 99` proceeds: the preview
read's `ProtocolError` is swallowed into `<unreadable: …>`, the confirmation
prompt is shown anyway, and `bridge.send_midimap(99, words)` sets a Game-free
frame whose only check is fourteen bits (`emu/messages.py:632-633`). This puts
an invented location on the wire — `CLAUDE.md`: never invent a byte or a
number.

**Fix.** Validate before the confirmation prompt:

```python
if location is None:
    print("store: not a number; refusing")
elif not 0 <= location <= 31:
    print("store: a midimap location is 0-31; refusing")
elif not backup_succeeded:
    ...
```

Also fix the preview read so a real read failure is not silently swallowed
into an unreadable name *and then asked anyway*: keep the name fallback for the
message, but the range refusal above runs first, so an in-range location is the
only one that reaches the prompt.

## B2 · (HIGH, test) Pin the `--store` range refusal

**File:** `tests/test_midimap_bench.py` (alongside `test_refuses_store_without_tty`,
`:87-96`).

Add tests that, with `stdin.isatty -> True` and `--yes`, a `--store 99`,
`--store -1` and `--store nope` run is rejected **before any frame is sent**.
The robust way without a device: assert the location-validation helper (the
pure piece B1 introduces) refuses `99`/`-1`/`nope` and accepts `0`..`31`; a
`main`-level test can assert `SystemExit`/the printed refusal if the parse path
reaches it without connecting. Prefer a pure helper so the assertion is
deterministic.

## B3 · (LOW, style) The `--store` help text is stale

**File:** `tools/bench_midimap_write.py:669-674`. The help still reads
`"(destructive; needs --yes)"`. Extend it to name the read-back and the verdict
("…; it reads the stored map back and a disagreement fails the run"). Keep it
within the parser's line width.

## B4 · (LOW, correctness) A PASS verdict is silent about a store that never ran

**Finding.** After `"store: aborted (location not confirmed)"` or
`"store: refused -- no successful backup in this run"`, `store_attempted`
stays `False`, so the verdict prints
`VERDICT: PASS -- written and restored…` with no store suffix. An operator
skimming the tail can read that as the store having been proven — the half
TODO item 6 is waiting on.

**Fix.** Track whether a store was *requested* (`store_requested =
args.store is not None`) separately from *attempted*, and make the PASS suffix
honest: attempted-and-agreed → `(store read back and agreed)`;
requested-but-not-run → `(store requested but not run)`; not requested → no
suffix. Do not turn an operator abort into a FAIL; only make the text truthful.

## B5 · (LOW, correctness) The bench disagreement sentence contradicts itself on a length mismatch

**File:** `tools/bench_midimap_write.py` (the store read-back block added in
`45f44f3`). Mirror A7: when the read-back length differs from the sent map,
print `store to M..: read-back was N words, not 360` rather than
`read-back disagreed (360/360 words agree)`.

**Verify (group B):** `.venv/bin/python -m pytest tests/test_midimap_bench.py
-q -o addopts="" -p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# Group C — demo device contract

**Files (owned by this group):** `emorphed/demo.py`,
`tests/test_midimapedit.py`.

## C1 · (MEDIUM, correctness) The demo accepts any word count where the wire requires 360

**Finding.** `emorphed/demo.py:241-254` `send_midimap` validates only the
index; `emu/messages.py:630-631` requires exactly 360 words:

```python
if len(words) != 360:
    raise ProtocolError(...)
```

So synthetic store tests can pass shapes the bridge could never send, which is
what lets A5's empty-map success slip through.

**Fix.** In `DemoDevice.send_midimap`, after the index check, mirror the
library: `if len(words) != 360: raise m.ProtocolError("a midimap is 360
words; got {len}")`. Reuse the same wording style as `messages.midimap_data`.

**Test.** Extend `tests/test_midimapedit.py::test_demo_send_midimap`
(`:108-113`) and/or add one: a 360-word map stores and reads back; a 359-word
map raises `m.ProtocolError`. Confirm every existing caller already passes 360
(`tests/test_protocol.py:465-489`, `tests/test_backup.py:157-210` do).

**Verify (group C):** `.venv/bin/python -m pytest tests/test_midimapedit.py
tests/test_protocol.py tests/test_backup.py -q -o addopts=""
-p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# Group D — ledger and doc contradictions

**Files (owned by this group):** `TODO.md`, `docs/RESOLUTION_NOTES.md`,
`emu/backup.py` (docstring only), `docs/SQS_NOTES.md`.

## D1 · (MEDIUM, docs) `RESOLUTION_NOTES.md` §22 still says `read_parameter` re-reads the whole map

**Finding.** `docs/RESOLUTION_NOTES.md:595-598` (the "What is implemented"
list) says `read_parameter` re-reads the whole owning map, "one 730-byte reply
per verification". That contradicts the code (`emu/bridge.py:403-414`: a
Parameter Request 0x02, one small frame) and §22's own narrative two paragraphs
up (`:529-532`: "`read_parameter` now sends a Parameter Request (0x02)").

**Fix.** Correct the sentence to describe the Parameter Request per-parameter
read (one small frame, manual p.232 scratch-map quote). This is the stale line
the previous wave's U8 promised to sweep but missed.

## D2 · (MEDIUM, docs) `TODO.md` item 5 says Enter refuses hyperpresets and midimaps

**Finding.** `TODO.md:238-239` (item 5, present tense): "Enter refuses
hyperpresets and midimaps before sending, since no program change reaches a
midimap at all." This contradicts item 4 in the same file (`:220-224`: a
midimap "is made current over System Exclusive behind a confirmation") and the
code (`emorphed/app.py:1590-1606`: hyperpresets select; a midimap selects
behind a confirmation).

**Fix.** Reword item 5's sentence to: Enter selects presets and hyperpresets;
a midimap is made current over System Exclusive behind a confirmation (a
Program Change reaches neither midimap nor — per the 2026-10-16 measurement —
is there a midimap bank). Keep it short; item 4 is the detailed entry.

## D3 · (MEDIUM, docs) The parity tail is backwards on screenshots and the favourites key

**Finding.** `TODO.md:732-733` (the divergence tail): "no marked-list or
screenshot capture, favourites stays on `F`." Both are wrong now: screenshots
exist and are committed (`tools/capture_screenshots.py`,
`docs/screenshots/*.png`), and favourites moved to `v`
(`emorphed/app.py:242`, `emorphed/screens.py:59-74`, pinned in
`tests/test_conformance.py`).

**Fix.** Restate the actual divergences: no marked-list/paper-scan tool; the
favourites view moved to `v` (family canonical is `F`); screenshots are
captured by `tools/capture_screenshots.py`.

## D4 · (MEDIUM, docs) `emu/backup.py`'s module docstring still claims there is no write path

**Finding.** `emu/backup.py:13-19`: "`emorphed` has no write path (TODO item 6
keeps it parked), so there is no `restore` command and none is offered here."
There **is** a gated write path (midimap parameters + store); only `restore` is
absent.

**Fix.** Reword to: `restore` is not offered because there is no restore
command; the one write path (midimap parameters + store) keeps its own backup
and read-back (see `CLAUDE.md`, "Writing is fenced"). Do not change code.

## D5 · (LOW, docs) `SQS_NOTES.md` miscounts the samples

**Finding.** `docs/SQS_NOTES.md:74` says "`~/Dokumente/SYNTHS/` (41 `.sqs`
files …) and `~/Dokumente/Sound Quest/` (a few more)". Measured:
**39** in `SYNTHS/`, **2** in `Sound Quest/`, **41 total**.

**Fix.** Correct to `39` and `2`, with the `41` total clearly the sum. This is
a document whose premise is truthful sourcing.

**Verify (group D):** `grep -n` for each corrected sentence; confirm no
remaining "has not been run" contradiction; `.venv/bin/python -m pytest tests/
-q -o addopts="" -p no:cacheprovider` still green (docs-only, but run it).

---

# Group E — the dispatch prompt's own accuracy

**Files (owned by this group):** `docs/PROMPT-resolve-todos.md` only.

## E1 · (LOW, docs) The task table's TODO line citations have drifted

**Finding.** `docs/PROMPT-resolve-todos.md:58-66` cites `TODO.md` line numbers
that moved when the ledger was rewritten in the same wave: item 6 cited
`:226-316` (actual heading `:248`), item 7 `:318-326` (actual `:350`), ER-F1
`:569-595` (actual `:613`), item 3 `:169-186` (actual `:179`), edisyn
`:537-548` (section `:502`, the notes paragraph `:589-592`). A prompt that
dispatches agents to exact lines sends them to the wrong ones.

**Fix.** Update each citation to the **current** line numbers. Anchor on the
heading text, not the number, when you check.

## E2 · (LOW, docs) Iron rule 5's headline does not match its intent

**Finding.** `docs/PROMPT-resolve-todos.md:41-44` says "No E-mu / MidiQuest /
third-party names in the repo", while task U7 itself mandates naming MidiQuest
in `TODO.md`/`SQS_NOTES.md`. The rule's body clarifies the intent is *identity
strings / patch names*.

**Fix.** Reword the headline to something like "No E-mu / MidiQuest / third
party **identity strings or patch names** in the repo" and keep the body.

**Verify (group E):** re-derive each cited line number with
`grep -n "<heading text>" TODO.md` and confirm the doc agrees; no broken
Markdown.

---

# Dispatch map (parallelise by file ownership)

| agent | tasks | files |
|---|---|---|
| A | A1–A8 | `emorphed/app.py`, `tests/test_app.py` |
| B | B1–B5 | `tools/bench_midimap_write.py`, `tests/test_midimap_bench.py` |
| C | C1 | `emorphed/demo.py`, `tests/test_midimapedit.py` |
| D | D1–D5 | `TODO.md`, `docs/RESOLUTION_NOTES.md`, `emu/backup.py`, `docs/SQS_NOTES.md` |
| E | E1–E2 | `docs/PROMPT-resolve-todos.md` |

No two agents share a file, so all five run in parallel. The coordinator
commits after every agent is green and runs the full suite once more.

## Report format

Per agent: files touched, tasks done, tests added (count), the tail of each
verify command, and any finding you could not fix with the reason.
