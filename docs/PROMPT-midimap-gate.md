<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — the write gate must govern the whole-map writes

## Analysis (do not skip this)

The report was "DEL goes through even if the write gate is not armed; the gate
does not reach the device either way". Two separate claims were checked on
the bench unit:

1. **The reset does reach the device.** Storing `mm.DEFAULT_WORDS` to `M00`
   changed its name `A:RWrm B:-` → `Dry`, read back equal, and a restore put
   it back. `send_midimap` is the same call the store uses. **The wire is not
   the bug.**
2. **The gate is not consulted.** `_reset_midimap_to_default`,
   `_store_midimap` and the midimap-undo `_restore_midimap` never check
   `EditGate`. The parameter, name and channel-preset writes do (through
   `EditGate.allow`), so the two whole-map writes are the exception: with the
   gate **locked** (the default) they still confirm and send.

So the fix is to make the whole-map writes honour the gate, exactly like the
other writes: **locked -> refuse, say why (the status `refused` class paints
it red), send nothing.**

## Tasks (small and atomic)

### T1 - the reset honours the gate (`emorphed/app.py`)
At the top of `_reset_midimap_to_default` (before the confirmation),
`refusal = self._editor.gate.refuse()`; if it is not `None`,
`notify_status(refusal, refused=True)`, say it on the editor screen if one is
open (`top.say(refusal, refused=True)`), and return -- nothing is confirmed or
sent. This covers both the editor's `DEL` and the browser's `DEL` (which calls
`_reset_midimap_to_default(entry.index)`).

### T2 - the store honours the gate (`emorphed/app.py`)
The same check at the top of `_store_midimap` (`s`), before the picker.

### T3 - the midimap undo honours the gate (`emorphed/app.py`)
- `_restore_midimap`: the same refusal (return `False`, so
  `_undo_master_edits` pushes the record back).
- `_undo_master_edits`'s P2 pre-consume peek currently refuses a batch that
  contains a `ParamChange` or `NameChange` when the gate is locked. Add
  `ChannelPresetChange` and `MidimapChange` to that tuple -- every gate-gated
  change kind must be refused **before** the log is consumed.

### T4 - tests (`tests/test_app.py`)
- `DEL` (editor and browser) with the gate **locked**: it refuses with the
  gate sentence and `device.midimap_stores` does not grow; with it **armed**
  it stores (existing tests must arm the gate before the store/reset they
  expect to succeed).
- `s` with the gate locked: refuses before the picker, nothing stored.
- A `MidimapChange` undo with the gate locked: the record survives (pushed
  back), nothing restored; armed: restores.
- Keep the existing tests green by arming the gate where a write is expected
  -- do not weaken an assertion.

### T5 - docs
- `CLAUDE.md` "Writing is fenced": state that **every** write -- parameter,
  name, channel preset, whole-map store (`s`), reset (`DEL`) and their undos
  -- is behind the gate; a locked gate refuses before anything is sent.
- `README.md`: the gate paragraph says the same for the store and the reset.

## Constraints

- **No hardware; no MIDI ports.** `DemoDevice` only. Do not run
  `make test-hardware`.
- `.venv/bin/...` only; **no commit or push**.
- ruff line length 79; mypy strict. Verify:
  `.venv/bin/python -m pytest tests/test_app.py -q -o addopts=""
  -p no:cacheprovider`, `.venv/bin/ruff check`,
  `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
  tests`, and one full `tests/` run.

## Dispatch

| agent | tasks | files | model |
|---|---|---|---|
| A | T1-T4 | `emorphed/app.py`, `tests/test_app.py` | `opencode-go/beam-free#xhigh` |
| B | T5 | `CLAUDE.md`, `README.md` | `opencode/glm-5.3-flash-free#high` |

A and B touch disjoint files and run in parallel.
