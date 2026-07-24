# astraide — agent contract

A patched [Orca](https://github.com/stablyai/orca) (`stablyai/orca`, MIT, Electron) built into
a Linux `.AppImage` that runs `orca serve --trusted-proxy` behind a Coder subdomain app **like
`code-server`**: click the workspace tile and the full Orca web UI loads — no pairing token in
the URL, no per-workspace config. The Dockerfile is a hermetic **build sandbox**, not a shipped
image; the artifact is the exported `.AppImage`, published as a GitHub Release asset.

This file is the single source of truth for this app. It replaces the old README, HANDOFF, and
PROBLEM docs. Everything below is a **contract**: verified behavior, not aspiration. If you
change behavior, change this file in the same commit.

> Mobile pairing (patch `0002`) went **live 2026-07-24**: phone paired through the public
> edge and survives workspace restarts (verified). The v3 handoff is folded into §1b, §5,
> and §6 and deleted.

---

## 1. The problem and the design

Stock `orca serve` mints a per-startup pairing token and delivers it **only in the URL
fragment** (`…/web-index.html#pairing=<token>`). A Coder tile URL is fixed at template-build
time — it can never carry a runtime-minted fragment — so a stock tile lands on a "paste a
pairing code" form. `code-server` solves the same problem with `--auth none` + loopback bind,
trusting the proxy that already authenticated the user.

`patches/` is a **series**: one patch per logical capability, applied in filename order by the
Dockerfile (`for p in /patches/*.patch`). Patches are scoped by logic, never by count — a new
independent capability gets the next number.

| Patch | Capability |
|---|---|
| `0001-serve-trusted-proxy-web-session.patch` | Orca web UI behind Coder (trusted-proxy session) — §1a |
| `0002-web-mobile-pairing.patch` | Mobile pairing from the web client through Coder — §1b |
| `0003-web-runtime-share-links.patch` | Runtime-scope share links from the web client — §1c |
| `0004-web-session-device-name.patch` | Trusted-session devices named `Web session <date>` (were the `CLI <date>` default) so the shared-access list reads honestly: Web session / Runtime / Mobile |

### 1a. Patch 0001 — trusted-proxy web session

Adds one opt-in capability, `serve --trusted-proxy`, that keeps Orca's E2EE intact:

| Piece | Contract | Where |
|---|---|---|
| **Loopback bind** | Trusted mode binds the runtime WS listener to `127.0.0.1` only. A loopback peer is proof the request came through Coder (which enforced auth) — code-server's `bind-addr: 127.0.0.1` + `--auth none` trust model. | `src/main/runtime/runtime-rpc.ts` |
| **`GET /trusted-session`** | Loopback-gated JSON endpoint returning the current pairing offer: non-loopback → **404**; no offer mintable yet → **503**; else **200** `{"pairingUrl": "orca://pair?code=…"}` with `Cache-Control: no-store`. | `src/main/runtime/rpc/static-web-client-handler.ts` |
| **Same-origin dial** | The web client keeps the offer's E2EE credential but replaces its WS endpoint with one derived from `window.location`. The browser already loaded from the correct Coder subdomain (`<app>--<workspace>--<owner>.<domain>`, dynamic per workspace), so **no `--pairing-address` is needed**. | `src/renderer/src/web/{web-pairing.ts,main.tsx}` |
| **Stale-credential recovery** | On `auth-failed` (serve restarted → re-keyed offer), the web client re-probes `/trusted-session`; a NEW offer is adopted same-origin + page reload; the SAME token falls through to stock manual re-pair (that comparison is also the reload-loop guard). | `src/renderer/src/web/{web-runtime-client.ts,web-preload-api.ts}` |
| **Honest reporting** | `orca_server_ready` reports the actual bind host (`ws://127.0.0.1:<port>` in trusted mode), not a hardcoded `0.0.0.0`. | `src/main/runtime/runtime-rpc.ts` |

**E2EE is kept** — the offer's credential carries the key; the patch only moves its delivery
from the URL fragment to a loopback-gated fetch. Coder still cannot read runtime traffic.

**Threat model (accepted, by design):** loopback gating means ANY local process on the host can
read the offer and gain runtime access — identical to code-server's `--auth none` posture, where
same-machine implies same-owner. `--trusted-proxy` is only safe on single-owner hosts (a
per-user Coder workspace), never on shared multi-user machines.

**Offer persistence:** the device registry and E2EE keypair persist on disk (`userDataPath`),
so a stored offer stays valid across restarts of the *same* server process state. The web client
persists the environment and reuses it; re-fetching per load would mint a new device each
reload. Recovery (above) handles the re-key case.

### 1b. Patch 0002 — web-client mobile pairing

Stock Orca's Settings → Mobile / "Pair this computer" screen is desktop-Electron-only: in the
web client every `window.api.mobile.*` call was a hardcoded stub ("No interfaces found").
The LAN-interface model is also wrong behind Coder — the workspace's IPs are never
phone-reachable; the only address worth advertising is the Coder subdomain URL.

| Piece | Contract | Where |
|---|---|---|
| **Runtime-RPC mint** | New methods `mobile.createPairingOffer` (`{rotate?}`, **strict** — caller-supplied addresses are an error), `mobile.listDevices`, `mobile.revokeDevice`. Authorization = `ctx.trustedMobilePairing`, injected at the WS transport boundary **only for `runtime`-scope connections**; absent → fail closed. None are in `MOBILE_RPC_METHOD_ALLOWLIST`, so a **paired phone (`mobile` scope) can never mint or revoke credentials** — both gates are test-enforced (`mobile-pairing.test.ts`, `mobile-rpc-allowlist.test.ts`). | `src/main/runtime/rpc/methods/mobile-pairing.ts`, `runtime-rpc.ts` (`buildTrustedMobilePairingContext`) |
| **Server-side address policy** | Offers mint against the serve-configured `--pairing-address` with connection mode pinned `local-only` (headless serve has no Relay provider; Coder covers "anywhere"). No address configured → honest `available:false` with guidance. | `runtime-rpc.ts` |
| **Web preload** | `getPairingQR`/`listDevices`/`revokeDevice` call runtime RPC; QR rendered client-side (`qrcode/lib/browser`, same params as desktop main). | `src/renderer/src/web/web-preload-api.ts` |
| **Web UI** | Web client pins connection mode `local-only`; Relay/Local chooser replaced by a "connects through this workspace's web address" notice; interface picker + address step hidden (both the MobilePage hero and Settings → Mobile). Gate = `isWebClientLocation()`. | `use-mobile-pairing-connection-mode.ts`, `MobilePairingConnectionOptions.tsx`, `MobileHero.tsx`, `MobilePairingSetupSection.tsx` |

**The advertised endpoint** (what the QR carries, minted by the template — see §5):

```
wss://<app-slug>--<agent>--<workspace>--<owner>.<wildcard>/?coder_session_token=<token>
```

Coder authenticates the phone's wss upgrade via the `coder_session_token` query param (same
lane as Coder's own web terminal), proxies to the loopback WS listener, and Orca's E2EE
device-token handshake runs on top: **Coder is authn, Orca is authz + E2EE**.

**Security invariants (do not regress):** the pairing URL is a double secret (Orca device
token + Coder session token) — owner-tile/serve.log only, never in build logs, Terraform
outputs, or `coder_metadata`. The tokenized URL also appears in the loopback-gated
`/trusted-session` offer body via `trustedProxyAddress` — accepted (single-owner workspace).
Coder-token expiry is recoverable: Regenerate (`rotate:true`) → rescan.

### 1c. Patch 0003 — web-client runtime share links

Orca has two credential scopes: `mobile` (phones — RPC allowlist + payload diet) and
`runtime` (full clients). The mobile QR (§1b) pairs a desktop app too, but it then runs
*as a phone*. Upstream's "Advertise this app as a server → New Link" surface (runtime-scope
grants) is desktop-only — a headless serve's grants were mintable by nobody.

