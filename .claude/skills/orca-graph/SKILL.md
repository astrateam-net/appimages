---
name: orca-graph
description: >-
  Answer any question about Orca SOURCE from a queryable code graph instead of grepping
  `.upstream/orcaide-v2`. Use it BEFORE Grep, Glob, or reading files in the fork — one
  `trace_path` call returns every caller, where grep needs a dozen passes and still misses
  renamed namespaces. Two indexed graphs: `orca-fork` (build tag + our patch series) and
  `orca-pristine` (the bare tag), so it also answers whether a symbol is ours or upstream's.
when_to_use: >-
  Whenever you are about to search the Orca fork. Triggers: "find where X is defined", "search
  the fork for", "grep for", "who calls X", "what calls into", "all usages/references of",
  "where is this handled", "what does X call", "is this wired up", "which stub is missing an
  RPC", "did upstream already implement this", "is this symbol ours or upstream's", "what would
  this patch touch", "enumerate every producer/writer/call site". Also when a claim needs the
  full set rather than the first hit — the contract requires enumerating every producer before
  concluding one does not exist, and grep silently under-reports. Sister skill `orca-wiki`
  covers upstream DOCS (how Orca is meant to work); this one covers CODE.
---

# Orca fork code graph (local codebase-memory-mcp index)

Local-only: binary in `mise.local.toml`, server in `.mcp.json`, both git-excluded. **Never cite the
graph from a committed file** — other clones and CI do not have it (`CLAUDE.md` §0 invariant 6).
The enumeration rules this exists to serve are in `orca-coder-patch-author`.

## Two graphs

| `project` | Source | What it is |
|---|---|---|
| **`orca-fork`** | `.upstream/orcaide-v2` | the build tag **+ the whole patch series** — what we ship |
| **`orca-pristine`** | `.upstream/orcaide-pristine` | the bare build tag, detached worktree off the fork |

Pass `project` on **every** call. Default to `orca-fork`; switch to `orca-pristine` the moment the
question is *"is this upstream's or ours?"*.

**The second graph is not redundancy.** The series touches a small fraction of the tree, so
`orca-fork` is overwhelmingly pristine upstream with our work invisibly mixed in — one graph cannot
tell you which is which. Both misreadings are live hazards: copying "how upstream does it" from a
pattern we invented, or assuming behavior is ours when it shipped upstream. CLAUDE.md §3/§4 already
require a pristine worktree off the real tag for exactly this reason; the second graph indexes what
that rule already prescribes.

| Symbol appears | Verdict |
|---|---|
| in both graphs | upstream's — safe to cite as reference |
| only in `orca-fork` | **ours** — a patch added it; never cite it as upstream behavior |
| in both, different shape | we modified it — `get_code_snippet` on both and compare |
| only in `orca-pristine` | a patch removed or renamed it |

When you only need the changed-file list, git is faster than either graph:
`git -C .upstream/orcaide-v2 diff --stat <tag>..HEAD`. Exported diffs live in
`apps/orca-coder/patches/`.

## Task → tool

Tool ids are `mcp__codebase-memory__<name>` and they are **deferred in this harness** — load them
before the first call: `ToolSearch("select:mcp__codebase-memory__trace_path,mcp__codebase-memory__search_graph,mcp__codebase-memory__query_graph,mcp__codebase-memory__get_code_snippet")`.
Every call takes `project`. Parameter names are snake_case (`name_pattern`, `file_pattern`,
`semantic_query`, `qn_pattern`); `trace_path` additionally requires `function_name`. The `--flag`
spellings below are the equivalent one-shot CLI form
(`mise exec -- codebase-memory-mcp cli <tool> --project … --<flag> …`).

| What you need | Call |
|---|---|
| Every caller of X (the "enumerate all producers" rule) | `trace_path` `direction: inbound` |
| What X fans out to | `trace_path` `direction: outbound`, depth 1–5 |
| The shared resolver behind several call sites | inbound trace, then find the common parent |
| Exact name unknown | `search_graph` with `name_pattern` regex |
| Concept known, name unknown | `search_graph --query "<words>"` — BM25 full-text, camelCase-aware |
| Read the body | `get_code_snippet` by qualified name |
| Blast radius of the current diff | `detect_changes` |
| Unwired stub / dead end | `query_graph`: `MATCH (f:Function) WHERE NOT EXISTS { (f)<-[:CALLS]-() } RETURN f.name, f.file_path` |
| Cross-reference `webContents.send` namespaces against `ALL_RPC_METHODS` | `search_graph` for both, then `query_graph` to intersect |
| Shape of an unfamiliar area | `get_architecture` |

