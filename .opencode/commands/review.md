---
description: Review a branch or change target for bugs and missing tests
agent: general
model: opencode-go/mimo-v2.6-flash
subagent: true
---

Review the target "$ARGUMENTS" for **correctness bugs first**, then missing
tests, then style drift. "branch" (or an empty target) means the current
branch: inspect `git log --oneline master..HEAD` and `git diff master..HEAD`,
and read the changed files in full rather than trusting the diff alone.

Rules for this review:

1. Report findings in priority order: **correctness bugs**, then **missing or
   weak tests**, then **docs/ledger contradictions**, then minor style.
2. For every finding give the exact `file:line`, the evidence (quote the
   code), and why it is wrong. No finding without a location.
3. Do **not** run the hardware suite, open MIDI ports, or run
   `make test-hardware`. This repository has no attached unit.
4. Verify claims against the code and the sibling references
   (`../rxved`, `../p2ked`, `../vinsynlib`); if a suspected bug is actually
   handled, say so and drop it.
5. Do not modify any file. Produce a written review only, ending with a short
   "what I could not verify" list.
