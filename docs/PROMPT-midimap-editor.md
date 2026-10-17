<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — make the midimap editor comprehensible

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).
The user opened the midimap editor and found it "pretty much useless and
confusing": a wall of 360 near-identical parameter rows, an empty demo map
whose name reads `????????????`, and a `name` row whose "range" is a
per-character `32-127`. This prompt fixes that.

Read `CLAUDE.md` first. `../vinsynlib`, `../rxved`, `../p2ked` are read-only.

## What the editor is (context for the work)

A midimap is the Morpheus's MIDI-routing map: 16 channels, each with a
program/bank/volume/pan/mix-bus and a bank of on/off switches, plus a
Global/Effects block — **360 words**, offsets 0-359. Offsets 0-11 are the
twelve name characters. The editor (`emorphed/midimapui.py`) is a `DataTable`
with columns **offset · section · label · value · range**, one row per word.

## Iron rules

1. **No hardware.** No MIDI ports, no `--hardware`, no `make test-hardware`.
   Use `emorphed/demo.py`.
2. **Never invent a byte, timeout, size or name.** Parameter facts come from
   `emu/midimap.py` (`PARAMS`, `param_at`, `spell`, `spell`/`choices_for`); a
   demo name comes from the invented pool in `emorphed/demo.py`.
3. Targeted tests, coverage off: `.venv/bin/python -m pytest <file> -q
   -o addopts="" -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.**
5. Keep the family diction: docstrings name the decision; status lines are
   plain sentences; the screen owns no worker and sends nothing on its own
   (everything goes through `on_edit`/`on_name`).

## The tasks, and the free model chosen for each

| task | files | model | why this model |
|---|---|---|---|
| D1 demo seed | `emorphed/demo.py`, `tests/test_midimapedit.py` | `opencode/deepseek-v4.1-flash-free#high` | data-model precision against `emu/midimap.py` |
| R1 clarity | `emorphed/midimapui.py`, `tests/test_midimapui.py` | `opencode/glm-5.3-flash-free#high` | careful, small UI edits with exact test updates |
| R2 collapse | `emorphed/midimapui.py`, `tests/test_midimapui.py` | `opencode-go/beam-free#max` | hardest task: row-mode state + navigation |
| DOC | `README.md`, `CLAUDE.md`, `TODO.md` | `opencode/nemotron-3.5-lightning-free` | short mechanical prose |
| REVIEW | (read-only) | `opencode/nemotron-3-ultra-free` | independent verification pass |

D1 and R1 share no file and run in parallel. R2 runs after R1 (same file).
DOC runs after R2 (it describes the finished editor). REVIEW runs last.

---

# D1 · Seed the demo midimap (parallel with R1)

**Files:** `emorphed/demo.py`, `tests/test_midimapedit.py`.

**Finding.** `DemoDevice.__init__` seeds `self._midimap` and
`self._stored_midimap` as `[0] * 360` (`emorphed/demo.py:103-108`). So the
editor opens on an all-zero map: every value `0`, and the name decodes to
`????????????`, which is why the demo editor looks broken.

**Spec.** Build a deterministic, plausible seed from the real parameter table
(no invented values — read `emu/midimap.py`):
- a helper `_seed_midimap() -> list[int]` returning 360 words;
- a twelve-character **invented** name (a word from `emorphed/demo.py`'s own
  pool, or `"Demo Midimap"`), written via `mm.set_name([0]*360, text)`;
- Channel 1 (offsets 12-31): program `0`, bank `0` (`RAM Presets`), volume
  `100`, pan `0`, mix bus `0` (`Preset`), `Ch. Enable = 1`, `ProgChg Enbl = 1`
  and a couple more switches on;
- Channel 2 (offsets 32-51): a different program and volume so the summary
  rows differ;
- the remaining channels enabled at most (`Ch. Enable = 0`);
- Global/Effects: FX A type (offset 333) set to a named type (e.g. the index
  of `"Room"` in `_FX_A_NAMES`), and one or two FX A params (334+) non-zero —
  all through `mm.param_at(...)` lookups, never a bare literal that could
  drift from the table.
- `self._midimap` and `self._stored_midimap` both start as that seed (a
  stored map is loaded into scratch; `read_midimap` returns the stored one).

**Tests.** In `tests/test_midimapedit.py`:
- `DemoDevice().read_midimap(0)` equals `_seed_midimap()`;
- `mm.name_of(seed)` is the invented printable name (12 chars, 32-127);
- the specific offsets above carry the expected values; `read_parameter`
  answers the same for `mm.PARAM_BASE + 12` etc.
- **Run the whole suite.** `tests/test_app.py::TestMidimapParamUndo` and any
  other test that asserts a demo pre-edit value is `0` must be updated to the
  seeded value — **update the assertion, do not weaken it**. Report every
  test you had to touch.

