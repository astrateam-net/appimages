# orca-coder changelog

orca-coder ships as a **patch series** over pristine upstream Orca (see
[CLAUDE.md](CLAUDE.md) for the build + authoring contract). Each patch `000N` is an
independent capability and, in practice, a **release**: merging it to `appimages` main
rebuilds the `.AppImage` and re-publishes the same `orca-coder-<VERSION>` GitHub Release
asset (CLAUDE.md §3). The Dockerfile applies the series in filename order on the pristine
upstream tag.

This file is the skimmable "what shipped in each patch" list, newest first. The durable
invariants behind these capabilities live in CLAUDE.md §1.

Recurring root cause: Orca's web client replaces the Electron preload with
`web-preload-api.ts` and upstream **stubs most of it** — empty lists, `{available:false}`,
throw-on-call. Most "works on desktop, dead in the tile" reports are one of those stubs; the
`orca-coder-patch-author` skill has the diagnose/fix playbook.

---

## 0011 — bridge agent status to the web client

`patches/0011-web-agent-status-bridge.patch`

**Symptom:** toggling an agent tab from terminal to chat in the tile showed "Start a chat with
Claude" — the *empty* state, not an error — while the same agent's transcript renders on desktop
and on a phone paired to a desktop server. The terminal view was unaffected, which is the tell:
terminal streams a live PTY, chat opens a transcript file.

**Cause:** native chat resolves what to open from `agentStatusEntry.providerSession` alone
(`sessionId` + `transcriptPath`, `native-chat-pane-resolution.ts`). The web preload stubs the whole
`agentStatus` namespace — `getSnapshot → []`, `onSet`/`onClear` → noop — so that entry never
exists and the view correctly reports it has no conversation. Nothing was missing on the server:
hooks fire under `orca serve`, the hook server caches `providerSession`, and the runtime already
holds `getAgentStatusSnapshot` — the same dep `worktree.ps` reads (verified live: `orca worktree
ps --json` returns 5 agents with full hook fields). Only the pipe to the browser was absent,
because `agentStatus:set`/`getSnapshot` relay through `mainWindow`, which serve never opens.

**Fix:** `agentStatus.getSnapshot`/`subscribe`/`unsubscribe`, mirroring those IPC handlers 1:1 so
the browser feeds the renderer's existing `setAgentStatus` path rather than a parallel one. The RPC
module is dependency-free: it reads the runtime, which grows the push half
(`subscribeAgentStatusChanges`) as a sibling of the pull dep already wired in `index.ts` — keeping
the `agentHookServer` value import out of the RPC tree entirely, which is how `0012` closed a cycle.
The hook server's change signal carries no payload, so `subscribe` republishes the whole enriched
snapshot and the web preload diffs it back into the desktop's `onSet`/`onClear` contract; a clear is
an absent `paneKey`, leaving main's single-listener clear channel untouched. Rows carry prompts,
tool input and transcript paths, so all three stay out of `MOBILE_RPC_METHOD_ALLOWLIST` —
test-enforced both directions; phones already get agent status via the mobile session tabs snapshot.