| Piece | Contract | Where |
|---|---|---|
| **Runtime-grant RPC** | `mobile.getRuntimePairingUrl` (`{rotate?}`, strict), `mobile.listRuntimeAccessGrants`, `mobile.revokeRuntimeAccess` — same `trustedMobilePairing` context gate (runtime-scope connections only; none mobile-allowlisted — a phone minting a runtime grant would be scope escalation, test-enforced). Grants mint against `--pairing-address`, scope `runtime`. | `mobile-pairing.ts`, `runtime-rpc.ts` |
| **Web UI** | Settings → Remote Orca Servers shows the share section in web, reframed **"Share the connected server"** (the browser has no server of its own; grants belong to the workspace server it is connected to). Address picker hidden — server policy. Generate → pairing URL (paste into desktop "Add Server") + web-client URL; grants listed + revocable. | `Settings.tsx`, `RuntimeEnvironmentsPane.tsx`, `RuntimePairingGeneratorForm.tsx`, `web-preload-api.ts` |

Note: the pending (never-connected) runtime device is shared between `/trusted-session`
offers and New Link mints until first connect; New Link always rotates, and the tile's
stale-credential recovery covers a browser that fetched an offer rotated out from under it.

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

Canonical launch (what the Coder install script does — see §5):

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
- **amd64 only** — the dev Mac (arm64) cannot run it natively. Test on Linux/amd64 (§6).

