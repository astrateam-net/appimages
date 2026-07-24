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
  as plain diffs. `git apply` fails the build loudly on upstream drift.

## Build

```bash
mise install                                                   # host jq
docker buildx bake -f apps/astraide/docker-bake.hcl appimage   # -> ./dist/*.AppImage
```

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
**not** auto-merged: a VERSION bump can fail `git apply` and needs a human to
refresh the patch.

## CI

Thin `release.yaml` / `pull-request.yaml` orchestrators detect changed apps and
fan out to the reusable `app-builder.yaml`. Port more composite actions from
`containers` only when a consumer exists — no dead scaffolding.

## `.upstream/`

Gitignored reference clones — study upstream source here to ground decisions;
never a build input.
