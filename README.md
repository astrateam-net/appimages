# appimages

AppImage factory for `astrateam-net` — the AppImage counterpart to
[`containers`](https://github.com/astrateam-net/containers). Each app under
`apps/` builds a patched upstream desktop app into a Linux **`.AppImage`** and
publishes it as a GitHub Release asset. Renovate tracks the upstream `VERSION`
pins in `docker-bake.hcl`.

Unlike `containers`, nothing here ships as a container image. Docker is used only
as a hermetic build sandbox; the artifact extracted and released is the
`.AppImage` file.

## Apps

| App | Upstream | What it is |
|-----|----------|-----------|
| [`orca-coder`](apps/orca-coder/) | [stablyai/orca](https://github.com/stablyai/orca) | Upstream Orca (MIT) at a pinned release tag plus our patch series — the runtime (`orca serve`) with the trusted-proxy web-session patch, packaged for running behind Coder like `code-server`. Not a fork we maintain: the app keeps upstream's identity (`productName` `Orca`, `appId` `com.stablyai.orca`, userData `~/.config/orca`); only the release asset is named `orca-coder` — "Orca, for Coder". |

## How a build works

1. `apps/<name>/docker-bake.hcl` pins the upstream `VERSION` (Renovate-tracked).
2. `apps/<name>/Dockerfile` clones the pristine upstream tag, applies
   `patches/*.patch`, builds with the app's own toolchain, and packages
   `electron-builder --linux AppImage` (or the app's equivalent).
3. A `scratch` `export` stage holds just the `.AppImage`; CI extracts it with
   `docker buildx bake` → `--output type=local` and publishes it via a GitHub
   Release (`ncipollo/release-action`).

The build depends only on **upstream**, never on a fork. What ships is the pristine
upstream release tag with `patches/` applied on top — no app here is a fork we
maintain, and each built app keeps upstream's own identity (`productName`, `appId`,
userData path) verbatim. Only the release asset carries our name. Patches are
authored and tested in the app's fork (the "polygon") and exported here as plain
diffs.

## Consuming an AppImage

Releases are tagged `<app>-<version>` (e.g. `orca-coder-v1.4.154`). Install via
script the way Coder installs `code-server` — download the release asset,
`chmod +x`, run. See each app's directory for its runtime flags.

## Local build

```bash
mise install                              # host toolchain (jq)
docker buildx bake -f apps/orca-coder/docker-bake.hcl appimage   # -> ./dist/*.AppImage
```

## Conventions

- **Versions**: upstream pins live in `docker-bake.hcl` with a `// renovate:`
  annotation. App toolchain pins (node, pnpm, …) match what upstream declares.
- **CI actions**: pinned to full commit SHA with a `# vX.Y.Z` comment, kept
  current by Renovate.
- **`.upstream/`**: gitignored reference clones — study upstreams here, never a
  build input.