### Success criteria (all verified 2026-07-24 in CT 100 as user `coder`)

1. `ss -ltn` shows **`LISTEN 127.0.0.1:<PORT>`** — loopback, correct port, no `0.0.0.0:6768`.
2. `curl http://127.0.0.1:<PORT>/web-index.html` → **200**.
3. `curl http://127.0.0.1:<PORT>/trusted-session` (loopback) → **200** with the offer JSON.
4. The Coder subdomain tile loads the Orca UI with **no pairing prompt**.

With `--json`, one `{"type":"orca_server_ready", …}` line prints the endpoints. Side effect on
first run: serve installs `~/.local/bin/orca-ide` + a bare `orca` dispatcher — benign, useful.

---

## 3. Build contract

- `docker-bake.hcl` pins `VERSION` to a **real `stablyai/orca` stable tag** (Renovate-tracked).
  Verify against `git ls-remote upstream 'refs/tags/<tag>^{}'` — the fork's local tag store has
  contained a fabricated `v1.4.154` that upstream never published.
- Dockerfile: clone pristine tag → `git apply /patches/*` (**fails the build loudly** if the
  patch drifts from VERSION) → `pnpm build:desktop` → `electron-builder --linux AppImage` →
  export the `.AppImage`.
- CI (`.github/workflows/release.yaml` → `app-builder.yaml`): any push to `apps/**` on main
  rebuilds and publishes to the Release **tagged `astraide-<VERSION>`** with
  `allowUpdates: true` — a re-release **replaces the asset under the same tag**.
- **Same-tag updates:** the install script re-extracts when `VERSION` changes **or** when the
  release asset's HTTP ETag differs from the one recorded at last extract (`ASSET_ETAG` next to
  `VERSION` in the module dir). A same-version re-release is picked up on the next workspace
  start with no template change; offline or ETag-less responses keep the cached extract so a
  start never bricks. On refresh the script kills the old serve so the port guard relaunches
  the fresh build.

---

## 4. Patch authoring workflow (fork = polygon, never a build input)

