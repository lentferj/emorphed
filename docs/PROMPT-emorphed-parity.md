<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — bring `emorphed` to the feature level of `rxved` and `p2ked`, on vinsynlib 0.4.2

> **Note (superseded in places).** This document is retained as a historical
> record of the parity programme; its task bodies are not rewritten. Three of
> its contract statements have since drifted from the code:
>
> 1. It claims there is no write path / no `EditGate` / no `--allow-write`. In
>    fact `emorphed/edit.py` defines `EditGate` and the app accepts
>    `--allow-write`.
> 2. It leaves the card's Bank Select number unresolved (2 or 3). `emu/banks.py`
>    `BANK_SELECT` now records card = 3, measured 2026-10-16.
> 3. It says the unnumbered-reply checksum is unknown. `docs/RESOLUTION_NOTES.md`
>    §20 resolved it: unnumbered replies carry no checksum.
>
> For the current truth see `TODO.md` and `docs/RESOLUTION_NOTES.md`.

You are working in **`/home/lentferj/git-repos/emorphed`** — a terminal browser for the
E-mu Morpheus. Two sibling programs, **`/home/lentferj/git-repos/rxved`** (Roland XV-2020)
and **`/home/lentferj/git-repos/p2ked`** (E-mu Proteus 2000), already do everything this
project does and more, because they adopted every part of the shared library
**vinsynlib 0.4.2** (`/home/lentferj/git-repos/vinsynlib`, installed, live on PyPI and
GitHub). `emorphed` adopted only the 0.2/0.3-era surface. Your job is to adopt the rest,
task by task, exactly as the siblings did — and to stand up the family test suites,
including the real-hardware suite, because the Morpheus is on right now.

Work through the tasks below **in the order the coordinator hands them to you**. One
agent = one task. Do not wander into other tasks' files.

---

## Who the readers of this file are

This file is written as a **prompt for a less capable LLM**. That means:

- Every task names the exact files to create or edit, and the exact sibling files to
  copy the pattern from. Copy the siblings' structure; the siblings are the
  specification. When a sibling solves a problem in a particular way, do it the same
  way — the family's consistency *is* a feature.
- If you are unsure how to do something, look it up in the sibling indicated by the
  task, not in your own imagination.
- Never guess a MIDI byte, a timeout or a behaviour. The manual is the spec
  (`emu/messages.py`'s comments cite it; `docs/RESOLUTION_NOTES.md` records how every
  number was established). When the code cannot know a fact, print the observation and
  let the human record it — p2ked's hardware probe is the model (`../p2ked/tests/test_hardware.py:194`).

---

## Iron rules (violating any of these fails the task)

1. **`make check` must be green before you end.** Run `make lint` / `format-check` /
   `typecheck` / `test` for the touched scope; run the full `make check` at the end of
   every task. Tests are **synthetic** — no test in the normal suite touches MIDI
   (the library's devcheck `config_saves_without_path` and the family pattern enforce
   this; `--demo` and fake devices only).
2. **The venv.** Everything runs inside `/home/lentferj/git-repos/emorphed/.venv/`
   (`bin/python`, `bin/pytest`, `bin/ruff` …). vinsynlib **0.4.2 is already installed
   from PyPI** — do not reinstall, do not touch the venv otherwise.
3. **No hardware writes.** `emorphed` has no write path (TODO item 6 keeps it parked —
   that is a *design decision*, not a gap). Nothing you write may send a data write to
   the unit. Information requests, name requests, data reads, and the Bank
   Select/Program Change pair from `select_messages` are the hardware suite's entire
   vocabulary. `select` is the only sound-maker and the hardware suite does not select.
4. **No E-mu names in the repository.** `emu/data/catalog.json` is generated and
   gitignored; test fixtures, demo names and docs use **invented, non-E-mu word pools**
   (see `emorphed/demo.py`'s pools and p2ked's demo for the style).
5. **Cursor movement never sends MIDI.** Reading names (`r` and the auto-reads) sends
   nothing audible on the Morpheus (names are free — one list request per kind). The
   only emission that plays is Select (Bank Select + PC), reached from `enter`.
6. **Workers do MIDI; the main thread does everything else.** `@work(thread=True)`
   workers own the wire and `call_from_thread` for UI updates — rxved's
   `tests/test_legend.py` even AST-checks this; copy the pattern.
7. **Never invent wire bytes or assert values the manual does not guarantee.**
   Unknown facts are printed observations or TODO entries, never assertions.
