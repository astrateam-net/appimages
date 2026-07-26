---
name: orca-coder-patch-audit
description: >-
  Before fixing any orca-coder bug or Orca web-tile stub, decide WHERE the change belongs — which
  existing patch already owns those symbols, or whether it earns a new number. Also audits the whole
  series against upstream and against itself, and decides keep/shrink/merge/drop on a VERSION bump.
  Run FIRST, before orca-coder-patch-author. `git apply` succeeding is not the acceptance criterion —
  a patch can apply cleanly and still be redundant, duplicated or already shipped upstream.
when_to_use: >-
  After diagnosis names the symbols you will change and before writing code; on a VERSION bump before
  refreshing patches; periodically to find coupled or stale patches.
paths:
  - apps/orca-coder/**
  - .upstream/orcaide-v2/**
---

# orca-coder — audit, and decide where a change belongs

## Where this sits in the chain

```
orca-coder-patch-audit  →  orca-coder-patch-author  →  -verify  →  -ship
   (decide WHERE)             (write it THERE)
```

**This skill runs first.** The failure it exists to prevent: a floating-workspace problem is found
and fixed as one patch; later a second floating-workspace problem is found and becomes a *new*
patch, because no agent remembered the first. Now two patches edit the same symbols — the very
coupling this skill reports as a defect, manufactured on purpose. Auditing after the fact only
tells you it already happened.

On a VERSION bump it runs first too: decide what each patch should still be, *then* refresh.
Rebasing until `git apply` passes is not a decision — it is skipping the decision.

## Step 0 — after diagnosis, before writing anything

**Order matters: diagnose first.** Placement is answered with the SYMBOL list from diagnosis in
hand. Asked earlier — from the capability's name alone — it cannot reach a verdict, and answering
"new patch" from a name is precisely how a second floating-workspace fix became its own patch
instead of extending the first.

```bash
cd "$(git rev-parse --show-toplevel)"
MAP=/tmp/attr.$$.json      # per-run: a failed self-check exits BEFORE writing, so a fixed
                           # path would silently feed the previous run's map to locate.py
mise run cbm-fork &&                                    # standing rule: reindex after ANY fork edit
mise run patch-map --self-check --out "$MAP" &&         # `&&` — never read a map whose check failed
python3 .claude/skills/orca-coder-patch-audit/locate.py --map "$MAP" \
  --symbols 'src/path/a.ts:symA,symB' --files 'src/path/a.ts,src/path/b.ts' --area 'capability words'
```

Arguments are **comma-separated single strings**, not space-separated lists. `patch-map` runs
`attribute.py` (symbol→patch map; needs the local graph); if the fork has uncommitted work it
refuses — commit or stash first, or run the script directly with `--allow-dirty` and distrust the
symbol tier.

**Act on `verdict.decision` — this is the skill's decision, not an escalation:**

| `decision` | What you do |
|---|---|
| `EXTEND_EXISTING` | **No new patch number.** Commit into the fork, restack *that* patch's boundary, re-export the series. Record in the CHANGELOG which patch you extended |
| `NEW_PATCH_BUT_CHECK` | Read the patches in `read_first`. Take a new number only if none covers this capability — and the CHANGELOG entry must name the ones you considered and say why this is not an extension |
| `NEW_PATCH` | New number, normal author flow |
| `CANNOT_DECIDE` | Two causes, read which. `ambiguous_symbols` → a bare name resolves to several files (`handler` is five different functions), so re-run with `file:symbol` for each. Otherwise nothing you passed is in the map → check the paths are repo-relative as they appear in the patches. **Never proceed on either** |

A `weak_input` field means you passed no symbols, so the verdict rests on files and area words and
**cannot** reach `EXTEND_EXISTING`. Finish diagnosis and re-run.

### Without the local index — the answer is still committed

`mise run patch-map` and the graphs exist on one machine (git-excluded config). On any other clone
the same question is answerable from the exported diffs alone, which is where ownership actually
lives. **Missing tooling never licenses skipping placement.**

```bash
# which patches own a symbol (grep the added/removed lines, not just the file headers)
grep -l '<symbol>' apps/orca-coder/patches/*.patch
# which patches touch a file — the file tier, verbatim
grep -l '^+++ b/<path>$' apps/orca-coder/patches/*.patch
```

Weaker than the graph in one respect only: it matches text, so a symbol merely *mentioned* in a
patch reads as owned. Confirm by opening the hunk. Everything else — the decision rule, the
CHANGELOG obligation — is unchanged.

### Symbols decide; files inform

Measured on this series: `web-preload-api.ts` is touched by **11 of 13** patches, `orca-runtime.ts`
by 5, `mobile-rpc-allowlist.test.ts` by 6. The web client is one hub file behind one hub factory,
so "shares a file" is true of nearly every change and means nothing. An earlier version of this
rule counted files as ownership, and every web-tile fix came back `EXTEND_EXISTING → 0001` — the
trusted-proxy security patch — chosen out of an 11-way tie by filename order. Obeying that would
have folded the series into its most review-sensitive patch and destroyed bisection.

So: a shared **symbol** means one capability is being split in two, and decides. A shared **file**
is normal and produces a reading list only. Patch size never enters into it — size is how much
work restacking costs, not whether splitting a capability is correct.

## Full audit — on a bump, or periodically

```bash
mise run patch-map --self-check --out /tmp/attr.json
python3 .claude/skills/orca-coder-patch-audit/audit.py --map /tmp/attr.json --out /tmp/findings.json
```

`--self-check` validates every attribution against git and **exits non-zero** on contradiction.
Never read findings from a run whose self-check did not pass. On a bump pass the new tag:
`mise run patch-map --tag <new> --self-check`.

### Act on each finding

| Key | Signal | Action |
|---|---|---|
| `stale_exports` | Applies but is not byte-identical to what its boundary produces (usually stale hunk offsets; `git apply` re-anchors, so CI never notices) | Re-export that patch from the fork. Mechanical, do it |
| `patch_overlap` | Every pair sharing symbols or files, ranked. **Over-reported on purpose** | Work top-down. Shared *symbols* + same subject area → one capability split in two: merge, or make the later extend the earlier. Shared *files* only → leave it, that is normal (same reason files do not decide in step 0) |
| `coupled_patches` | One symbol edited by several patches | Ordering is load-bearing. Record it, and never restack one of them without re-verifying the others |
| `thin_patches` | Owns very few symbols | Not a verdict — size never decides placement. It is a prompt: look up this patch in `patch_overlap`, and fold it in only if it shares SYMBOLS with a neighbour in the same capability |
| `ours_vs_upstream` | `genuinely_new` = symbols only we have | These carry the reinvention risk. Review them before anything else |
| `upstream_candidates` | Upstream functions sharing ≥2 name tokens with one of ours | Open both. Upstream already does it → shrink the patch to reuse. This is the highest-value finding on a bump |

### Verdict per patch on a bump

The findings above are lexical and structural — they say where to look. The verdict itself is
**behavioural**, and the only trustworthy instrument is the patch's `Acceptance` test from its
CHANGELOG entry, run against the new pristine tag.

Apply in order; the first that matches wins:

1. **Drop — prove it, do not infer it.** Build a pristine worktree at the NEW tag, apply **no
   patches**, and run this patch's `Acceptance` test plus its `Symptom` repro:
   ```bash
   git -C <fork> worktree add --detach /tmp/probe <newtag>
   # install deps in /tmp/probe, then run the patch's acceptance test there
   ```
   Test passes / symptom absent on bare upstream → upstream shipped it → **drop** (renumber per
   `orca-coder-patch-author`, and keep the CHANGELOG entry retitled with a `**Dropped:**` line
   recording exactly this probe). `upstream_candidates` is a *hint* that this probe is worth
   running; it is never the proof.
2. **Shrink** — the probe fails, but `upstream_candidates` shows upstream now has a mechanism ours
   reimplements. Rewrite to call upstream's, keep only the genuinely missing part, and re-run the
   acceptance test. Delete one hunk-group at a time and re-run: anything removable with the test
   still green was dead weight.
3. **Merge** — `patch_overlap` shows shared **symbols** in one capability **and** neither patch's
   acceptance test passes without the other. If each passes alone they are two capabilities that
   happen to share a file; leave them. Procedure in `orca-coder-patch-author`.
4. **Keep** — and re-export if `stale_exports` lists it.

**Order the work by what upstream actually moved**, which costs nothing to compute:

```bash
git -C <fork> diff <oldtag>..<newtag> --stat -- $(grep -h '^+++ b/' apps/orca-coder/patches/*.patch \
  | sed 's|^+++ b/||' | sort -u | tr '\n' ' ')
```

Patches whose files upstream did not touch are almost certainly `keep`; spend the probe budget on
the ones it did.

**A patch with no `Acceptance` entry cannot be dropped, shrunk or merged** — there is nothing to
run, so every verdict would be a guess. Recompute which patches are in that state instead of
trusting a list here:

```bash
for p in apps/orca-coder/patches/*.patch; do
  c=$(grep '^+++ b/' "$p" | grep -cE '\.test\.(ts|tsx)$')
  [ "$c" -eq 0 ] && echo "no acceptance test: $(basename "$p")"
done
```

Measured today it names `0001`, `0004`, `0011`, `0012` — and `0001` is the trusted-proxy patch that
carries the loopback trust model, i.e. the one where an untested behavioural claim is most
expensive. Give such a patch a test **before** deciding anything about it; that is cheaper than
being wrong about it on a bump.

Every verdict then goes through `orca-coder-patch-verify` before shipping — never on the audit's
word alone.

## What does not work here — silence is not absence

- **`cross_patch_clones` is near-useless on this series.** `SIMILAR_TO` (MinHash near-clone)
  reached exactly **one** of our attributed symbols: most of what we touch are upstream functions
  whose bodies stay upstream, and our own additions are small. An empty result says nothing about
  duplication — check `similar_to_coverage`, which is emitted so this cannot be mistaken for a
  clean bill. Use `patch_overlap` for the intra-series question.
- **Lens A uses BM25 deliberately, not the vector path.** `semantic_query` is a *parameter*
  (`search_graph --semantic-query`), not a tool, and it takes an ARRAY of keywords. For the question
  lens A asks — "does upstream already have something like this NAMED symbol?" — BM25 (`--query`)
  ranks the right symbol first while per-keyword min-cosine returns high-scoring wrong hits. That is
  a fit judgement, not a claim that vector search is broken; see the measurements in `orca-graph`.
- **No tuned thresholds anywhere.** `patch_overlap` reports every pair with any overlap and ranks
  it. An earlier version filtered by a similarity ratio — choosing the constant that yields a
  small tidy result is fitting the audit to pass rather than measuring. If you add a cutoff you
  are hiding findings; rank instead.

## Evidence status

Findings are **leads**. Name matching, BM25 and static reachability tell you where to look; they
never settle whether a patch is still needed. CLAUDE.md §0 invariant 7 holds — *"a path existing in source is
not evidence it is taken"*. `locate.py`'s verdict is different in kind: it is a decision about
*where code goes*, derived from exact ownership, and you act on it directly.