**Verify:** `.venv/bin/python -m pytest tests/ -q -o addopts=""
-p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# R1 · Name row and column labels (parallel with D1)

**Files:** `emorphed/midimapui.py`, `tests/test_midimapui.py`.

**R1a — the name row must not pretend to be a number.**
- `_display_value("name")` (`midimapui.py:213-215`) currently returns
  `literal(self._name_text())` — which, for a blank map, is `????????????`.
  Change it to: the decoded name wrapped in double quotes
  (`literal(f'"{name}"')`), **or** the literal text `(empty)` when the name
  is blank — all twelve words `< 32`, or the decoded text consisting only of
  spaces and `?`.
- `_range_text("name")` (`:223-225`) returns `32-127`; that is the
  per-character ASCII range, not a value range. Return `text · 12 chars`
  (use a plain ASCII hyphen if a middle dot is risky).
- `_update_status` (`:306+`) sets `rng = "32-127"` for the name; make it the
  same text.
- Keep entering the name via Enter — unchanged.

**R1b — clearer column headers.** In `_build_rows`/the table setup
(`midimapui.py:361-365`) the columns are `offset · section · label · value ·
range`. Rename to `#  · section · parameter · value · allowed`. Update the
header-order test in `tests/test_midimapui.py` (it asserts the current
headers) to the new names — do not delete the test.

**Tests.** A screen with name words set shows `"<name>"` in the value cell and
`text · 12 chars` in the range cell; a screen built from all-zero name words
shows `(empty)`, never `????`. Header names are the new ones.

