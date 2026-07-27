# Settings provisioning — declaring Orca's configuration at workspace-create time

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

**Question this answers:** can a Coder workspace bring Orca up already configured — the theme we
want, the experimental features we want — so nobody re-clicks the same toggles after every
workspace create?

**Short answer:** not with stock Orca. The web client's settings live in the *browser*, not on the
workspace, so nothing you write on the workspace filesystem reaches them. Patch `0007` adds a
seed path. Everything below is the evidence for that, verified live on 2026-07-25 against
`v1.4.153` in workspace `ceo/harlequin-catfish-23`.

---

## 1. Where settings actually live

```
~/.config/orca/                                   ← userData; lowercase `orca`, not `Orca`
├── orca-profile-index.json                       ← { activeProfileId: "local-default", … }
└── profiles/
    └── local-default/
        ├── orca-data.json                        ← THE store
        └── orca-data.json.bak.{0,1,2}
```

Two traps, both confirmed on the live box:

- **Lowercase `orca`.** `productName` is `Orca`, but `initDataPath()` runs *before*
  `app.setName('Orca')` on purpose (`src/main/persistence.ts`, comment above `_dataFile`), so the
  path comes from package.json's `name` — `orca`. The CLI's own resolver mirrors it
  (`src/cli/runtime/metadata.ts`, `$XDG_CONFIG_HOME/orca`). Do not look in `~/.config/Orca`, and
  do not look in `~/.config/orca-coder` — the AppImage renames only the release asset, never the app.
- **There is a profile layer.** The store is *not* at `~/.config/orca/orca-data.json`. That is the
  legacy path (`src/main/orca-profiles/profile-storage-paths.ts`, `LEGACY_DATA_FILE_NAME`); the
  live file is under `profiles/<activeProfileId>/`. Read `activeProfileId` out of
  `orca-profile-index.json` — never hardcode `local-default`.

### What's in it

`PersistedState` (`src/shared/types.ts`) has ~25 top-level blocks. The interesting ones:

| Block | Holds |
|---|---|
| `settings` | `GlobalSettings` — **183 keys** in the type, 167 persisted on a fresh profile |
| `repos`, `projects`, `projectGroups` | registered repos, sidebar shape |
| `sshTargets`, `deletedSshConfigAliases` | SSH hosts |
| `automations`, `automationRuns` | automations |
| `onboarding` | `closedAt`, `outcome`, and a 12-item `checklist` incl. `dismissed` |
| `workspaceSession`, `worktreeMeta`, `worktreeLineageById` | live session + worktree registry |

`GlobalSettings` spans appearance, ~45 terminal keys, editor, git/worktrees, agents, UI chrome,
diff/source-control, confirmations, network, keybindings, notifications, telemetry, integrations.
It also holds **credentials** — `codexManagedAccounts`, `claudeManagedAccounts`,
`opencodeSessionCookie`. Anything that widens what leaves this object must be an allowlist.

### Seeding the file works — with one rule

`loadState` deep-merges a partial file over defaults:

```js
settings: { ...defaults.settings, ...stripLegacyTerminalScrollbackBytes(parsed.settings), … }
```

So a file holding only the keys you care about is valid, and keys upstream adds later keep their
defaults. **Write it only while serve is stopped** — a running serve holds state in memory and
overwrites the file on its next save.

Verified live: an edit made while serve was running survived 20s untouched *and* survived serve's
quit (mtime unchanged), and the next start loaded it. Serve writes on state change, not on a timer.

---

## 2. Why that isn't enough — the web client keeps settings in the browser

This is the finding that kills the obvious plan.

`src/renderer/src/web/web-preload-api.ts`:

```js
const SETTINGS_STORAGE_KEY = 'orca.web.settings.v1'
```

The web client's settings live in **localStorage**. From the runtime it pulls exactly five keys
(`getRuntimeBackedStoredSettings`):

```
experimentalNewWorktreeCardStyle   compactWorktreeCards
minimaxGroupId                     minimaxUsageModels
prBotAuthorOverrides
```

