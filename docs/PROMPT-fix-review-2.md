<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — fix the findings from the GLM-5.3-Flash re-review

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).
The re-review verified every earlier finding fixed and raised the issues
below (3.1–3.5). Fix **all of them**. One agent = one file-group.

Read `CLAUDE.md` first. `../vinsynlib`, `../rxved`, `../p2ked` are read-only.

## Iron rules

1. **No hardware.** No MIDI ports, no `--hardware`, no `make test-hardware`.
2. **Never invent a byte, timeout, size or name.**
3. Targeted tests only, coverage off: `.venv/bin/python -m pytest <file> -q
   -o addopts="" -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.**
5. The undo library's two doors are documented in
   `vinsynlib/undo.py`: `plan`/`settle` **consume on take**, and a tool
   whose failure is a retry **pushes back what failed**. Use that door.

---

# Group P — the undo batch and the read-back (`emorphed/app.py`, `tests/test_app.py`)

## P1 · (HIGH) `Z`/undo-all consumes changes it never applies

**Finding.** `_undo_master_edits` (`app.py:940-991`) calls
`self._undo_log.plan(n)` — which **consumes** all `n` records — then walks
them and calls `_apply_parameter` for each. `_apply_parameter`
(`app.py:697-716`) acquires `self._exchange` on the main thread and only then
spawns the worker, so in the loop the **second** MIDI change finds the
exchange held, is refused as "busy" (`app.py:710-714`), and its record is
already gone. The summary (`app.py:986-991`) still counts it. Net: `Z` over
two parameters undoes one, drops the other, and says "undid 2 parameters".

**Fix — push back what was not applied.** Use the library's retry door:
- Make `_apply_parameter(self, offset, value, *, record=True) -> bool`
  return `True` when it acquired the exchange and dispatched the worker,
  `False` on **every** refusal (gate refusal, `_busy`, or a failed
  `_exchange.acquire`). Keep its `notify_status`/screen reporting.
- Make `_apply_name_text(self, text) -> bool` the same: `True` after it
  dispatches `_write_midimap_name_worker(text, record=False)`, `False` on any
  per-character gate refusal or busy refusal.
- In `_undo_master_edits`, keep a `not_applied: list[Any]` (records). For a
  `ParamChange`: `if self._apply_parameter(change.offset, change.old,
  record=False): params += 1 else: not_applied.append(record)`. Same shape
  for `NameChange` with `_apply_name_text`. Favourites/ratings/tags still
  apply unconditionally (they are synchronous and cannot refuse).
- After the loop, put the failures back **oldest-first** so the log still
  describes what is applied: `for record in reversed(not_applied):
  self._undo_log.push(record)`. (`taken` is newest-first; `_log` is
  oldest-first.)
- The sentence must be honest: build it from the applied counts as now, and
  when `not_applied` is non-empty append `f"; {len(not_applied)} could not be
  applied -- press z again"`. If nothing applied, say
  `f"{len(not_applied)} could not be applied -- press z again"`.

Worked example to encode as a test: two parameter nudges, then `Z` →
exactly one undo write lands, `len(app._changes) == 1`, the status names the
one that could not be applied; a later `Z` (after the worker settles)
applies the remaining one.

## P2 · (MEDIUM) `z` under a locked write gate loses the undo

**Finding.** `UndoLog.plan` consumes regardless of the **write** gate
(`self._undo_gate` at `app.py:406-407` answers only the *busy* gate). So with
the gate locked, `z` takes the record, `_apply_parameter`/`_apply_name_text`
then refuse at `_editor.allow`, and the record is gone — even after
re-arming, the change can no longer be undone.

**Fix — refuse before consuming.** At the top of `_undo_master_edits`,
before `plan`, peek the newest `n` payloads via `self._changes` (the
oldest-first payload view): `n = len(self._changes) if count is None else
min(count, len(self._changes))`, `newest = self._changes[-n:]`. If any of
`newest` is a `ParamChange` or `NameChange` and the write gate is locked
(`self._editor.gate.refuse()` is not `None`), `notify_status(refusal,
refused=True)` and **return without planning** — the log is untouched.
Favourites-only batches must not be blocked by the gate.

P1's push-back remains the safety net for the busy case; P2 handles the gate
case up front with the gate's own sentence.

## P3 · (MINOR) Silence reads as agreement for a value of `0`

**Finding.** `_parameter_edited` (`app.py:787-791`):
```python
rb = read_back if read_back is not None else 0
```
`emu/bridge.py`'s `read_parameter` returns `None` when the unit stays silent.
Mapping `None` to `0` means a silent unit plus a write of `0` passes
`self._editor.finish` as **agreed** and is logged.

**Fix.** Do not conflate `None` and `0`. When `failure is None and read_back
is None`, set `ok = False` and a plain sentence such as
`f"offset {offset}: the unit stayed silent (no read-back)"`; only call
`self._editor.finish(...)` when `read_back is not None`. Keep the existing
"only an agreed read-back is logged / updates `_current_midimap_words`"
behaviour.

## P4 · (MINOR, app half of 3.4) A refused parameter write must tell the editor screen

