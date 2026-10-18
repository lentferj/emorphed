<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — Fix all code review findings since aa198937

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `master`).

**Current state:** Branch `master` at `181b39e`, clean working tree except for a stash on `vsl042`. There are some uncommitted changes already applied (signed 14-bit writes, effect-type validation, cursor preservation fixes).

Your task: **Fix ALL findings from the code review** (independent of severity) by creating small, atomic tasks and dispatching them to subagents using the most suitable free LLM.

---

## ALL FINDINGS TO FIX

### HIGH SEVERITY

#### 1. App init: `UndoLog` created before `_busy_gate`/`_exchange`
- **File:** `emorphed/app.py:317` (approx)
- **Issue:** `UndoLog(gate_hook=self._undo_gate)` is created before `_busy_gate` and `_exchange` exist. `_undo_gate` calls `self._busy` which dereferences `_busy_gate`/`_exchange`. A watcher firing during early construction would raise `AttributeError`.
- **Fix:** Guard `_busy` property with `getattr(..., None)` or reorder initialization so `_busy_gate`/`_exchange` are created first.

#### 2. Cursor reset during background verify
- **File:** `emorphed/app.py:2441-2458` (`_verify_catalog_now` → `_verify_catalog_worker` → `_adopt_kind_quiet` → `_adopt_kind` → `_fill`)
- **Issue:** Background verify calls `_fill` which rebuilds the table and calls `_detail(0)`, resetting cursor/detail. Should use `_refill_keeping_place` or a quiet fill that preserves cursor.

#### 3. Undo midimap: `_restore_midimap` returns success before read-back completes
- **File:** `emorphed/app.py:1507-1540` (`_restore_midimap`)
- **Issue:** Returns `True` immediately after spawning worker, before the async write/read-back completes. No rollback on failure. Undo log doesn't record the restore.

### MEDIUM SEVERITY

#### 4. Shutdown race: Worker running at exit prevents `close_when_idle` from closing bridge
- **File:** `emorphed/app.py:2982-2990` (`main()` shutdown sequence)
- **Issue:** `store.close()` runs before `close_when_idle(device, gate=app._busy_gate)`. The 0.25s grace window aborts the close entirely if any worker is active at entry, so a live verification/scan worker at exit leaves the bridge unclosed.

#### 5. Backup fence inconsistency
- **File:** `emorphed/app.py:1090-1104` (`_backup_before_write`)
- **Issue:** Logs a backup failure but returns without preventing the subsequent parameter/channel write. Store/reset correctly refuse without backup.

### LOW SEVERITY

#### 6. Effect-type validation (PARTIALLY FIXED)
- **File:** `emorphed/edit.py:142-160` - `MidimapEditor.allow` accepted invalid effect-type IDs for FX A/B types (non-contiguous IDs like 15, 136). Already fixed in working tree - verify complete.

#### 7. Signed 14-bit writes (PARTIALLY FIXED)
- **File:** `emu/bridge.py:360-379`, `emorphed/demo.py:305-317` - `write_parameter`/`send_midimap` rejected signed values (-8 pan etc.). Fixed in working tree - verify complete.

#### 8. Stash cleanup
- **Stash:** `stash@{0}: WIP on vsl042: 52bab3b editor: the cell cursor keeps its column through edits` - contains changes to `emorphed/app.py`, `emorphed/midimapui.py`, `emorphed/screens.py`, `emu/midimap.py`, `tests/test_midimapui.py` (~755 lines). Should be dropped or reviewed.

#### 9. Documentation updates needed
- `CLAUDE.md:63-68` - "card's select bank is unresolved" (resolved to bank 3)
- `README.md:408` - "whole write path unverified" - parameter writes verified, only store unverified
- `README.md:290` - "title carries unstored marker" - marker moved to status line

---

## TASK BREAKDOWN FOR SUBAGENTS

