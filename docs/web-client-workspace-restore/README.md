# SHIPPED as `0013` — the tile restores the workspace it was left in

> **Status: fixed 2026-07-27, shipped as `0013-web-workspace-restore`.** Full rationale, placement
> argument and acceptance criteria: [CHANGELOG `0013`](../../apps/orca-coder/CHANGELOG.md).
> Not yet live-verified — needs a rebuild and a workspace restart.
>
> §2's measurement was correct but led the wrong way, and §3's replacement lead was **also wrong**.
> Both are kept below with what actually disproved them, because the mistake is reusable: it is the
> `0012` reflex ("the host does it itself, from its own disk") applied without checking whether the
> client ever reads the surface being written.

## 1. Symptom

The Mac desktop reopens the previous session on launch — worktrees, tabs, splits, focused tab.
Upstream documents this as a product feature (`orca-wiki/guide/model/session-restore.md`), with no
headless carve-out.

The Coder tile did not. After a workspace restart it landed on **"Select a workspace from the
sidebar to begin"** with an empty main pane, even though the sidebar listed every worktree. You had
to click your way back to where you were.

Separate from the agent-status freeze fixed in `0011` ("the pane opens but has no chat toggle") and
from `0012` ("the pane opens but is backed by a shell"). This one was "nothing opens at all".

## 2. What was measured (2026-07-27, `ceo/apricot-sheep-57` vs this Mac)

Comparing `workspaceSession` in `orca-data.json` on both hosts:

| Key | Mac desktop | `orca serve` host |
|---|---|---|
| `activeWorktreeIdsOnShutdown` | present — 4 worktree ids | **absent** |
| `activeWorkspaceKey` | present | **absent** |
| `sleepingAgentSessionsByPaneKey` | present | **absent** |
| `lastVisitedAtByWorktreeId` | present | **absent** |
| `tabsByWorktree` / `unifiedTabs` / `terminalLayoutsByTabId` | present | **present** (11 / 11 / 21) |

The numbers are real. The inference drawn from them — *"therefore the host must start writing the
absent fields"* — was not, for the reason in §4.

## 3. Two leads, both wrong — and what disproved them

**Lead A (original): "no wire — let the browser read the host's session."** There is no
`workspace.session.*` RPC, only `session.tabs.*`; upstream's host-partitioned session API
(`workspace-session-host-persistence.ts`) stores partitions in the *client's own* main-process
store, which for a browser is `localStorage`, which upstream sanitizes to nothing.

**Lead B (its replacement, after `0011`/`0012`): "the host does it itself, from its own disk, at the
single point that replaces the renderer's mechanism"** — expecting no client change at all, because
`0012` needed none.

**What actually killed both:** the write target was never reachable.

- `activeWorktreeIdsOnShutdown` has exactly one writer,
  `persistWindowlessPtyBindingsForDesktopAttach`, reachable only from `attachWindow`, called only
  from `window/attach-main-window-services.ts` — a desktop window attach that never happens under
  `orca serve`. So lead B's premise ("the host could derive it") is true; upstream already has the
  derivation.
- But it would have been **inert anyway**: the browser never reads the host's `workspaceSession`.
  `window.api.session.get` is `localStorage` only, and on a paired client
  `getStoredWorkspaceSession` discards even that, rebuilding the boot session from
  `ui.lastActiveRepoId` / `ui.lastActiveWorktreeId`.
- And it would have been **harmful**: that field drives `pendingReconnectWorktreeIds` → eager PTY
  spawn *from the client*, the exact stale-remote-PTY replay `sanitizeWebRuntimeWorkspaceSession`
  exists to prevent.

**The generalisable lesson**, now in [CLAUDE.md §5](../../apps/orca-coder/CLAUDE.md): *check the
read path before designing the write.* A host-side fix is only equivalent to `0012`'s when the data
reaches the client over a surface the client actually reads.

## 4. What the gap actually was

Upstream's consumer already existed and was already correct. `getStoredWorkspaceSession` restores a
paired client's workspace from `ui.lastActiveRepoId` / `ui.lastActiveWorktreeId`. Repo-wide, those
two fields have **one reader**, a `null` default, a clear-on-project-removal path, and a slot in the
`UiUpdate` RPC schema — and **no producer at all**, on desktop or web. Upstream designed the restore
and never wired the write.

Everything else was already in place:

- the wire — `ui.get` / `ui.set`, live in the web client (`createWebUiApi`) and host-persisted via
  `runtime.updateUIState` → `orca-data.json`;
- the boot order — `App.tsx` awaits `ui.get()` (step `ui-get`) *before* the session read, so the
  host's pointer is in local UI state by the time `session.get()` runs;
- the tabs — mirrored over `session.tabs.listAll`/`subscribeAll` once a worktree is active;
- the focused tab within a worktree — already persisted per client on the host
  (`PersistedMobileClientTabSelections`, keyed by `pairedDeviceId`).

So `0013` is one missing producer, not a new mechanism: `rememberWebActiveWorkspace` records the
pointer from the web session adapter through `ui.set`. Answers to the questions §3 left open, in
order: (1) moot — desktop-vs-remote never mattered, the client's own read path did; (2) no
two-writers hazard, because the pointer lives in the `ui` slice and not in `workspaceSession` at
all; (3) neither candidate field — `ui.lastActive*` is authoritative.

## 5. How to measure it cheaply

The technique that closed the `0011` investigation works here too, and needs no browser: the host's
own `orca-ide` browser CLI can load the tile from loopback and `eval` in it as a real web client.

```bash
coder ssh <ws> -- 'cd /home/coder/.coder-modules/astrateam/orca && \
  ./squashfs-root/resources/bin/orca-ide tab create --url http://127.0.0.1:6799/web-index.html --worktree <sel> --json'
# then: orca-ide eval --expression "<js>" --worktree <sel> --json
```

For this capability the direct check is the `ui` slice on the host, not `workspaceSession`:

```bash
# resolve the file rather than assuming the profile dir — it is <userDataDir>/orca-data.json
coder ssh <ws> -- 'find ~/.config -name orca-data.json 2>/dev/null \
  -exec jq "{lastActiveRepoId: .ui.lastActiveRepoId, lastActiveWorktreeId: .ui.lastActiveWorktreeId}" {} +'
```

Both should be non-null after using the tile; then restart the workspace and confirm it opens on
that worktree instead of Landing. Compare against this Mac's
`~/Library/Application Support/orca/profiles/local-default/orca-data.json` — the desktop is the
reference implementation, so port its path rather than designing a new one.
