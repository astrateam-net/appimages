# Renderer-parity tracker — every capability `orca serve` lost with the renderer

> **Purpose:** stop diagnosing tile bugs one at a time. `orca serve` is the *same* Electron main
> process as the desktop app, with the *same* storage (`orca-data.json`, `orchestration.db`,
> `agent-hooks/`). The only thing it lacks is a **renderer**. Every "works on desktop, dead in the
> tile" report is therefore a capability whose source of truth, channel, or lifecycle writer lives in
> `src/renderer/src/`. That set is finite and enumerable — this file is the enumeration.
>
> Measured 2026-07-27 against fork `v1.4.156` + series, and against the live workspace
> `ceo/apricot-sheep-57`. Re-derive rather than trust the counts.

## 0. The three shapes (and why storage is never the answer)

| Shape | Desktop's source of truth | Headless |
|---|---|---|
| **S1 — store-backed** | renderer's zustand store, projected onto a surface | no store; needs resolution at the host's single publish boundary |
| **S2 — window channel** | `mainWindow.webContents.send('<ns>:…')` | no window; needs an RPC |
| **S3 — lifecycle writer** | renderer's boot/quit path writes to `orca-data.json` | nothing writes it at all |

Storage is **not** a shape. Adding Postgres/Redis would not fix any row below — but adding a real
service *is* allowed when a capability genuinely needs one (see `apps/orca-coder/CLAUDE.md` intro).

## 1. Renderer-only `WorkspaceSessionState` fields (S3)

Derived by walking all 28 declared fields and classifying every writer as renderer or main:

```bash
# fields whose only writers are under src/renderer/src
python3 - <<'PY'   # see git history of this file for the full script
PY
```

**Renderer-only writers:** `activeConnectionIdsAtShutdown`, `activeRepoId`, `browserUrlHistory`,
`markdownFrontmatterVisible`, `sleepingAgentSessionsByPaneKey`.

**Confirmed absent on the live server** (present on the Mac) — compare the two `orca-data.json`:

| Field | Mac | server | consequence |
|---|---|---|---|
| `sleepingAgentSessionsByPaneKey` | ✅ | ❌ | no resume registry → §3 |
| `activeWorktreeIdsOnShutdown` | ✅ | ❌ | nothing reopens your worktrees |
| `activeWorkspaceKey` | ✅ | ❌ | no focused-workspace restore |
| `lastVisitedAtByWorktreeId` | ✅ | ❌ | sidebar ordering/recency lost |

Writer is `buildTerminalSessionData` / `buildWorkspaceSessionPayload`
(`src/renderer/src/lib/workspace-session.ts`), reached only from `App.tsx`, `useIpcEvents`,
`createSessionWriteSubscriber` — all renderer. Consumer is
`src/renderer/src/store/slices/terminals.ts:3163`, which treats `activeWorktreeIdsOnShutdown` as
authoritative and falls back to `tabsByWorktree` — `{}` for a web client, because upstream's
`sanitizeWebRuntimeWorkspaceSession` strips it by design.

Parked detail: [`web-client-workspace-restore`](../web-client-workspace-restore/).

## 2. Window-only channels (S2)

23 namespaces are reachable only by a renderer window:

```bash
grep -rhoE "webContents\.send\('([a-zA-Z]+):" src/main/ | sed "s/webContents.send('//;s/:$//" \
  | sort | uniq -c | sort -rn
```

Top by call count: `ui` 32, `pty` 15, `terminal` 9, `window` 7, `ssh` 7, `speech` 6, `browser` 6,
`agentStatus` 5, `repos` 4, `worktrees` 3. Names are **renamed** across the RPC boundary
(`repos:` → `repo.*`, `pty:` → `terminal.*`), and some are legitimately renderer-only (`window`,
`ui`) — so this is a lead list, not a defect list. Each candidate needs its own trace.

## 3. ✅ FIXED in `0012` — headless cold restore (was the blocker)

**Symptom (live, 2026-07-27):** after a workspace restart, opening an agent pane in the tile renders
the full transcript in chat view, but typing in the composer lands in a bare shell:

```
bash: command not found: THIS
bash: command not found: what
```