8. **Commits.** Conventional, one commit per logical change, subject in the family
   style (`config: take the store from bind()`, `report: the library's frame carries
   the help and scrolls it`). No AI attribution, no trailers, **never push** — the
   coordinator decides when things land.
9. **Stay on the copy.** Do not edit `../vinsynlib`, `../rxved` or `../p2ked`. They are
   read-only references.
10. **Line style:** ruff line-length 79, GPL-2.0-or-later SPDX header on every
    `.py`, mypy strict must keep passing. Match the surrounding code's diction
    (docstrings cite the manual and the siblings; status lines are plain sentences).

---

## The parity contract

At the end of this programme, `emorphed` uses from vinsynlib what the siblings use:

| vinsynlib surface (0.4.2) | rxved uses | p2ked uses | emorphed before | emorphed after (task) |
|---|---|---|---|---|
| pin `vinsynlib>=0.4.2` + entry gate | rxved/entry.py:41,44 | p2ked/entry.py:57,61 | pin 0.3.1, gate 0.2.0 | T1 |
| `catalog` (`Catalog`, `Entry`, `make_key`, `split_key`, `UNNAMED`, `load`, `dump`) | xv/catalog.py:61 | p2k/catalog.py | private parallel copy | T3 |
| `livenames` (sidecar `live-names.json`, `apply_to`, `FILE_NAME`, `key`) | rxved/livenames.py | (via catalog file) | none — live names die with the session | T4 + T5 |
| `build.build_of` about line | rxved/app.py:2756, app.py:2764 | p2ked/app.py:3256 | none | T2 |
| `ui.report.ReportScreen` frame | rxved/screens.py:43,240 | p2ked/app.py:90 | local copy | T2 |
| `ui.prompt.PromptScreen` | (own) | p2ked/prompts.py:37 | local copy | T2 |
| `ui.work` (`BusyGate`, `QUIET_BRIDGE_ERRORS`, `close_when_idle`) | rxved/app.py:66,2999 | (own) | manual `_busy` + `RLock` | T2 |
| `undo.UndoLog` (+ `plan`, `settle`, `gate_hook`) | rxved/app.py:176–207 | p2ked/app.py:353,1733 | none — no undo | T5 |
| `ui.modals` (`RatingFilter`, `RatingFilterScreen`) | own screens.py:2378 | own | none | T5 (library's, not a copy) |
| `backup` (JSON envelope) | own format | p2k/backup.py:56–87 | none | T6 |
| `render` (`table`, `progress`) | rxved/cli.py:39 | — | none | T6 |
| `spec.flag_help`, `cli` flag family | rxved/cli.py:39–41 | p2ked/cli.py:34 | `cli` mostly adopted | T6 |
| scan offer + progress screens | rxved/scan.py | p2ked/scan.py | none | T7 |
| hyperpreset/midimap browsing | — | (banks pane) | TODO item 4: read but not browsed | T8 |
| `conftest.py` + `--hardware` + env twin | tests/conftest.py | tests/conftest.py:49,64 | none | T9 |
| hardware suite `make test-hardware` | tests/test_hardware.py (14) | tests/test_hardware.py (10) | none | T9 |
| `tools/extract_catalog.py` | tools (from editor binary) | tools (from .ins) | does not exist (TODO 8) | T10 |
| docs day (README/CLAUDE/TODO/RESOLUTION) | CLAUDE.md, README | CLAUDE.md, README | 194-line README | T11 |

**Deliberate divergences (do not "fix" these):**
- No category filter (`C`): the Morpheus printed catalog has no categories
  (rxved/p2ked filter over printer-supplied categories; when the Morpheus tool's source
  provides none, there is nothing to filter — record as a divergence in
  `tests/test_conformance.py` EXTRAS if it becomes load-bearing).
- No write path / no `EditGate` / no `--allow-write`: retained divergence (TODO 6,
  arm-then-fire design is parked). The backup envelope (T6) is machinery for the day
  writes arrive — delivered via the CLI as read-only bank capture.
- No marked-list/paper-scan tool and no screenshot capture: out of scope.
- Favourites view stays on `F` (family canonical `F/t/n`; p2ked/rxved diverged to `v`
  for their own reasons — emorphed keeps `F`, which `conformance.check_legend` expects).

**Morpheus facts every task must respect** (from `docs/RESOLUTION_NOTES.md` and
`emu/messages.py`): SysEx `F0 18 0C ...`; 14-bit signed words, LSB7 first; names are 12
ASCII words; the three numbered data messages carry a 7-bit additive checksum (preset
566 B, hyperpreset 484 B, midimap 730 B total; whether unnumbered replies carry one is
unknown — TODO 1, measured on the bench, never assumed); one list request returns a
whole kind's names; P-RAM/P-ROM/P-CARD hold presets 0–383 (index ≠ display number;
card-flagged; RAM writable), H-RAM/H-CARD 0–255, M-RAM/M-CARD 16+16; Bank Select is
CC32 = bank (bank = index//128 — the *card* bank number is TODO 9, unresolved: 2 or 3).

---

## How to execute a task

For every task below:

1. **Read the named reference files first** (sibling files and this project's files).
2. **Do only the steps listed.** If a step surprises you, look at what the sibling
   does in the identical situation.
3. **Add/port the named tests.** Tests are the deliverable's proof: the weakest
   invocation must fail loudly if the behaviour regresses.
4. **Verify:** the commands listed under *Verify*. All green or the task is not done.
5. **Commit** with the given subject line and stop.

Runner's note: the coordinator assigns one task per agent. Chains (A, B) must run in
order; waves may run in parallel when tasks do not share files.

Dependency graph (coordinator's view):

```
T1 ┐
T3 ├─ (wave 1, parallel)
T9 ┘
T2 ┬────────── (wave 2, parallel with T4, T6)
T3→T4 ┘
T5 ← (A2: needs T2's app state + T4's emu/livenames)
T10 ← (wave 3, parallel with T5)
T7 ← (A3: needs T5)
T8 ← (A4: needs T7)
T11 (docs: needs everything)
```

Chains: **A** = T2 → T5 → T7 → T8 (all touch `emorphed/app.py` — strictly sequential).
**B** = T3 → T4 (device layer), T6 separate. **C** = T9 standalone. **D** = T10, T11.

---
---

# The tasks

## T1 · Stand on 0.4.2: the pin and the gate

**Files:** `pyproject.toml`, `emorphed/entry.py`, `tests/test_entry.py`.
**Copy the shape from:** `../rxved/pyproject.toml` (line 60), `../rxved/entry.py`
(`MINIMUM`/`SOURCE`), `../p2ked/entry.py:44–56` (the floor rationale docstring).

Steps:
1. `pyproject.toml` dependencies: `vinsynlib>=0.4.2`; check the install-sources comment
   stays truthful about where the pin resolves from.
2. `emorphed/entry.py`: `MINIMUM = (0, 4, 2)`, `SOURCE = "vinsynlib>=0.4.2"`. Update the
   docstring with the floor rationale **specific to what emorphed's new code needs**:
   0.4.2 is the version `emorphed` asks for features from (`build.build_of`,
   `ui.report.ReportScreen` frame, undo's `plan`/`settle` need 0.4.1 or newer). Keep
   the gate stdlib-only and keep `devchecks.release_parts_drift` happy — do not confuse
   the two copies of `_release_parts`.
3. `tests/test_entry.py`: every expectation that names a string moves to
   `vinsynlib>=0.4.2`; keep the missing/too-old/fake-version tests, message bodies
   unchanged apart from the number.
4. Sanity imports in the venv (no test needed): `vinsynlib.build`,
   `vinsynlib.ui.report`, `vinsynlib.undo.UndoLog.plan` all importable.

**Verify:** `.venv/bin/python -m pytest tests/ -q` (98 pass; some may now assert
stricter 0.3.0-era devchecks — fix the project side, never weaken the check);
`make lint typecheck`; `ruff format --check`. Also
`.venv/bin/python -c "import emorphed.entry, sys; sys.exit(1) if '0.4.2' not in emorphed.entry.SOURCE else 0"`.

**Commit:** `entry, pyproject: the floor is 0.4.2 -- build_of and the report frame need it`

---

## T3 · (chain B1) Catalog on the library's back

**Files:** `emu/catalog.py`, `tests/test_catalog.py` (new), `tests/test_store.py` (only
the catalog class moves out).
**Copy the shape from:** `../p2ked/p2k/catalog.py` (the binding structure and the
printed-vs-live discipline), `../rxved/xv/catalog.py:61` (`from vinsynlib.catalog
import UNNAMED, make_key`).

Steps:
1. `emu/catalog.py` keeps its public API (the browser calls
   `entry/display_name/search/set_live_name/is_live/differs/load/empty`) but the
   storage grammar becomes **vinsynlib.catalog**: keys built with `catalog.make_key`
   (`"P-RAM:013"`), `UNNAMED = "--"` placeholder, `split_key` for reading keys back.
   The two-layer rule stays: printed (generated file) vs live (read off the unit), live
   wins, `differs` flags a disagreement with `*`.
2. `load(path=None)` reads `emu/data/catalog.json` with the family's leniency
   (missing file → `Catalog.empty()`; bad rows counted to stderr, never fatal).
   The Morpheus rows carry no `kind`; keys are `make_key(bank_id, number)`.
3. Split the catalog test class(es) out of `tests/test_store.py` into
   `tests/test_catalog.py` (model on `../p2ked/tests/test_catalog.py`: 116 lines, both
   layers kept apart; invented names only).

**Verify:** `pytest tests/test_catalog.py tests/test_store.py -q`; `make lint typecheck`;
`devchecks.foreign_imports` still clean (`tests/test_config_paths.py` must pass
unmodified).

**Commit:** `catalog: the key grammar and the unnamed placeholder come from the library`

---

## T4 · (chain B2) Live names survive the session

**Files:** `emu/livenames.py` (new), `tests/test_livenames.py` (new).
**Copy the shape from:** `../rxved/rxved/livenames.py` (119 lines — the thin binding is
exactly this), `../vinsynlib/src/vinsynlib/livenames.py` (the library's API:
`FILE_NAME`, `key`, `load`, `save`, `apply_to`).

Steps:
1. `emu/livenames.py`: `default_path()` (beside the favourites DB in emorphed's data
   dirs — see `emu/favorites.py` for how the data dir is got: `favorites.data_dir`
   pattern), `load(path=None)`/`save(names, path=None)`/`apply_to(catalog, path)` thin
   bindings that only supply the default path and docstrings in emorphed's words
   (rxved's docstring explains *why* the sidecar is separate from the catalog file —
   write the Morpheus version of the same reasoning).
2. Do **not** wire the app in this task (T5 does that). No `app.py` edits.
3. `tests/test_livenames.py` modelled on `../rxved/tests/test_livenames.py` (15 tests,
   all synthetic, `tmp_path` stores): load-missing is empty, corrupt warns and loads
   the readable subset, apply sets live names and skips unparseable keys, save writes
   atomically and never raises on OSError, key round-trip.

**Verify:** `pytest tests/test_livenames.py -q`; `make lint typecheck`.

**Commit:** `livenames: bind the sidecar to vinsynlib's -- names read off the unit outlive the session`

---

## T2 · (chain A1) The screens, the working rules, the build line

**Files:** `emorphed/screens.py` (new), `emorphed/app.py`, `tests/test_report.py` (new),
`tests/test_app.py` (adjust call sites if needed).
**Copy the shape from:** `../rxved/rxved/screens.py:20–43,240–303` (ReportScreen
subclass + re-export block + KEY_HINTS via `keys.legend`), `../rxved/rxved/app.py`
for `build_of` (`:2756`) and `QUIET_BRIDGE_ERRORS` (`:66`), `../p2ked/p2ked/app.py:88–91`
(modal import block).

Steps:
1. `emorphed/screens.py`: re-export `wrap_blocks` and `KeyHints`;
   `class ReportScreen(_Frame)` where `_Frame = vinsynlib.ui.report.ReportScreen`, adding
   **only** `enter` as a closer (rxved's subclass is three lines — copy that shape, not
   more); `PromptScreen` = vinsynlib's `ui.prompt.PromptScreen`, re-exported.
   `KEY_HINTS = keys.legend(("d device ID",))` in family order (emorphed's current
   `KEY_HINTS` blocks must all be expressible this way; `conformance.check_legend`
   continues to pass — it computes the expected legend from `extras`).
2. `emorphed/app.py`: delete the local `ReportScreen`/`PromptScreen` classes; import
   from `emorphed.screens`; keep every call site's semantics (search results, device
   info, help all push the frame — and gain scrolling bodies for free).
3. Adopt `vinsynlib.ui.work`: `BusyGate` replaces the `_busy` flag/`RLock` pair
   (`refuse` on the main thread before spawning, `check()` in the worker's guard,
   `exit`-time close via `close_when_idle` with rxved's grace shape
   `rxved/app.py:2999–3021`), and fold `QUIET_BRIDGE_ERRORS` into emorphed's
   `_BRIDGE_ERRORS` (emorphed may extend with its own wire errors — start from the
   library's frozenset).
4. About line: `_build_line()` using `vinsynlib.build.build_of` for
   `(("emorphed", __file__), ("vinsynlib", None))` — both named, rxved's wording
   shape. The help report and device info both prepend it. `make_parser` gains
   `distribution="emorphed"` so `--version` is one implementation.
5. `tests/test_report.py` modelled on `../rxved/tests/test_report.py` (11 tests):
   subclass of the library frame, `escape`/`q`/`enter` close, the body is a
   `VerticalScroll` (test the scroll, not the CSS string), `_build_line` agrees with
   `build_of("vinsynlib")`.

**Verify:** `pytest tests/test_report.py tests/test_app.py tests/test_conformance.py -q`;
full `make check`.

**Commit:** `report: the library's frame carries the help and the searches, and it scrolls`

---

## T5 · (chain A2) Undo on the library's log, rating filter from the library, live names wired in

**Files:** `emorphed/app.py`, `emu/terms.py` (no — leave terms alone), `tests/test_app.py`
(extend), `tests/test_favorites.py` (un-empty it).
**Copy the shape from:** `../p2ked/p2ked/app.py:353,1449–1748` (the `_ChangesView`
write-through window, `_push_change`, `_undo_master_edits`, `_undo_gate`),
`../rxved/rxved/app.py:176–207` (the `_Change` record shape), the library's
`ui/modals.py` (`RatingFilter`, `RatingFilterScreen`) and `undo.py` (`Record`,
`UndoLog`).

Steps:
1. `UndoLog(gate_hook=self._undo_gate)` made **first in `__init__`** (a watcher can
   fire before the constructor finishes — p2ked learned this; docstring the reason).
   The app keeps a write-through `_ChangesView`: kinds
   `FavouriteChange | RatingChange | TagNoteChange`; `z` takes one plan step
   (`UndoLog.plan(1)`), `Z` takes all; `last_refusal` ("busy") shows as a refused
   status; favourites/tags/notes flip on the main thread (SQLite is local), wired kinds
   would go to a worker — there are none yet, so nothing may send MIDI.
   Undo restores **previous values**: favourite toggles restore annotations
   (favorites.toggle already does), rating restores the old rating, tags/note restore
   old text.
2. Rating filter: `V` binding pushing `vinsynlib.ui.modals.RatingFilterScreen`
   (escape returns unchanged; `x`+enter clears), filter applies over the visible list,
   state parked via `emu/config.py`'s ui-state wrappers
   (`load_ui_int`/`load_ui_bool`/`save_ui_state` — the 0.4.0 API; keys
   `rating_stars`, `rating_at_least`). Rows show `rating_cell` (already re-exported).
3. Wire `emu/livenames.py` into the app: startup loads the sidecar and
   `livenames.apply_to(catalog, path)` **before the first frame** (rxved's
   `main` order, `rxved/app.py:2970–2974`); after a successful names read, the
   worker persists the live names (`livenames.save`) and calls
   `favorites.refresh_names` from the main thread (SQLite is main-thread's — check
   p2ked's worker/MainThread split). `--live-names` flag overrides the default path
   (rxved naming).
4. Un-empty `tests/test_favorites.py` (it is a 0-byte placeholder): port the useful
   subset of `../p2ked/tests/test_favorites.py` family-vs-local cross-checks
   (`rating_cell` identical) and emorphed's pending favouriting pins.
   `tests/test_app.py` gains the undo pins (z after toggle restores, labelled in the
   status line) and the V-filter pins.

**Verify:** `pytest tests/test_app.py tests/test_favorites.py -q`; `make check`.

**Commit:** `undo, rating filter: the timeline is the library's log; the filter is the library's screen`

---

## T7 · (chain A3) The scan offer and its screen

**Files:** `emorphed/scan.py` (new), `emorphed/app.py`, `tests/test_scan.py` (new).
**Copy the shape from:** `../p2ked/p2ked/scan.py` (184 lines — offer semantics) and
`../rxved/rxved/scan.py:74–212` (offer + progress screens, mount-safe
`set_progress`, cancel `threading.Event` checked **between** requests).

Steps:
1.    `emorphed/scan.py`: `ScanOffer = str` (`"scan" | "later" | "never"`),
   `ScanOfferScreen` (`y`/`n`/`d`, escape == later, "never" persisted via
   `config.save_ui_state("scan_offer_dismissed", True)`), `ScanScreen`
   (progress line + Cancel; cancel = event; mount-safe before compose). Both screens
   **MIDI-free** — the app drives the wire.
2. App wiring: the offer fires when the catalog is empty and not dismissed and not
   demo (`_maybe_offer_scan` shape, `p2ked/app.py:2868`). `S` (`scan_device`) reads
   **all three kinds** with the free name requests (one exchange per kind, silent),
   applies to the catalog, persists live names, and announces the count; progress on
   the shared `ScanScreen`; the cancel event is checked between kinds.
   The Morpheus has no per-bank "scan" that plays — document that in the screen's
   `SCAN_OFFER` honest text (rxved's honesty standard, `rxved/scan.py:63`).
3. `tests/test_scan.py` modelled on `../p2ked/tests/test_scan.py` (222 lines): offer
   answers, persistence of "never", mount-safe progress, cancel honoured between
   requests, no MIDI from the screens themselves.

**Verify:** `pytest tests/test_scan.py -q`; `make check`.

**Commit:** `scan: the offer and the progress -- names for all three kinds, read quietly and kept`

---

## T8 · (chain A4) Hyperpresets and midimaps become browsable (TODO item 4)

**Files:** `emorphed/app.py`, `emu/banks.py` (if a kind table helps), `tests/test_app.py`.
**Copy the shape from:** emorphed's existing preset table machinery (it is the least
capable LLM's friend: the flow for presets already exists); `../p2ked/p2k/roms.py`
for "kinds-of-containers are fixed tables, never arithmetic".

Steps:
1. A key cycles the right pane across **preset → hyperpreset → midimap** views;
   `names(kind)` already reads all three in one exchange each — the browser just needs
   the views and the catalog keys (`catalog.make_key(bank_id, number, kind=…)`).
   Hyperpreset and midimap regions: H-RAM/H-CARD per `emu/banks.py`; midimap 16+16.
2. Display numbers follow `emu/banks.py`'s index-vs-number rule per kind; the card
   flag is shown, the writable flag is shown. Names from the live read win over the
   catalog (existing rule) and persist via the same sidecar path.
3. `enter` selects presets only (Bank Select + PC machinery is preset-only —
   hyperpresets and midimaps have no Program Change address). Selecting a
   hyperpreset/midimap row is refused with a plain sentence explaining why; the
   refusal follows the family's `notify_status(..., refused=True)` styling.
4. Tests: the kind cycle, the three name reads landing in the right regions, the
   refusal sentence on enter for non-preset kinds, cursor silence still holds.

**Verify:** `pytest tests/test_app.py tests/test_conformance.py -q`; `make check`;
`conformance.check_bindings` still passes (the new key is declared as an extra in the
legend's `extras` order — update `keys.legend(...)` extras and
`tests/test_conformance.py` expectations if needed).

**Commit:** `browser: hyperpresets and midimaps get views -- read, kept, and refused on enter`

---

## T6 · (chain B3) The CLI: render, the family commands, and the backup envelope

**Files:** `emorphed/cli.py`, `emu/backup.py` (new), `tests/test_backup.py` (new),
`tests/test_cli_favorites.py` (new), `pyproject.toml` only if a flag is added.
**Copy the shape from:** `../p2ked/p2k/backup.py` (250 lines: binding, KIND/BLOCK,
save_setup/list/load), `../rxved/rxved/cli.py:39–41` (render + spec), p2ked's
`p2kcli` command anatomy, `../rxved/rxved/cli.py:1186–1221` (the fav command).

Steps:
1. `emu/backup.py`: `from vinsynlib import backup as _backup` + `FORMAT`;
   `Backup(_backup.Backup)` record; `APP_NAME`, `KIND = "preset"`, `BLOCK = "preset"`;
   `default_dir()` = `<data_dir>/backups`; `save_preset(words, ...)` — the block is the
   preset's own bytes from `messages` (never a re-description; p2ked encodes the
   *unit's* bytes); `list_backups(dir)`; `load(id)` refuses wrong kind/missing block.
   Pure stdlib + our messages module. **No restore**: the Morpheus write path does not
   exist; `load` exists and `restore` is explicitly not offered (docstring names the
   TODO-6 design decision).
2. `morphcli backup save <region>` (requires the unit; confirms with `--yes` because
   it reads a whole RAM region — 128 requests with `PRESET_GAP`; family convention:
   sweeps confirm) writes each read preset to the envelope with progress from
   `render.progress`; `morphcli backup list` (offline, newest first, corrupt listed
   with `error`); **no** `restore` command (help text says why).
3. `morphcli fav` for parity with the family: `--add/--remove/--rate/--tags/--note/
   --tag/--search/--rating-at-least/--rating-exactly/--order` (rxved's surface,
   `rating_cell` glyphs in list output). `morphcli tags` (counts). `morphcli ports`
   (via `vinsynlib.midi.list_ports`/`render_ports` — import inside the command body so
   non-MIDI commands never pay for rtmidi).
4. CLI tables/progress from `vinsynlib.render` (`table` for regions/list/current-style
   output if applicable; `progress` for backup save). `spec.flag_help` for any
   emorphed-specific flag help framing.
5. Tests: `tests/test_backup.py` modelled on `../p2ked/tests/test_backup.py` minus the
   app auto-backup half (no writes exist) — round-trip, never-overwrite names,
   refuse-wrong-kind; `tests/test_cli_favorites.py` modelled on
   `../rxved/tests/test_cli_favorites.py` (12 tests), and demo-device-driven CLI tests
   keep every command runnable without hardware.

**Verify:** `pytest tests/test_backup.py tests/test_cli_favorites.py tests/test_app.py -q`;
`make check`; `morphcli --help` shows the family flag order
(`conformance.check_flags` expectations in `tests/test_conformance.py` updated to the
new command list — required flags stay `("port","scan","recv-port","demo","config",
"catalog")`).

**Commit:** `cli: the family's fav, ports, tags -- and the preset backup envelope (save and list, read-only)`

---

## T9 · (chain C) The hardware suite — the Morpheus is on

**Files:** `tests/conftest.py` (new), `tests/test_hardware.py` (new), `Makefile`.
**Copy the shape from:** `../rxved/tests/conftest.py` (the option + fixture anatomy) and
`../p2ked/tests/conftest.py:49–103`; the test bodies follow emorphed's bench TODOs.

Steps:
1. `conftest.py`: `pytest_addoption("--hardware")` + env twin `EMORPHED_HARDWARE=1`
   (the family pattern; reasons spelled in the skip messages), and a session-scoped
   `bridge` fixture: `MorpheusBridge.connect()` (remembered ports first); on
   connection failure retry **once** with `connect(scan=True)`; failing that
   `pytest.skip` with the named-causes list (powered off, port renumbered, busy
   session, Rx Exclusive... — the Morpheus equivalent: "Master Exclusive off"),
   never a one-cause diagnosis. Close in `finally`.
2. `test_hardware.py` — **read-only**; assert only manual-guaranteed facts; print
   observations for the human to record (p2ked's probe style
   `p2ked/tests/test_hardware.py:194`):
   - `version()` round-trips (frame shape, device id in reply).
   - `configuration()`: structural sanity + **printed observation** of the RAM sizes
     for TODO item 2 (manual 256–384 contradiction) and card presence.
   - one `names(kind)` exchange per kind: `parse_name_list` returns names of 12
     chars in ASCII 32–127; count matches the reply's word (structural, no name values
     asserted).
   - one `read_preset` from a RAM slot: 566-byte frame, checksum recomputed from the
     data bytes agrees (TODO item 1's ER-2 bench step), words re-decode.
   - one `preset_bank_request` exchange: full-bank read with the 40 s timeout class;
     checksum status of every frame **printed**; the reply/absence resolves TODO
     item 1's bank-request question — record, don't assert.
   - timing probe: two preset requests spaced `PRESET_GAP` both answered → print
     measured gap tolerance for TODO item 3 (a read-only timing observation).
   - the card question (TODO 9): select with `CC32=2` vs `3` would move the machine —
     **do not**. Print which card regions the configuration reports and leave the
     select-based settle to a listed manual bench step in TODO.md.
3. `Makefile`: `test-hardware` target, family-shaped:
   `pytest tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s`
   (copy p2ked's target, change the env var name in help text). Never part of
   `check`.
4. **Do not run `make test-hardware`.** Building the suite is the task's work;
   executing it against the unit is a separate decision the human makes — the
   Morpheus is a real instrument that is powered on, and no agent drives it unless
   the coordinator's dispatch prompt explicitly says a hardware run is approved.
   Build the suite so it *would* run (`.venv/bin/pytest tests/test_hardware.py
   --hardware --collect-only -q` succeeds), then stop. Report which of TODO items
   1, 2, 3 and 9 the bench would answer when the human chooses to run it.

**Verify:** `.venv/bin/pytest tests/test_hardware.py --hardware --collect-only -q`
(collection succeeds; no device traffic); `make lint typecheck`; `pytest tests/ -q`
green — the synthetic suite is untouched and the hardware file is opted-in, so the
normal suite neither runs nor needs the device.

**Commit:** `hardware: the bench suite -- identity, sizes, checksums, and the observations TODO 1-4 asked for`

---

## T10 · (chain D1) The catalog extraction tool

**Files:** `tools/extract_catalog.py` (new), `pyproject.toml` (`[dependency-groups]` a
`tools` extra only if a non-stdlib dependency is genuinely required), `tests/test_extract.py` (new).
**Copy the shape from:** `../p2ked/tools/extract_catalog.py` (414 lines, from Cakewalk
`.ins`) and `../rxved/tools/extract_catalog.py` (the guard philosophy).

Steps:
1. The tool builds `emu/data/catalog.json` (gitignored) from a **user-supplied** name
   listing: primary source a Cakewalk `.ins` (E-mu instrument definitions were
   released by third parties; the .ins name lists are plain `key=value` — p2ked's
   parser is the model), alternative source a plain-text preset list (one name per
   line, prose heading per bank) with `--from-text`. The names are **E-mu's** — the
   file is gitignored, never committed (rule 4).
2. Region targeting: `--region P-ROM` etc.; rows land via `catalog.make_key`
   grammar; the tool never invents a name (a gap is a gap: UNNAMED placeholder rows or
   omitted, p2ked's rule).
3. Guards: duplicate display numbers refused (p2ked's guard class); control
   characters and unprintables refused; a name that survives parsing must survive
   re-reading — copy p2ked's actual guards in spirit
   (`p2ked/tools/extract_catalog.py:51–120`).
4. Tests on **invented** fixture files only (`tests/fixtures/invented.ins`).
   No network, no local file presence required to run the suite.

**Verify:** `pytest tests/test_extract.py -q`; `make check`;
`python tools/extract_catalog.py --help` renders.

**Commit:** `tools: extract_catalog -- the printed list leaves the checkout`

---

## T11 · (chain D2) The docs day

**Files:** `README.md`, `TODO.md`, `docs/RESOLUTION_NOTES.md`, `CLAUDE.md` (new).
**Copy the shape from:** `../p2ked/CLAUDE.md` (232 lines — the conventions, in
emorphed's words), `../rxved/rxved/README.md` (feature documentation structure).

Steps:
1. `CLAUDE.md`: the family conventions with emorphed's facts — the identical-edit
   rule (index vs display number; device IDs 0–15 where the manual's words are the
   panel numbers), workers/MIDI rule, "no hardware — act like it" rule restated, the
   fenced-write park (TODO 6), never-commit-E-mu-names, the two-file issue ledger,
   the no-push rule.
2. `TODO.md`: resolve/advance items 1 (bench findings from T9 go here),
   2 (card size observation), 3 (gap timing), 4 (browsing shipped in T8 — close or
   state what remains), 8 (tool exists — how to run), 9 (printed observation only),
   and add the adopted-in-this-programme items with their tasks as sub-entries.
3. `docs/RESOLUTION_NOTES.md`: one entry per resolution this task wave produced
   (truthful sourcing: which test, which observation, which manual section).
4. `README.md`: the new feature surface in the family's documentation structure —
   favourites with undo, rating filter, live names kept between sessions, the backup
   envelope, scan, CLI commands, `make test-hardware` for the bench. Honest limits
   stay truthful (no write path; `restore` not offered).

**Verify:** nothing mechanical: `make check` once more; spell-check the CLI surface
against `morphcli --help` and `emorphed --help` output so docs name real flags.

**Commit:** `docs: the browser as it now is -- conventions, bench findings, TODO answers`

---

## Coordinator's reminders to every agent

- The sibling code is **the specification**; when a sibling has a comment explaining
  *why* something is the way it is, carrying the equivalent comment into emorphed is
  part of the work, not decoration.
- If a step's assumption turns out false (an import the pin lacks, a Textual API
  difference), do **not** improvise around it: stop, record the finding in your final
  report, and let the coordinator decide. A wrong-but-green suite is the family's
  definition of the worst outcome.
- **No agent touches the hardware.** The only approved traffic to a real device is
  explicitly authorised in a dispatch prompt by the coordinator (and, through the
  coordinator, by the human). Absent that sentence, `MorpheusBridge` is instantiated
  against synthetic/demo devices and fakes only.
- Report at the end: files touched, tests added (count), verify-command tail, the
  commit hash, and any observation a human must bench-verify.
