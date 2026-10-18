<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — bring the whole-map writes (store / reset) into the undo timeline

You are working in **`/home/lentferj/git-repos/emorphed`** on branch
**`master`** (the parity work has been fast-forwarded here).

## The gap

`z`/`Z` undo a favourites/rating/tag/note change, a parameter write, a
midimap **rename**, and a channel **preset pair**. They do **not** cover the
two *whole-map* writes:

- the **store** (`s`, a Midimap Data frame to a location), and
- the **reset** (`DEL`, writing the captured factory default).

Both overwrite all 360 words of a location and currently push **no undo
record**. The goal: record the overwritten map and let one `z` put it back.

## Model

A location's previous map is the whole 360-word tuple. One record per
whole-map write:

```python
@dataclass(frozen=True)
class MidimapChange:
    """One whole-map store: the location and the words it held before."""

    index: int
    words: tuple[int, ...]
```

`_change_label` returns `"midimap"`. Undo restores `words` to `index` with a
**best-effort backup first** and a **read-back** (the store's fence); the
`z` keypress is the confirmation (as for every other undo -- do not add a
second modal). The restore is **not** logged (`record=False`), so a second
`z` is a no-op.

## Tasks (small and atomic)

### T1 - the record (`emorphed/app.py`)
Add `MidimapChange(index: int, words: tuple[int, ...])` beside
`ChannelPresetChange`, with the docstring above, and handle it in
`_change_label` (`"midimap"`).

### T2 - record the store's previous map (`emorphed/app.py`)
In `_store_midimap_worker`, read the target's current words **before**
sending (`old_words = list(self.device.read_midimap(loc))`, best-effort:
on a failed read leave it `None` and still store). Add keyword-only
`record: bool = True` and `backup: bool = False`; when `backup`, first save
`old_words` via `bkmod.save_midimap(..., source="emorphed (midimap undo)")`.
Pass `old_words` and `record` to `_finish_store`. In `_finish_store`, on a
successful read-back **and** `record` **and** a 360-word `old_words`, push
`MidimapChange(loc, tuple(old_words))`.

### T3 - record the reset's previous map (`emorphed/app.py`)
`_reset_midimap_worker` already reads the target's words (`current`) before
the reset. Pass them to `_finish_reset`; on a successful read-back push
`MidimapChange(index, tuple(current))` (honour a `record` flag).

### T4 - undo a `MidimapChange` (`emorphed/app.py`)
Add `_restore_midimap(self, index: int, words: tuple[int, ...]) -> bool`:
refuse if `self._busy` or the exchange cannot be acquired (return `False`,
say why); otherwise acquire the exchange **once** and call
`_store_midimap_worker(index, list(words), record=False, backup=True)` and
return `True`. In `_undo_master_edits`, add the `MidimapChange` branch: if
the restore dispatches, count a midimap; else push the record back
(`not_applied`, as the other async changes do). Add the midimap(s) to the
summary sentence. Do **not** put `MidimapChange` behind the write-gate
peek: a store is not gate-armed today.

### T5 - tests (`tests/test_app.py`)
- Store to a location, then `z`: exactly one more `send_midimap`, of the
  location's **previous** words; `_changes == []`.
- `DEL` reset, then `z`: the pre-reset words are stored back; `_changes == []`.
- A second `z` after either does nothing (not re-logged).
- The store's `MidimapChange` is not pushed when the read-back disagrees.

### T6 - docs
- README: the undo paragraph now says `z`/`Z` also restore a midimap store
  or reset (one record per whole-map write).
- CLAUDE.md: one line in "Writing is fenced" that a whole-map write is in
  the undo timeline as a `MidimapChange`, and undo is itself a (backed-up,
  read-back) store.
- TODO: item 6 one line.

## Constraints

- **No hardware; no MIDI ports.** `DemoDevice` only. Do not run
  `make test-hardware`.
- `.venv/bin/...` only; **no commit or push**.
- ruff line length 79; mypy strict. Verify with
  `.venv/bin/python -m pytest tests/test_app.py -q -o addopts=""
  -p no:cacheprovider`, then `.venv/bin/ruff check`,
  `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
  tests`, and one full `tests/` run.

## Dispatch

| agent | tasks | files | model |
|---|---|---|---|
| A | T1-T5 | `emorphed/app.py`, `tests/test_app.py` | `opencode-go/beam-free#xhigh` |
| B | T6 | `README.md`, `CLAUDE.md`, `TODO.md` | `opencode-go/beam-free#xhigh` |

A and B touch disjoint files and run in parallel.

Report: files touched, tests added, verify tails, anything unfixed.
