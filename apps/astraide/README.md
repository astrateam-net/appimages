# astraide — Orca as a one-click Coder app

A patched [Orca](https://github.com/stablyai/orca) built into a Linux `.AppImage` that runs
`orca serve --trusted-proxy` behind a Coder subdomain app **like `code-server`**: click the
workspace tile and the full Orca web UI loads — no pairing code, no token in the URL, any
workspace name.

> Full agent/operator contract — design invariants, launch rules, verification, gotchas —
> lives in [CLAUDE.md](CLAUDE.md). This README is the short human tour.

## Why a patch

Stock `orca serve` delivers its pairing token only in the URL fragment, minted fresh every
start — a fixed Coder tile URL can't carry it. The patch adds a `--trusted-proxy` mode that
mirrors `code-server`'s `--auth none` + loopback trust model while keeping Orca's E2EE:

- binds the runtime to `127.0.0.1` only (Coder's proxy is the auth layer),
- serves the pairing offer over a loopback-gated `GET /trusted-session`,
- the web client dials back **same-origin** — so no per-workspace configuration exists at all,
- recovers automatically when a restart re-keys the offer.

## Use it

Grab the latest asset from
[Releases](https://github.com/astrateam-net/appimages/releases) (`astraide-<VERSION>-x86_64.AppImage`, amd64 only), then:

```bash
./astraide-<VERSION>-x86_64.AppImage --appimage-extract   # LXC/no-FUSE friendly
LIBGL_ALWAYS_SOFTWARE=1 ORCA_APPIMAGE_NO_SANDBOX=1 dbus-run-session -- xvfb-run -a \
  squashfs-root/resources/bin/orca-ide serve --trusted-proxy --port 6799
```

⚠️ Launch via `squashfs-root/resources/bin/orca-ide` — **not** `squashfs-root/AppRun`, which
is the desktop GUI entry and silently ignores `serve`. Needs the Chromium shared libs plus
`xvfb xauth dbus-x11`. Details and the Coder-side wiring: [CLAUDE.md](CLAUDE.md).

## Build

`docker-bake.hcl` pins `VERSION` to a real upstream tag (Renovate-tracked). The Dockerfile
clones that tag, applies [`patches/`](patches/) (build fails loudly on drift), runs the
Electron build, and exports the `.AppImage`. Any push touching `apps/**` on `main` rebuilds
and republishes the Release asset under the same `astraide-<VERSION>` tag.