`mergeSettings(local, runtimeSettings)` — local is the base, those five overlay it. Writes go the
same way (`syncRuntimeBackedSettings`): only those five reach the runtime, the rest stay in the
browser.

`theme` is not among them. **For the tile, `orca-data.json` governs almost nothing.** Settings are
per-browser, per-origin, on the user's own machine — Terraform, Coder and the workspace filesystem
cannot reach them.

### Proven empirically

| Step | Result |
|---|---|
| Wrote `theme: light` to `orca-data.json`, serve stopped, restarted | file loaded, UI unchanged |
| Wrote `theme: dark` + 4 experimental flags, serve running | UI unchanged |
| Set `theme: light` again, browser fully reloaded | UI unchanged |

Restarting serve was never going to fix it. The value the UI renders never came from that file.

---

## 3. What is schema-validated (and what isn't)

There is no zod schema over the *store*. `settings` is a TypeScript type plus hand-written
normalizers for ~15 specific keys; only `workspaceSession` and the per-host session partitions are
zod-validated at read (`persistence.ts`).

There **is** a zod schema on the RPC write path — and it is the hard gate:

```
src/main/runtime/rpc/methods/client-ui-schemas.ts   SettingsUpdate = z.object({…}).strict()
```

`.strict()`, **16 keys**. An unknown key doesn't get dropped, it rejects the whole call. Four
allowlists gate this area in total:

| Layer | Location | Keys (stock) |
|---|---|---|
| Server read | `orca-runtime.ts` `getClientSettings()` | 17 |
| Server write | `orca-runtime.ts` `updateClientSettings()` | 16 |
| RPC params (`.strict()`) | `client-ui-schemas.ts` `SettingsUpdate` | 16 |
| Web client | `web-preload-api.ts` get/sync | 5 |

**Consequence for a version-pinned validator:** there is no runtime schema you can borrow to check
a Terraform-declared settings map. The contract has to be derived from the pinned source. The
cheapest version-exact contract is empirical — a fresh profile's `orca-data.json` *is* the key set
with its default values for that build, so it can be extracted in CI and published beside the
AppImage.

---

## 4. Patch 0007 — seed, don't override

`0007-web-runtime-seeded-settings.patch`. Read side only; the write path is untouched.

**Semantics: defaults, not policy.** `settings.get` now also returns a list of seedable keys, and
the web client adopts them **exactly once** — on a browser's first visit, when localStorage holds
no settings blob yet. After that the browser's copy wins, the user's choices stick, and nothing is
re-imposed on later loads. "The workspace decided" never fights "the user decided".

Nothing is written back to the runtime, so a user flipping the theme in one browser does not
change what the next fresh client seeds.

**The boundary rule:**

- **LOOK and CAPABILITY seed from the runtime** — a workspace declares its theme and its enabled
  feature set, every fresh client starts there.
- **SIZE and ERGONOMICS stay per-device** — zoom, window bounds, font sizes are deliberately
  absent. The same runtime is driven from a laptop, an external monitor and a phone; each wants
  its own answer. *"As a user I want to control zoom from backend settings"* is not a user story.
- **CREDENTIALS never appear** — they sit in the same `GlobalSettings` object; listing one would
  hand it to every client that opens the tile.

The last two are enforced by `src/shared/runtime-seeded-settings.test.ts`, not by review.

### Seeded keys

```
Appearance    theme · appIcon · appFontFamily · uiLanguage
              leftSidebarAppearanceMode · leftSidebarTintColor · leftSidebarTintOpacity
              terminalThemeDark · terminalThemeLight · terminalUseSeparateLightTheme

Experimental  experimentalActivity · experimentalAgentDashboardPopout
              experimentalAgentHibernation · agentHibernationIdleMs
              experimentalEphemeralVms · experimentalNativeChat
              openAgentTabsInChatByDefault · experimentalPet
              experimentalTerminalAttention · experimentalMobile · mobileEmulatorEnabled
```

### Files

