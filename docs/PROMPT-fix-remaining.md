<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — Fix remaining code review findings (T4-T12)

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `master`, commit `HEAD`).

## Remaining Tasks

| Task | Description | Priority |
|------|-------------|----------|
| **T4** | Shutdown race: Track active workers and wait for them with timeout in `close_when_idle` | HIGH |
| **T5** | Backup fence: `_backup_before_write` should notify + return False on failure | MEDIUM |
| **T6** | Tests for T3-T5 | HIGH |
| **T7** | Verify editor cursor fix complete | MEDIUM |
| **T8** | Verify signed 14-bit writes + add tests | MEDIUM |
| **T9** | Verify effect-type validation | MEDIUM |
| **T10** | Backup fence test | MEDIUM |
| **T11** | Documentation updates (README, CLAUDE.md, TODO.md) | LOW |
| **T12** | Clean up stash `stash@{0}` | LOW |

---

## Task Details

### T4: Shutdown Race Fix (`emorphed/app.py`)
**Problem:** Workers running at exit prevent `close_when_idle` from closing the bridge. The 0.25s grace window aborts the close entirely if any worker is active.

**Fix:** Track active workers (`_active_workers: set[int]`) and in `on_mount`/`close`:
- Add worker ID to set when spawning
- Remove when worker completes
- In `on_mount`/`close`, wait for `_active_workers` to empty with timeout (e.g., 5s)
- Force-close if timeout

**Files:** `emorphed/app.py`, `tests/test_app.py`

### T5: Backup Fence Consistency
**Problem:** `_backup_before_write` logs failure but returns without preventing the write. Store/reset correctly refuse.

**Fix:** In `_backup_before_write`, on failure: `self.notify_status(..., refused=True); return False`. Caller (`_apply_parameter_worker`, `_apply_channel_preset_worker`, `_write_midimap_name_worker`) must check return and abort.

**Files:** `emorphed/app.py`, `tests/test_app.py`

### T6: Tests for T3-T5
Add tests to `tests/test_app.py`:
- Shutdown waits for workers
- Backup fence refuses write on failure
- Reset/Store/Undo all respect gate
- Undo of midimap change works correctly

### T7: Editor Cursor Fix Verification
Verify cursor preservation is complete in `emorphed/midimapui.py`:
- `result()` success/failure branches
- `_nudge` (both choice and numeric)
- `action_edit_current` (choice picker, numeric prompt, text prompt)
- `action_filter`
- `update_params`
- `action_toggle_all_channels`

### T8: Signed 14-bit Writes
- Verify `write_parameter`/`send_midimap` accept `-0x2000..0x3FFF`
- Add test: `-0x2001` refused, `-0x2000` accepted
- Add test for signed pan/volume values

### T9: Effect-Type Validation
- Verify `MidimapEditor.allow` uses `mm.values_for(param)` for FX types
- Test non-contiguous IDs (FX A/B types have gaps)

### T10: Backup Fence Test
- Test that failed backup blocks parameter write
- Test that backup failure doesn't crash

### T11: Documentation Updates
- `README.md`: Fix "whole write path unverified" → distinguish parameter writes (verified) vs store (unverified)
- `CLAUDE.md:63-68`: Update "card's select bank is unresolved" → bank 3
- `TODO.md`: Update item 7 (resolved), item 6 (store unverified), item 3 (gap sweep added)
- `README.md:290`: Fix "title carries unstored marker" → marker moved to status line

### T12: Stash Cleanup
- Inspect `stash@{0}` (WIP on vsl042, ~755 lines)
- Decide: drop or apply relevant parts

---

## Dispatch Plan

| Agent | Tasks | Model | Files |
|-------|-------|-------|-------|
| A | T4, T5, T6 | Beam Free/xhigh | `emorphed/app.py`, `tests/test_app.py` |
| B | T7, T8, T9, T10 | Beam Free/xhigh | `emorphed/app.py`, `emorphed/midimapui.py`, `emorphed/edit.py`, `tests/test_app.py`, `tests/test_midimapui.py`, `tests/test_midimapedit.py`, `tests/test_protocol.py` |
| C | T11 | GLM-5.3-Flash-Free | `README.md`, `CLAUDE.md`, `TODO.md` |
| D | T12 | Manual | Stash cleanup |

---

## Instructions for Subagents

1. **Each task is independent** where possible
2. **Use Beam Free/xhigh** (`opencode-go/beam-free#xhigh`) for code tasks
3. **Use GLM-5.3-Flash-Free** (`opencode/glm-5.3-flash-free`) for docs
4. **Run verification after each task:**
   ```bash
   .venv/bin/python -m pytest tests/test_app.py -q -o addopts="" -p no:cacheprovider
   .venv/bin/ruff check
   .venv/bin/ruff format --check
   .venv/bin/mypy --strict emorphed emu tests
   ```
4. **Full suite at end:** `.venv/bin/python -m pytest tests/ -q`
5. **Do NOT commit or push** - leave changes staged
6. **Report:** files touched, tests added/changed, verify tails, anything unfixed

---

## Questions for You (Already Answered)

1. **Stash:** Apply it (already done)
2. **Shutdown (T4):** Track workers + wait (B)
3. **Backup fence (T5):** Notify + return False
4. **Priority:** Sequential T1 first, then T2-T5 parallel

---

Let me start by dispatching the subagents.