**Why:** native chat is a TUI wrapper — `sendNativeChatMessage(settings, ptyId, text)` writes bytes
into the pane's PTY. On desktop that PTY is either the surviving daemon-held agent, or one the
renderer **relaunched with resume flags**. That decision is `coldRestoreStartup` /
`coldRestoreOverride` in `src/renderer/src/components/terminal-pane/pty-connection.ts` — 7+ sites
passing `resumeProviderSession`, all renderer.

**The runtime already accepts it** (`orca-runtime.ts:21917`, `:22104` consume
`launchOpts.resumeProviderSession`) and `shared/agent-session-resume.ts` exports
`getAgentResumeArgv`. Nothing on a headless host ever passes it.

Ruled out as the seam:
- `terminal.recoverPane` → `recoverTerminalPane` requires a *recently expired SSH lease*
  (`getRecentExpiredSshLease`, else `terminal_not_recoverable`) and calls `createTerminal` with **no**
  resume. It is SSH relay recovery, not agent resume.
- `session.tabs.createTerminal` accepts `launchConfig` / `launchAgent` but has **no**
  `resumeProviderSession` field — a resume is only expressible if the caller smuggles `--resume <id>`
  inside `launchConfig.agentCommand` (`orca-runtime.ts:1360` sniffs exactly that).
- `getFreshRetainedAgentStatusForMobileTab` — reads `latestAgentStatusByPaneKey` (live ingest only,
  never disk hydration) and drops rows older than 30 min. Empty after any restart.

**There was no decision to make** — and asking the owner for one was the wrong instinct. Sleep is an
explicit context-menu command he had not used; a full Mac reboot restores working sessions on its
own. So desktop cold-restores automatically and headless mirrors that, full stop. `0012` does it: the
host reads its own hook rows and resumes. The gate was `ensureAgentSession` refusing
`kind: 'automatic'` — correct for client-supplied sleep records, irrelevant to the host's own cache.

## 4. web-preload stubs (S1/S2) — 238 hardcoded returns

```bash
grep -cnE "=> *(Promise\.resolve\(\[\]\)|Promise\.resolve\(null\)|...)" src/renderer/src/web/web-preload-api.ts
```

By namespace (top): `platforms` 156, `activeAccountIdsByRuntime` 43, `agentStatus` 12,
`management` 9, `crashReports` 4, `mobile` 4, `app` 3, `session` 2. Most of `platforms` is
legitimately inert. The ones that cost real capability so far:

| Namespace | Stub | Status |
|---|---|---|
| `agentStatus.*` | `getSnapshot: () => []`, `onSet/onClear` no-op | worked around by filling the session-tab surface (`0011`) — a separate channel fights `buildMirroredAgentStatusPatch`, which prunes any pane key absent from the surface |
| `session.readTerminalScrollback` | `() => null` | desktop does `sendSync('session:read-terminal-scrollback-sync')` → `store.readTerminalScrollbackSnapshot(ref)`. **No scrollback snapshots exist on the server's disk at all**, so this is S3 *and* S2 |
| `management.*` (Manage Sessions) | `listSessions: () => ({sessions: []})`, no-op kill | tile cannot see or kill a wedged session — real loss of recovery |

## 5. Fixed so far

| Capability | Patch | Verified |
|---|---|---|
| A dead agent pane resumes against its provider session instead of spawning a bare shell | `0012` | Unit 5/5 on the decision logic. **Live: unproven** — needs a restart plus typing in the composer |
| Agent identity + `providerSession` + transcript reach the browser, survive restart **and** republish by any of the 11 snapshot producers | `0011` | Live: `session.tabs.listAll` → 3/18 panes carry `agentStatus` with transcript paths, 0 hooks fired in 3h; chat renders both transcripts. **Does not make the session live — see §3.** |

## 6. Method

1. Name the capability; find how **desktop** does it end to end (store slice → IPC → main).
2. Classify S1/S2/S3. Find the *single* point that replaces desktop's mechanism — not the nearest
   place the symptom disappears. Filling 1 of 11 snapshot producers cost two failed passes.
3. `orca-coder-patch-audit` step 0 with the real symbol list; obey the verdict.
4. Acceptance test that fails without the patch. Then live check.

Do not claim a capability works until it has been exercised the way a user exercises it — rendering
a transcript is not the same as continuing a conversation.
