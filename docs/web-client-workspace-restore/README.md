# NEXT UP — nothing on a headless host records which worktrees were open

> **Status: parked 2026-07-27, not diagnosed.** Raised while fixing the agent-status freeze
> ([`web-client-session-persistence`](../web-client-session-persistence/)) and deliberately kept out
> of that patch — it is a separate capability and would have bundled two into `0011`.
>
> Everything below §2 is **measurement**. §3 is a lead, not a conclusion. Per CLAUDE.md §0
> invariant 1, placement is decided from a symbol list produced by diagnosis, so **no patch number
> is claimed here** — run `orca-coder-patch-audit` step 0 when the diagnosis is real.

## 1. Symptom

The Mac desktop reopens the previous session on launch — worktrees, tabs, splits, focused tab.
Upstream documents this as a product feature (`orca-wiki/guide/model/session-restore.md`).

The Coder tile does not. After a workspace restart it lands on **"Select a workspace from the
sidebar to begin"** with an empty main pane, even though the sidebar lists every worktree. You have
to click your way back to where you were.

This is separate from the agent-status freeze fixed in `0011`. That one was "the pane opens but has
no chat toggle"; this one is "nothing opens at all".

## 2. What was measured (2026-07-27, `ceo/apricot-sheep-57` vs this Mac)

Comparing `workspaceSession` in `orca-data.json` on both hosts:

| Key | Mac desktop | `orca serve` host |
|---|---|---|
| `activeWorktreeIdsOnShutdown` | present — 4 worktree ids | **absent** |
| `activeWorkspaceKey` | present | **absent** |
| `sleepingAgentSessionsByPaneKey` | present | **absent** |
| `lastVisitedAtByWorktreeId` | present | **absent** |
| `tabsByWorktree` / `unifiedTabs` / `terminalLayoutsByTabId` | present | **present** (11 / 11 / 21) |

So the host persists tab *topology* perfectly well — the runtime writes it as `session.tabs.*` RPCs
mutate it — but nothing on that host ever writes the fields that say **which worktrees were open**.

The restore consumer is `src/renderer/src/store/slices/terminals.ts:3163`:

```js
// activeWorktreeIdsOnShutdown is authoritative when present; persisted tab/layout PTY IDs
// are only wake hints, not a full active-workspace list.
const shutdownIds = session.activeWorktreeIdsOnShutdown ?? <derive from tabsByWorktree>
```

and the writer is `buildTerminalSessionData` (`src/renderer/src/lib/workspace-session.ts:255`),
reached only from `App.tsx` / `useIpcEvents` / `createSessionWriteSubscriber` — **all renderer**.
`orca serve` has no renderer, so that path never runs.

The fallback branch would work off `tabsByWorktree`, but for a web client that is `{}`: upstream's
`sanitizeWebRuntimeWorkspaceSession` strips it by design, and the client boots from
`window.api.session` → `localStorage`, not from the host. Tabs arrive afterwards by mirroring
(`session.tabs.listAll` / `subscribeAll`), which is *after* hydration has already decided nothing is
open.

## 3. Lead — NOT established

The shape looks like CLAUDE.md §1 "no wire": there is no `workspace.session.*` RPC, only
`session.tabs.*`. Upstream *does* have a host-partitioned session API
(`workspace-session-host-persistence.ts` — `fetchWorkspaceSessionFromHosts`, `persistWorkspaceSessionByHost`,
with a `hostId` on `session:get/set/patch`), but on desktop those partitions are stored in the
**client's own** main-process store (`src/main/ipc/session.ts` → `store.getWorkspaceSession(hostId)`),
never pushed to the remote host. For a browser the "client's own store" is `localStorage`, which
upstream sanitizes to nothing — the exact "wrong locality" shape, where local IS the server.

**Superseded by `0011`/`0012` — do NOT route this through the client.** The lead above assumed the
fix was "let the browser read the host's session". Two patches later the proven shape is the
opposite: **the host does it itself, from its own disk, at the single point that replaces the
renderer's mechanism.** `0012` needed no client change and no `sleepingAgentSessionsByPaneKey` at
all — the host's own hook rows were sufficient authority. Expect the same here: the host already
persists `tabsByWorktree` / `terminalLayoutsByTabId` and already knows which tabs carry serve-owned
PTY bindings (`hasServeOrSshOwnedBinding`), so it can derive "which worktrees were open" without any
client-supplied record.

**Answered since parking:**

- *Would restore actually bring panes back live, or is the PTY unreachable after a dead daemon?* →
  Live. `0012` resumes an exited agent from `providerSession`, verified with 4 live `claude`
  processes after a restart. Restore and cold restore compose: restore decides *which* panes open,
  `0012` makes each one live.
- *What about `sleepingAgentSessionsByPaneKey` on a headless host?* → Not needed. It is the desktop
  renderer's registry; the host's `agent-hooks` cache carries the same facts and survives restarts.

**Still genuinely open:**

1. Does the *desktop* app restore a session when driving a **remote** runtime? If not, this is
   upstream behaviour for remote hosts, not orca-coder-specific — that changes the fix.
2. Two-writers hazard: the runtime already writes `workspaceSession` on `session.tabs.*` mutations.
   Whatever writes the which-was-open fields must be the *only* writer of them. Upstream's desktop
   split keeps exactly one writer per partition.
3. Which field is authoritative for the web client. `activeWorktreeIdsOnShutdown` is what
   `terminals.ts:3163` prefers, but its fallback derives from `tabsByWorktree` — which
   `sanitizeWebRuntimeWorkspaceSession` empties for a browser. So either the host supplies the field,
   or the client's hydration has to stop reading a sanitized session for this decision. Decide which
   before writing.

**Placement:** run `orca-coder-patch-audit` step 0 with the real symbols once diagnosis names them.
`0012`'s audit returned `NEW_PATCH_BUT_CHECK` for the analogous case, so expect `0013` rather than an
extension — but do not assume it.

## 4. How to measure it cheaply

The technique that closed the `0011` investigation works here too, and needs no browser: the host's
own `orca-ide` browser CLI can load the tile from loopback and `eval` in it as a real web client.

```bash
coder ssh <ws> -- 'cd /home/coder/.coder-modules/astrateam/orca && \
  ./squashfs-root/resources/bin/orca-ide tab create --url http://127.0.0.1:6799/web-index.html --worktree <sel> --json'
# then: orca-ide eval --expression "<js>" --worktree <sel> --json
```

Compare against this Mac's `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
— the desktop is the reference implementation, so port its path rather than designing a new one.
