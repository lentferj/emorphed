<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  emorphed contributors
-->

# MidiQuest `.sqs` container notes

Structure only. No sample, identity string, bank name or patch name is
committed or reproduced here; the observations below come from reading the
user's own files in place.

## What it is

A MidiQuest bank container: a big-endian IFF-style file. The top level is a
`LIST` whose payload is a run of `FORM` chunks, each typed `BANK`. Forms are
padded to a word boundary between them. All sizes are 32-bit big-endian.

```
LIST <size> "    "          (top-level; type field is four spaces)
  FORM <size> BANK
    CHNL ...
    SHDR ...
    ...
  FORM <size> BANK
    ...
```

## Chunk vocabulary

Chunks observed inside a `FORM ... BANK`, in the order seen:

`CHNL, SHDR, FILE, TRAN, RECV, [AUDI,] XTRA, [BDEF, TDEF,] MPIN, MPOT, BODY`

Some files also carry `NAME`, `LNAM`, `COMM` and/or `FIND`. `AUDI`,
`BDEF` and `TDEF` are present on some forms and absent on others (they are
optional per form). `NAME`/`LNAM` appear on a minority of forms. `COMM` and
`FIND` appear only in a few files and look like a search/index scratchpad
rather than bank data.

Per-chunk roles observed (structural only):

- `CHNL` — small (8 bytes); channel/identity-ish header.
- `SHDR` — fixed 370 bytes; high-entropy payload (see below).
- `FILE` — 4 bytes.
- `TRAN` — variable; high-entropy payload.
- `RECV` — variable; high-entropy payload.
- `AUDI` — optional; small, high-entropy.
- `XTRA` — 96 bytes; carries the instrument's identity string in clear
  ASCII (for example the synth model name), plus MIDI-ish bookkeeping.
- `BDEF`, `TDEF` — optional; 2 or 14 bytes; near-zero entropy (index/
  definition tables).
- `MPIN`, `MPOT` — 26-32 bytes; clear ASCII MIDI port names.
- `BODY` — variable; the bank payload (see below).
- `NAME` — optional; short, low-entropy.
- `COMM`, `FIND`, `LNAM` — optional; index/scratchpad.

## Entropy

Measured over the 41 local `.sqs` files (read-only):

- `SHDR`: 7.09-7.28 bits/byte, consistently, across every form.
- `TRAN`: ~6.7 bits/byte; `RECV`: ~6.3; `AUDI`: ~6.4.
- `BODY`: populated forms measure up to ~5.9 bits/byte; empty slots are
  ~0 bits/byte (all zero).
- `XTRA`: ~1.7 bits/byte (identity string in clear plus padding).
- `BDEF`, `TDEF`, `COMM`, `FIND`, `LNAM`, `NAME`: near zero.

The `SHDR`/`BODY` payloads are therefore high-entropy: compressed and/or
obfuscated, **not** raw SysEx. No SysEx framing (`F0`...`F7`) is visible in
them.

## Where this was observed

- `~/Dokumente/SYNTHS/` (39 `.sqs` files across several instrument folders)
  and `~/Dokumente/Sound Quest/` (2 more), 41 total, read in place.
- These files are the user's own and are **not committed** to this
  repository. No sample, name or identity string is committed either.

## Scope (TODO item 7)

- **Container: documented** (this file).
- **`BODY` decode: remains open.** The high-entropy payload has not been
  decoded; no decoder ships in emorphed. Decoding it once would serve
  rxved, kwsed, p2ked, x5ded, nanosyned, ensqsqed and this project alike.
- Nothing in emorphed reads, writes or depends on `.sqs` files.