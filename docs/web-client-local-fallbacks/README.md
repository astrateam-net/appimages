# "Not a named runtime" is not the same as "this machine"

> ### ⚠️ Patch numbers in this document predate the 2026-07-27 renumbering
>
> The series was consolidated **14 → 11** (now 12) in `f218528`: two merges collapsed three patches.
> Every number below may name a different capability today. Authoritative map — old → current:
>
> | This doc says | Was | Today |
> |---|---|---|
> | floating-workspace owner, local-fallback floor, active-runtime pin | `0009` / `0011` / `0012`-ish | all **`0008`** (`web-execution-owner`) |
> | mobile pairing, runtime share links | two patches | both **`0002`** (`web-pairing-credentials`) |
> | directory picker | `0006` | **`0005`** |
> | seeded settings | `0007` | **`0006`** |
> | "Open in" browser-editor URLs | `0008` | **`0007`** |
> | usage analytics | `0013` | **`0010`** |
> | — | did not exist | **`0011`** agent-status bridge, **`0012`** headless agent cold restore |
>
> Resolve any number against `ls apps/orca-coder/patches/` before acting on it. The *reasoning* in
> this document is still good; only the labels rotted.

**Question this answers:** in a Coder workspace tile, a floating-workspace terminal refused to
start with *"Local PTYs are unavailable in the web client"*, markdown would not open or create,
the embedded browser rendered its chrome over a blank page, launching an agent from the
tab-create menu failed with *"No renderer window available"*, and a freshly created project's
terminal failed until the browser was reloaded. Five unrelated-looking failures — how many bugs?

**Short answer:** one shape, five places. Code all over Orca treats *"no named runtime
environment"* as *"therefore the shell / window / file dialog is on THIS machine."* That is true
for a desktop app driving a remote runtime. It is never true for a web client the runtime itself
is serving, where **local and runtime are the same host** and every local affordance is a stub.

Fixed in patch `0009` on `v1.4.156`. This document records what was verified, and what was not.

---

## 1. What was observed

Live on `ceo/harlequin-catfish-23`, tile at `orca--harlequin-catfish-23--ceo.portal.astrateam.net`.

| Action | Result | Cause |
|---|---|---|
| Terminal in a **worktree** | works | resolves to the runtime |
| Terminal in the **floating workspace** | *Local PTYs are unavailable in the web client* | §2 |
| New / Open **Markdown Note** | nothing happens, no error | §3 |
| **Browser** → any URL, public or private | chrome renders, page area blank | §4 |
| **Claude/Codex** from the tab-create menu | *No renderer window available* | §5 |
| Terminal in a **just-created project** | same PTY toast; **works after reload** | §6 |
| Create worktree **with** an agent | works | never took the broken path |

That last row is the most informative one in the table: worktree-creation-with-agent goes through
the runtime, so it always worked. Everything that broke had fallen back to "local" first.

---

## 2. The mechanism

`window.api.pty` is a stub in the web client. Its `spawn` always rejects
(`src/renderer/src/web/web-preload-api.ts`):

```ts
spawn: () => Promise.reject(new Error('Local PTYs are unavailable in the web client.')),
```

That string *is* the toast, verbatim. Nothing failed to find a shell — the call was refused before
it left the renderer. Real web terminals never touch it; they ride the `terminal.*` runtime RPC.
Which one a pane gets is decided by one ternary in `pty-connection.ts`, whose fallback encodes
*"no named runtime environment, therefore I am the desktop app."*

**Why the floating workspace specifically.** Not because it "has no id" — because it is *pinned*
local, deliberately, in three places at once:

- `getRuntimeEnvironmentIdForWorktree` returns `null` **unconditionally** for
  `FLOATING_TERMINAL_WORKTREE_ID`; `getExecutionHostIdForWorktree` returns `'local'`.
- the browser passes `browserRuntimeEnvironmentId: null`, with a comment stating the rule outright.
- markdown passes `LOCAL_RUNTIME_SETTINGS`.

