# astraide — agent contract

Upstream [Orca](https://github.com/stablyai/orca) (Electron, MIT) patched so `orca serve
--trusted-proxy` runs behind a Coder subdomain tile **like `code-server`**: click the workspace
tile → the full Orca web UI loads, no pairing token in the URL, no per-workspace config.

Below is the **astraide-specific** contract — the invariants any patch must respect. (Generic
AppImage-factory mechanics — build sandbox, fork = polygon, `git apply`, Renovate, CI — are in
the repo-root CLAUDE.md. Per-patch history: [CHANGELOG.md](CHANGELOG.md).) Change behavior →
change this file in the same commit.

---

## 1. The problem and the design

Stock `orca serve` mints a per-startup pairing token and delivers it **only in the URL
fragment** (`…/web-index.html#pairing=<token>`). A Coder tile URL is fixed at template-build
time — it can never carry a runtime-minted fragment — so a stock tile lands on a "paste a
pairing code" form. `code-server` solves the same problem with `--auth none` + loopback bind,
trusting the proxy that already authenticated the user; astraide's opt-in `serve
--trusted-proxy` does the same while keeping Orca's E2EE intact.

The invariants below are what any patch must respect.

### The trusted-proxy web session

- **Loopback bind = proof of Coder auth.** Trusted mode binds the runtime WS listener to
  `127.0.0.1` only; a loopback peer is proof the request arrived through Coder (which enforced
  auth) — code-server's `--auth none` + loopback model. `runtime-rpc.ts`.
- **`GET /trusted-session`** (loopback-gated, `Cache-Control: no-store`): non-loopback → **404**;
  no offer mintable yet → **503**; else **200** `{"pairingUrl": …}`. `static-web-client-handler.ts`.
- **Same-origin dial.** The web client keeps the offer's E2EE credential but derives the WS
  endpoint from `window.location`, so **the tile needs no `--pairing-address`**. On `auth-failed`
  (serve re-keyed) it re-probes `/trusted-session` and adopts a NEW offer + reload; the SAME
  token falls through to stock manual re-pair (that compare also guards the reload loop).
  `web-pairing.ts`, `web-runtime-client.ts`, `web-preload-api.ts`.
- **E2EE preserved** — the patch only moves the credential's delivery from URL fragment to a
  loopback-gated fetch; Coder never reads runtime traffic. Device registry + keypair persist on
  disk (`userDataPath`), so a stored offer survives restarts of the same server state.
- **Threat model (accepted):** loopback gating means ANY local process on the host can read the
  offer → runtime access. Safe ONLY on single-owner hosts (a per-user Coder workspace), never a
  shared multi-user machine.

### Credential scopes & pairing

- Two scopes: **`mobile`** (phones — RPC allowlist + payload diet) and **`runtime`** (full
  clients). `MOBILE_RPC_METHOD_ALLOWLIST` (`runtime-rpc.ts`) is the scope gate: a method's
  **absence** from it = runtime-only. Anything host-mutating or that mints/revokes credentials
  must never be on it — phone-reachable would be escalation. Test-enforced
  (`mobile-rpc-allowlist.test.ts`).
- **Credential mint/revoke** — mobile offers AND runtime-share grants (`mobile.createPairingOffer`,
  `getRuntimePairingUrl`, the `list*`/`revoke*` pairs) — is authorized by the
  `trustedMobilePairing` context, injected **only for `runtime`-scope connections**; absent →
  fail closed. Server callbacks live in `buildTrustedMobilePairingContext()`; params are strict
  zod (server-policy fields like addresses must error, not strip). `mobile-pairing.ts`.
- **Advertised address is always server policy** (`--pairing-address`), never client-chosen; the
  headless serve pins connection mode `local-only`. The QR/link carries
  `wss://<app-slug>--<agent>--<workspace>--<owner>.<wildcard>/?coder_session_token=<token>` —
  **Coder is authn, Orca is authz + E2EE**. Web-UI copy reframes to "connects through this
  workspace" / "share the connected server" (the browser has no server of its own).
- **The pairing URL is a double secret** (Orca device token + Coder session token) — owner-tile
  / serve.log only; never build logs, Terraform outputs, or `coder_metadata`. Coder-token expiry
  is recoverable (Regenerate `rotate:true` → rescan); the durable owner token (§4) survives
  workspace restarts.

### The web client is mostly stubs

Orca's web client replaces the Electron preload with `web-preload-api.ts`
(`createWebPreloadApi()`), and upstream **stubs most of it** — empty lists, `{available:false}`,
no-op/throw. That is the root cause of nearly every "works on desktop, dead in the tile" report;
the fix is almost always to route the stub to a runtime RPC (or add one), mirroring the desktop
`ipc/*.ts` contract 1:1.

---

## 2. ⚠️ Launch contract — the #1 trap in this app

**`squashfs-root/AppRun` is the Electron DESKTOP entrypoint. It silently ignores a `serve`
positional** — the Electron main only reads internal `--serve-*` flags
(`src/main/index.ts`, `isServeMode = process.argv.includes('--serve')`). Launching
`AppRun serve --trusted-proxy --port 6799` boots the GUI under Xvfb with the **stock** runtime
server on `0.0.0.0:6768` and no error. This cost days of debugging (2026-07); do not
rediscover it.

The user-facing CLI ships as a bash shim at **`squashfs-root/resources/bin/orca-ide`**
(electron-builder `extraResources` — the same shim Orca's deb symlinks to `/usr/bin/orca-ide`).
It runs `ELECTRON_RUN_AS_NODE=1 <electron> resources/app.asar.unpacked/out/cli/index.js "$@"`;
the CLI (`src/cli/runtime/launch.ts`, `serveOrcaApp`) re-encodes the user flags to
`--serve --serve-port <p> --serve-trusted-proxy` and re-spawns the Electron binary, staying in
the foreground to supervise it.

Canonical launch (what the Coder install script does — see §4):

```bash
# LXC has no FUSE → extract once per VERSION:
./astraide-<VERSION>-x86_64.AppImage --appimage-extract        # → squashfs-root/
# ALWAYS the shim, NEVER AppRun:
LIBGL_ALWAYS_SOFTWARE=1 ORCA_APPIMAGE_NO_SANDBOX=1 nohup dbus-run-session -- xvfb-run -a \
  squashfs-root/resources/bin/orca-ide serve --trusted-proxy --port "$PORT" \
  > "$LOG_DIR/serve.log" 2>&1 &
```

Non-negotiable pieces:

- **`ORCA_APPIMAGE_NO_SANDBOX=1`** (env), never a `--no-sandbox` flag — the flag is not in
  serve's `allowedFlags`, the CLI rejects it ("Unknown flag") and serve never starts. The env
  var is Orca's own knob; `serveOrcaApp` injects `--no-sandbox` into the Electron child.
- **`dbus-run-session -- xvfb-run -a`** — serve is Electron, needs an X server + session bus,
  and does NOT auto-start Xvfb here (dies "Missing X server or $DISPLAY"). Matches upstream's
  headless harness (`config/docker/headless-pairing/`).
- **Runtime deps** (Electron, not Node): Chromium shared libs (`libgtk-3-0 libnss3 libgbm1
  libasound2 libatk-bridge2.0-0 libatspi2.0-0 libdrm2 libxcomposite1 libxdamage1 libxfixes3
  libxkbcommon0 libxrandr2 libxss1`) plus `xvfb xauth dbus-x11`.
- **`--pairing-address`** — not needed for the browser tile (same-origin dial), but **required
  for mobile pairing** (patch 0002): the template passes
  `--pairing-address "https://<tile-hostname>/?coder_session_token=<token>"` so QR offers
  advertise the Coder subdomain URL. Without it, Generate code fails honestly
  ("no advertised pairing address").
- **Healthcheck → `GET /web-index.html`** (200). Not `/trusted-session` (503 until pairing
  init) and not the WS port itself.
- **amd64 only** — the dev Mac (arm64) cannot run it natively. Test on Linux/amd64 (§5).

### Success criteria (all verified 2026-07-24 in CT 100 as user `coder`)

1. `ss -ltn` shows **`LISTEN 127.0.0.1:<PORT>`** — loopback, correct port, no `0.0.0.0:6768`.
2. `curl http://127.0.0.1:<PORT>/web-index.html` → **200**.
3. `curl http://127.0.0.1:<PORT>/trusted-session` (loopback) → **200** with the offer JSON.
4. The Coder subdomain tile loads the Orca UI with **no pairing prompt**.

With `--json`, one `{"type":"orca_server_ready", …}` line prints the endpoints. Side effect on
first run: serve installs `~/.local/bin/orca-ide` + a bare `orca` dispatcher — benign, useful.

---

## 3. Build & release specifics

Generic build / Renovate / CI mechanics live in the repo-root CLAUDE.md. astraide-only:

- **VERSION must be a REAL `stablyai/orca` tag** — verify with `git ls-remote upstream
  'refs/tags/<tag>^{}'`; the fork's local tag store has held a fabricated `v1.4.154` that
  upstream never published.
- **Release:** CI publishes to the tag `astraide-<VERSION>` with `allowUpdates: true`, so a
  re-release **replaces the asset under the same tag** — VERSION need not bump for a patch fix.
- **Same-tag refresh:** the install script re-extracts when `VERSION` changes OR the asset's
  HTTP ETag differs (`ASSET_ETAG` beside `VERSION` in the module dir); offline/ETag-less
  responses keep the cached extract so a start never bricks. On refresh it kills the old serve
  so the port guard relaunches the fresh build.

---

## 4. Deployment map

| Repo | Path | Role |
|---|---|---|
| **appimages** (this) | `apps/astraide/` | Builds + releases the AppImage |
| **fork** | `mrkhachaturov/orcaide` @ `patch/trusted-proxy-v2` | Patch authoring (worktree `…/orcaide-v2`) |
| **upstream clone** | `…/astrateam-net/containers/.upstream/orca` | Read-only source for tracing |
| **control-plane** | `terraform/coder/templates/proxmox-lxc/{astraide.tf, scripts/install-astraide.sh}` | Installs + launches in the workspace, publishes the `coder_app` tile (`url = "http://localhost:6799"`, `subdomain = true`, `share = "owner"`). Mobile pairing: the script passes `--pairing-address "https://<app-hostname>/?coder_session_token=<durable token>"` |

**Durable pairing token (verified live 2026-07-24):** `data.coder_workspace_owner.me.session_token`
is **revoked on every rebuild**, so it is only the *bootstrap* credential. The install script
mints an `application_connect`-scoped owner token once (`POST /api/v2/users/me/keys/tokens`,
lifetime 30d → 7d fallback, ns-valued `lifetime`), caches it 0600 at
`<module_dir>/pairing-token`, and validates it each start **against the app lane**
(`GET https://<app-host>/web-index.html?coder_session_token=…`; 2xx/5xx = valid, 3xx/4xx =
re-mint) — NOT `/api/v2/users/me`, where that scope is RBAC-denied (404) and would silently
re-mint every boot. Phones therefore survive workspace restarts; re-pair is only needed when
the durable token expires (Regenerate → rescan). Tokens are never echoed; templatefile
escaping: shell `$${…}` AND curl format `%%{http_code}` (both `${` and `%{` are template
directives).

Live test env: workspace LXC **CT 100** (`astradev`) on Proxmox host `coder01`; module dir
`/home/coder/.coder-modules/astrateam/astraide/` holds the extract, `VERSION`, `logs/serve.log`.
(How to run + verify inside it: `astraide-patch-verify` skill.)

---

## 5. Debugging gotchas (each cost real time — don't relearn them)

- **Flags "ignored", binds `0.0.0.0:6768`** → you launched via `AppRun`. Use the shim (§2).
  `6768` = `DEFAULT_WS_PORT` non-trusted default; GUI-style log lines (dbus `login1 Inhibit
  AccessDenied`, `GpuControl` failures, `[pty:history:gc]`) mean the desktop app booted.
- **`FATAL … Failed to shutdown` + `SIGTRAP` after ready** → your own `timeout <s>` wrapper
  fired SIGTERM at the tree. Not a crash.
- **`pkill -f <pattern>` over `ssh`/`pct exec` kills itself** — the wrapping shell's cmdline
  contains the pattern. Use `pkill -f "[b]racketed"` patterns AND keep the kill in a separate
  invocation from any command whose text contains the pattern.
- **`ss -ltn` is the only bind truth.** Ready-JSON endpoint strings are derived, not observed
  (fixed in the current patch, but always confirm with `ss`).
- **Zombie listeners skew results** — kill `[s]quashfs-root` + `Xvfb` remnants before a clean
  repro; a leftover from an earlier flagless run holds `0.0.0.0:6768`.
- The `login1 Inhibit AccessDenied` and GPU `kTransientFailure` lines are benign in an LXC
  (no logind session / software GL) — they do not abort the listener.
- Cmdline of a live process: `tr '\0' ' ' < /proc/<pid>/cmdline` — the fastest way to see
  whether the CLI translated flags to `--serve-*` for the Electron child.
- **Phone loops "WebSocket closed" while the browser tile works** → the phone is on the
  PUBLIC DNS path (cellular/VPN, or Wi-Fi with iCloud Private Relay/DoH) hitting the edge,
  not the internal Traefik. A `*.astrateam.net` cert **cannot** cover
  `*.portal.astrateam.net` — wildcards match ONE level. Check with
  `openssl s_client -servername <app-host> -connect <edge-ip>:443`; the edge needs the
  portal wildcard cert (or SNI passthrough) + WS routing. Discriminate layers: GET with
  `?coder_session_token=` (Coder authn) vs a real WS client (`node -e` with `ws`) — curl
  cannot do WS upgrades, its 200 there is meaningless.
- **Phone shows paired in UI but can't connect after a workspace restart** → the QR carried
  the per-build session token, which Coder revokes on rebuild (registry persists → UI looks
  fine). The durable-token mint in the install script (§4) is the fix; if it regressed,
  check `pairing-token` mtime across restarts — it must NOT change on a healthy boot.
