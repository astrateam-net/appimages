# RESOLVED — the sessions were never in the browser; the host froze its own snapshot

> **Status: closed 2026-07-27.** Fixed in patch `0011` (post-merge agent-status resolution).
> The original version of this document argued the tile persisted its session into browser
> `localStorage` and that this was the bug. **That premise was wrong**, and it is kept below only as
> a record of what misled the investigation.

**The report:** after a workspace restart, clicking an agent's tab in the tile opens a plain
terminal with no chat toggle. On the Mac desktop the same restart restores everything.

**The answer:** nothing was lost and nothing was stored in the browser. The host had all of it on
disk the whole time. Its in-memory session-tab snapshot froze at boot without agent status, and
upstream's snapshot merge then preserved that frozen row against every rebuild.

---

## 1. What is actually on the host — measured, not inferred

On `ceo/apricot-sheep-57`, after the restart that produced the report:

| What | Where | Measured |
|---|---|---|
| Agent conversations | `~/.claude/projects/*/` | 2.5 MB across 9 project dirs |
| Pane → session link | `~/.config/orca/agent-hooks/last-status.json` | 5 rows, each with `providerSession.id` + transcript path |
| Tabs / splits / layouts | `orca-data.json → workspaceSession` | 11 worktrees of tabs, 11 `unifiedTabs`, 21 layouts |
| The runtime's own view | `orca-ide worktree ps --json` | all 5 agents, with `state`, `agentType`, prompts, replies |

The live agent *processes* were genuinely gone — the LXC restart killed the PTY daemon. That is
upstream's documented behaviour (`orca-wiki/guide/model/session-restore.md`: the daemon dies with
the host, layout and scrollback still restore) and happens on the Mac after a reboot too. It is not
data loss and it is not this bug.

## 2. Why the browser was a dead end

`sanitizeWebRuntimeWorkspaceSession` (`src/renderer/src/web/web-workspace-session.ts`) is **pristine
upstream** and unconditionally reduces the persisted web session to four fields —
`activeRepoId`, `activeWorktreeId`, `browserUrlHistory`, `lastVisitedAtByWorktreeId`:

> *"paired web clients get live tabs from the host runtime. Persisting those remote handles in
> browser storage replays stale terminal/browser selectors after a new pairing or host restart."*

So an empty `localStorage` session is **the designed state**, not a symptom. The web client is
deliberately stateless and is fed by the host over `session.tabs`. Verified live in the tile: both
`orca.web.workspaceSession.v1` and the per-environment key were `{}` on every session field — as
intended. Clearing the Shared Server Access grants only forces a re-pair; it changes nothing here.

Patch `0001` is the door (auth + pairing delivery) and has no bearing on session visibility.

## 3. The measurement that closed it

The previous investigation left one question open: *does the surface still carry `agentStatus`?*
Answered by calling the RPC from the tile itself (`window.api.runtime.call`, no store access needed):

```js
await window.api.runtime.call({ method: 'session.tabs.listAll', params: null })
// → 19 terminal surfaces, 0 with agentStatus
```

and for the four panes that have hook rows, the surface carried the **exact** pane key those rows
use (`leafMatches: true` on all four) with live `ptyId`s attached. Host-side inputs all correct,
output empty ⇒ the break is hop 2, the host's own build.

*Technique worth reusing:* the host's `orca-ide` browser CLI can load `http://127.0.0.1:6799/web-index.html`
and `eval` in it, giving a real web client with no Coder auth and no browser needed.

## 4. Root cause

`mergeMobileSessionSnapshotTabs` dedupes by tab identity and keeps the **cached** tab, so a rebuild
that stamped `agentStatus` had it discarded. That merge is upstream's, and safe there — upstream's
headless builder pins only stable topology on those tabs. `0011` put a hook-derived, time-varying
field into a snapshot upstream's merge is entitled to pin.

The one path that replaced wholesale instead of merging was a `force: true` rebuild, whose sole
trigger is the hook **change** signal — which cannot fire on a host whose agents all exited before
the last restart:

```
23:47:53  last hook write to last-status.json
00:14:04  serve restarts (workspace restart)
00:15:03  snapshots built — frozen here
01:05     still 0 agentStatus on the wire
```

That is exactly the reported shape: fine while an agent was live, permanently broken after a
restart.

## 5. Fix

Resolve the field **after** the merge (`resolveSessionSurfaceAgentStatus`) rather than during the
build — at the consumer, without changing what upstream's merge means. Post-merge resolution also
repairs the cached tabs the merge preserved, so the first `listAll` after a restart heals the
snapshot with no hook required. Authoritative both ways, or a dead agent stays advertised.

Acceptance: `src/main/runtime/headless-agent-status-surface.test.ts` drives
`listAllMobileSessionTabs` against a cached statusless snapshot; both cases fail without the fix.

## 6. What the original document got right, and what it got wrong

Right: the host holds the hook rows and they survive a restart (§3.1); mirrored tabs carry no agent
attribution (§3.3); the desktop's session writer is renderer-only (§3.6); Manage Sessions is a stub
and is a **separate** bug (§3.7); the model picker is a **separate** bug (§3.8); the on-disk TTL is
not involved (§3.9).

Wrong, and it cost the most time: the title. "The tile persists its session in the browser" reads
the empty `localStorage` as loss when it is upstream's deliberate design, which pointed the whole
investigation at the client. The suspicion that `buildMirroredAgentStatusPatch` was deleting rows
(§4) was also misdirected — it deletes rows absent from the snapshot, and the snapshot never had
any.

Still open, unaffected by this fix:

- **Manage Sessions is a stub** (`web-preload-api.ts` hard-codes `listSessions: () => ({sessions: []})`),
  so the tile cannot see or kill a wedged session. Real loss of recovery.
- **The model picker does not self-populate.**
- ~~**Nothing re-opens the previously open worktrees**~~ — fixed as `0013`: the tile now reopens the
  workspace it was left in. The cause was not the missing `workspaceSession` fields this doc's
  neighbours measured, but a missing producer for `ui.lastActive*`; see
  [`web-client-workspace-restore`](../web-client-workspace-restore/).