**Finding.** `_apply_parameter`'s gate-refusal branch (`app.py:700-709`) and
its busy branch call `top.say(refusal, refused=True)` / `notify_status` only.
The editor (Group Q) reverts an optimistically painted cell on
`result(False, …)`, so the app must emit that signal on a refusal too.

**Fix.** In `_apply_parameter`, on the gate refusal and on each busy refusal,
call the top screen's `result(False, sentence, parameter_id=offset,
value=value)` when it has one (mirroring the shape at `app.py:793-801`),
instead of — or in addition to — the current `say`. Do not change the
`notify_status` calls. Parameters only; the name path is a text prompt, not an
optimistic cell.

## P5 · Tests for P1–P3 (`tests/test_app.py`)

- P1: the worked example above (two nudges then `Z`; one lands, one is pushed
  back and named in the status; a second `Z` applies the rest).
- P2: one parameter edit, then lock the write gate, then `z`; assert the gate
  refusal is said **and** `len(app._changes) == 1` (the record survived).
- P3: arm the gate, monkeypatch `DemoDevice.read_parameter` to return `None`,
  nudge; assert the change log stays empty and the status reports silence.

Model on the existing `TestMidimapParamUndo` and the write-gate tests.

**Verify (P):** `.venv/bin/python -m pytest tests/test_app.py -q
-o addopts="" -p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# Group Q — the editor's optimistic cell (`emorphed/midimapui.py`, `tests/test_midimapui.py`)

## Q1 · (MINOR, screen half of 3.4) The cell keeps the value the unit refused

**Finding.** `MidimapEditScreen` paints optimistically in three places —
`_nudge` (`midimapui.py:517`), the choices picker (`:579`) and the
range-apply prompt (`:616`) — each doing `self._values[off] = value` before
`self._on_edit(off, value)`. `result()` (`:376-390`) only updates `_values`
when `ok` is true; on `ok=False` it just says the message. So a refused or
disagreed write leaves the cell showing a value the unit does not hold until
a re-read.

**Fix.** Remember the pre-edit value and restore it when the result is not
ok:
- Add `self._pre_edit: dict[int, int] = {}` to `__init__`.
- At each of the three optimistic sites, before `self._values[off] = value`,
  record the previous once: `self._pre_edit.setdefault(off,
  self._values.get(off, value))` (the outer-most previous wins if several
  edits are in flight).
- In `result`, resolve `off = parameter_id if parameter_id is not None else
  offset`. On `ok=True`, `self._pre_edit.pop(off, None)` (keep the existing
  `_values[off] = value` update). On `ok=False`, if `off` is not None and in
  `_pre_edit`, restore `self._values[off] = self._pre_edit.pop(off)`, refresh
  the table and status. When `off` is None, behave exactly as today.

**Test.** A screen with `{14: 5}` and an armed gate, cursor on the `14` row:
`action_nudge_up()` paints `6`; then `screen.result(False, "Ch. Volume did
not take 6", parameter_id=14, value=6)` must leave
`screen._values[14] == 5`. Keep the existing mismatch-sentence test
(`result(False, …)` with no id) unchanged.

**Verify (Q):** `.venv/bin/python -m pytest tests/test_midimapui.py -q
-o addopts="" -p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# Group R — the review's own prose (`TODO.md`, `docs/PROMPT-fix-review-findings.md`, `emu/backup.py`)

## R1 · (LOW) Three leftover prose defects

- `TODO.md:240-241` — the D2 rewrite left a broken sentence: "a Program
  Change reaches neither midimap nor -- per the 2026-10-16 measurement -- is
  there a midimap bank". Reword to one clean clause, e.g. "a Program Change
  reaches neither a midimap nor a midimap bank (no midimap bank exists, per
  the 2026-10-16 measurement)".
- `docs/PROMPT-fix-review-findings.md:250` — the B1 finding quote contains a
  garbled "sets a Game-free frame". Replace it with what was meant: "sends a
  Midimap Data frame whose only structural check is fourteen bits". This is
  the fix prompt's own ledger and must read true.
- `emu/backup.py:19` (docstring) — the D4 fix removed the false "no write
  path" claim but left "When writes arrive, the other half -- sending those
  bytes back -- can be added on top of this". Now that a gated midimap write
  path exists, say "When **preset** writes arrive…".

**Verify (R):** `grep -n` each corrected sentence; no code changes.

---

# Dispatch map

| agent | tasks | files |
|---|---|---|
| P | P1–P5 | `emorphed/app.py`, `tests/test_app.py` |
| Q | Q1 | `emorphed/midimapui.py`, `tests/test_midimapui.py` |
| R | R1 | `TODO.md`, `docs/PROMPT-fix-review-findings.md`, `emu/backup.py` |

No two agents share a file; all three run in parallel. P4 (app side) and Q1
(screen side) are two halves of the same contract: the app emits
`result(False, …, parameter_id=off, value=…)`; the screen reverts that cell.

## Report format

Per agent: files touched, tasks done, tests added (count), verify tails, and
anything you could not fix.
