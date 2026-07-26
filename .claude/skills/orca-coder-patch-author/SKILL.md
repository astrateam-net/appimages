---
name: orca-coder-patch-author
description: Create an orca-coder patch — diagnose a stubbed web-client feature and implement the fix in the Orca fork, then export the boundary diff to apps/orca-coder/patches/. Use when adding or fixing an orca-coder capability. Run orca-coder-patch-audit FIRST to learn whether an existing patch already owns the area; hand to orca-coder-patch-verify when done.
paths: apps/orca-coder/**
---

# orca-coder — author a patch

orca-coder = patched upstream Orca → Linux AppImage. `apps/orca-coder/patches/` is a series of
`git diff`s applied in filename order on pristine `v1.4.156`. **Author in the fork, never in this
repo.** Invariants you must respect: `apps/orca-coder/CLAUDE.md`. History: `apps/orca-coder/CHANGELOG.md`.

- `<repo>` = this appimages repo root.
- `<fork>` = **`<repo>/.upstream/orcaide-v2`** — a git worktree of `mrkhachaturov/orcaide` @ branch
  `patch/trusted-proxy-v2`, base `v1.4.156`. Gitignored, so it never enters a build.
  Ignore branch `patch/trusted-proxy` — phantom `v1.4.154` base. `backup/v153-series` holds the
  pre-bump series on `v1.4.153`.

**Read Orca source ONLY in `<fork>`, and prove the version first:** `git -C <fork> describe --tags`
must start with the VERSION in `docker-bake.hcl`. Never trace in `…/containers/.upstream/orca` —
that is another repo's clone, pinned elsewhere (it sat 5 minors behind and produced confidently
wrong answers). See `apps/orca-coder/CLAUDE.md` §4.

Each patch = diff between consecutive feature-boundary commits on the fork branch:

Base is **`v1.4.156`**. Patch `0000` was dropped on that bump (upstream landed the
`DetachedHeadBadge` `tabIndex` fix) — every patch in the series is now an orca-coder capability,
none carries an upstream fix. See `apps/orca-coder/CLAUDE.md` §3.

**Derive the boundaries; never keep a table of them.** A hand-maintained copy used to live here,
was mandated by the ship skill, and was declared untrustworthy in the same breath — so it rotted.

`git -C <fork> log --oneline <base>..HEAD` lists our commits, but **there are more commits than
patches**: a feature plus its follow-up fixes share one boundary (today 15 commits, 13 patches, the
first three all inside `0001`). So the Nth commit is NOT patch N, and counting mis-assigns every
boundary. The mapping is resolved from diff content — a patch equals the diff between two
consecutive boundaries — by `orca-coder-patch-audit`'s `patch-map`:

```bash
mise run patch-map --out /tmp/m.json      # then read .patches[].commits
```

Graph-free equivalent when that is unavailable: for each patch in filename order, find the commit
whose `git diff <prev-boundary> <commit>` equals the patch file (ignoring `index` lines and hunk
offsets). That is exactly what `patch-map` automates, and it is why the export command below must
name both ends.

**Rebasing the series onto a new tag:** `git branch -f backup/<old> HEAD` first, then
`git rebase --onto <newtag> <oldtag> patch/trusted-proxy-v2`, re-export every boundary, and
`rm -f config/*.tsbuildinfo` before typechecking — stale incremental build info will happily
report an error you already fixed (and hide one you just introduced).

## Diagnose (the usual bug: a web-client stub)

#### The one fact behind every tile bug: the browser is a REMOTE client of the same box

Orca grew web support after the fact, and bolted it onto the remote-runtime machinery. Upstream's
own mental model (`guide/remote-servers.md`) has exactly **two roles**: a *server machine* that
runs `orca serve` and "owns the repos, worktrees, terminals, and agent processes", and a *client
machine* that "runs the Orca UI and connects" — and it assumes they are different boxes ("Do not
use `127.0.0.1` unless the client is running on the same machine"). **orca-coder collapses both
roles onto one host**: the browser is a *client-machine* client of a runtime that is the very
process serving it the page. The product says so in the UI (Settings → **Remote Orca Servers** →
"Selecting a saved server makes this browser use that paired Orca runtime as its default Host",
pointing at our own tile URL). The client even carries a `LOCAL_EXECUTION_HOST_ID` notion
(`web-preload-api.ts`, used to partition localStorage) that is a **fiction** there — it has no
local. Upstream is explicit that headless deliberately drops window-bound subsystems ("In headless
mode Orca wires up no auto-updater at all — the built-in updater only runs in the desktop GUI");
what is *not* documented is how much else went with it. **Consequence: every capability needs a wire representation, because there is no "just do
it locally" fallback — local IS the server.** Orca's web client replaces the Electron preload
with `web-preload-api.ts` (`createWebPreloadApi()`) and upstream stubs much of it — empty lists,
`{available:false}`, no-op/throw — precisely where no wire exists yet.

Three failure shapes come out of that. **Decide which one you are in before writing code** — the
fix differs per shape, and one patch often has to answer more than one (`0009` = 39 locality
decisions plus a single RPC; only `0004`/`0005`/`0008`/`0013` are purely shape 1).

| # | Shape | Tell | Fix |
|---|---|---|---|
| 1 | **No wire.** The capability only ever existed as Electron IPC (`mainWindow.webContents.send(…)` + `ipc/*.ts`), so the web preload was stubbed | Hardcoded return in `web-preload-api.ts`; no matching namespace in `ALL_RPC_METHODS` | Add the RPC (or route to an existing one), mirroring `ipc/*.ts` 1:1 |
| 2 | **Wrong locality.** "No `runtimeEnvironmentId`" read as "therefore this machine", then a desktop-only affordance | see the next subsection | Fix at the resolver, not the call site |
| 3 | **Renderer-graph-driven.** Wired and locality-correct, but the *trigger* reads `this.leaves` / the window graph — permanently empty under serve | Logic keyed on `getLeavesForPty`, `handleByLeafKey`, `getLiveLeafForHandle` | Add the PTY-record counterpart, gated on leaf-emptiness so desktop never double-fires (`0010`) |

**Shape 3 is the least obvious, so know the mechanism:** `serve` publishes ONE empty graph
(`HEADLESS_RUNTIME_WINDOW_ID`, `main/index.ts`), `web-preload-api.ts`'s `syncWindowGraph` is a
stub, and there is no `graph.*` RPC — a browser **structurally cannot publish leaves**, so
`this.leaves` stays empty for the process lifetime. But such a terminal still carries a real pane
identity on its **PTY record**, so `terminal.list` returns real UUID `tabId`/`leafId` and *looks*
leaf-backed. It is not. The discriminator is the `orphaned` field, emitted only by
`buildPtyTerminalSummary` (live 2026-07-26: 14/14 terminals in the tile carried it — zero leaves).

**Upstream ships docs — read them before inferring.** A local mirror of onorca.dev + the in-repo
`docs/` is indexed for the `orca-wiki` skill, which holds the (machine-local) mirror path. The two that
matter here: `guide/remote-servers.md` (the two-role model above) and
`engineering/docs/reference/headless-linux-server.md` (the `serve` spec — ready-JSON contract,
pairing `reason` codes, upgrade/rollback). Note where our §2 diverges: that spec claims modern
builds auto-start Xvfb and that `dbus-run-session -- xvfb-run` "should not be needed", while our
launch line still requires both — our version is the live-verified one, but it is worth a
re-measure on the next bump rather than a permanent assumption.

**Finding the next gap:** `grep -rhoE "webContents\.send\('([a-zA-Z]+):" src/main/` lists the 23
namespaces only a renderer window can receive. Cross-referencing them against `ALL_RPC_METHODS`
yields **leads, not defects** — namespaces are renamed across the boundary (`repos:` → `repo.*`,
`pty:` → `terminal.*`, `sparsePresets:` → `repo.sparsePresets`) and some are legitimately
renderer-only (`window`, `ui`). Every candidate needs its own trace before it earns a number.

#### "Not a named runtime" ≠ "this machine" (shape 2, in depth)

The one that keeps recurring (`0006`, `0008`, `0009` twice over): code that
reads *no `runtimeEnvironmentId`* as *therefore local*, then does something only a desktop app
can do — spawn a PTY, mount a `<webview>`, open a native dialog, focus a renderer window. Correct
for a laptop driving a remote runtime; **never correct for a browser the runtime itself serves,
where local and runtime are the same host and every local affordance is a stub.**

- **Diagnose by locality, not by feature.** Grep what the code believes: `=== null` on a runtime
  id, `'local'`, `LOCAL_EXECUTION_HOST_ID`, `isWebClient`, `window.api.<ns>`. In `0009` every fix
  was reachable from an existing runtime path — the whole patch is ownership decisions plus one
  RPC wrapping a helper the desktop handler already called.
- **Fix at the resolver, not the call site.** Terminal, browser and the setup/default-tab
  automations all route through `getRuntimeEnvironmentIdForWorktree`; fixing the ternary in
  `pty-connection.ts` alone would have fixed one of three.
- **A path existing in source is not evidence it is taken.** Two `0009` conclusions were inferred
  from reading routing code and both were wrong. Behavioral claims need a test or a live check.
- **Check the runtime first — it is usually already capable.** It answers the floating sentinel
  with the home dir, `browser.tabCreate`'s `worktree` is optional, and there is an offscreen
  browser backend for headless hosts. Prefer omitting a parameter over teaching the server a new
  concept.
- **Hook-reported agent status IS live under headless serve — the gap is usually a projection, not
  a missing path.** The single `new OrcaRuntimeService` (`main/index.ts`) is constructed before the
  headless/desktop split and is handed `getAgentStatusSnapshot: () => agentHookServer.getStatusSnapshot()`,
  so `worktree.ps` serves real hook rows in the tile (verified live 2026-07-26: 5 agents with
  `state`/`prompt`/`lastAssistantMessage`/`toolName`). What is missing is dropped by **explicit
  field allowlists** — `attachAgentRowsToSummaries`' `rowSources` shape omits `providerSession`, so
  the session id + transcript path never leave the runtime and native chat is empty on web AND
  mobile. Before
  designing a new RPC or ingest point, check whether the data is already in the runtime and merely
  unprojected.
- **Enumerate every producer before concluding one doesn't exist.** The inverse of the bullet above:
  a map with ten `.set(…)` call sites is not characterized by the first one you open (that mistake
  produced a wrong "mobile is dead" call). Grep all writers, classify each as renderer-fed or
  main-fed, then speak.


Symptom: works on desktop, dead in the browser tile ("No interfaces found", zeros, "…unavailable").

0. **Ask upstream first** — the **`orca-wiki`** skill indexes onorca.dev + stablyai/orca's own
   design docs. Some tile gaps are documented, deliberate headless omissions (no auto-updater),
   and the specs name the mechanism faster than grepping does. Docs narrow the search; only source
   in `<fork>` and a live check settle behavior.
1. **Confirm it's a stub.** Grep the error string / `window.api.<ns>` in `web-preload-api.ts`.
   Hardcoded return (`Promise.resolve({...})`, `createEmpty…()`, `reject`) = stub, not a bug.
2. **Read the desktop contract:** `src/preload/index.ts` (+`api-types.ts`), `src/main/ipc/*.ts`.
   Mirror names/shapes 1:1 so the renderer stays untouched.
3. **Existing runtime RPC?** Check `src/main/runtime/rpc/methods/` + `ALL_RPC_METHODS`. If one
   exists, the fix is one line: route the stub through `callRuntimeResult('<method>')` (0004).
4. **No RPC → add one:**
   - Host probe/op (not credential-minting): plain method reusing `ipc/*.ts`, like
     `diagnostics`/`preflight`. Scope gate = absence from `MOBILE_RPC_METHOD_ALLOWLIST` (0005).
   - Credential mint/revoke: authorize via the `trustedMobilePairing` ctx (runtime-scope only,
     injected in `handleWebSocketMessage`, fail closed). Strict zod params. Server callbacks in
     `buildTrustedMobilePairingContext()` (0002/0003).
5. **Scope (never regress):** new methods stay OUT of `MOBILE_RPC_METHOD_ALLOWLIST` unless phones
   need them; anything mutating the host or minting/revoking credentials is never phone-reachable.
   Add the not-allowlisted + registered assertions to `mobile-rpc-allowlist.test.ts`.
6. **UI:** branch on `isWebClientLocation()`; hide desktop-only affordances (interface pickers,
   custom addresses, Relay); advertised address is always server policy (`--pairing-address`);
   reframe copy (browser = client, "this app" = the workspace server).

Can't fix server-side: needs the STOCK phone/desktop client to change → upstream PR (e.g. offer
carries no server name → phone shows "Host 1"). Web needs data the runtime doesn't expose → the
RPC method is the patch.

### ⚠️ `import type` only from the hub modules — and never evaluate at module scope

`orca-runtime.ts` is ~33k lines and sits in an import cycle with the RPC tree:
`orca-runtime → ipc/ssh → ssh-relay-session → ssh-remote-orca-cli → rpc/dispatcher →
rpc/methods/index → your method → back to orca-runtime`. Every one of the six existing
`rpc/` files that references it uses **`import type`**, which TypeScript erases, so no runtime
edge exists and the cycle never runs.

Patch `0013` added the series' only **value** import from it (`RUNTIME_USAGE_PROVIDERS`) and used
it at module scope (`z.enum(...)`). When the cycle is entered through `orca-runtime.ts`, that line
evaluates before the constant is initialised: `TypeError: Cannot convert undefined or null to
object` at module load. Measured cost — **29 test files failed to collect and 411 tests never
ran**, while `orca serve` survived only because `main/index.ts` happens to reach the cycle via
`ipc/ssh` 16 lines earlier. Fixed by moving the constant to a dependency-free leaf,
`src/shared/runtime-usage-providers.ts`.

So, two rules:

1. **From a hub module (`orca-runtime.ts`, and anything that imports `ipc/*`) use `import type`.**
   Need the *value*? Put it in a leaf under `src/shared/` — that is where this series already keeps
   `open-in-applications`, `open-in-url-template`, `runtime-seeded-settings`,
   `floating-workspace-worktree` — and re-export from the hub for existing consumers. A bare
   `export type { X } from …` does **not** bring `X` into local scope; add a companion
   `import type` or the hub's own uses fail with `TS2304`.
2. **Nothing imported across a cycle may be evaluated at module scope.** Schemas, `z.enum`,
   frozen maps, computed constants — build them inside the handler or behind a lazy getter. Module
   scope runs at import time, where initialisation order is not yours to choose.

Cheap check before you commit: `grep -rn "from '\.\./\.\./orca-runtime'" src/main/runtime/rpc/`
— every hit must say `import type`.

## Place it — a new number is a decision, not a default

Diagnosis has just told you which **symbols** you will change. Before writing code, run
**`orca-coder-patch-audit`** step 0 with those symbols and obey its `verdict.decision`.

The trap it closes: a capability is fixed as one patch, a second problem in the SAME area appears
later, and it takes a new number because nobody remembered the first — two patches then own the
same symbols. Pass symbols, not just the feature name; a name alone cannot reach a verdict, and
guessing "new patch" from a name is exactly how that happens.

- `EXTEND_EXISTING` → **no new number.** Same path as "a fix to existing patch logic" below:
  restack *that* boundary and re-export the series.
- `NEW_PATCH_BUT_CHECK` → read the patches it lists. New number only if none covers this
  capability, and the CHANGELOG entry must name the ones you considered and why this is separate.
- `NEW_PATCH` → new number.
- `CANNOT_DECIDE` → your paths/symbols are not in the map. Fix them and re-run; never proceed.

Sharing a *file* with an existing patch is normal here (`web-preload-api.ts` is in 11 of 13) and
is not a reason to extend. Sharing a *symbol* is. Patch size is never the argument — restacking
cost is work, not correctness.

## Implement + export

1. Edit + commit in `<fork>`. New capability → new number. A fix to existing patch logic →
   restack that boundary and re-export the series (never a new number).
2. Export the boundary diff — **both ends explicit, never `HEAD`:**
   ```bash
   cd <fork>
   git diff <prev-boundary> <this-boundary> > <repo>/apps/orca-coder/patches/000N-<capability>.patch
   ```

   `git diff <prev-boundary> HEAD` is correct **only for the newest patch** and silently wrong for
   every other one: it captures every later patch too, and the post-image blob it records is
   HEAD's. Patches `0011`–`0013` shipped that way and were re-exported on 2026-07-26.
   Measured symptoms — none of which `git apply` alone reveals, and `--3way` does NOT reject them:
   the `index` lines named blobs absent at that boundary (3 wrong across the series, now 0),
   forward apply reported `offset -50 lines`, reverse apply drifted, and `0001..000N` no longer
   reproduced boundary N's tree. `HEAD` here is the single most expensive typo in this workflow.

3. **Re-export the whole series after a restack**, not just the patch you touched: restacking a
   mid-series boundary rewrites every boundary after it. Same two-ended command per patch.

4. Prove the exports are their boundaries before handing off — see `orca-coder-patch-verify`
   step 2, which now checks byte-identity, not just that the series applies.

## Merging two patches into one

`orca-coder-patch-audit` prescribes this when `patch_overlap` shows two patches sharing **symbols**
in one capability. It is a rewrite of history, so do it deliberately:

```bash
cd <fork>
git branch -f backup/pre-merge-$(git rev-parse --short HEAD) HEAD    # always, first
git rebase -i <boundary before the EARLIER patch>                    # squash the later into the earlier
```

Then: re-export **every** patch from the merge point onward with the two-ended command above,
delete the now-absent patch file, renumber per the policy below, and fold both CHANGELOG entries
into one whose `Placement` line records the merge and whose `Acceptance` lists **both** patches'
tests. Merging is only justified when neither capability's acceptance test can pass without the
other — if each passes alone, they are two capabilities that happen to share a file, and
`CLAUDE.md` §0 invariant 2 says leave them alone.

Verify then has to prove more than usual: the union of both acceptance tests, plus step 2a on the
whole series, because every boundary after the merge point moved.

## Renumbering — when a patch is dropped or merged away

**Numbers are positions, not identities.** They set `git apply` order, and the Dockerfile applies
`patches/*.patch` in filename order, so a gap is harmless to the build but a lie to the reader.

- **Renumber the tail** so the sequence stays dense: `0007` drops → `0008`–`000N` shift down one.
  Rename the files, re-export each (their boundaries did not move, but their names did), and update
  every CHANGELOG heading.
- **The CHANGELOG keeps the dropped entry**, retitled `## 0007 — <capability> (dropped in <tag>)`
  with a `**Dropped:** upstream now ships this — <how it was proved>` line. Never delete history:
  the next bump needs to know this was once necessary and why it stopped being.
- **Never reuse a number** for a different capability. If `0007` was dropped and the tail shifted,
  the new `0007` is the old `0008` — the CHANGELOG makes that traceable, which is exactly why the
  dropped entry stays.
- A patch that carries an **upstream** fix is the one exception: keep it at `0000` so it can be
  deleted without touching anything else the moment upstream lands it (`apps/orca-coder/CLAUDE.md`
  §3 records why `0000` is gone today).

→ Hand to **orca-coder-patch-verify**.
