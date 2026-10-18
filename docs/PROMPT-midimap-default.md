<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# PROMPT — the DEL reset writes the real factory-default midimap (the "Dry" map)

You are working in **`/home/lentferj/git-repos/emorphed`** (branch `vsl042`).

**The correction.** `DEL` currently resets a midimap by copying `M00`
(`-defMIDIMap-`) over the target. That is wrong: **`M00` is a user midimap
like any other** (on the bench unit `M00` is named `A:RWrm B:-`). The real
factory-default parameter values are the unit's internal ("RAM") midimaps
**named `Dry`**. So the default must be **captured once from the unit, stored
in the application, and written by `DEL`** -- no more reading `M00`.

**Verified on the bench unit** (read-only, silent): midimaps **2 and 5-15**
are named `Dry`, and **midimap 2 is byte-identical to midimap 5**, i.e. the
`Dry` content is the stable factory default. `read_midimap(0)` is the user's
`A:RWrm B:-`.

## Authorisation (the coordinator approves one read-only capture)

Exactly **one** read-only capture against the attached unit:
`bridge.read_midimap(2)` (a `Dry` map), and possibly `read_midimap(5)` to
confirm it is identical. **Silent, no writes, no selection, no Bank
Select / Program Change.** Every other test stays synthetic (`DemoDevice`).
No other device traffic.

## Iron rules

1. **No hardware except that capture read.** `make test-hardware` is not run.
2. **Never invent a byte.** The default is the captured `Dry` words, not a
   guess. Cite the capture in the docstrings.
3. Targeted tests, coverage off: `.venv/bin/python -m pytest <file> -q
   -o addopts="" -p no:cacheprovider`. Then `.venv/bin/ruff check`,
   `.venv/bin/ruff format --check`, `.venv/bin/mypy --strict emorphed emu
   tests`. Ruff line length 79; mypy strict.
4. **Do not commit and never push.**
5. The reset stays in-fence: **confirm -> back up the target -> store ->
   read back**.

## The tasks

### D1 - a read-only capture tool (`tools/read_midimap.py`, new)

A small tool in the family's bench-tool style: connect (remembered port),
`read_midimap(--index)` (default 0), and print
- the 12-char name (`mm.name_of`), and
- the 360 words as a ready-to-paste Python tuple `DEFAULT_WORDS = (...)`.
Read-only; it must `--help`, and it must not write anything. A synthetic test
(`tests/test_midimap_bench.py` style) is welcome but optional.

### D2 - capture and embed (`emu/midimap.py`)

Run the tool for `--index 2` (a `Dry` map) and confirm the name is `Dry`;
confirm index 5 matches. Add to `emu/midimap.py`:

```python
#: The factory-default midimap's 360 words, captured from the unit's
#: internal ("RAM") midimap named ``Dry`` on 2026-10-18 (read_midimap(2);
#: indices 2 and 5-15 are the same map). ``DEL`` writes these values.
#: The twelve name characters are the unit's own ("Dry"), kept deliberately
#: -- see CLAUDE.md, "E-mu's content is not ours to redistribute".
DEFAULT_WORDS: tuple[int, ...] = (...,)
```

It must be exactly **360** ints in `0..0x3FFF`. Add a `__all__` entry.

### D3 - the reset writes the constant (`emorphed/app.py`)

In `_reset_midimap_worker` replace the `M00` read with
`default = list(mm.DEFAULT_WORDS)`; keep the backup-first fence, the store
(`send_midimap(index, default)`) and the read-back unchanged. The
confirmation text loses the `M00` mention:
`reset M{index:02d} to the factory default midimap? this erases the map
there`. Update the docstrings that name `-defMIDIMap-`/`M00` as the source.
`_finish_reset` is unchanged (it compares the read-back to `default`).

### D4 - tests

- `_reset_midimap_worker` sends exactly `mm.DEFAULT_WORDS` to the target
  (assert the stored frame's words equal the constant), and **never calls
  `read_midimap(0)`** for the default.
- `DEFAULT_WORDS` is 360 ints in range; its name is `Dry`.
- The editor and browser `DEL` flows still open a confirm and store once.

### D5 - docs

- `README.md`: the reset writes the application's captured factory default
  (the `Dry` map), not `M00`.
- `CLAUDE.md`: correct the store bullet (`M00` is not a default), and record
  the **rule-4 divergence**: a captured midimap name (`Dry`) is committed in
  `emu/midimap.py`, deliberately, so `DEL` produces the real factory map.
- `TODO.md` item 6: one line that the default is captured, not `M00`.

## Dispatch

| task | model | files |
|---|---|---|
| all | `opencode-go/beam-free#xhigh` | `tools/read_midimap.py`, `emu/midimap.py`, `emorphed/app.py`, `tests/`, `README.md`, `CLAUDE.md`, `TODO.md` |

Report: the captured name/word count, files touched, tests added, verify
tails, and any observation a human must bench-check.