That rule is *correct on the desktop app*: the floating workspace is a deliberate local scratchpad
that stays yours even when a remote runtime is focused. It is only wrong in a browser.

> **Upstream knew.** `web-preload-api.ts` ships `floatingTerminalEnabled: false` as a web-client
> default. Upstream's answer was to *hide the surface in the web client*. It is visible in our tile
> because the setting is user-toggleable and was switched on. This was never an unwritten branch.

---

## 3. Markdown — traced

`getFloatingMarkdownDirectory` stubs to `''`. The panel guards `if (!markdownCwd) return`, and
`''` is falsy — so New Markdown Note returned silently, with no toast and no console error. Open
Markdown Note calls `pickFloatingMarkdownDocument`, a native OS dialog stubbed to `null`.

Both stubs, one falsy value, exactly matching "clicking does nothing".

---

## 4. The browser was never a separate mystery

An earlier draft of this document called the browser unexplained, listed `x-frame-options` and
IPv6 egress as dead theories, and recommended reading the web console next. All of that was
wasted motion. The cause was three lines away in the same file as the terminal bug:

```ts
// Why: browser tabs in the floating workspace share the same local-only
// ownership rule as floating terminals.
browserRuntimeEnvironmentId: null
```

`browser.ts` maps `null` → `LOCAL_EXECUTION_HOST_ID`. A client-local browser pane needs a
`<webview>`, which the web client does not have. Hence: chrome renders, page area blank —
for `google.com` and `10.1.110.11:8006` alike, which is exactly why the framing theory never fit.

**Was this switched off upstream, or broken?** Neither, exactly. It is a deliberate design rule —
the floating browser follows the floating terminal's local-only ownership — and the rule is sound
until the client *is* the runtime's own browser. Upstream never had to confront that, because it
hides the whole floating workspace in the web client (§2). So this was not a bug in their product
and not a feature flag; it was a premise that stopped holding in our topology.

**Correction — the floating workspace was not the whole story.** A per-worktree browser tab is not
pinned local in code: `openNewBrowserTabInActiveWorkspace` routes to the runtime's offscreen
backend *when `getRuntimeEnvironmentIdForWorktree` returns an id*, and falls back to a
client-local tab when it returns null. Testing showed the browser blank in an ordinary project
too, and markdown in that same project failing with *"Couldn't verify which host owns this file."*

Both point at one thing, and it is not the floating workspace: **ownership is not resolving for
ordinary worktrees in the tile.** When it returns null, the browser silently takes the local
fallback (blank pane), `editor-file-operation-owner` throws the host-ownership error, and the file
explorer shows "No files in this workspace". Three surfaces, one missing answer.

An earlier revision of this document asserted the per-worktree browser worked. That was inferred
from reading the routing code, not observed. It was wrong — see §12.

**Lesson worth keeping:** the blank page was reproducible on *every* URL. A cause that is
URL-independent cannot be about any particular URL. Two theories were tested and discarded before
anyone read the code that constructs the pane.

---

## 5. Focus is a request, not a guarantee

`createTerminal` chooses between a background (headless-capable) branch and a renderer-IPC branch:

```ts
const shouldCreateInBackground =
  worktreeSelector !== undefined &&
  (Boolean(opts.agentSessionClaim) ||
    (!requiresRendererFocus && opts.rendererBacked !== true) ||
    (opts.rendererBacked === true && rendererWindow === null))
```

"Launch Claude in a new terminal" asks for focus. `requiresRendererFocus` is therefore true, no
clause matches, and control falls to `getAuthoritativeWindow()` — which throws *"No renderer window
available"* on a headless `orca serve`.

The third clause already grants headless callers a background terminal; it just never considered
that a *focused* caller could also be headless. Focused creates now take the background branch,
which already honors `presentation === 'focused'` through `notifier.revealTerminalSession` and
degrades to a warning if the reveal fails — so nothing is lost by routing them there.

