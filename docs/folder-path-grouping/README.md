# Grouping projects by folder path, triggered without a human

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

**Question this answers:** a Coder workspace can clone repositories anywhere at create time. Can
Orca pick them up on its own, and put them into groups derived from the folder they sit in — so a
provisioned workspace opens with its sidebar already organized?

**Short answer:** every piece exists except two — a *scriptable trigger* and the *rule*. Orca has a
scanner, a group model and an import that assigns repos to groups, but the only ways to invoke them
are a UI action or a desktop IPC call, and the grouping it does implement is not the one we want.
What is needed is one command our provisioning script can run.

**Parked, not scheduled.** Written 2026-07-25. Separate from
[open-in-runtime-backed](../open-in-runtime-backed/README.md) — different problem, same workspace.

---

## 1. The rule we want

A root directory, and **the group is always the first path segment after it.** Nothing deeper ever
becomes a group.

Root: `/home/coder/orca/projects`

| Path | Group | Project |
|---|---|---|
| `…/projects/Gitlab/tower` | `Gitlab` | `tower` |
| `…/projects/Gitlab/proxmox-foundation` | `Gitlab` | `proxmox-foundation` |
| `…/projects/Github/appimages` | `Github` | `appimages` |
| `…/projects/Gitlab/abc/tower` | `Gitlab` | `tower` |

The last row is the whole point: `abc` is an organizational folder on disk, not a group. Depth
below the first segment is invisible to the sidebar.

## 2. Why this is not just "call the existing import"

Orca already has `importNestedRepos({ parentPath, groupName, mode: 'group' })`, and it does assign
repos to a group. But its resolver
([`nested-repo-import.ts`](../../apps/orca-coder/patches/0008-web-open-in-browser-editor-urls.patch))
mirrors **every** folder level as a nested group — `ensureFolderScopeGroup` walks the relative path
and creates a group per scope, chained by `parentGroupId`.

So for `…/projects/Gitlab/abc/tower`, pointing it at `…/projects` yields:

```
projects            ← root group, created from the parentPath
└── Gitlab
    └── abc         ← we do not want this
        └── tower
```

And pointing it at `…/projects/Gitlab` yields `Gitlab > abc > tower`. Either way `abc` becomes a
group. There is no option to flatten.

That is a reasonable default for someone importing an arbitrary folder tree. It is not our rule.
**A flat one-level resolver is the actual new thing here** — the rest is plumbing that exists.

## 3. What exists today

| Piece | Where | Reusable as-is |
|---|---|---|
| Folder scanner | `scanNestedRepos()` | yes |
| Group records | `ProjectGroup`, `createProjectGroup` | yes |
| Membership | `repo.projectGroupId`, `moveProjectToGroup` | yes |
| Register a repo | `runtime.addRepo(path)` / RPC `repo.add` | yes |
| Group RPC surface | `projectGroup.{list,create,update,delete,moveProject,scanNested,importNested}` | yes |
| Grouping rule | `ensureFolderScopeGroup` — nests every level | **no, see §2** |
| Trigger | — | **does not exist** |
| CLI for groups | — | **does not exist** |

Two gaps confirmed by reading the source:

- **No automatic trigger anywhere.** `scanNestedRepos` has exactly four callers: the
  `projectGroup.scanNested` RPC handler, `importNestedRepos`, and two desktop IPC paths. All four
  are reactions to an explicit user action. No timer, no filesystem watcher, no startup scan.
  `createdFrom: 'folder-scan'` on a group is a record of *provenance*, not a live mode — Orca never
  re-reads that folder on its own.
- **The CLI has `repo add` but no group commands.** `orca repo add --path <repo>` registers one
  project by path and is idempotent, but sets no `projectGroupId`. A grep for `projectGroup` across
  `src/cli/` returns nothing. So today, scripted provisioning can produce a correct but **flat,
  ungrouped** sidebar and no more.

### Limits worth knowing

`scanNestedRepos` defaults to `maxDepth: 3` (clamped 1–8) and `maxRepos: 100`. Relative to root
`…/projects`, depth 3 is exactly `Gitlab/abc/tower` — **our deepest example sits on the limit.**
One more level (`Gitlab/abc/def/tower`) is missed silently unless the caller raises it. Any
implementation should pass `maxDepth` explicitly rather than inherit the default.

## 4. The shape: one command, callable from the provisioning script

The requirement is not a UI affordance. It has to be **launchable from our own script** — the
Coder module, after the `git-clone` modules have put the folders in place. That fixes the shape:

```
orca project-group sync --root /home/coder/orca/projects [--max-depth 4] [--json]
```

One command that runs the scan, applies the flat rule from §1, creates missing groups, registers
missing repos, and moves them into place. A runtime RPC (`projectGroup.syncFromRoot`) underneath is
an implementation detail — worth having so the tile can trigger it too, but the CLI is the surface
that matters, because that is what a script can call.

Ruled out for this purpose: a **watched root** that Orca re-scans on startup. It would work, but it
makes the behaviour implicit, fires when nobody asked, and surprises anyone whose tree does not
follow the rule. We want an explicit call at a moment we choose.

**Requirements on that command:**

- **Idempotent and additive** — it runs on every workspace start. `importNestedRepos` already
  models this: an already-registered repo returns `already-known` and is still moved into its
  group. Same semantics.
- **Non-fatal** — a provisioning script must not fail the workspace build because a folder was
  empty or a repo was mid-clone. Exit 0 with a report; `--json` for anything that wants to parse it.
- **Ordering-aware.** Verified live 2026-07-25: the CLI does reach a running `orca serve` from
  inside the workspace (`orca repo list` answered correctly), so this is viable at provisioning
  time — but only *after* serve is up. A `coder_script` may well run before that, so the call needs
  a bounded wait-and-retry rather than a single attempt. This is the one operational detail most
  likely to make a first implementation look broken.

## 5. Open questions

- **A repo directly at the root** (`…/projects/tower`, no group segment) — leave ungrouped, or
  invent a default group? Ungrouped seems right.
- **Same basename in two groups** (`Gitlab/tower` and `Github/tower`) — both register fine since
  identity is `path`, but the sidebar shows two rows called `tower`. `displayName` is derived from
  the basename by `addRepo`; do we qualify it?
- **Removals.** If a folder disappears, does sync unregister the project or leave it? Leaving it is
  safer and matches "additive"; it also means the sidebar drifts from disk over time.
- **Renames.** Moving `Gitlab/tower` to `Github/tower` changes its group under the rule, but the
  repo record is keyed by path — it would look like a new project plus a stale one.
- **Does the rule belong in Orca at all**, or is it ours? A generic Orca would want the nested
  behaviour it already has. A flat-first-segment rule is opinionated and may be better as an option
  (`--flat`, or `groupDepth: 1`) than as a replacement — which also makes it far more plausible as
  an upstream contribution than a behaviour swap would be.
