# Engineering Workflow — Codified Practices

Codified Aug 30. This is a standing reference, not a status update. Review it at the start of any significant work session.

It combines practices already working well (some established before Aug 30) with corrections identified from that session specifically. Items marked NEW were added Aug 30 and were not previously standing practice.

Condensed always-applied copy: `.cursor/rules/engineering-workflow.mdc`.

## 1. Before writing any fix or feature

**Verification checklists before commit/PR, not after.** Spec 2–4 each went through a numbered checklist (diff-stat, quoted test names, exact file output) before merge. This caught real problems every time it was used and is standard for every feature going forward, not just the four specs.

**Schema diffs before building extraction/migration scripts.** (Existing practice — keep.)

**Demand literal output, not paraphrase, when verifying a claim.** Ask for line-numbered `sed`/`view` output or raw diffs rather than a re-typed summary. A garbled paste was mistaken for a real bug earlier this week purely because it was a summary rather than the literal file; it was confirmed fine once the literal version was requested.

## 2. When a bug is found

**Confirm the reproduction with the cleanest possible input before writing it up or escalating.** A suspected brand-matching bug (Krystal) was nearly logged as a real defect; retesting with a clean typed query showed it worked correctly. The original failure was voice/transcription noise, not the bug it looked like.

**Immediately quantify the blast radius, not just the instance found.** When the phantom-record bug surfaced from two examples, the very next step was counting how many of the ~2M records shared that pattern (≈152,000). Do this every time a new bug class is found, before deciding how urgently to fix it.

**Retype voice queries as text input** to isolate Whisper/transcription error from real backend error before concluding which one you're looking at. This single step resolved two separate false leads (Krystal, Enlightened/Dannon).

## 3. Before any write to production data

**TEST_MODE / dry-run before every real write**, with explicit sign-off required before the real run. (Existing practice — keep; followed correctly for both the index creation and the modifier backfill.)

**Never run a destructive command (`docker rm`, etc.) against a container holding data without a verified backup first.** (Existing practice — keep.)

**Sample and manually review automated extraction output before trusting it at scale.** The two-round manual review of 200 real branded records — not just the aggregate error-rate number — is what actually caught the false-positive patterns. An aggregate accuracy number alone would have hidden them.

**NEW: adopt a staging copy of Qdrant/Mongo before real users exist**, separate from whatever a future production instance will be. Testing currently runs safely against the only instance that exists because there are no real users yet. That stops being safe once there are, and the habit is easier to build now than to retrofit later.

## 4. Decision-making discipline

**NEW: consequential, hard-to-reverse decisions get flagged in the moment but formally decided in a separate, calmer review** — not finalized in the middle of a late debugging session. This covers schema/tiering choices and scope calls like the `lactose_free` definition. The Aug 30 calls were reasonable, but making that a habit rather than a lucky outcome is the actual goal.

**NEW: keep a running decision log** — `DECISIONS.md` at the repo root, one line per consequential choice with a one-line rationale — separate from the roadmap. The roadmap describes current state and plans; it isn't built to answer "why did we decide X" six weeks later.

**Multi-AI review (GPT + Gemini + Claude synthesis) for significant architectural decisions.** (Existing practice — keep; the identity-resolution rework, whenever it's scheduled, is exactly the kind of decision this is for.)

## 5. Session and commit hygiene

**NEW: land isolated, independently-verified fixes** rather than committing while multiple interacting issues are still open in the same area. The phantom-record fix was committed cleanly on its own; the earlier settings bugs were similarly landed one at a time. Keep that pattern rather than batching unrelated in-progress fixes together.

**Commit frequently with verb-led, detailed messages; `git add -A` consistently.** (Existing practice — keep.)

**Propose commit grouping and messages for everything since the last push, then wait for approval before `git commit`.** Unpushed commits stay as-is; new work is additional isolated commits. Do not commit unprompted.

**Four-tier testing standard for any data/ranking/parsing logic change.** (Existing practice — keep.)

- Tier 1 — verify the specific bug
- Tier 2 — adjacent cases
- Tier 3 — promote to the pytest eval suite
- Tier 4 — test both voice and text paths for shared logic
