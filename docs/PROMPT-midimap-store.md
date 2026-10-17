<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — make a midimap edit survive a power cycle (the STORE)

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).

**The report.** With the write gate armed, a midimap edit reaches the unit --
you hear it -- but it is gone after a power cycle. A parameter write is the
unit's **scratch** map; only a **STORE** makes it permanent. The store exists
(`s` in the editor) but the flow is neither obvious nor proven.

**The manual already settles the frame.** `Morpheus_Operation_Manual.pdf`
(at `~/Dokumente/SYNTHS/Morpheus/Morpheus_Operation_Manual.pdf`), page 227
(Command Summary) lists `47 Midimap Data`; page 233 says of Midimap Data:

> "If map is sent to current selected location, the scratch map will be
> loaded from the newly stored map. Midimap numbers: 0-15 RAM, 16-31 CARD"

and gives the frame `F0 18 0C dd 47 vv ll mm … cs F7`. So a Midimap Data
frame sent to a location **is** the store, and `emu/messages.py
midimap_data` already builds exactly that frame. **The frame is not the bug.**
The work is to make the store reachable, reliable and *proven*, and to stop
the editor treating scratch edits as if they were saved.

Read `CLAUDE.md` first. `../vinsynlib`, `../rxved`, `../p2ked`, `../edisyn`
are read-only references. The manual PDF is read-only.

## Iron rules

1. **No hardware.** No MIDI ports, no `--hardware`, no `make test-hardware`.
   Build the bench step; a human runs it.
2. **Never invent a byte, a size or a page.** Cite the manual page or the
   sibling. The store frame is manual p.233.
3. Targeted tests, coverage off: `.venv/bin/python -m pytest <file> -q
   -o addopts="" -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.**
5. One exchange at a time; the screen owns no worker.

## The facts you are working from

- **Frame.** `midimap_data(words, number=loc)` -> `F0 18 0C <id> 47 01
  <ll> <mm> <360 words, 2 bytes each> <checksum> F7`. Store at `loc`
  (0-15 RAM, 16-31 CARD). `emu/messages.py`, manual p.233.
- **The store is gated on a backup.** `_store_midimap` refuses unless
  `self._midimap_backed_up` is true ("no midimap backup this session").
- **The bug that makes it unreachable:** `_backup_before_write` is called by
  `_apply_parameter_worker` and `_apply_channel_preset_worker`, but **not**
  by `_write_midimap_name_worker` (`emorphed/app.py`). A rename-only session
  therefore cannot store.
- **Scratch vs stored.** A parameter/name/pair write edits the **scratch**
  map; the store writes a location. `_current_midimap_words` holds the
  edited scratch and is what the store sends.
- **The store sends the edited words** (`_store_midimap` -> `words =
  _current_midimap_words` -> `send_midimap(loc, words)`), then reads the
  stored dump back and compares.

---

# Group S1 — the app: a reliable, honest store

**Files:** `emorphed/app.py`, `emu/messages.py` (only if the manual forces a
change), `tests/test_app.py`, `tests/test_protocol.py`.
**Model: `opencode-go/beam-free#max`** (the protocol + worker work).

1. **Back up on every write path.** `_write_midimap_name_worker` must call
   `_backup_before_write()` before its writes, exactly as the parameter and
   pair workers do, so any edited session can store. Add a test: a rename
   alone leaves `_midimap_backed_up` true and a subsequent store is allowed.
2. **The store must be honest about persistence.** After a store whose
   read-back agrees, say so in a way that names what happened, e.g.
   `stored to M{loc:02d} -- survives a power cycle (read back N/N words)`.
   A disagreement or a short dump must refuse and say the unit did not take
   it (the worker already reads back; keep that).
3. **Do not let a store silently no-op.** Every refusal path (no backup,
   busy, bad location, read-back disagreement) must notify and mark the
   editor status, so "I stored it" is never a silent no-op.
4. **Warn before losing scratch edits.** When the editor closes with edits
   that were never stored this session, warn (a status/`say`, or an offered
   confirm) that the changes are scratch and will be lost on a power cycle.
   Keep it non-destructive -- do not auto-store. If a confirm is used, say
   what is lost and default to keeping the session open. (Use the family's
   `ConfirmScreen`.)
5. **Tests.** Store sends the exact manual frame to the chosen location
   (`tests/test_protocol.py`); a store with no backup is refused; a
   rename-then-store works; a store read-back disagreement is reported and
   refused; a store to a card location with no card behaves as the read
   does (record, do not assert a hardware fact the manual does not).

**Verify:** `pytest tests/test_app.py tests/test_protocol.py`; ruff; format;
mypy.

---

# Group S2 — the editor says "scratch", and the bench proves the store

**Files:** `emorphed/midimapui.py`, `tests/test_midimapui.py`,
`tests/test_hardware.py`, `README.md`, `CLAUDE.md`, `TODO.md`.
**Model: `opencode/glm-5.3-flash-free#high`** (small, careful UI + prose).

1. **A visible scratch/stored state.** The editor must make it obvious that
   what is on screen is the unit's **scratch** map until stored. Add a
   marker the screen can set -- e.g. a `*`/`unstored` tag in the title or
   status once any edit has been made this session -- driven by a new
   optional callback/property the app sets (`set_unstored(True)` after a
   successful write). Keep it the screen's own state; the screen still
   sends nothing.
2. **Say what `s` does.** The footer hint and the status must read like the
   manual: `s store to a location (survives a power cycle)`. No "[b]refused[/b]"
   prefixes -- the family `refused` class already colours a refusal red.
3. **Bench step (build only; a human runs it).** In `tests/test_hardware.py`
   add an **opt-in** test `TestHardwareStore` that: reads midimap 0, changes
   one benign parameter, stores it back to a RAM location, reads the stored
   dump and checks the word took, then restores the original parameter and
   stores again -- and **prints** the location and the before/after so the
   operator can power-cycle and confirm. Assert only what the manual
   guarantees (the stored dump equals what was sent); print the rest. Do not
   run it.
4. **Docs.** README's "Editing a midimap": a parameter write is the scratch
   map; `s` stores to a location and *that* is what survives a power cycle;
   the manual p.233 citation. CLAUDE.md "Writing is fenced": one sentence
   that a scratch edit is lost on a power cycle until stored. TODO item 6:
   point at the retail store + the bench store step.

**Verify:** `pytest tests/test_midimapui.py`; `pytest
tests/test_hardware.py --hardware --collect-only -q` (collection only, no
device); ruff; format; mypy.

---

# Dispatch

| group | model | files |
|---|---|---|
| S1 | beam-free#max | `emorphed/app.py`, `emu/messages.py`, `tests/test_app.py`, `tests/test_protocol.py` |
| S2 | glm-5.3-flash-free#high | `emorphed/midimapui.py`, `tests/test_midimapui.py`, `tests/test_hardware.py`, `README.md`, `CLAUDE.md`, `TODO.md` |

The two groups touch disjoint files and run in parallel.