Each task is independent and can run in parallel. Use **Beam Free/xhigh** (`opencode-go/beam-free#xhigh`) for code tasks, **GLM-5.3-Flash-Free** (`opencode/glm-5.3-flash-free`) for docs.

| Task | Files | Model | Description |
|------|-------|-------|-------------|
| **T1** | `emorphed/app.py` | Beam Free/xhigh | Fix app init: move `_busy_gate`/`_exchange` creation before `UndoLog`, guard `_busy` with `getattr` |
| **T2** | `emorphed/app.py` | Beam Free/xhigh | Fix background verify cursor reset: use `_refill_keeping_place` or preserve cursor in `_verify_catalog_worker` |
| **T3** | `emorphed/app.py` | Beam Free/xhigh | Fix `_restore_midimap`: wait for read-back, push `MidimapChange` on failure, integrate with undo log |
| **T4** | `emorphed/app.py` | Beam Free/xhigh | Fix shutdown: wait for workers or add timeout in `close_when_idle` |
| **T5** | `emorphed/app.py` | Beam Free/xhigh | Fix backup fence: make `_backup_before_write` refuse write on failure (consistent with store/reset) |
| **T6** | `emorphed/app.py`, `tests/test_app.py` | Beam Free/xhigh | Tests for all above fixes |
| **T7** | `emorphed/midimapui.py`, `tests/test_midimapui.py` | Beam Free/xhigh | Verify cursor fix complete (row/col preservation in all paths) |
| **T8** | `emorphed/app.py`, `emorphed/demo.py`, `tests/test_protocol.py` | Beam Free/xhigh | Verify signed 14-bit writes complete; add signed-boundary tests |
| **T9** | `emorphed/edit.py`, `tests/test_midimapedit.py` | Beam Free/xhigh | Verify effect-type validation complete; add non-contiguous ID test |
| **T10** | `emorphed/app.py`, `tests/test_app.py` | Beam Free/xhigh | Verify backup fence consistency; add test |
| **T11** | `README.md`, `CLAUDE.md`, `TODO.md` | GLM-5.3-Flash-Free | Update docs per findings 9 |
| **T12** | Stash | Manual | Drop or inspect stash@{0} |

---

## INSTRUCTIONS FOR SUBAGENTS

1. **Each task is independent** - files don't overlap between T1-T5, T7-T10.
2. **Use Beam Free/xhigh** for code tasks, **GLM-5.3-Flash-Free** for docs (T11).
3. **Run verification after each task:**
   ```bash
   .venv/bin/python -m pytest tests/test_app.py -q -o addopts="" -p no:cacheprovider
   .venv/bin/ruff check
   .venv/bin/ruff format --check
   .venv/bin/mypy --strict emorphed emu tests
   ```
3. **Full suite at end:** `.venv/bin/python -m pytest tests/ -q`
4. **Do NOT commit or push** - leave changes staged.
5. **Report:** files touched, tests added/changed, verify tails, anything unfixed.

---

## QUESTIONS BEFORE STARTING

Before I dispatch subagents, I need your confirmation on:

1. **Stash handling:** Should I drop `stash@{0}` (WIP on vsl042) or apply it? It contains changes to `emorphed/app.py`, `emorphed/midimapui.py`, `emorphed/screens.py`, `emu/midimap.py`, `tests/test_midimapui.py` from a previous parallel-agent run.

2. **Shutdown fix approach (T4):** Two options:
   - (A) Add a timeout to `close_when_idle` and force-close after grace period
   - (B) Track active workers and wait for them in a loop with timeout
   - (C) Cancel workers on shutdown and wait briefly
   Which approach do you prefer?

3. **Backup fence (T5):** Should `_backup_before_write` raise an exception on failure (like store/reset) or return a bool and let caller decide? Current store/reset pattern: returns False and notifies.

4. **Stash (T12):** Drop it entirely, or do you want me to inspect first?

5. **Priority order:** Should I run all subagents in parallel, or do you want a specific sequence (e.g., T1 first since it's foundational)?

Please answer these questions and I'll dispatch the subagents immediately.