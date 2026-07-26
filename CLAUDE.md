# CLAUDE.md

AppImage factory (sibling to `containers`, which builds Docker images). Each app
under `apps/` builds a patched upstream desktop app into a Linux `.AppImage`
published as a GitHub Release asset.

## Non-obvious facts

- **Docker is only a build sandbox — nothing ships as an image.** The Dockerfile's
  final `scratch` `export` stage is copied out with `buildx --output type=local`;
  the artifact is the `.AppImage`. Don't add registry/push logic.
- **The build depends only on pristine upstream + `patches/`, never on a fork.**
  Patches are authored/tested in the app's fork (the "polygon") and exported here
  as plain diffs.
- **A `RUN` loop over `patches/` needs `set -e`** — otherwise `RUN` takes the LAST
  iteration's status and a mid-series failure passes the build.
- **`git apply` succeeding is not acceptance** — it re-anchors by context, so it also
  passes a patch that is not its boundary diff, and says nothing about whether the
  patch is still needed. Real gates: the app's own contract.

## Build

```bash
mise install                                                   # host jq + ruff
docker buildx bake -f apps/orca-coder/docker-bake.hcl appimage   # -> ./dist/*.AppImage
mise run lint [--fix]                                          # ruff; also lints uncommitted *.py
```

`*.py` in this repo is agent tooling under `.claude/skills/`, never a build input.

## Version discipline (IMPORTANT — do not use training-data versions)

- **Our infra → always latest, verified live.** Pin GitHub Actions to the *latest*
  release by full commit SHA + `# vX.Y.Z` comment. Resolve with `gh` (release tag
  → its commit SHA) and check the action's `action.yml` — its input contract may
  have changed. Never assume from memory.
- **mise**: `min_version` = the machine's installed mise; tools pinned to explicit
  latest numbers (`mise latest <tool>`), not `"latest"`.
- **Upstream-required deps → match upstream, NOT latest.** An app's own toolchain
  (Orca's node 24 / pnpm 10.24.0) is pinned to what upstream declares — a newer
  pnpm breaks the frozen lockfile.

## Renovate

`VERSION` is tracked by a custom regex manager on `docker-bake.hcl`. Its
`managerFilePatterns` MUST be `/.../`-wrapped — unwrapped it's a glob that
silently matches nothing (validator still passes). Patch-over-upstream apps are
**not** auto-merged: a bump needs a human to re-justify every patch
(keep / shrink / merge / drop), not merely to make `git apply` pass again.

## CI

Thin `release.yaml` / `pull-request.yaml` orchestrators detect changed apps and
fan out to the reusable `app-builder.yaml`. Port more composite actions from
`containers` only when a consumer exists — no dead scaffolding.

## `.upstream/`

Gitignored, never a build input. Reference clones, plus per-app git **worktrees**: the fork
carrying the patch series and a pristine one at the build tag. Which tree is authoritative — and
which to never read — is in that app's contract.