---

## 6. The new-project failure — mitigated, not diagnosed

**Be precise about this one.** The exact reason ownership resolves local for a few seconds after
project creation was *not* established. The evidence says it is a hydration race: the worktree and
repo rows land in the store before they carry their runtime host, and a reload fixes it because
hydration then supplies the host. But that was inferred from the shape, not proven.

What `0009` does is put a **floor** under the fallback rather than chase the race: a web client
that reaches `createIpcPtyTransport` addresses the runtime that served the page instead of a
rejecting stub. Whatever made ownership come out local, the connected runtime is a better
destination than an exception.

This is a backstop, and it is labelled as one in the code. It also covers any *other* caller that
reaches the same fallback — which was an open question in the earlier draft and is now moot.

Note that `v1.4.156` shipped `fix(runtime): stop the headless hydration repo gate from dropping
every tab` (#10437, #10443), in exactly this area. The race may already be gone upstream; the
floor is cheap either way.

---

## 7. Why one ownership fix covered so much

The terminal transport, the browser slice, and the setup/default-tab automations all route through
`getRuntimeEnvironmentIdForWorktree`. Fixing ownership there carried all three onto runtime paths
that already existed, rather than adding new ones.

The automations mattered more than they looked. `launchWorktreeBackgroundTerminals` already returns
early for runtime-owned worktrees so the server materializes setup scripts and default tabs — but
when ownership came out local it fell through to `pty.spawn`, where default tabs were swallowed by
a `console.warn` and setup scripts threw. Silent failure, and nobody had reported it.

**The runtime needed no changes.** It already answers the floating sentinel with the home dir
(`resolveTerminalWorkspaceLaunchScope`), and `browser.tabCreate`'s `worktree` parameter is
optional, so the floating browser omits it and gets an unscoped offscreen page. The floating
sentinel is terminal-only on the runtime and would have thrown in `resolveWorktreeSelector` —
omitting the parameter sidesteps that instead of teaching the server a new concept.

---

## 8. Markdown, end to end

Nothing blocked file creation. `getFloatingMarkdownDirectory` returns `''` in the web client, and
the panel's first line is `if (!markdownCwd) return`. Empty string is falsy, so it gave up *before*
attempting anything — it never reached "where do I save this", it concluded there was nowhere and
returned. That is why there was no error to find.

Both halves now mirror what the desktop app does:

- **New** creates `untitled.md` in the app-owned floating-workspace directory, which
  `floatingWorkspace.markdownDirectory` resolves on the server via the same
  `ensureDefaultFloatingWorkspacePath` helper the desktop handler calls.
- **Open** uses the host filesystem browser — the same one behind *Add a project → Browse folder*,
  which already lists the workspace host. It only ever selected directories, so it gained an opt-in
  `selectableFileExtensions` mode: pass extensions and a click on a matching file selects it,
  directories still navigate, and the "Select folder" confirm is hidden because in file mode the
  clicked file *is* the selection. Omit the prop and it behaves exactly as before, so the
  "Add a project" flow is untouched.

## 8b. `selector_not_found` — the second layer, found by testing

Routing the floating workspace at the runtime worked, and immediately exposed the next layer.
The floating terminal came up; the browser pane reached the runtime ("Remote browser — rendered
from the active runtime server") and then showed `selector_not_found`; New Markdown showed the
same. That is not a CSS selector — it is Orca's *worktree* selector.

**The floating sentinel is terminal-only on the server.** It resolves in
`resolveTerminalWorkspaceLaunchScope` (which is exactly why terminals worked first), and every
other workspace API goes through `resolveWorktreeSelector`, which searches real worktrees and
throws. Upstream states this outright in a comment: *"the floating sentinel is terminal-only — no
backing repo/worktree record for other workspace APIs."* That comment was read during the original
diagnosis and its consequence was not followed through.

- **Browser** — client-side. `BrowserPane` derives one selector used by ~15 RPCs. `tabCreate`
  already omitted it, so the tab appeared and the *screencast subscribe* failed, which is why the
  error rendered inside a pane that otherwise looked correct.
- **Markdown** — server-side, and it could not be fixed the same way: file RPCs address
  `worktree` + `relativePath`, so omitting the worktree leaves the server with no root to join
  against. `resolveRuntimeFileTarget` now answers the sentinel with the app-owned floating
  workspace directory.

**Worth noting how this was found.** Not by reading — by deploying and clicking. The terminal
working while the browser failed, both on the same ownership fix, is what localized it to the
server's selector resolution rather than the client's routing.

## 9. Still broken — the ordinary-workspace ownership failure

**This is now the biggest open item, and it is bigger than the floating workspace.** In an
ordinary project in the tile: the browser renders blank, markdown open throws *"Couldn't verify
which host owns this file"*, and the file explorer says "No files in this workspace". All three
are what happens when `getRuntimeEnvironmentIdForWorktree` / `resolveWorktreeOperationRoute`
cannot name an owner for a worktree that plainly belongs to the connected runtime.

Exact throw sites are known — `editor-file-operation-owner.ts` rejects when `route` is null or
when the file's `ownerHint` disagrees with the resolved route, and `isWorktreePublished` requires
the worktree to appear in `worktreesByRepo` or `detectedWorktreesByRepo`. What is *not* known is
which of those inputs is missing at runtime.

`0009`'s IPC floor rescues the terminal in this state, because the terminal is the one surface
that can fall back to "just use the connected runtime". The browser and the editor cannot: they
fail closed by design, which is correct behavior given a missing owner.

**Do not guess the fix from source.** Two conclusions in earlier revisions of this document were
inferred from reading and both were wrong (§4, §6). The next step is the store state from a live
tile — `worktreesByRepo`, `detectedWorktreesByRepo`, `repos`, and `settings.activeRuntimeEnvironmentId`
for the failing worktree — which says in one look whether the rows are absent, present without a
host stamp, or present with a conflicting one.

- **Browser Settings…** in the floating panel does nothing. Never investigated.

## 10. Not yet verified live

Everything above is source-verified: typecheck clean, 8004 tests passing, all nine patches applying
on pristine `v1.4.156`. None of it has been exercised in the tile yet. The floating browser is the
least certain part — it stages through the session snapshot with an unscoped page, and that is the
one behavior that cannot be proven by reading.

---

## 12. Two wrong conclusions, and why

Both came from the same habit: reading routing code, seeing a correct-looking path, and reporting
that the feature therefore works.

1. *"The browser is unexplained and not this bug."* It was three lines away in the file already
   being edited, and two network theories were tested before anyone read the code that builds the
   pane.
2. *"The per-worktree browser works."* The routing code does contain a runtime path. It just is
   not the path taken, because the condition guarding it fails.

A path existing in source is not evidence it is taken. Where a claim is about behavior, it needs
an observation — either a test that exercises it or a live check. Claims in this document are now
marked as verified, inferred, or unknown, and inferred claims are not to be relied on.

## 13. What this cost, and the rule that would have saved it

Four patches have now each hand-rolled some version of *"is the thing I am about to do actually
local?"* — `0006` (directory picker), `0008` (Open In), and `0009` twice over. Each was discovered
separately, by a user hitting a dead surface.

The generalizable rule, which `0008` stated and nobody applied outward:

> the guards exist because `command` spawns a process on THIS machine against a path that belongs
> to another one. A URL has neither problem.

**For the next one:** when a web-client surface is dead, do not start by reading the feature. Grep
for what the code believes about locality — `=== null` on a runtime id, `'local'`, `isWebClient`,
`window.api.<ns>` — and check whether the runtime already has an RPC for it. In `0009` every fix
turned out to be reachable from an existing runtime path; the entire patch is ownership decisions
and one new RPC method that wraps a helper the desktop handler already called.