| File | Change |
|---|---|
| `src/shared/runtime-seeded-settings.ts` | new — the allowlist, its zod value schemas, `pickRuntimeSeededSettings()` |
| `src/shared/runtime-seeded-settings.test.ts` | new — credential + per-device exclusions, schema rejection |
| `src/main/runtime/orca-runtime.ts` | `getClientSettings()` also returns the seeded keys |
| `src/renderer/src/web/web-preload-api.ts` | adopt them when `localStorage[SETTINGS_STORAGE_KEY] === null` |

`isFirstVisit` is read **before** `getStoredSettings()`, because the first successful
`settings.get` writes the blob — so the condition is true exactly once per browser.

---

## 5. Using it from the Coder module

1. Module gains a `settings` variable (map / raw JSON) — the workspace's declared defaults.
2. `templatefile` renders it to a seed file under the module dir.
3. `install.sh` merges it into `profiles/<activeProfileId>/orca-data.json` **before** the serve
   launch block, and only when serve isn't already up. Merge key-by-key rather than replacing
   `settings` wholesale.
4. Resolve the profile id from `orca-profile-index.json`; don't hardcode it.

**Never point `workspace-files` at `orca-data.json` directly.** It writes verbatim on every
workspace start, and that file also holds `repos`, `worktreeMeta`, `workspaceSession` and the
paired-device registry — overwriting it each start would wipe the worktree registry and paired
phones. Use it to deliver the *seed*, and let `install.sh` do the merge.

Agent CLI auth (`~/.claude`, `~/.codex`) is not in this store — separate files, belongs in
`workspace-files` or the gold image.

---

## 6. The v1.4.155 bump — and an upstream landmine

Bumped 2026-07-25 from `v1.4.153` to `v1.4.155` (latest stable). There is no `v1.4.154` on the
remote, consistent with the fabricated-tag warning in `apps/orca-coder/CLAUDE.md`.

The rebase itself was clean — of the 41 files our patches touch, only four changed between the
tags, and `git rebase --onto` replayed all nine commits with zero conflicts. All eight patches
apply on pristine `v1.4.155`; all three typechecks and 32 focused tests pass.

**But `v1.4.155` does not build from source as shipped.** It added a caller passing `tabIndex={0}`
to `DetachedHeadBadge` without widening `DetachedHeadBadgeProps`, so `pnpm typecheck` fails
TS2322 — and `build:desktop` runs `typecheck` first. Every tag through `v1.4.156-rc.2` has the
same mismatch; upstream fixed it on `main` after the release, unreleased at the time of writing.

`0000-upstream-detached-head-badge-tabindex.patch` carries that fix. **It is the only patch in
the series that is not ours — drop it the moment a tag declares the prop.** Details and the
per-bump check are in `apps/orca-coder/CLAUDE.md` §3.

Gotcha worth remembering: `rm -f config/*.tsbuildinfo` before typechecking after a rebase. Stale
incremental build info reported the error as still present *after* it was fixed, which is a
great way to talk yourself out of a correct fix.

### Renovate did not catch this bump

Checked the same day: the config is fine — `.renovaterc.json5` is a supported filename
(renovate `lib/config/app-strings.ts`, `.renovaterc.json{,c,5}`), the custom-manager regex does
match `docker-bake.hcl` and extracts `depName=stablyai/orca` / `currentValue=v1.4.153`, and the
preset's `minimumReleaseAge: "3 days"` is scoped to `matchManagers: ["github-actions"]` so it
wasn't holding anything back. The Renovate app is installed org-wide (`repository_selection:
all`) and issues are enabled.

Yet the repo has zero PRs, zero `renovate/*` branches, and no **"Renovate Dashboard 🤖"** issue —
which `:dependencyDashboard` creates on the first run, always. So Renovate has never executed
here; the repo is one day old (created 2026-07-24) and the answer lives in the Mend job log at
`developer.mend.io/github/astrateam-net/appimages`, not in our config.

The fail-loud path it would feed *is* correctly wired: a PR touching
`apps/orca-coder/docker-bake.hcl` matches `pull-request.yaml`'s `paths: ["apps/**"]`, resolves to
the `orca-coder` app, and `app-builder.yaml` runs `docker/bake-action` → the Dockerfile's
`git apply` → red build on a broken patch.
