# orca-coder — agent contract

Upstream [Orca](https://github.com/stablyai/orca) (Electron, MIT) patched so `orca serve
--trusted-proxy` runs behind a Coder subdomain tile **like `code-server`**: click the workspace
tile → the full Orca web UI loads, no pairing token in the URL, no per-workspace config.

Below is the **orca-coder-specific** contract — the invariants any patch must respect. (Generic
AppImage-factory mechanics — build sandbox, fork = polygon, `git apply`, Renovate, CI — are in
the repo-root CLAUDE.md. Per-patch history: [CHANGELOG.md](CHANGELOG.md).) Change behavior →
change this file in the same commit.

## 0. How a change enters the series

`orca-coder-patch-` **audit** (where it goes) → **author** (write it there) → **verify** → **ship**.
How each answers its question is in its own SKILL.md. Invariants:

1. **Diagnose, place, then write.** Placement needs the *symbol* list from diagnosis; from a
   capability's name alone it cannot decide. Guessing from a name is how a second
   floating-workspace fix became `0009` instead of extending `0006`.
2. **Ownership is by symbol, never by file.** Hub files are touched by almost every patch, so a
   shared file decides nothing. A shared **symbol** means one capability split in two.
3. **A new number is a claim, defended in the CHANGELOG** — its entry names the patches considered
   and why this is not an extension. No sentence, no new number: that entry is the only committed
   record of the decision. It also carries `Acceptance` (the test that fails without the patch);
   without one the patch can never be shrunk, merged or dropped with confidence.
4. **A fix to existing patch logic never takes a new number** — restack that boundary and
   re-export. Restacking cost is work, not a correctness argument.
5. **A patch must be byte-identical to `git diff <prev-boundary> <this-boundary>`.** Exporting
   against `HEAD` is right only for the newest patch; otherwise it swallows later patches and
   records blobs that do not exist at that boundary. Such a patch still applies — `git apply`
   re-anchors, and `--3way` re-derives the post-image — so the damage is quiet: `offset` lines,
   reverse-apply drift, and `0001..000N` no longer reproducing boundary N's tree. **`git apply`
   succeeding is not acceptance**, of correctness or of purpose: a patch can apply cleanly and be
   redundant or already shipped upstream. Every bump re-justifies each patch
   (keep / shrink / merge / drop) rather than rebasing until it applies.
6. **The tooling is local-only; the obligation is not.** Graphs and audit scripts live in
   git-excluded config on one machine. Everything they accelerate is answerable from the exported
   diffs alone, so missing tooling means answer slower, never skip — and nothing committed may
   depend on it.

7. **A path existing in source is not evidence it is taken.** Static reachability, grep hits and
   graph traces are leads, never proof — behavioural claims need a test or a live check. Two `0009`
   conclusions were inferred from reading routing code and both were wrong.

Test for what belongs here: a line that changes when a command or file list changes goes in a skill;
one that changes only when the *rules* change goes here.

## 1. The problem and the design

Stock `orca serve` delivers its pairing token **only in the URL fragment**, and a Coder tile URL is
fixed at template-build time — so a stock tile lands on a "paste a pairing code" form.
`serve --trusted-proxy` solves it as `code-server` does (`--auth none` + loopback bind, trusting the
proxy that already authenticated) while keeping Orca's E2EE. Invariants any patch must respect:

**Trusted-proxy web session**

- **Loopback bind = proof of Coder auth.** Trusted mode binds the WS listener to `127.0.0.1` only.
  `runtime-rpc.ts`.
- **`GET /trusted-session`** (loopback-gated, `no-store`): non-loopback → 404; no offer yet → 503;
  else 200 `{"pairingUrl": …}`. `static-web-client-handler.ts`.
- **Same-origin dial** — the client keeps the offer's E2EE credential but derives the WS endpoint
  from `window.location`, so **the tile needs no `--pairing-address`**. On `auth-failed` it re-probes
  and adopts a NEW offer + reload; the SAME token falls through to manual re-pair, which is also
  what guards the reload loop. `web-pairing.ts`, `web-runtime-client.ts`, `web-preload-api.ts`.
- **E2EE preserved** — only the credential's delivery moved (fragment → loopback fetch); Coder never
  reads runtime traffic. Device registry + keypair persist on disk, so an offer survives restarts.
- **Threat model (accepted):** loopback gating means any local process on the host can read the offer
  and reach the runtime. Safe only on single-owner hosts, never a shared machine.

**Credential scopes & pairing**

- Two scopes: **`mobile`** (RPC allowlist + payload diet) and **`runtime`** (full). Absence from
  `MOBILE_RPC_METHOD_ALLOWLIST` = runtime-only. Anything host-mutating or credential-minting must
  never be on it — phone-reachable would be escalation. Test-enforced.
- **Mint/revoke is authorized by the `trustedMobilePairing` context**, injected only for
  `runtime`-scope connections; absent → fail closed. Strict zod params: server-policy fields like
  addresses must error, not strip. `mobile-pairing.ts`.
- **Advertised address is always server policy** (`--pairing-address`), never client-chosen; headless
  pins connection mode `local-only`. **Coder is authn, Orca is authz + E2EE.**
- **The pairing URL is a double secret** (Orca device token + Coder session token) — owner tile and
  `serve.log` only; never build logs, Terraform outputs or `coder_metadata`.

**The browser is a REMOTE client of the same box — the fact behind every tile bug**

Upstream's model has two roles on two machines: a *server* running `orca serve` that owns repos,
worktrees, terminals and agent processes, and a *client* that runs the UI and connects. **orca-coder
collapses both onto one host**, so `LOCAL_EXECUTION_HOST_ID` is a fiction and headless drops every
window-bound subsystem. **Every capability therefore needs a wire representation — there is no "just
do it locally" fallback, because local IS the server.** Upstream stubs `web-preload-api.ts` exactly
where no wire exists yet. Three failure shapes follow (no wire / wrong locality /
renderer-graph-driven); telling them apart is `orca-coder-patch-author`'s playbook, not this file's.

## 2. ⚠️ Launch contract — the #1 trap in this app

**`squashfs-root/AppRun` is the Electron DESKTOP entrypoint and silently ignores a `serve`
positional** — the Electron main only reads internal `--serve-*` flags (`src/main/index.ts`).
`AppRun serve --trusted-proxy --port 6799` boots the GUI under Xvfb with the **stock** server on
`0.0.0.0:6768`, no error. Cost days in 2026-07; do not rediscover it.

The user-facing CLI is a bash shim at **`squashfs-root/resources/bin/orca-ide`**
(electron-builder `extraResources`). It runs the CLI under `ELECTRON_RUN_AS_NODE=1`, which
re-encodes user flags to `--serve --serve-port <p> --serve-trusted-proxy` and re-spawns Electron,
staying in the foreground to supervise (`src/cli/runtime/launch.ts`, `serveOrcaApp`).

Canonical launch (what the Coder install script does — §4):

```bash
./orca-coder-<VERSION>-x86_64.AppImage --appimage-extract   # LXC has no FUSE; once per VERSION
LIBGL_ALWAYS_SOFTWARE=1 ORCA_APPIMAGE_NO_SANDBOX=1 nohup dbus-run-session -- xvfb-run -a \
  squashfs-root/resources/bin/orca-ide serve --trusted-proxy --port "$PORT" \
  > "$LOG_DIR/serve.log" 2>&1 &      # ALWAYS the shim, NEVER AppRun
```

Non-negotiable:

- **`ORCA_APPIMAGE_NO_SANDBOX=1`** as an env var, never a `--no-sandbox` flag — the flag is not in
  serve's `allowedFlags`, so the CLI rejects it and serve never starts. `serveOrcaApp` injects the
  flag into the Electron child itself.
- **`dbus-run-session -- xvfb-run -a`** — serve is Electron and does NOT auto-start Xvfb here (dies
  "Missing X server or $DISPLAY"), matching upstream's headless harness.
- **Runtime deps are Electron's, not Node's**: Chromium shared libs (`libgtk-3-0 libnss3 libgbm1
  libasound2 libatk-bridge2.0-0 libatspi2.0-0 libdrm2 libxcomposite1 libxdamage1 libxfixes3
  libxkbcommon0 libxrandr2 libxss1`) plus `xvfb xauth dbus-x11`.
- **`--pairing-address`** is unnecessary for the tile (same-origin dial) but **required for mobile
  pairing** (0002); without it Generate code fails with "no advertised pairing address".
- **Healthcheck is `GET /web-index.html`** (200) — not `/trusted-session` (503 until pairing init),
  not the WS port.
- **amd64 only.** The dev Mac is arm64; test on Linux/amd64.
## 3. Build & release specifics

Generic build / Renovate / CI mechanics are in the repo-root CLAUDE.md. orca-coder-only:

- **VERSION must be a REAL `stablyai/orca` tag** — `git ls-remote upstream 'refs/tags/<tag>^{}'`.
  The fork's local tag store has held a fabricated `v1.4.154` upstream never published.
- **A patch carrying an UPSTREAM fix stays at `0000`** so it can be deleted the moment upstream
  lands it — otherwise `git apply` fails the build. `0000` was dropped at `v1.4.156` (upstream took
  the `DetachedHeadBadge` `tabIndex` fix); every current patch is an orca-coder capability. If a
  bump ever needs one again, record the drop condition here.
- **Upstream's own suite is not clean** — `project-view-wrapper-source-context-boundary` fails under
  full-suite parallel load on pristine `v1.4.156`. Before blaming a patch, run the same suite on the
  **pristine tag**; comparing against the previous patch boundary only rules out that patch, not the
  bump.
- **Release:** CI publishes to tag `orca-coder-<VERSION>` with `allowUpdates: true`, so a re-release
  replaces the asset under the same tag — VERSION need not bump for a patch fix.
- **Same-tag refresh:** the install script re-extracts when `VERSION` changes or the asset's HTTP
  ETag differs (`ASSET_ETAG` beside `VERSION`); an ETag-less response keeps the cached extract so a
  start never bricks. On refresh it kills the old serve so the port guard relaunches.

## 4. Deployment map

| Repo | Path | Role |
|---|---|---|
| **appimages** (this) | `apps/orca-coder/` | Builds + releases the AppImage |
| **fork worktree** ⭐ | `.upstream/orcaide-v2/` — `mrkhachaturov/orcaide` @ `patch/trusted-proxy-v2` | **THE source of truth.** Base = VERSION; HEAD = base + the series. Author, export and trace Orca source here |
| ~~upstream clone~~ | `…/containers/.upstream/orca` | **Do not use** — the sibling repo owns it and pins it elsewhere |
| **Coder module** | GitLab `registry/…/modules/orca/` (`main.tf`, `scripts/install.sh`) | Installs + launches in the workspace; publishes the `coder_app` tile (`localhost:6799`, `subdomain = true`, `share = "owner"`) and passes `--pairing-address`. Module is named **`orca`**; `orca-coder` names only the release asset |
| **control-plane** | `terraform/coder/templates/proxmox-lxc/agent.tf` → `module "orca"` | Consumes the registry module; holds no install script of its own |

### ⚠️ Trace Orca source ONLY in the fork — and prove the version first

```bash
git -C .upstream/orcaide-v2 describe --tags   # must start with the VERSION in docker-bake.hcl
```

The fork is the only tree both at our base tag and carrying our series. The `containers` clone is
pinned by another repo — it sat 5 minors behind and **produced confident, wrong answers** (its
`buildPtyTerminalSummary` hardcodes `tabId: "pty:<ptyId>"`, which faked a contradiction of `0010`'s
premise and cost a full investigation). Same rule for pristine comparisons: `git worktree add` off
the real tag in the fork, never a nearby clone.

**Durable pairing token.** `data.coder_workspace_owner.me.session_token` is revoked on every
rebuild, so it is only the bootstrap credential. The install script mints an
`application_connect`-scoped owner token once, caches it 0600 at `<module_dir>/pairing-token`, and
validates it each start **against the app lane** (`GET https://<app-host>/web-index.html?…`;
2xx/5xx = valid) — NOT `/api/v2/users/me`, where that scope is RBAC-denied (404) and would silently
re-mint every boot. Phones therefore survive restarts. Tokens are never echoed; templatefile needs
`$${…}` and `%%{http_code}` escaping.
## 5. Debugging gotchas (each cost real time — don't relearn them)

