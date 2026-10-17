<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — midimap channels as named presets

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).
The midimap editor shows each channel's routing as raw numbers. The user
wants the **preset** a channel selects to be a first-class thing:

1. the channel summary and the channel's detail rows show the **preset name**
   (`003 - Pad:BallHyvs`);
2. `+`/`-` on a collapsed channel **steps the preset**, rolling into the next
   bank at a boundary (`Bank 1 / Preset 127` + `+` → `Bank 2 / Preset 0`);
3. `Enter` on a channel's **Ch. Program** or **Ch. Bank** cell opens a
   **preset picker** (banks × slots, favourite-aware) that sets **both** cells
   in one go — the rxved/p2ked pattern (`../rxved/rxved/screens.py:968`
   `PatchPickerScreen`).

Read `CLAUDE.md` first. `../vinsynlib`, `../rxved`, `../p2ked` are read-only.

## The model (get this exactly right)

Channel `n` (1..16) occupies offsets `12 + (n-1)*20 .. +19`
(`emu/midimap.py` `_CHANNEL_BLOCK`): **Ch. Program** at `base+0` (0-127, the
slot number), **Ch. Bank** at `base+1` (0-4). The bank word names a region:

| bank word | `_PROGRAM_BANKS` (emu/midimap.py) | region id (emu/banks.py) |
|---|---|---|
| 0 | RAM Presets | `P-RAM` |
| 1 | ROM Presets | `P-ROM` |
| 2 | RAM Hypers | `H-RAM` |
| 3 | Card Presets | `P-CARD` |
| 4 | Card Hypers | `H-CARD` |

A channel's **combined preset index** is `bank * 128 + number` (0..639). A
name is `catalog.display_name(region_id, number)`; the catalog's `UNNAMED`
placeholder (`--`) means the slot has no name — then show just the number.

## Iron rules

1. **No hardware.** No MIDI ports, no `--hardware`, no `make test-hardware`.
2. **Never invent a byte, size, name or page.** Everything traces to
   `emu/midimap.py`, `emu/banks.py`, `emu/catalog.py`.
3. Targeted tests, coverage off: `.venv/bin/python -m pytest <file> -q
   -o addopts="" -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.**
5. The screen owns no worker and sends nothing itself — every change goes out
   through a callback. A pair of words is written atomically by **one** worker
   (the exchange admits one write at a time).
6. Use the free model named for your task; report the visible tail of each
   verify command.

## The frozen interface (tasks B and C must agree)

`MidimapEditScreen` gains three optional callbacks:

- `name_for(bank: int, number: int) -> str` — the preset name, or `""`.
- `on_channel(channel: int, bank: int, number: int) -> None` — write the
  channel's bank+program (used by `+`/`-` on a summary).
- `on_pick(channel: int) -> None` — open the preset picker for that channel.

`emu/midimap.py` gains the pure helpers below (task A). `emorphed/screens.py`
gains `PresetPickerScreen` (task D).

---

# A · Pure channel-preset helpers (`emu/midimap.py`, `tests/test_midimap.py`)

Model: **`opencode/deepseek-v4.1-flash-free#high`** (data precision).

Add, with manual/table citations in the docstrings:

- `CHANNEL_BANKS: tuple[str, ...]` — the bank-word → region-id table above.
- `channel_program_offset(channel: int) -> int` and
  `channel_bank_offset(channel: int) -> int` — `base+0` / `base+1`, refusing a
  channel outside 1..16 with a message.
- `channel_bank(bank: int) -> str` — the region id for a bank word 0..4;
  refuse out of range.
- `step_channel_preset(bank: int, number: int, delta: int) -> tuple[int, int]`
  — the combined index `bank*128+number` clamped to `0..639`, recombined into
  `(bank, number)`. `+` at `bank 1 / 127` gives `(2, 0)`; `-` at `bank 2 / 0`
  gives `(1, 127)`; the ends clamp (no wrap past `bank 4 / 127` or below
  `bank 0 / 0`). Refuse a bank outside 0..4 or a number outside 0..127.