Qualified names are `<project>.src.<path>.<name>`. Search first, then trace — on an ambiguous name
the tool lists candidates, and test doubles usually outnumber the real definition, so check whether
a hit is a `.test.ts` mock before building on it.

`query_graph` is a read-only openCypher subset: `MATCH`/`WHERE`/`WITH`/`UNWIND`/`UNION`/`CASE`,
variable-length paths `[*1..3]`, aggregates, regex `=~`, `EXISTS { }`. Anything outside it fails
loudly with `unsupported …` rather than returning a misleading empty result.

### Searching by meaning

`semantic_query` is **not a tool** — it is a parameter, `search_graph --semantic-query`, and the
binary exposes 14 tools without it. It takes an **ARRAY of keywords**, never a sentence, and answers
in a separate `semantic_results` field; the ordinary `results` array in the same response is
unranked and label-unfiltered junk when only `--semantic-query` was passed, so read the right field.

Scoring is per-keyword min-cosine: a hit must score against **every** keyword. Measured on
`orca-pristine`:

| Call | Outcome |
|---|---|
| `--semantic-query '["restore","scrollback","checkpoint"]'` | 0.98–0.97, top 5 all the right `pty-connection.ts` restore functions |
| `--semantic-query '["parse","file","uri","path"]'` (looking for `parseFileUriPathParts`) | 0.97 scores, every hit wrong |
| `--semantic-query '["parse file uri into path parts"]'` (a sentence — **misuse**) | 0.02–0.05, hits like `kotlin.Any.toString` |
| `--query "parse file uri path parts"` (BM25) | rank 1 is `parseFileUriPathParts`, then the rest of its file |

So: **for a named symbol or anything you can spell, use `--query`** (BM25, splits camelCase, boosts
Functions/Methods/Routes) or `--name-pattern`. Reach for `--semantic-query` only for a concept you
cannot name, pass 2–4 real keywords, and treat a high score as a lead — it happily returns confident
nonsense. `--limit` defaults to 200; check `has_more` before concluding a search found everything.

## ⚠️ What is NOT in the graph — read those files directly

- **`resources/linux/bin/orca-ide`** and **`resources/darwin/bin/orca`** — bash shims with no file
  extension, and the grammar is picked by extension, so they are skipped. `extra_extensions` cannot
  fix it (keys must start with a dot). `orca-ide` is the shim CLAUDE.md §2 calls the #1 trap in this
  app — **always open it with `Read`; never conclude anything about the launch contract from the
  graph.**
- **The fork's `docs/**`** — dropped by the fork's own `.gitignore`; the indexer applies gitignore
  patterns to its walk regardless of git tracking, and a `.cbmignore` negation cannot override that
  layer. Docs live in the **`orca-wiki`** skill. Clean split: graph = code, orca-wiki = docs.
- **`node_modules`** and media under `resources/` — excluded, correctly.

Verify current coverage rather than trusting any number written here:
`mise exec -- codebase-memory-mcp cli list_projects`.

## Staleness is the real hazard

Both graphs are snapshots. Patch authoring *edits the fork*, so `orca-fork` goes stale exactly when
you are relying on it. **Reindex after any edit under `.upstream/orcaide-v2`:**

```bash
mise run cbm-fork       # patched fork — after every edit / patch commit
mise run cbm-pristine   # pristine upstream — only after a VERSION bump
mise run cbm            # both
```

`cbm-pristine` takes the tag from `VERSION` in `apps/orca-coder/docker-bake.hcl` (single source of
truth), verifies it is a real published `stablyai/orca` tag before indexing — §3's guard — and
recreates the worktree only if the tag moved. Override with `ORCA_TAG=<tag> mise run cbm-pristine`.

## Evidence status — the guard that matters

`CALLS` edges are type-resolved rather than name-matched (Hybrid LSP covers TS/TSX/JSX, Orca's whole
stack), so a trace beats a grep. It is still **static reachability**. CLAUDE.md §0 invariant 7 — *"a path
existing in source is not evidence it is taken"* — applies unchanged: the graph yields **leads, not
proof**, exactly like the grep it replaces. Behavioral claims still need a test or a live check
(`orca-coder-patch-verify`).

Corollary the other way: an inbound trace returning more callers than the docs mention is a finding,
not a contradiction — that is the "enumerate every producer" rule doing its job.
