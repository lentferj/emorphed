<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors -->

# emorphed

A terminal browser for the **E-mu Morpheus** — its presets, hyperpresets
and midimaps, and the Z-plane machine's awkward habit of numbering
everything three different ways.

Sibling to [rxved](../rxved), [kwsed](../kwsed), [p2ked](../p2ked),
[x5ded](../x5ded), [nanosyned](../nanosyned) and
[ensqsqed](../ensqsqed), and it follows their conventions.

## Support this project

emorphed is free software and always will be. Nothing is behind a paywall, no
feature is withheld, and none of what follows changes that.

But if it has been useful — if it saved you an evening of mapping zones
by hand, or got a library onto a machine that had no way of reading it, or
**best of all, if it has your vintage instrument switched on and in use more often
than it was, and you are having more fun with it** — then please consider
supporting the work.

**Because here is what it has actually cost:**

- **Real machines on a real bench.** Much of what these tools know about these
  formats was measured on hardware rather than read anywhere, because for most
  of it there is nowhere to read it. That needs the machines — the instruments
  themselves — and it puts hours of wear on hardware that has been locked up and
  recovered more than once in the course of it. Some of these instruments were
  bought specifically to add and verify a format; the others were already here,
  because the person doing this is a vintage instrument enthusiast first and the
  projects exist because the instruments were in the room.
- **Dozens — realistically hundreds — of hours of human time.** Format
  reverse-engineering is slow: measure, be wrong, measure again. A single
  parameter law in this README can represent an evening at the bench.
- **AI assistance, which is a paid service**, used heavily throughout and not
  cheap at this volume.

**This is support, not a donation — and the distinction is a legal one, not a
turn of phrase.** The maintainer is based in Germany, where payments like these
are *not* `Spenden` in the tax sense: they count as **taxable income** for the
recipient and are **not tax-deductible** for the giver. So this section is
titled *Support*, deliberately, and no receipt for tax purposes can be issued.
(That is a statement of how it is handled here, not tax advice.)

