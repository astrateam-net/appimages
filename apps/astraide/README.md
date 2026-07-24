# astraide — Orca runtime AppImage for Coder

A patched [Orca](https://github.com/stablyai/orca) built into a Linux `.AppImage` that runs
`orca serve` behind a Coder subdomain app **like `code-server`**: click the workspace tile and
you're in — no pairing token in the URL, works for any workspace name.

The Dockerfile is a hermetic **build sandbox**, not a shipped image. The artifact is the
exported `.AppImage`, published as a GitHub Release asset (`astraide-<VERSION>-x86_64.AppImage`).

## Problem

Stock `orca serve` mints a per-startup pairing token and delivers it in the URL fragment
(`…#pairing=<token>`). A Coder app tile's URL is fixed at template-build time — before any
workspace or token exists — and a URL fragment never reaches the server, so stock Orca can't
be a one-click Coder app. `code-server` solves the same problem with `--auth none` + a loopback
bind, trusting the proxy that already authenticated the user.

## How the patch works

`patches/0001-*.patch` adds `orca serve --trusted-proxy`, the `--auth none` equivalent:

1. **Loopback bind.** In trusted mode the runtime WebSocket binds `127.0.0.1` only. Behind
   Coder, the only way a packet reaches the port is through Coder's agent, which already
   enforced auth — so a loopback peer is proof the request came through the trusted proxy
   (`main/runtime/runtime-rpc.ts`).
2. **`GET /trusted-session`.** A loopback-gated endpoint returns the current pairing offer as
   JSON. Non-loopback → 404; before an offer can be minted → 503; otherwise 200. The web client
   fetches it on load (relative to the page), so it pairs with nothing in the address bar
   (`main/runtime/rpc/static-web-client-handler.ts`).
3. **Same-origin dial.** The offer carries the server's E2EE credential (device token + key)
   *and* a WebSocket endpoint. The web client keeps the credential but **replaces the endpoint
   with one derived from `window.location`** (`renderer/src/web/{web-pairing.ts,main.tsx}`,
   `sameOriginWebSocketEndpoint`).

Orca's channel is end-to-end encrypted, so the offer's credential is not a skippable password —
it carries the key. The patch **keeps** the E2EE and issues the credential over the loopback
endpoint instead of the URL. Same trust boundary as `code-server`; Coder still cannot read
runtime traffic.

## Why it's built this way

- **Endpoint derived same-origin, not from `--pairing-address`.** A Coder subdomain is
  `<app>--<workspace>--<owner>.<domain>` — dynamic per workspace name (Coder source:
  `coderd/agentapi/manifest_test.go`). A loopback-bound runtime cannot know it. The browser
  already loaded from that subdomain, so `window.location` is the reachable address; deriving
  the endpoint client-side fits any workspace with nothing to configure. This is why
  `code-server` is launched with only `--auth none --port` and never told its own URL — Orca
  needs **no `--pairing-address`** for the web client.
- **The offer is persisted and reused, not re-fetched per load.** The device registry and the
  E2EE keypair both persist on disk (`userDataPath`: `DeviceRegistry.load`,
  `loadOrCreateE2EEKeypair`), so a stored offer stays valid across a workspace restart.
  Re-fetching `/trusted-session` on every load would mint a new device each reload
  (`getOrCreatePendingDevice` coalesces only *pending* devices; connected ones are never
  pruned) and fill the paired-devices list. Persist-and-reuse is restart-safe with no churn.
- **E2EE is kept.** It is Orca's property beyond `code-server` (the proxy cannot read traffic)
  and is invisible to the user, so it costs nothing to keep.

## Launch (Coder module — authored separately, not in this repo)

```bash
# An LXC has no FUSE → extract, then run the inner AppRun.
./astraide-<VERSION>-x86_64.AppImage --appimage-extract        # → squashfs-root/
# serve is Electron: a D-Bus session + virtual X display, and no Chromium sandbox in the LXC.
LIBGL_ALWAYS_SOFTWARE=1 dbus-run-session -- xvfb-run -a \
  squashfs-root/AppRun --no-sandbox serve --trusted-proxy --port "$PORT" &
```

- **No `--pairing-address`** — same-origin handles it.
- **`dbus-run-session -- xvfb-run -a`.** serve is Electron and needs an X server + session bus;
  it does **not** auto-start Xvfb (it dies "Missing X server or $DISPLAY"). This matches upstream's
  own headless harness (`config/docker/headless-pairing/run-appimage-case.sh`).
- **`--no-sandbox` is passed explicitly.** AppRun only auto-adds it when `unshare -Ur` *fails*
  (user namespaces unavailable); a **nesting-enabled** LXC has userns, so it is not auto-added and
  Chromium's sandbox would crash. It forwards ahead of `serve`.
- **Electron system deps** (this is Electron, not Node): the Chromium shared libs
  (`libgtk-3-0`, `libnss3`, `libgbm1`, `libasound2`, `libatk-bridge2.0-0`, `libxkbcommon0`, …)
  **plus `xvfb`, `xauth`, `dbus-x11`** (`xvfb-run` shells out to `xauth`; `dbus-run-session` comes
  from `dbus-x11`). `apt-get` them in the install script or bake them into the workspace image.
- **`coder_app` healthcheck → `/web-index.html`** (200). Not `/trusted-session` (loopback-gated,
  503 until pairing init).

## Version

`VERSION` in [`docker-bake.hcl`](docker-bake.hcl) is a real `stablyai/orca` **stable tag**
(e.g. `v1.4.153`), Renovate-tracked. Note `v1.4.154` is not an upstream tag. On bump the patch
must still apply — `git apply` fails the build loudly otherwise; refresh the patch (below).

## Authoring the patch (fork = polygon, never a build input)

Patches are written and tested in the fork `mrkhachaturov/orcaide` and exported here as a plain
`git diff` against the pinned tag:

```bash
git worktree add -b patch/trusted-proxy /tmp/orca <tag>
cd /tmp/orca && git apply <this>/patches/0001-serve-trusted-proxy-web-session.patch
# …edit the touch points below…
git diff > <this>/patches/0001-serve-trusted-proxy-web-session.patch   # verify: git apply --check on a clean <tag>
```

Touch points: `main/runtime/runtime-rpc.ts` (loopback bind + `/trusted-session` provider),
`main/runtime/rpc/static-web-client-handler.ts` (loopback-gated endpoint),
`renderer/src/web/{main.tsx,web-pairing.ts}` (same-origin dial). amd64 only — Orca is Electron.
