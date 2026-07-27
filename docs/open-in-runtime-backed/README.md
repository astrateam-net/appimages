# Open In entries should be runtime-backed, not seeded

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

**Question this answers:** patch `0008` made browser-editor "Open in" entries work, and the Coder
module seeds them correctly — so why does a developer who already used the workspace still not see
them, and what is the actual fix?

**Short answer:** because `openInApplications` is currently a *seeded* setting, and seeding runs
exactly once per browser per origin, forever. An "Open in" entry is not a preference — it is a
fact about the host — so it belongs on the runtime-backed path the web client already has for
other keys. Moving it there removes the browser from the loop entirely.

**Parked, not scheduled.** Written 2026-07-25 after `0008` was verified working end to end. This
exists so the reasoning survives to whenever the decision gets made.

---

## 1. What was verified live

Workspace `ceo/harlequin-catfish-23`, 2026-07-25, after a rebuild.

Everything on the host side was correct:

| Check | Result |
|---|---|
| Installed build | `v1.4.155`, asset ETag `0x8DEEA9780414CAA` — exact match with the published release |
| Patch `0008` in bundle | all four marker strings present (`Web URL`, `Opens this URL instead of the command`, `That app has an invalid URL`, `Set a command or a URL`) |
| serve | shim-launched, `LISTEN 127.0.0.1:6799`, `/web-index.html` 200, `/trusted-session` 200 |
| code-server / vscode-web | live on 13337 (302) and 13338 (200) |
| Module seed | `applied-settings.json` carries both URL entries |
| Runtime store | holds them normalized: `{id, label, command: "", url}` |

That `command: ""` is worth keeping in the record — it is the shape the pre-fix `.strict()` seed
schema rejected as an unknown key, dropping the whole list. The store never emits the hand-written
`{id, label, url}` shape that the old tests asserted against.

**And the tile showed neither entry.** Only `VS Code — Local only` and `Finder — Local only`.

## 2. The tell was the theme, not the menu

The module seeds `"theme": "light"`. The tile was rendering dark. So it was not an
`openInApplications` problem — *nothing* from the seed had applied.

Root cause, [`web-preload-api.ts`](../../apps/orca-coder/patches/0007-web-runtime-seeded-settings.patch):

```js
const isFirstVisit = window.localStorage.getItem('orca.web.settings.v1') === null
…
if (isFirstVisit) {
  Object.assign(runtimeSettings, pickRuntimeSeededSettings(result.settings))
}
```

**localStorage lives in the browser, not the workspace.** Rebuilding the workspace re-seeds
`orca-data.json` on the host but cannot touch what the browser already stored. Coder workspace
names are stable across rebuilds, so the origin is stable, so the blob is stable — and
`isFirstVisit` is false for that browser from its very first visit onward, permanently.

Confirmed by clearing the key:

```js
localStorage.removeItem('orca.web.settings.v1'); location.reload()
```

After which both entries appeared, enabled, with the VS Code mark, and **code-server opened at the
worktree path**. `0008` itself is good. The delivery mechanism is what is wrong.

## 3. Why "add a Clear cache button" is the wrong fix

It would work. It is still wrong:

- it makes a **user** perform a **provisioning** action, and they must know to repeat it every time
  the template changes;
- `orca.web.settings.v1` is not a cache — it is the entire web settings blob, so clearing it to
  pick up two menu entries resets every preference the user ever set;
- it does not scale past one person remembering;
- and it leaves the semantics wrong: Open In stays "a browser-local preference that happens to be
  initialised from the workspace".

Worth having as a debug affordance. Not as the mechanism.

## 4. The mechanism already exists

The web client has **two** paths, and Open In is in the wrong one:

| | Read | Written back | Keys |
|---|---|---|---|
| **A. Runtime-backed** | every load | yes, via `settings.update` | `experimentalNewWorktreeCardStyle`, `compactWorktreeCards`, `minimaxGroupId`, `minimaxUsageModels`, `prBotAuthorOverrides` |
| **B. Seeded (`0007`)** | once, only if localStorage is empty | never | theme, appearance, experimental flags, **`openInApplications`** |

In path A the workspace store is the source of truth and localStorage is merely a cache.

The boundary `0007` drew — LOOK and CAPABILITY seed, SIZE and ERGONOMICS stay per-device — is
still right for what it covers. `openInApplications` just does not belong on either side of it. A
theme is a taste. `https://code-server--<workspace>--<owner>.<domain>/?folder={path}` is a fact
about the host, it changes when the template changes, and it must reach people who already opened
the tile.

## 5. Sketch of the change

1. Add `openInApplications` to the always-applied read block in `getRuntimeBackedStoredSettings`.
2. Add it to `syncRuntimeBackedSettings`, so edits made in the tile's Settings persist **to the
   workspace store** rather than being reverted on the next load.
3. Remove it from `RUNTIME_SEEDED_SETTING_SCHEMA` — it stops being a seed.

Desktop is untouched (local persistence, not this path). Mobile keeps the withholding added in
`0008`. Net effect: change the Coder module, restart, everyone gets it on next reload — no
localStorage dependency, no first-visit gate, no clear-cache button.

### Open decisions

- **Write-back means the workspace changes, not just the browser.** A Coder workspace is
  `share = "owner"`, so it is one person — but the semantics should be stated deliberately rather
  than fallen into.
- **Command entries.** `0007` filters out any entry carrying a real `command` so a runtime cannot
  hand a client something to execute. On the web that is moot — the browser has no OS to spawn
  into, and such an entry renders disabled "Local only". Keep the filter (tile shows URL entries
  only), or drop it and let a desktop-created `code` entry appear greyed out?

### The alternative, if seeding is kept

A seed **generation stamp**: the runtime declares a seed revision, the client records the last one
it applied, and re-seeds when the revision increases — still never overwriting a key the user has
touched themselves. This fixes the same symptom for *every* seeded key, not just Open In, and
keeps "defaults, not policy" intact.

The two are not exclusive. Runtime-backing Open In is the right answer for Open In; the generation
stamp is the right answer for theme and feature flags, which genuinely are defaults.