- **Never redefine an absence upstream already encodes.** Upstream stores "no active server" as an
  **absent** settings key; a patch that defaulted that same absence to the paired environment made an
  explicit `null` unrepresentable and kept three upstream tests red from the day it landed. If a
  value must mean something different for the web client, resolve it **at the consumer**, never by
  redefining what the stored absence means. (The `0013` import-cycle entry below is the same shape:
  the damage was invisible because the patch's own tests stayed green.)
- **Moving a decision from a synchronous source to store state inherits a hydration window.**
  `state.runtimeEnvironments` is filled fire-and-forget at boot (`fetchSettings` →
  `void hydrateRuntimeEnvironmentStatuses()`), so until it lands the catalog is `[]` — and for the
  web client "no environments" resolves ownership to **local**, the one answer a browser can never
  act on. ~100 call sites reach that resolver. `hydrateRuntimeEnvironmentCatalog` (a localStorage
  list) is therefore separate from the status probes (network) and is awaited in the browser only.
  When a fix reads store state where it used to read storage, ask what that state is before boot.
- **`TypeError: Cannot convert undefined or null to object` at module load** → import cycle entered
  from the wrong end. `orca-runtime.ts` sits in one with the RPC tree; the other `rpc/` files
  reference it with `import type` (erased, no runtime edge). `0013` added the only **value** import
  and used it at module scope — **29 test files and 411 tests** died; `orca serve` survived on
  import-order luck. **Value imports from a hub module go in a leaf under `src/shared/`, and nothing
  crossing a cycle is evaluated at module scope.** Its own tests stayed green: the 29 were upstream
  tests the series never names, so a patch-derived test list is necessary and not sufficient.
  `6768` = `DEFAULT_WS_PORT` non-trusted default; GUI-style log lines (dbus `login1 Inhibit
  AccessDenied`, `GpuControl` failures, `[pty:history:gc]`) mean the desktop app booted.
- **`FATAL … Failed to shutdown` + `SIGTRAP` after ready** → your own `timeout <s>` wrapper
  fired SIGTERM at the tree. Not a crash.
- **`pkill -f <pattern>` over `ssh`/`pct exec` kills itself** — the wrapping shell's cmdline holds
  the pattern. Use `[b]racketed` patterns, and keep the kill in its own invocation.
- **`ss -ltn` is the only bind truth.** Ready-JSON endpoint strings are derived, not observed
  (fixed in the current patch, but always confirm with `ss`).
- **Zombie listeners skew results** — kill `[s]quashfs-root` + `Xvfb` remnants first; a leftover
  flagless run holds `0.0.0.0:6768`. `login1 Inhibit AccessDenied` and GPU `kTransientFailure` are
  benign in an LXC. To see whether the CLI translated flags for the Electron child:
  `tr '\0' ' ' < /proc/<pid>/cmdline`.
- **Phone loops "WebSocket closed" while the tile works** → the phone is on the PUBLIC DNS path
  (cellular/VPN, or Wi-Fi with Private Relay/DoH) hitting the edge, not internal Traefik. A
  `*.astrateam.net` cert **cannot** cover `*.portal.astrateam.net` — wildcards match ONE level.
  Check `openssl s_client -servername <app-host> -connect <edge-ip>:443`. Discriminate layers with a
  real WS client (`node -e` with `ws`), not curl — curl cannot upgrade, so its 200 means nothing.
- **Phone paired in the UI but cannot connect after a restart** → the QR carried the per-build
  session token, which Coder revokes on rebuild while the registry persists, so the UI looks fine.
  §4's durable token is the fix; if it regressed, `pairing-token` mtime must NOT change on a
  healthy boot.
