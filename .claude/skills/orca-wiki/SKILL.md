---
name: orca-wiki
description: Look up UPSTREAM Orca documentation (onorca.dev product guide + stablyai/orca in-repo design docs) in the local Miyo index labeled `orca-wiki`. Use when a question is about how Orca itself is meant to work — `orca serve` / headless spec, Remote Orca Servers & pairing, the worktree/tab/pane model, agents & sessions, the CLI, orchestration, automations, mobile, SSH — before inferring from source or writing an orca-coder patch. Also use to check whether a tile bug is a deliberate upstream design or a genuine gap.
---

# Orca upstream docs (local Miyo mirror)

orca-coder patches upstream Orca. **Read what upstream says the behavior should be before
concluding it is broken** — several "bugs" in the tile are documented, deliberate headless
omissions, and several of our hard-won findings are stated plainly in a spec we hadn't read.

Mirror lives at `/Volumes/Devops/Projects/orca-docs/`, indexed in Miyo under the folder label
**`orca-wiki`**. Paths are Miyo-relative (`orca-wiki/<…>.md`) — pass them to
`mcp__miyo__read_file`; the native `Read` tool cannot open them.

```
mcp__miyo__search(query: "<question>", folder_path: "orca-wiki", path: "<scope>", limit: 5)
mcp__miyo__read_file(file_path: "orca-wiki/<...>.md")
mcp__miyo__list_files(file_path: "orca-wiki/")
```

Two subtrees — always scope with `path`:

| `path` | What | Use for |
|---|---|---|
| `guide` | onorca.dev product docs | how Orca is meant to be USED — features, settings, workflows |
| `engineering` | stablyai/orca in-repo `docs/` + `skill-guides/` | how Orca is BUILT — design rationale, reference specs, agent automation |

## Start here for orca-coder questions

| Question | Page |
|---|---|
| What is `orca serve` supposed to do? ready-JSON contract, pairing `reason` codes, Xvfb/D-Bus, upgrade & rollback | `engineering/docs/reference/headless-linux-server.md` |
| Why does the web client act like a remote client? The two-role model our tile collapses | `guide/remote-servers.md` |
| Who owns an agent session across client/server | `engineering/docs/reference/remote-agent-session-host-authority.md` |
| Tabs / panes / leaves / worktrees vocabulary | `guide/model/*` |
| CLI flags & subcommands (`terminal create`, `orchestration`, `--environment`) | `guide/cli/reference.md`, `guide/cli/orchestration.md` |
| Driving Orca from an agent | `engineering/skill-guides/orca-cli.md`, `…/orchestration.md` |
| Agent session identity, hooks, transcripts, usage tracking | `guide/agents/*` (`hooks-memory`, `session-history`, `usage-tracking`) |

**The load-bearing one:** `guide/remote-servers.md` defines exactly two roles — a *server machine*
running `orca serve` that "owns the repos, worktrees, terminals, and agent processes", and a
*client machine* that "runs the Orca UI and connects" — and assumes they are different boxes ("Do
not use `127.0.0.1` unless the client is running on the same machine"). orca-coder collapses both
onto one host. That single fact explains most of the patch series; see `apps/orca-coder/CLAUDE.md` §1.

## Two guards (both cost real time already)

- **Docs describe the INTENDED design, not our deployment.** Everything there assumes two boxes and
  a desktop window. Read them for what upstream meant, then verify against our shape.
- **Docs can lag the shipped tag.** `headless-linux-server.md` claims modern builds auto-start Xvfb
  and that `dbus-run-session -- xvfb-run` "should not be needed"; our launch contract (CLAUDE.md §2)
  requires both and is live-verified. **A doc is never evidence about behavior at `v1.4.156` —
  source in `.upstream/orcaide-v2` and a live check are.** Docs narrow the search; they don't settle it.

## Querying well

Miyo is hybrid (dense + BM25, RRF-fused, literal-match boosted), so the usual failure is **recall,
not ranking** — if a query misses, reformulate rather than raising `limit`. Use Orca's own
vocabulary: worktree, pane, leaf, session, runtime environment, pairing offer, advertised endpoint,
hook status, provider session, hibernation, orchestration, Design Mode, ConPTY, OSC7.

Anti-patterns: searching without `folder_path: "orca-wiki"` (other indexes leak in); `WebFetch` to
onorca.dev or github.com/stablyai/orca when the mirror is local; reading files to "find" something
instead of searching first; searching `guide` for design rationale or `engineering` for usage.