If the project saved you the work, you can support it through
**[GitHub Sponsors](https://github.com/sponsors/lentferj)** — the *Sponsor*
button at the top of the repository. Payment is handled entirely by GitHub and
Stripe, so bank and tax details are never handed to the person paying.

**Support is not expected, and it is not the only currency.**

- **Bug reports** — ideally with the bank, preset or disk image that produced
  them. A tool's failures are usually specific to one file rather than
  general, and without that file they are very hard to reproduce.
- **Confirmations from hardware that is not on this bench**, which matters more
  here than for a single-machine tool. These tools write for whole *families*
  of instruments, and the bench holds only a subset. Whether a variant accepts
  what we write is genuinely unknown, and several notes say "on this unit" for
  that reason. A "loads fine here too", or a "no, mine refuses it", is worth a
  great deal.
- **Corrections to the reverse-engineering notes.** The wrong turns are
  recorded next to the findings in `docs/RESOLUTION_NOTES.md` — retractions
  included, because a finding that was withdrawn is as useful as one that
  stood. If any of it is wrong in a way that is still costing someone time,
  saying so improves the record.

---

---



## AI assistance & human authorship

emorphed was built by its human author together with AI assistance. The
**ideas, the project vision, and every feature** came from the human author;
AI assisted with **writing the code and analyzing the binary formats**.
Crucially, the **reverse engineering rests on hands-on human work** — all testing
and verification on real hardware, creating the reference images/banks on those
instruments (disk saves, SysEx probes), and aural A/B comparison of presets —
which is what makes the results correct.
Full account in [DISCLAIMER.md](DISCLAIMER.md).

---
## ⚠️ Use at your own risk — back up first

 is provided **as is, with absolutely no warranty and no liability**
for data loss or **hardware damage**. You assume all risk. Full terms:
[DISCLAIMER.md](DISCLAIMER.md).

Before you use this software, **make good, current backups of all your files** —
and of any existing banks on your instrument and storage media. These tools can
write to hardware and storage media; a mistake, a bug, or untested output could
overwrite or corrupt data, or be rejected by hardware. Always test on a spare
unit or emulator **before** connecting irreplaceable equipment.

---

## What makes this one different

**The manual is the specification.** E-mu printed all twenty-six pages of
the MIDI spec as a chapter of the Operation Manual instead of making you
write away for it, which is the opposite of the SQ-R next door.

**One message gets every name.** `Preset List Request` returns all of
them, in the order the instrument shows them. None of the sibling
instruments can do that.

**Data is fourteen bits wide.** Every value is two MIDI bytes, low seven
first, signed two's complement sign-extended to bit 13 — *whatever* the
parameter's documented range. Read a dump a byte at a time and you get
plausible halves of numbers.

**Bank Select is Controller 32**, with Controller 0 held at zero:
`Bn 00 00 20 bb Cn pp`. That is the opposite way round from
[nanosyned](../nanosyned)'s instrument, which ignores 32 entirely.

**A preset index is not a program number.** The index is what SysEx
addresses; a Program Map decides what program change reaches it. The code
keeps them apart and says so when it assumes.

## Memory

| region | indices | n | |
|---|---|---|---|
| Presets RAM | 0–127 | 128 | writable |
| Presets ROM | 128–255 | 128 | |
| Presets card | 256–383 | 128 | card only |
| Hyperpresets RAM | 0–127 | 128 | writable |
| Hyperpresets card | 128–255 | 128 | card only |
| Midimaps RAM | 0–15 | 16 | writable |
| Midimaps card | 16–31 | 16 | card only |

## Install

Two checkouts, side by side — this project and the shared library it uses:

```sh
git clone https://github.com/lentferj/vinsynlib.git ../vinsynlib
python3 -m venv .venv
.venv/bin/pip install --no-deps -e ../vinsynlib
.venv/bin/pip install -e .
```

Needs Python 3.11+, `python-rtmidi` and `textual`, plus **vinsynlib** — the
shared base of this family of terminal instrument tools: the settings cache,
the keymap and legend, the command line and the port listing. It is **not on
PyPI**, so it is installed from the sibling checkout above, and installed
*first* so that the second command finds the requirement already satisfied.

`--no-deps` on the first install because vinsynlib's dependencies are this
project's too, and a second copy of `textual` in the same venv is a version
skew to diagnose somewhere else. With `uv`, `uv sync` takes the path from
`[tool.uv.sources]` in `pyproject.toml`, so the checkout only has to exist
and neither `pip` line is needed.

## Running it

```
python -m emorphed.cli regions          # the memory map
python -m emorphed.cli --demo names     # every name, in one exchange
python -m emorphed.cli read dump.syx    # read a .syx, verify checksums
python -m emorphed.cli status           # ask the unit who it is
```

`read` checks every dump's checksum, so it can tell you a file is
*damaged* rather than only that it is the wrong length.

## Development checks

A no-AI quality gate. Install the dev tools, then run everything:

```
uv sync
make check          # or: uv run make check
```

`make check` runs each stage in sequence and stops at the first failure:

| target | what it does |
|---|---|
| `make lint` | `ruff check` + `ruff format --check` — lint (E, F, I, B, S, SIM, UP, C4, PL, RUF, C901) and formatting |
| `make format` | `ruff format` — apply formatting manually |
| `make typecheck` | `mypy --strict emorphed emu tests` |
| `make test` | `pytest` with coverage (`--cov-report=term-missing`, no threshold) |
| `make audit` | `pip-audit`, `vulture`, `deptry`, `detect-secrets audit` |

`pre-commit install` (once) runs ruff (lint + format), mypy and detect-secrets
on every commit. shellcheck/shfmt are omitted — this repo has no shell
scripts.

The code is clean under every gate: ruff (lint + format), mypy strict, and the
audit tools all pass without suppressions. `rtmidi` and `nano` ship no type
stubs, so mypy is told to ignore those two imports. `setuptools>=83` is pinned
as a dev dependency to keep `pip-audit` clear of the build tool's known
vulnerabilities.

## Licence

GPL-2.0-or-later. AI assistance was used; see `DISCLAIMER.md`.