**Verify:** `.venv/bin/python -m pytest tests/test_midimapui.py -q
-o addopts="" -p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# R2 · Collapse each channel to one summary row (after R1)

**Files:** `emorphed/midimapui.py`, `tests/test_midimapui.py`.

**Finding.** 320 of the 360 rows are sixteen near-identical channel blocks;
the section repeats on every row. Collapse each channel to a single summary
row that expands on Enter.

**Spec.**
1. State: `self._expanded: set[int] = set()` (channel numbers 1-16 that are
   open; default all collapsed).
2. Row grammar: a channel summary row is the string key `f"ch{n}"`.
   `_build_rows` (`:131-140`) becomes: the `"name"` row (if a name block is
   present); then for each channel `1..16` either the one `f"ch{n}"` summary
   (collapsed) **or** its twenty offsets `12 + (n-1)*20 .. +19` (expanded);
   then the Global/Effects offsets present in `_values` (332-359) — those are
   always expanded.
3. `_section_of` (`:142-151`): `f"ch{n}"` → `f"Channel {n}"`; unchanged for
   the rest.
4. `_param_of` (`:153-162`): `f"ch{n}"` → `None`.
5. `_label_of`: `f"ch{n}"` → `f"Channel {n}"`.
6. `_display_value` for `f"ch{n}"`: one plain sentence built from the channel's
   twenty words via the real labels and `mm.spell`, e.g.
   `prog 0 · RAM Presets · vol 100 · pan Preset · bus Preset · 6 switches on`.
   Count the switches as the number of `Ch. * Enbl` words equal to 1.
7. `_range_text` for `f"ch{n}"` → `20 params · enter to expand`.
8. `action_edit_current` (`:531`): if the current row is `f"ch{n}"`, toggle
   whether that channel is in `_expanded`, `_refresh_table()`, and put the
   cursor back on the same `f"ch{n}"` row (`_index_of_row`). Otherwise keep
   the existing edit behaviour.
9. A new binding `c` → `action_toggle_all_channels`: if any channel is
   expanded, collapse all; else expand all. Add it to `BINDINGS` and to the
   footer hint line.
10. **Section-once, not every row:** in `_refresh_table` (`:243-265`), write
    the `section` cell only on the first row of each contiguous section;
    leave it blank on the following rows. (A collapsed channel is one row, so
    its section shows once naturally.)
11. Filter (`_visible_rows`, `:233-241`): when a filter is set, ignore the
    collapse and search every row's label, so a match is never hidden inside
    a summary (predicate: if `self._filter`, build from all offsets).
12. `on_key` digit typing (`:784-813`) and the Enter-commit path must ignore
    `f"ch{n}"` rows exactly as they ignore `"name"` (a summary row has no
    value to type).

**Tests** (`tests/test_midimapui.py`), with the real Textual pilot:
- the default view has one row per channel (16 `Channel n` summaries), no
  per-parameter channel rows;
- Enter on a summary row expands it (the twenty offsets appear, keyed
  `str(off)`), Enter again collapses it;
- `c` expands all then collapses all;
- `n`/`p` section jumps still land on section boundaries;
- a filter that matches a parameter inside a collapsed channel still shows
  that parameter (collapse is ignored while filtering);
- typing a digit on a summary row does nothing.

**Verify:** `.venv/bin/python -m pytest tests/test_midimapui.py
tests/test_app.py -q -o addopts="" -p no:cacheprovider`; `ruff check`;
`ruff format --check`; `mypy --strict emorphed emu tests`.

---

# R3 · Adapt the app tests to the collapsed default (after R2)

**Files:** `tests/test_app.py`.

**Finding.** R2 made every channel collapsed by default, so row 1 of the
table is now the `Channel 1` summary, not offset 12. Seven app tests move the
cursor with `move_cursor(row=1, column=2)` (or `row=2`) and now land on a
summary row: `test_gate_locked_edit_sends_nothing`,
`test_backup_failure_announced_write_proceeds_flag_stays_false`,
`test_write_holds_exchange_lock`,
`test_param_write_armed_then_z_restores_previous_value`,
`test_undo_two_nudges_one_lands_one_pushed_back`,
`test_undo_under_locked_gate_survives`, `test_silent_readback_not_logged`.

**Spec.** In each, after the editor opens (`action_midimap_edit()` and settle),
expand the channels before moving the cursor — the `c` binding (R2's
`action_toggle_all_channels`) restores the old flat layout, so `row=1` is
offset 12 again. Use the same mechanism consistently (`await pilot.press("c")`
after a pause, or call the screen action, whichever is already the file's
style). Do **not** change what each test asserts; only make the cursor reach
the parameter row. If any test also asserts the row count or the section cell,
update it to the expanded layout.

Run the whole suite afterwards; it must be fully green.

**Verify:** `.venv/bin/python -m pytest tests/ -q -o addopts=""
-p no:cacheprovider`; `ruff check`; `ruff format --check`;
`mypy --strict emorphed emu tests`.

---

# DOC · Describe the finished editor (after R2/R3)

**Files:** `README.md`, `CLAUDE.md`, `TODO.md`.

- `README.md`'s "Editing a midimap" section (around the `m` binding): say the
  right pane now shows **one summary row per channel** (program · bank ·
  volume · pan · mix bus · how many switches), which **expands on Enter** and
  collapses again; `c` toggles all; the name is one row showing the quoted
  name (or `(empty)`); the columns are `# · section · parameter · value ·
  allowed`. Keep the existing write-gate / read-back / store paragraphs.
- `CLAUDE.md`, "Writing is fenced": if it describes the editor's rows, add one
  sentence that channels are collapsed to summaries and expand on Enter.
- `TODO.md` item 6: one line noting the collapsed-channel summary view.

**Verify:** `grep -n` the new sentences; `README.md` still names only real
keys (`c` must exist after R2).

---

# F · Fix the REVIEW findings

**Files:** F1 owns `emorphed/midimapui.py` + `tests/test_midimapui.py`;
F2 owns `README.md` + `TODO.md`. Run F1 and F2 in parallel.

## F1 · Editor correctness, UX and coverage

- **A1 (correctness).** In `result()` the branch
  `if "name" in self._all_rows and self._filter: self._ordered =
  self._visible_rows()` recomputes the row model **without** rebuilding the
  table, so after an FX-type change (which relabels FX rows) `_ordered` and
  the rendered table diverge and the cursor row goes inert. Replace it with a
  consistent rebuild — `self._build_rows()`, `self._refresh_table()`, then
  restore the cursor to the row that was current (`_index_of_row`). Reproduce
  with a filter + an FX A type change and assert table rows and `_ordered`
  agree afterwards.
- **A2.** `_range_text("ch{n}")` says `20 params · enter to expand` even when
  the channel is expanded; return `20 params · enter to collapse` when
  `n in self._expanded`. Test both states.
- **A3.** `action_toggle_all_channels` resets the cursor to row 0 (via
  `_refresh_table`); restore the cursor to the row it was on, the way
  `action_edit_current` already does. Test: the current row key survives `c`.
- **A4.** `_nudge` on a `ch{n}` row returns silently; say something like
  `"the channel summary is expanded with enter"` (the name row already
  explains itself).
- **C3.** Update the module docstring (`midimapui.py:8`): it still says "one
  row per word"; describe the collapsed summary rows.
- **B1.** Add pilot tests that press `c` and `enter` on a summary row instead
  of calling the actions directly.
- **B2.** Replace the six tests that expand a channel with
  `screen._expanded.add(1); _build_rows(); ...` with the public action.
- **B3.** Add tests for the summary sentence text, the `ch{n}` range text, and
  the section-written-once rule (a continuation row's section cell is blank).
- **B4.** Add a test that editing a channel parameter while the channel is
  collapsed updates that channel's summary value cell.

## F2 · Docs drift

- **C1.** `README.md:240` says "every row shows its offset"; the column is now
  `#` and a summary row's `#` cell holds `ch1`. Reword.
- **C2.** `README.md:271`'s worked example is not what the code prints;
  channel 1 actually renders
  `prog 0 · RAM Presets · vol 100 · pan 0 · bus Main · 4 switches on`.
- **C5.** `TODO.md:336`'s new bullet uses `-` unbolded inside a list of
  `* **bolded**` bullets; match the sibling style and make clear it is a
  shipped behaviour note.
- **C6.** `README.md:270` calls the editor "the right pane"; it is a centred
  modal. Reword.

---

# REVIEW · Independent check (last)

Read the finished `emorphed/midimapui.py`, `emorphed/demo.py`,
`tests/test_midimapui.py`, `tests/test_midimapedit.py` and the docs. Confirm:
each task above is actually implemented; no row/keystroke path is unreachable;
the collapse state cannot desync from the table; typing and Enter still edit
parameters correctly; nothing asserts a hardware fact. Report findings with
`file:line`; do not modify any file.