Patches are authored in the fork **`mrkhachaturov/orcaide`**, branch
**`patch/trusted-proxy-v2`** (based on verified upstream `v1.4.153`), and exported here as
plain `git diff`s. Durable worktree: `/Volumes/Devops/Git/Github/mrkhachaturov/orcaide-v2`.
The older `patch/trusted-proxy` branch sits on the phantom `v1.4.154` base — do not build on it.

**Series layout:** patches are scoped by logic — one per capability, open-ended numbering.
Each patch is the diff between consecutive feature boundaries (commits) on the branch, so the
series applies in filename order on the pristine tag:

| Patch | Exported as |
|---|---|
| `0001` (trusted-proxy session) | `git diff v1.4.153 a50eb31b5` |
| `0002` (web mobile pairing) | `git diff a50eb31b5 e56b5ad5c` |
| `0003` (web runtime share links) | `git diff e56b5ad5c 1a1d2a4e9` |
| `0004` (web session device name) | `git diff 1a1d2a4e9 8172807c8` |
| next capability | `git diff <prev-boundary> <new-commit>` → `0005-….patch` |

```bash
cd /Volumes/Devops/Git/Github/mrkhachaturov/orcaide-v2
# …edit, commit…
git diff <prev-boundary> HEAD > <this-app>/patches/000N-<capability>.patch
# verify the WHOLE series before shipping — same mechanism the Dockerfile uses:
git worktree add --detach /tmp/orca-pristine v1.4.153
for p in <this-app>/patches/*.patch; do git -C /tmp/orca-pristine apply "$p" || break; done && echo CLEAN
git worktree remove --force /tmp/orca-pristine
```

Patch touch points — 0001: `src/cli/{specs/serve.ts,handlers/core.ts,runtime/launch.ts}`,
`src/main/index.ts`, `src/main/runtime/{runtime-rpc.ts,rpc/ws-transport.ts,
rpc/static-web-client-handler.ts}`, `src/renderer/src/web/{main.tsx,web-pairing.ts,
web-runtime-client.ts,web-preload-api.ts}`. 0002: `src/main/runtime/rpc/{core.ts,dispatcher.ts,
methods/mobile-pairing.ts,methods/index.ts}`, `runtime-rpc.ts`, `web-preload-api.ts`,
`src/renderer/src/components/{mobile,settings}/…` (see §1b table).

### Verifying fork changes locally

```bash
mise x pnpm@10.24.0 -- pnpm install --ignore-scripts --prefer-offline   # mise has no pnpm pinned here
mise x pnpm@10.24.0 -- pnpm run typecheck:tsc                            # node + cli + web, must be clean
mise x pnpm@10.24.0 -- pnpm exec vitest run \
  src/renderer/src/web/web-runtime-client.test.ts \
  src/renderer/src/web/web-pairing.test.ts \
  src/cli/runtime/launch.test.ts src/cli/args.test.ts \
  src/main/runtime/rpc/methods/mobile-pairing.test.ts \
  src/main/runtime/rpc/methods/pairing.test.ts \
  src/main/runtime/mobile-rpc-allowlist.test.ts                          # 89 tests, must pass
```

Known-broken baseline (NOT yours to fix): `web-preload-api.test.ts` fails 75/75 with
`Cannot find package '@/lib/browser-uuid'` — a pre-existing vitest alias-resolution quirk in
this environment, identical with and without local changes.

---

## 5. Deployment map

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

Test infrastructure: `ssh coder01` → Proxmox host (user `rkadmin`, sudo for `pct`). Workspace
LXC = **CT 100** (`astradev`); run inside it with
`ssh coder01 'sudo pct exec 100 -- runuser -l coder -c "<cmd>"'`. Module dir in the workspace:
`/home/coder/.coder-modules/astrateam/astraide/` (extract, `VERSION`, `logs/serve.log`).

---

## 6. Debugging gotchas (each cost real time — don't relearn them)

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
  fine). The durable-token mint in the install script (§5) is the fix; if it regressed,
  check `pairing-token` mtime across restarts — it must NOT change on a healthy boot.