**Placement:** audit returned `NEW_PATCH_BUT_CHECK` with `ownership = 0` — no patch owns any
discriminating symbol. Considered and rejected as extensions: **0012** (same *shape* — new RPC
family mirroring desktop IPC 1:1 plus a routed preload stub — but usage-scanning symbols, disjoint
from agent-status); **0010** (also hook-adjacent under headless, but its capability is orchestration
*message delivery* into a PTY); **0011** (client-side environment identity, not agent
state); **0004**/**0005** (same route-a-stub shape, unrelated symbols). The patches sharing
`web-preload-api.ts` share the hub file only, which decides nothing. Cross-checked against
`orca-pristine`: `subscribeStatusChanges`, `getStatusSnapshot` and `enrichAgentStatusIpcPayload` all
exist upstream and are reused; `AGENT_STATUS_METHODS` is the only genuinely new symbol.
**Fixed 2026-07-27 (same patch, boundary amended):** the bridge shipped and the symptom did not
move — the chat view still showed "Start a chat with Claude". The rows were never the problem:
`agentStatus.getSnapshot()` in the tile returned all six hook rows with correct `providerSession`.
They arrive stamped with the host's own pane key (`ORCA_PANE_KEY`, `<hostTabId>:<leafId>`), but the
web client mirrors every host terminal under `toWebTerminalSurfaceTabId(parentTabId)` — so the
renderer's pane is `web-terminal-<hostTabId>:<leafId>` and `resolvePaneKey` finds no tab.
`applyAgentStatus` returns `'dropped'`, silently, and `providerSession` never reaches the store.
Measured live: hook row `cb5db10b-…:07996bf7-…` vs `ORCA_PANE_KEY`, `orca terminal list` and the
renderer store all agreeing on `24f43d36-…:a12b2698-…`; on a native Mac the two match exactly,
which is why desktop was unaffected. The single store entry the tile did hold came from the web
PTY's own OSC 9999 stream, carrying `state`/`agentType` but never a session id — hence a sidebar
row reading `Done - Claude` beside a chat pane that had no conversation, and an empty model picker.
The fix translates at the preload boundary (`web-agent-status-pane-key.ts`, a leaf so the
translation is unit-testable and the value imports stay out of the hub file), reusing upstream's
`toWebTerminalSurfaceTabId` + `makePaneKey` rather than restating the mapping. Not fixed on the
session-tabs channel: `buildHeadlessMobileSessionTerminalTabs` omits `agentStatus` entirely under
serve, and that payload is mobile-allowlisted — filling it would ship transcript paths to phones,
which this patch deliberately avoids.
**Acceptance:** `rpc/methods/agent-status.test.ts`, `mobile-rpc-allowlist.test.ts`,
`web/web-agent-status-pane-key.test.ts`

## 0010 — bridge usage analytics to the web client

`patches/0010-web-usage-analytics-bridge.patch`

**Symptom:** Settings → Stats & Usage sat on "Not scanned yet" in the tile and the Enable
Claude/Codex/OpenCode buttons did nothing at all — no error, no effect. The same build on a Mac
shows the full ledger.

**Cause:** `window.api.<provider>Usage.*` is desktop-only IPC. It is not in the web preload, so it
fell through `createFallbackProxy`, where every call resolves to `undefined`. Upstream's `#10073`
("guard web client against undefined usage scan state") fixed the resulting `TypeError` and left
the gap — turning a missing bridge into a silent no-op.

**Fix:** a `usage.*` RPC family (eight methods, provider as a parameter) over the stores that
already run under `orca serve`, and three real preload namespaces instead of the fallback. Nothing
about scanning changed: the logs, the scanners and the stores were always on the host — only the
pipe was missing. Grok is untouched; it is subscription rate-limit data behind
`rateLimits.*`/`grokAccounts.*`, which the web preload already implements. `setEnabled` mutates the
host, so all eight stay out of `MOBILE_RPC_METHOD_ALLOWLIST` — test-enforced.
**Fixed 2026-07-26 (same patch, boundary amended):** the `RUNTIME_USAGE_PROVIDERS` value import
from `orca-runtime.ts` closed an import cycle and `z.enum(...)` ran at module scope before the
constant existed — `TypeError: Cannot convert undefined or null to object`, which cost **29 test
files and 411 tests** in `src/main/runtime`. `orca serve` was unaffected only by import-order
luck in `main/index.ts`. Moved to the leaf `src/shared/runtime-usage-providers.ts`,
`orca-runtime.ts` re-exports it. After: 155 files / 2660 tests green, typecheck clean.
Rules that now prevent it: `apps/orca-coder/CLAUDE.md` §5 and `orca-coder-patch-author`.

**Placement:** shares symbols with 0002, 0003, 0004, 0006, 0007, 0009, 0010 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** `mobile-rpc-allowlist.test.ts`
## 0009 — deliver orchestration messages on a headless host

`patches/0009-web-headless-orchestration-delivery.patch`

**Symptom:** in the tile, orchestration messages were stored but never handed to a waiting
agent, so coordination degraded to "go tell each agent to check its inbox".

**Cause:** `orca serve` publishes an empty renderer graph (`HEADLESS_RUNTIME_WINDOW_ID`), and the
push-on-idle delivery path was driven from that graph — so it never fired.

**Fix:** `deliverPendingMessagesForPty`, driven from the same idle triggers the leaf loop uses,
plus a PTY-record counterpart to `isCursorAgentOrchestrationTarget` so runtime-owned handles
resolve in the order `sendTerminal` already uses.

Touch points: `main/runtime/orca-runtime.ts`, `main/runtime/orca-runtime.test.ts`.
**Placement:** shares symbols with 0006, 0007, 0009, 0013 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** `orca-runtime.test.ts`
## 0008 — own the web client's execution without a local machine

`patches/0008-web-execution-owner.patch`

**Merged 2026-07-27** from the former `0009` (floating workspace on the connected runtime) and the
former `0011` (local-fallback floor + active-runtime pin). One question, three fixes, previously
three patches.

**Symptom:** the tile behaved as if a laptop sat behind it. The floating terminal, the Settings
skill terminal and floating markdown notes failed as if no runtime existed — `pty.spawn` rejecting
with "Local PTYs are unavailable in the web client", "No runtime worktree owns
`<floating>/.orca/templates`" — while the server showed **Connected** the whole time.

**Cause:** ownership resolution reads "no `runtimeEnvironmentId`" as "therefore this machine",
which is correct for a laptop driving a remote runtime and impossible in a browser the runtime
itself serves. Three separate paths reached that conclusion, and a fourth never got an answer at
all because nothing set `activeRuntimeEnvironmentId`.

**Fix:** decided at the resolvers every surface already routes through
(`getRuntimeEnvironmentIdForWorktree`), never at individual call sites — the floating workspace on
the connected runtime; a floor under the three paths that never reach `pty-connection`'s fallback
(ephemeral setup terminals, direct PTY spawners, and a synthetic worktree record for the floating
directory); and, with no Active Server chosen, resolution to the single saved environment read from
`state.runtimeEnvironments`, the same source `getSingleFocusedRuntimeEnvironmentId` reads.

**Why one patch:** the three shared the resolver file end to end — `resolveFloatingWorkspace-
RuntimeEnvironmentId`, `getFloatingWorkspaceRuntimeEnvironmentId`,
`getWebClientLocalFallbackEnvironmentId`, `FloatingTerminalPanel` — and the later ones could not
apply without the earlier (probed: `0011` on a tree without `0009` fails outright). Audit weight 17
on non-hub symbols.

**Superseded mechanism.** The pin originally defaulted `activeRuntimeEnvironmentId` inside
`getStoredSettings()`. Upstream encodes "no active server" as an **absent key**, so pinning that
absence made an explicit null unrepresentable — and left three upstream `web-preload-api.test.ts`
tests red from the day it landed, unnoticed because that patch shipped without an acceptance test.
Bisected, not inferred: pristine `v1.4.156` 78/78, `0001..0010` 78/78, `+pin` → 3 red.
**Hydration window (found and closed the same day).** Moving the pin out of the settings value
traded a synchronous localStorage read for `state.runtimeEnvironments`, which the store fills
**fire-and-forget** at boot (`fetchSettings` → `void hydrateRuntimeEnvironmentStatuses()`). Until it
lands the catalog is `[]`, so the new fallback resolved to null — local — on the very paths this
patch exists to fix, and ~100 call sites reach that resolver. Proven, not assumed: a boot-ordering
test was red for a web client and green for desktop before the fix. Closed by splitting
`hydrateRuntimeEnvironmentCatalog` (a localStorage list) out of
`hydrateRuntimeEnvironmentStatuses` (network probes) and awaiting only the catalog, and only in the
browser — desktop startup still touches no round trip, and the probes stay best-effort everywhere.
**Acceptance:** `floating-workspace-runtime-owner.test.ts`, `web-preload-api.test.ts`,
`settings-web-runtime-catalog.test.ts`

## Base bump — `v1.4.155` → `v1.4.156`, patch 0000 dropped

Upstream shipped the `DetachedHeadBadge` fix this series had been carrying: `v1.4.156` declares
`tabIndex?: number` on `DetachedHeadBadgeProps` **and** forwards it to `Badge`. Per CLAUDE.md §3
that is the condition to delete `0000-upstream-detached-head-badge-tabindex.patch` — the only
patch in the series that fixed an upstream bug rather than adding an orca-coder capability.
Keeping it would fail `git apply` and break the build.

The rebase (`--onto v1.4.156 <0000-boundary>`) needed two conflict resolutions:
`switchRuntimeEnvironment` → `setActiveRuntimeEnvironmentPreference` (0003), and the folder-workspace
helpers moving out of `worktree-runtime-owner.ts` into `folder-workspace-runtime-owner.ts` (0009).

One upstream test (`project-view-wrapper-source-context-boundary`) fails under full-suite parallel
load. Verified pre-existing: it fails on **pristine `v1.4.156` with zero patches**, and pristine
`v1.4.155` fails 14 tests on the same suite. Not ours, and the bump improves it.

## 0007 — open a worktree in a browser editor

`patches/0007-web-open-in-browser-editor-urls.patch`

**Symptom:** in the tile, every **Open in** entry is disabled ("Local only"). There is no way to
open a worktree in an editor at all.

**Cause:** an Open In entry could only be a local shell command. `command` spawns a process on
*this* machine against a path that lives on *another* one, so the runtime disables all of them
whenever `activeRuntimeEnvironmentId` is set — which it always is for a web client. Behind that
guard, `openInExternalEditor` is a no-op returning `{ok:true}`, so even reaching it would lie.

**Fix:** an optional `url` on `OpenInApplication`, with `{path}` substituted by the worktree's
absolute path. A browser editor served by the host that owns the path has neither problem — it
is just a URL — so URL entries skip the guards and open through `shell.openUrl` on desktop and
web alike:

```
https://code-server--<workspace>--<owner>.<domain>/?folder={path}
```

Per-worktree, which is the point: Coder's own code-server tile opens one fixed folder, while
Orca knows every worktree path.

**Nothing deployment-specific enters Orca.** The slug, the domain, the reachability all live in
the template string, which the operator writes. Icons resolve from the entry's stable `id`
(`code-server`, `vscode-web`, `vscode`, `cursor`) — never the URL's host, which carries a
deployment-chosen slug on a domain no favicon service can reach. code-server and vscode-web
borrow VS Code's mark because they *are* VS Code in a browser, and neither has a usable icon of
its own: `code-server.dev` redirects to GitHub, so a favicon lookup there returns the octocat.

**Seedable, URL entries only.** `openInApplications` joins 0007's allowlist, and the seed schema
does not describe the row shape at all — it runs `normalizeOpenInApplications`, the same function
that *writes* these rows, then keeps only those with an empty `command` and a `url`. That single
filter is everything seeding adds on top of the store's own rules: `command` is a shell command a
desktop client executes, and seeding travels runtime → client.

This replaced a hand-written zod object, which had gone wrong in the way restated shapes do. It
demanded that `command` be *absent*, while the normalizer always emits it (as `''` for a URL row)
— and every row reaching the seed path has been normalized already, since the store normalizes on
load and `getClientSettings` seeds straight from the store. So the schema rejected the one shape
the runtime actually produces, and a correctly-seeded workspace silently got no Open in entries,
with unit tests green: every fixture had been hand-written in the shape the schema wanted rather
than taken from the producer. The regression test now seeds from `normalizeOpenInApplications`
itself, which is the only fixture that can prove anything here.

Reusing the producer also pays for itself three times over, with nothing to keep in sync: the
entry cap and id dedupe now apply to seeds (a raw schema skipped both); the normalizer builds each
row explicitly, so it is an allowlist by construction and no unknown field can cross however new
the runtime that sent it; and an unrecognised key costs that key rather than its row, which is the
degradation this path is supposed to have.

Templates are restricted to `http`/`https` for the same class of reason; `javascript:` would turn
a menu click into script execution. Both test-enforced.

**One definition per rule.** "Unfinished row" lives in `shared/open-in-applications.ts` and is used
by both the normalizer and the Settings commit gate — two copies of that rule means the pane
persists rows the normalizer then silently drops. Id minting moved there too, replacing a second
private copy in the Settings pane. Menu entry shape, availability and icon live in
`lib/open-in-menu-entries.tsx`, used by both "Open in" menus. Favicon domains for URL rows resolve
through the preset catalog first, so `vscode` and `cursor` are not restated beside it.

**Settings is a first-class editor for them.** The Open In Apps pane has a **Web URL** field, so a
URL entry can be created by hand, not only seeded. The pane's commit gate accepts
`label && (command || url)`: it had required a `command`, which a browser-editor entry by
construction has none of — one seeded row therefore made *every* write from the pane a silent
no-op (add, delete, edit of every other row) for as long as it existed. A row carrying a URL is
never collapsed to the preset editor, so the URL that decides what it opens is always visible and
clearable. An unusable template does not block the write; it surfaces as an inline error here and
a disabled **Invalid URL** item in the menu.

**One entry model, two menus.** The worktree card's dropdown and Source Control's file context
menu both open an entry by passing the whole entry to `openWorktreeOpenInEntry`, and both draw it
with `OpenInMenuEntryIcon`. Source Control had destructured only the fields it knew about, so a
URL entry rendered *enabled* there and could only fail on click. Entry shape, availability and
icon now live in `lib/open-in-menu-entries.tsx` and cannot drift apart.

Seeded rows are parsed one at a time and normalized, so an unknown key (a newer runtime talking to
an older client) costs that row rather than the whole feature, and the entry cap and id dedupe
apply to seeds too. `settings.get` is on the mobile allowlist, so it withholds `openInApplications`
from phones — the rows carry deployment hostnames a phone has no menu to spend them on.
**Placement:** no existing patch owned these symbols when it was written.
**Acceptance:** `client-ui.test.ts`, `OpenInMenuSetting.test.ts`, `WorktreeOpenInMenu.test.tsx`, `external-editor-open-capability.test.ts`, `open-in-applications.test.ts`, `open-in-url-template.test.ts`, `runtime-seeded-settings.test.ts`
## Renamed: astraide → orca-coder; VERSION v1.4.153 → v1.4.155

The app was called **astraide**, which implied a product we author. It never was one: what
ships is upstream Orca (MIT) from a pinned tag with this patch series applied, and the built
app keeps upstream's identity verbatim (`productName` `Orca`, `appId` `com.stablyai.orca`,
userData `~/.config/orca`). The invented name only ever labelled the release asset — and it
actively misled, including us, when a screenshot could not be attributed to "our Orca" vs
upstream's. `orca-coder` says what it is: Orca, for Coder. Release tag and asset become
`orca-coder-<VERSION>`; the Coder module that consumes them stays named `orca`.

VERSION moved to `v1.4.155` (latest upstream stable; there is no `v1.4.154`). The series
rebased with zero conflicts — only 4 of the 41 files the patches touch changed between tags.

## 0000 — upstream `DetachedHeadBadge` tabIndex fix ⚠️ NOT OURS

`patches/0000-upstream-detached-head-badge-tabindex.patch`

**Symptom:** `v1.4.155` cannot be built from source at all. `pnpm typecheck` fails TS2322,
and `build:desktop` runs typecheck first, so the Docker build dies before packaging.

**Cause:** upstream shipped `source-control-branch-context-row.tsx` passing `tabIndex={0}` to
`DetachedHeadBadge` without widening `DetachedHeadBadgeProps`. Every tag through
`v1.4.156-rc.2` carries the mismatch; their own release pipeline evidently does not run this
typecheck.

**Fix:** declare `tabIndex?: number` and forward it to the rendered `Badge` — identical to the
fix upstream landed on `main` after the release.

**⚠️ Delete this patch as soon as a tag declares the prop.** It is the only entry in the series
that fixes an upstream bug rather than adding a capability. Per-bump check in CLAUDE.md §3.

## 0006 — runtime-seeded appearance + experimental settings

`patches/0006-web-runtime-seeded-settings.patch`

**Symptom:** a freshly provisioned workspace could not declare how its Orca looks or which
features are on. Every browser opening the tile started at stock defaults, and the same
toggles got re-clicked after every workspace create. Writing `orca-data.json` on the workspace
changed nothing — verified three ways: seeded while serve was stopped then restarted, written
while serve ran, and re-set with a full browser reload. The UI never moved.

**Cause:** the web client keeps settings in **localStorage** (`orca.web.settings.v1`), not on
the workspace. Of 183 `GlobalSettings` keys it pulls exactly five from the runtime
(`getRuntimeBackedStoredSettings`); `theme` and every `experimental*` flag are not among them.
So for the tile, `orca-data.json` governs almost nothing — settings live per-browser,
per-origin, on the user's own machine, where Terraform and Coder cannot reach them.

**Fix:** a shared allowlist (`src/shared/runtime-seeded-settings.ts`) of appearance +
experimental keys that `settings.get` now returns, which the web client adopts **exactly
once** — on a browser's first visit, when localStorage holds no settings blob. Read side only;
the write path is untouched.

**Defaults, not policy.** Nothing is written back to the runtime and nothing is re-imposed on
later loads, so "the workspace decided" never fights "the user decided". Boundary: LOOK and
CAPABILITY seed from the runtime; SIZE and ERGONOMICS (zoom, window bounds, font sizes) stay
per-device — the same runtime is driven from a laptop, a monitor and a phone. Credentials
(`codexManagedAccounts`, `opencodeSessionCookie`, …) sit in the same object and are excluded.
Both exclusions are test-enforced, not review-enforced.

**Values are validated by the app's own rules, not by rules restated here.** The three
left-sidebar keys route through `normalizeLeftSidebarAppearanceMode` /
`normalizeLeftSidebarTintColor` / `normalizeLeftSidebarTintOpacity` — the same
`z.unknown().transform(...)` shape this allowlist already uses for `appIcon` and `uiLanguage`.
Describing them locally as `z.enum` / `z.string` / `z.number` had been strictly weaker than the
functions the app already owns: a hand-edited store could seed `leftSidebarTintColor:
'not-a-color'` and `leftSidebarTintOpacity: 999` into every fresh browser's blob, past a hex check
and a 0…0.35 clamp the settings UI itself can never exceed. The regression test asserts against
those normalizers rather than against literals, so a third copy of the rule cannot reappear.
(`agentHibernationIdleMs` and the terminal theme names stay loose on purpose — the app has no
normalizer for them, and inventing one here would be this same mistake in the other direction.)

Full evidence trail: [docs/settings-provisioning/](../../docs/settings-provisioning/README.md).
**Placement:** shares symbols with 0006, 0009, 0010, 0013 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** `runtime-seeded-settings.test.ts`
## 0005 — web-client floating-workspace directory picker

`patches/0005-web-floating-workspace-dir-picker.patch`

**Symptom:** in the web tile, Settings → Floating Workspace → **Terminal Directory**'s
folder button did nothing — no picker, no error — and no directory could be applied. (Same
native-dialog class as the pet Import/Upload buttons, a separate follow-up.)

**Cause:** the desktop feature is a **three-part host operation**, and the web client had a
path for none of them. (1) The button calls `window.api.app.pickFloatingWorkspaceDirectory()`,
a **native OS dialog** — stubbed to `Promise.resolve(null)` in the browser. (2) The native
picker also **grants trust** — `grantFloatingWorkspaceDirectory` authorizes the directory and
records it in `floatingTerminalTrustedCwds`. (3) Both the settings input and the floating
terminal read the cwd through `getFloatingTerminalCwd` → `resolveFloatingTerminalCwd`, which
expands `~`, canonicalizes, and **only returns a custom path when it's trusted** — else falls
back to the default app workspace. In the web client `getFloatingTerminalCwd` was stubbed to
`''`. So even a saved path was neither trusted, resolved, nor displayed. The tile's floating
terminals run on the connected **server**, so all three must happen on the workspace host.

**Fix — wire the whole contract over runtime RPC:**
- Two runtime methods `floatingWorkspace.resolveCwd` / `grantDirectory` reuse the existing
  `ipc/floating-workspace-directory.ts` helpers via a minimal `FloatingWorkspaceDirectoryStore`
  adapter over the runtime's settings store (the desktop `Store` stays structurally
  assignable — its callers are untouched).
- Both **mutate/authorize host state**, so — exactly like `cli.*` (0005) — they stay **out of**
  `MOBILE_RPC_METHOD_ALLOWLIST`: a paired phone must never resolve or trust host directories.
  Test-enforced (not-allowlisted + registered).
- `app.grantFloatingWorkspaceDirectory` added to the preload contract (desktop IPC handler +
  web routing) so a browser-picked directory records the **same grant** the native picker does.
- Web client: Terminal Directory opens the existing `RemoteFileBrowser` (`files.browseServerDir`,
  the "Add a project → Browse folder" path); `onSelect` **grants then stores**;
  `getFloatingTerminalCwd` routes to `resolveCwd` so both the input **and** the terminal cwd
  resolve on the host. Gated on `settings.activeRuntimeEnvironmentId` (pure
  `shouldUseServerDirectoryBrowser` helper) — with no environment, it falls back to the native
  no-op. **Desktop is unchanged.**

Touch points: `main/runtime/rpc/methods/floating-workspace.ts` (+ `.test.ts`), `rpc/methods/index.ts`,
`main/runtime/orca-runtime.ts`, `main/ipc/floating-workspace-directory.ts`, `main/ipc/app.ts`,
`preload/{api-types,index}.ts`, `web/web-preload-api.ts`,
`renderer/src/components/settings/FloatingWorkspacePane.tsx` (+ `.test.tsx`),
`main/runtime/mobile-rpc-allowlist.test.ts`.
**Placement:** shares symbols with 0002, 0003, 0004, 0007, 0009, 0010, 0013 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** `mobile-rpc-allowlist.test.ts`, `floating-workspace.test.ts`, `FloatingWorkspacePane.test.tsx`
## 0004 — web-client agent-skill CLI registration

`patches/0004-web-cli-registration.patch`

**Symptom:** every agent-skill setup card (Orchestration, Browser Use, Computer Use,
Linear, Ephemeral VMs, Mobile Emulator, Settings → CLI) warned **"Orca CLI registration is
unavailable"** and could never register `orca-ide`.

**Cause:** the skill-setup prerequisite (`ensureOrcaCliAvailableForAgentSkillTerminal`)
probes `window.api.cli.getInstallStatus()` and, if the CLI isn't on PATH, calls
`cli.install()` so the terminal it opens can resolve the Orca command. In the web client
`createCliApi()` was a hardcoded `supported:false` stub. But that terminal runs on the
connected **server** (like every web PTY), where `orca-ide` genuinely exists (serve
installs it on first run — CLAUDE.md §2).

**Fix:**
- New runtime RPC `cli.getInstallStatus` / `cli.install` / `cli.remove` reuse the exact
  `CliInstaller` behind the `cli:` IPC handlers (extracted as
  `{get,install,remove}CliInstallStatusWithShellPathHydration` in `ipc/cli.ts`; same
  shell-path hydration so `pathConfigured` matches what a PTY sees).
- `createCliApi()` routes those three through `callRuntimeResult`; the status probe falls
  back on transient failure, `install`/`remove` surface real server errors (like desktop).
  No active environment → honest `supported:false`.
- **Scope:** `install`/`remove` mutate the host (`~/.local/bin` symlink), so all three stay
  **out of `MOBILE_RPC_METHOD_ALLOWLIST`** — a paired phone can never register/remove host
  commands; runtime-scope only, like `terminal.*`/`files.*`. Not credential-minting, so no
  `trustedMobilePairing` context — a plain runtime method like `diagnostics`/`preflight`.
- Test-enforced: `mobile-rpc-allowlist.test.ts` (not-allowlisted + registered),
  `rpc/methods/cli.test.ts` (routing). WSL registration stays a Windows-desktop concern.

Touch points: `src/main/runtime/rpc/methods/cli.ts` (+test), `src/main/ipc/cli.ts`,
`src/main/runtime/rpc/methods/index.ts`, `src/main/runtime/mobile-rpc-allowlist.test.ts`,
`src/renderer/src/web/web-preload-api.ts`.
**Placement:** no existing patch owned these symbols when it was written.
**Acceptance:** `mobile-rpc-allowlist.test.ts`, `cli.test.ts`
## 0003 — web-client resource manager

`patches/0003-web-resource-manager.patch`

Resource Manager in the web client showed all zeros — the web preload `memory.getSnapshot`
was an empty-snapshot stub. Now routes to runtime `diagnostics.memory` (which phones
already poll), so the tile shows the **workspace's** processes + host RAM/CPU. One-line
stub→RPC reroute; falls back to the empty snapshot only when no environment is connected.
**Placement:** shares symbols with 0002, 0003, 0006, 0009, 0013 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** **none — cannot be dropped, shrunk or merged until it has one.**
**Acceptance (added 2026-07-27):** `web-preload-api.test.ts` — routes `memory.getSnapshot` at
`diagnostics.memory` and degrades to an empty snapshot rather than throwing when the runtime cannot
answer.

## 0002 — mint and revoke pairing credentials from the web client

`patches/0002-web-pairing-credentials.patch`

**Merged 2026-07-27** from the former `0002` (mobile pairing) and `0003` (runtime share links).

**Symptom:** the tile could not pair anything. **Generate code** for a phone did nothing, and there
was no way to hand another client access to this runtime at all.

**Cause:** both surfaces are desktop-only IPC the web preload never had.

**Fix:** two credential scopes over one mechanism — `mobile` offers for phones (RPC allowlist plus
payload diet) and `runtime` grants for full clients. Both mint or revoke a credential, so both are
authorized by the same `trustedMobilePairing` context, injected only for runtime-scope connections
and absent → fail closed. Advertised address stays server policy (`--pairing-address`), never
client-chosen; strict zod params error rather than strip it. Web copy is reframed for a browser
with no server of its own.

**Why one patch:** audit weight 30 — the highest in the series — on six non-hub symbols
(`TrustedMobilePairingRpcContext`, `TrustedRuntimeGrantResult`, `buildTrustedMobilePairingContext`,
`mobile-pairing.ts:handler`, `getRuntimePairingUrl`, `trustedContext`). Probed: the share-links half
does not apply at all without the mobile half.
**Acceptance:** `mobile-pairing.test.ts`, `mobile-rpc-allowlist.test.ts`

## 0001 — trusted-proxy web session

`patches/0001-serve-trusted-proxy-web-session.patch` · contract: CLAUDE.md §1

The foundation: `serve --trusted-proxy` binds the runtime WS listener to `127.0.0.1` and
exposes a loopback-gated `GET /trusted-session` offer, so the Coder subdomain tile loads
the full Orca web UI with **no pairing prompt** (code-server's `--auth none` + loopback
trust model), keeping Orca's E2EE intact. The web client dials same-origin from
`window.location`, with stale-credential recovery on serve re-key.

Also folds in **web-session device naming**: trusted-session devices are named
`Web session <date>` (fixes 0001's own mint, which previously leaked the upstream
`CLI <date>` default) so the shared-access list reads honestly: Web session / Runtime /
Mobile.
**Placement:** shares symbols with 0002, 0003 — coupling recorded by audit; kept separate because each is a distinct capability. Re-review on the next bump.
**Acceptance:** **none — cannot be dropped, shrunk or merged until it has one.**

**Acceptance (added 2026-07-27):** `static-web-client-handler.test.ts` — `/trusted-session` serves
the offer with `Cache-Control: no-store` to a loopback peer, 404s a non-loopback one (hiding the
endpoint rather than refusing it), 503s before an offer can be minted, matches behind a reverse-proxy
path prefix, and is absent entirely when trusted-proxy mode is off.