- `channel_preset_name(...)` is **not** here — the screen gets it via the
  `name_for` callback (the catalog is the app's).

Tests: the offset helpers for channels 1 and 16; the bank table; the two
rollover examples from the user; the four clamps; the refusals.

Verify: `pytest tests/test_midimap.py`; ruff; format; mypy.

---

# D · `PresetPickerScreen` (`emorphed/screens.py`, `tests/test_presets.py` new)

Model: **`opencode-go/beam-free#xhigh`** (a UI port).

Port rxved's `PatchPickerScreen` shape (`../rxved/rxved/screens.py:968-1160`)
into emorphed, adapted:

- Two panes: **banks** (the five preset-bearing regions, by label) over
  **slots** (that bank's names from the catalog). `tab` switches panes; arrows
  move; `⏎` confirms; `escape`/`q` cancel.
- `v` cycles the slot pane through the browser's three views — **all slots /
  this bank's favourites / every favourite** — so a person who marked
  favourites in the browser can pick from them here. The store is passed in
  (emorphed's `emu.favorites.Favorites`).
- Return `(bank_word: int, number: int) | None` — the **midimap bank word**,
  not a catalog key, so the caller can write the two words directly.
- `DEFAULT_CSS` must scale (`width: 90%`, not a fixed cell count — see the
  editor modal).
- Compose it from the **app's** catalog and favourites, passed in; the screen
  reads nothing itself.

Tests (`tests/test_presets.py`): the bank list is the five regions in order;
`v` cycles the three views; confirm returns `(bank, number)`; cancel returns
`None`; a favourite-only view lists only the marked slots; the modal scales.

Verify: `pytest tests/test_presets.py`; ruff; format; mypy.

---

# B · The editor shows and steps the preset (`emorphed/midimapui.py`, `tests/test_midimapui.py`)

Model: **`opencode/glm-5.3-flash-free#high`** (small, careful UI edits).

Wait for A (the helpers) — import them from `emu.midimap`.

- New keyword params: `name_for`, `on_channel`, `on_pick` (the frozen
  interface above), all optional.
- **Channel summary value** (`_display_value("ch{n}")`): lead with the preset
  — `f"{number:03d} - {name}"` when `name_for(bank, number)` is non-empty,
  else `f"{number:03d}"` — then the existing `vol … · pan … · bus … · N
  switches on` tail.
- **Detail rows:** for `base+0` (Ch. Program) show the same
  `{number:03d} - {name}` in the value cell; `base+1` (Ch. Bank) keeps the
  bank label (`mm.spell` already names it).
- **`+`/`-` on a `ch{n}` summary** (`_nudge`): instead of the current "expand
  with enter" message, compute `step_channel_preset(bank, number, +1/-1)` from
  the channel's two words, set both `_values`, and call
  `on_channel(n, bank, number)`. (`on_channel` is None in a test that does not
  care — then just set the words and refresh.)
- **`Enter` on a `base+0`/`base+1` row** (`action_edit_current`): call
  `on_pick(n)` instead of the numeric/choice prompt. Other rows unchanged.

Tests: the summary shows `003 - <name>`; the Program row shows it; `+` at
`bank 1 / 127` produces `(2, 0)` and calls `on_channel`; `-` at bank 2/0 →
`(1, 127)`; the ends clamp; Enter on Program/Bank calls `on_pick`; Enter on a
summary still expands.

Verify: `pytest tests/test_midimapui.py`; ruff; format; mypy.

---

# C · The app writes a channel's preset as a pair (`emorphed/app.py`, `tests/test_app.py`)

Model: **`opencode-go/beam-free#max`** (the hardest: one exchange, one undo).

- `_apply_channel_preset(channel, bank, number, *, record: bool = True) -> bool`
  — gate **both** offsets (`_editor.allow` for `base+1` = bank and `base+0` =
  number) before anything; refuse on the first refusal (nothing sent); then
  acquire `_exchange` **once** and run **one** worker that writes the bank
  word then the program word, reading each back. Report agreement; only an
  agreed pair is logged/updated (`record` gates the log, as `_apply_parameter`
  does). Return `True` when it dispatched, `False` on any refusal (so the undo
  push-back path in `_undo_master_edits` still works).
- A new record kind `ChannelPresetChange(channel, old_bank, old_number,
  old_program_bank, ..., new_*)` — actually: `(channel, old_bank, old_number)`
  is enough for undo (restore that pair). Push **one** record for the pair.
  `_undo_master_edits` restores it with
  `_apply_channel_preset(channel, old_bank, old_number, record=False)`.
- Wire the screen in `_open_midimap_screen`:
  - `name_for=lambda bank, number: self.catalog.display_name(mm.channel_bank(bank), number)`;
  - `on_channel=self._apply_channel_preset` (the summary `+`/`-` path);
  - `on_pick=self._open_preset_picker`.
- `_open_preset_picker(channel)`: build the banks from the catalog +
  `self.favorites`, push `PresetPickerScreen` (task D), and on a non-`None`
  result call `_apply_channel_preset(channel, bank, number)`.

Tests: `+` on a summary writes **exactly two** parameter writes (bank then
program) and no more; a locked gate sends nothing and refuses; the read-back
disagreement is reported and not logged; one `z` restores both words; the
picker confirm path writes the chosen pair.

Verify: `pytest tests/test_app.py`; ruff; format; mypy.

---

# E · Docs (`README.md`, `CLAUDE.md`, `TODO.md`)

Model: **`opencode/nemotron-3.5-lightning-free`** (short prose), after B/C.

One paragraph in README's "Editing a midimap": a channel's selected preset is
shown by name (`003 - Pad:BallHyvs`); `+`/`-` on a channel summary steps the
preset, rolling into the next bank at the end; Enter on the channel's Program
or Bank cell opens the preset picker (favourite-aware). A sentence in
CLAUDE.md if it describes channel rows.

---

# Dispatch

| task | model | files |
|---|---|---|
| A | deepseek-v4.1-flash-free#high | `emu/midimap.py`, `tests/test_midimap.py` |
| D | beam-free#xhigh | `emorphed/screens.py`, `tests/test_presets.py` |
| B | glm-5.3-flash-free#high | `emorphed/midimapui.py`, `tests/test_midimapui.py` |
| C | beam-free#max | `emorphed/app.py`, `tests/test_app.py` |
| E | nemotron-3.5-lightning-free | `README.md`, `CLAUDE.md`, `TODO.md` |

A and D run in parallel (disjoint files). B and C run in parallel after A/D
(disjoint files, the frozen interface). E last.
