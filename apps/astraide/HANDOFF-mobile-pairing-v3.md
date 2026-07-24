# HANDOFF — Mobile pairing v3: native "Generate code" QR in the web client behind Coder

## STATUS (2026-07-24)

**Patch authored, tested, and exported.** Done:

- Fork commit `0fc7d64da` on `patch/trusted-proxy-v2` (design differs slightly from the sketch
  below — see CLAUDE.md §1b for the shipped contract: RPC methods
  `mobile.createPairingOffer`/`listDevices`/`revokeDevice`, authorization via a
  `trustedMobilePairing` context injected only for runtime-scope WS connections, strict params,
  server-pinned `local-only` mode, client-side QR, web UI pins local-only + hides
  picker/Relay in both MobilePage hero and Settings → Mobile).
- Exported as `patches/0002-web-mobile-pairing.patch` (series: 0001 = tile session,
  0002 = mobile pairing; scoped by logic, applied in order). Full series `git apply` verified
  on pristine `v1.4.153`.
- `typecheck:tsc` clean; focused vitest 89/89 green incl. new scope tests
  (phone-scope cannot mint — allowlist + fail-closed context both test-enforced).

**Remaining** (acceptance criteria below still to be proven live):

1. ~~Commit/push this repo → CI republishes asset~~ **DONE** — asset republished 06:30Z, CI green.
2. ~~Control-plane template `--pairing-address`~~ **DONE & DEPLOYED** — QR renders in the tile,
   serve advertises the tokenized wss URL (verified in serve.log).
3. Live pairing: **BLOCKED ON PUBLIC EDGE, not on this patch.** Verified 2026-07-24: the full
   chain works over the internal path (10.1.125.235) — Coder query-param auth 200, real WS
   client upgrade OPEN, Orca accepts. But the public edge `zt.astrateam.net` (5.42.122.90),
   which phones hit via public DNS (cellular, and Wi-Fi under iCloud Private Relay/DoH),
   terminates TLS with a `*.astrateam.net` cert that does NOT cover `*.portal.astrateam.net`
   (one-level wildcard) → iOS closes the socket instantly ("WebSocket closed" loop).
   **Fix in control-plane**: give the zt edge a `*.portal.astrateam.net` cert (or SNI
   passthrough to the internal Traefik) + route those hosts to Coder with WS upgrades.
   Then rescan on cellular. Phone device credential verified healthy in orca-devices.json
   (pending mobile entry matches the QR token).

## Mission

Make Orca's **Settings → Mobile / "Pair this Mac" screen work natively in the web
client** when astraide runs as a Coder workspace app. The workspace owner opens the
astraide tile in their browser, clicks **Generate code**, sees a real QR, scans it
with the Orca mobile app — and the phone pairs and connects **from anywhere
(cellular included)** through Coder's wildcard app proxy.

**Design for many workspaces and many users.** A user may not know (or care) where
their workspace runs. They have no SSH, no `serve.log`, no operator on call. The
pairing flow must be fully self-service from the tile UI. Do NOT ship a
"read the QR from the log" workaround as the solution — that is the fallback we
already have, not the feature.

Current state (v1.4.153 + patch v2): the tile works, mobile pairing does not — the
web client's entire mobile API is stubbed out (see Root Cause).

---

## What astraide is (30-second context)

- **astraide** = patched build of [stablyai/orca](https://github.com/stablyai/orca)
  (an Electron "Agent Development Environment"), shipped as a Linux AppImage from
  this repo, run headless inside a Coder workspace (Proxmox LXC) as
  `orca-ide serve --trusted-proxy --port <p>`, and exposed as a Coder subdomain
  app tile (`share = "owner"`), the same shape as code-server.
- **Patch v2 (already shipped)** — `patches/0001-serve-trusted-proxy-web-session.patch`:
  loopback-only bind, loopback-gated `GET /trusted-session` that hands the web
  client its E2EE pairing offer (no token in URL), same-origin WS dial, stale-
  credential auto-recovery. Read `apps/astraide/CLAUDE.md` **first** — it is the
  binding agent contract for this app (design contract, launch contract, patch
  authoring workflow, deployment map, debugging gotchas).
- **This handoff adds patch v3**: web-client mobile pairing.

---

## Where everything lives (all paths verified on this machine)

| What | Path |
|---|---|
| This app (patch, contract, build) | `/Volumes/Devops/Git/Github/astrateam-net/appimages/apps/astraide/` |
| Agent contract (READ FIRST) | `apps/astraide/CLAUDE.md` |
| Current patch (v2) | `apps/astraide/patches/0001-serve-trusted-proxy-web-session.patch` |
| **Orca fork worktree** (the "polygon" — author patches HERE) | `/Volumes/Devops/Git/Github/mrkhachaturov/orcaide-v2` — branch `patch/trusted-proxy-v2`, based on verified upstream tag `v1.4.153` (commit `a7ba9d912`). LOCAL ONLY, not pushed. Ignore any local `v1.4.154` tag — upstream never published it. |
| Orca upstream reference clone | `appimages/.upstream/` (gitignored; study only, never a build input) |
| **Coder source code** (reference clone) | `/Volumes/Devops/Git/Github/astrateam-net/astrateam-control-plane/ref/coder` |
| **Our Coder template** (astraide tile + install script) | `/Volumes/Devops/Git/Github/astrateam-net/astrateam-control-plane/terraform/coder/templates/proxmox-lxc/` — `scripts/install-astraide.sh` (+ the `astraide.tf` coder_app/coder_script wiring next to it) |
| Coder docs wiki (Miyo index) | skill: `/Volumes/Devops/Projects/coder-docs/skills/coder-wiki/SKILL.md` → `mcp__miyo__search(folder_path: "coder-wiki", ...)` |
| Orca docs wiki (Miyo index) | skill: `/Volumes/Devops/Projects/orca-docs/skills/orca-wiki/SKILL.md` → `mcp__miyo__search(folder_path: "orca-wiki", ...)` — mobile pairing: `orca-wiki/guide/remote-servers.md`, `orca-wiki/guide/mobile.md` |
| Release artifact | GitHub `astrateam-net/appimages` → release tag `astraide-v1.4.153`, asset `astraide-v1.4.153-x86_64.AppImage` (CI re-publishes under the SAME tag; workspaces refresh via ETag — see CLAUDE.md §3) |
| Live deployment for testing | Coder host `coder01`, workspace CT 100; module dir in-workspace: `/home/coder/.coder-modules/astrateam/astraide/` (recipes in CLAUDE.md §5) |

Deployment note: the control-plane repo (template + install script) is **deployed
manually** — there is no CI there. Coordinate template pushes with the operator;
your patch ships through this repo's CI (commit → Release workflow → asset
republished → ETag refresh on next workspace start).

---

## Root cause (verified in source — all refs are fork-worktree paths at v1.4.153)

The Settings → Mobile pairing screen is desktop-Electron-only. In the **web
client** every mobile API is a hardcoded stub:

- `src/renderer/src/web/web-preload-api.ts:805-822` —
  `mobile.listNetworkInterfaces()` always resolves `{ interfaces: [] }` → the UI
  shows **"No interfaces found"**; `mobile.getPairingQR()` always resolves
  `{ available: false }`.
- `src/renderer/src/components/mobile/use-mobile-pairing-generation.ts:80-98` —
  maps `available: false` to the toast **"WebSocket transport is not running"**
  (misleading; the transport is fine).
- The real handlers exist only as Electron IPC: `src/main/ipc/mobile.ts`
  (`mobile:getPairingQR` → `rpcServer.createMobilePairingOffer`, interface
  enumeration via `node:os networkInterfaces()`).

So this is not a networking problem — the mint path simply doesn't exist in the
web client. Additionally, the LAN-interface model is wrong for a Coder workspace
anyway: the workspace's IPs are never phone-reachable; the only address worth
advertising is the Coder subdomain URL.

---

## The verified end-to-end chain (every link checked in source — build on this)

1. **Server-side mint exists and is transport-agnostic**:
   `OrcaRuntimeRpcServer.createPairingOffer({ address, scope: 'mobile', rotate })`
   — `src/main/runtime/runtime-rpc.ts:588-651`. (`createMobilePairingOffer` at
   `:653` adds Orca Relay provisioning on top — **do not use Relay**; headless
   serve has no relay provider and the product decision here is Coder-native
   networking only. `local-only` connection mode is what we want.)
2. **The advertised endpoint accepts a full URL with a query string**:
   `src/main/runtime/pairing-endpoint.ts` (`resolveFullUrl`, lines 41-65) rejects
   wildcard hosts / credentials / fragments but **allows `?query`**, and
   normalizes `https://` → `wss://`. This is the keystone.
3. **Coder authenticates subdomain-app requests via the `coder_session_token`
   query parameter** (no cookie needed — works for a non-browser WS client):
   - `ref/coder/coderd/workspaceapps/cookies.go:76-97` — `TokenFromRequest` falls
     back to `httpmw.APITokenFromRequest`;
   - `ref/coder/coderd/httpmw/apikey.go:928-943` — reads the
     `coder_session_token` query param;
   - precedent: Coder's own web terminal is WS-only and uses exactly this
     (`ref/coder/coderd/workspaceapps/db.go:175-181`);
   - the same pattern powers the VS Code Desktop button via `$SESSION_TOKEN`
     substitution (`ref/coder/site/src/modules/apps/apps.ts:12,125`).
4. **The Orca mobile app dials the offer endpoint verbatim** (query preserved):
   `mobile/src/transport/rpc-client.ts:299` — `new WebSocket(endpoint)`.
5. Coder proxies the wss upgrade to `127.0.0.1:<port>` inside the workspace —
   the same loopback WS server the tile already uses. Orca's E2EE device-token
   handshake runs on top; Coder is authn, Orca is authz+E2EE.

**Resulting advertised endpoint** (what the QR must carry):

```
wss://<app-slug>--<agent>--<workspace>--<owner>.<wildcard-domain>/?coder_session_token=<token>
```

Already validated as accepted by `resolveAdvertisedPairingEndpoint` and dialable
by the mobile client. `serve --mobile-pairing --pairing-address "https://…?coder_session_token=…"`
(printed-QR flavor, `src/main/index.ts:1544-1603`) is the low-level proof harness
you can use before touching the UI.

---

## Design sketch for v3 (recommended shape — you own the final design)

Authoring rules: work in the fork worktree on top of `patch/trusted-proxy-v2`,
follow `apps/astraide/CLAUDE.md` §4 (patch authoring workflow) exactly — regen the
patch as one cumulative diff vs `v1.4.153`, verify `git apply --check` on pristine
upstream, keep it upstreamable in spirit.

1. **New runtime-RPC method** (e.g. `mobile.createPairingOffer`) on
   `OrcaRuntimeRpcServer`, callable **only by `runtime`-scope connections** (the
   web client is runtime-scope; a paired phone is `mobile`-scope and must NOT be
   able to mint new device credentials — check the scope of the calling
   connection, not just authentication). Inputs: `{ rotate?: boolean }`. It calls
   the existing `createPairingOffer({ scope: 'mobile', rotate, address: <default> })`.
2. **Server-side default advertised address** = the serve-configured pairing
   address (patch v2 already carries `trustedProxyAddress` from
   `--serve-pairing-address`). The web client never chooses an address — the
   workspace's interfaces are meaningless to it. This kills the "No interfaces
   found" picker for the web case entirely.
3. **Web preload implementation** (`web-preload-api.ts`): replace the
   `mobile.getPairingQR` stub with the RPC call; render the QR client-side (the
   `qrcode` package is already a dependency — main uses `QRCode.toDataURL`,
   `src/main/ipc/mobile.ts:118`). `listDevices` / `revokeDevice` should also be
   wired through RPC if cheap — self-service revocation matters in multi-user
   land. Leave Windows-firewall APIs stubbed.
4. **UI adjustments** (`src/renderer/src/components/settings/MobilePane.tsx`,
   `MobilePairingConnectionOptions.tsx`, `src/renderer/src/components/mobile/*`):
   in web mode, hide the network-interface picker and the **Orca Relay** option
   (headless serve degrades relay to `local-only` anyway — the UI must not
   mislabel; see `createMobilePairingOffer`'s degrade logic,
   `runtime-rpc.ts:692-721`). Show the "the code connects through your workspace
   URL" framing instead.
5. **Template side** (control-plane, coordinate with its operator agent):
   `install-astraide.sh` / `astraide.tf` must pass
   `--pairing-address "https://<app-hostname>/?coder_session_token=${TOKEN}"` to
   serve. The hostname is constructible in Terraform from app slug + agent +
   `data.coder_workspace.me.name` + `data.coder_workspace_owner.me.name` +
   wildcard domain; the token from `data.coder_workspace_owner.me.session_token`
   (per-owner, minted per build — automatically correct in multi-user: each
   workspace advertises its own owner's token; `share = "owner"` already scopes
   the app). Hardened alternative: an
   `application_connect`-scoped token (`ref/coder/cli/tokens.go` — repeatable
   `--scope`, e.g. `workspace:application_connect`, plus `--lifetime`), but that
   requires per-user minting machinery — fine to defer.
   **Gotcha**: the script is rendered by Terraform `templatefile` — shell vars
   must be `$${…}`-escaped (see existing script for the pattern).

### Security invariants (do not regress)

- The pairing URL is a **double secret**: Orca device token + Coder session
  token. It must only ever be displayed inside the owner-authenticated tile
  (share=owner) or serve.log inside the owner's workspace. Never write it into
  build logs, Terraform outputs, or coder_metadata.
- `mobile`-scope connections must not mint offers (privilege escalation:
  phone → new runtime credential).
- Tile behavior unchanged: same-origin dial, loopback gate on
  `/trusted-session`, E2EE intact. Note the tokenized URL will also appear in
  the `/trusted-session` offer body via `trustedProxyAddress` — loopback-gated,
  single-owner workspace, accepted; document it in the patch comment.
- Token expiry is real: when the Coder token dies, the phone's reconnect fails
  → user regenerates the QR (rotate) and rescans. Make sure the UI regenerate
  path uses `rotate: true` and works after expiry. State this in the user-facing
  copy if you touch it.

---

## Acceptance criteria

1. Fresh workspace, any owner, zero operator involvement: open astraide tile →
   Settings → Mobile → **Generate code** → QR renders in the web client.
2. Scan with Orca mobile (iOS/Android) on **cellular** → phone pairs and shows
   the workspace's worktrees/agents live.
3. Phone survives workspace restart (device registry persists in the LXC
   rootfs); after Coder-token expiry, Regenerate → rescan works.
4. A paired phone cannot mint new pairing offers (scope check proven by test).
5. Tile web session still works exactly as before (regression: `/trusted-session`
   flow, same-origin dial, stale-credential recovery).
6. `git apply --check` clean on pristine `v1.4.153`; typecheck + focused vitest
   green (note: `web-preload-api.test.ts` is **known-broken at baseline** — 75
   alias-resolution failures pre-exist your change; see CLAUDE.md §4 — prove
   your delta doesn't add failures, don't try to fix the baseline);
   AppImage builds via `docker buildx bake -f apps/astraide/docker-bake.hcl appimage`;
   live verify in CT 100 per CLAUDE.md §5.

## Verification recipes you'll want early

- Prove the chain before UI work: restart serve in CT 100 with
  `--mobile-pairing --pairing-address "https://<tile-hostname>/?coder_session_token=<token>"`,
  scan the serve.log QR from a real phone on cellular. If that pairs, everything
  after is pure plumbing/UI.
- `curl -s "https://<tile-hostname>/web-index.html?coder_session_token=<token>"`
  from OUTSIDE (no cookies) → 200 proves the Coder query-param auth lane on your
  deployment before involving a phone at all.

## Known traps (inherited — details in CLAUDE.md §6)

- `AppRun` is the desktop entrypoint and silently ignores `serve` flags — the CLI
  shim `squashfs-root/resources/bin/orca-ide` is the only correct launcher.
- `--no-sandbox` must come via `ORCA_APPIMAGE_NO_SANDBOX=1` env, never as a serve flag.
- `pkill -f`/`pgrep -f` self-match their own command line over ssh/pct exec — use
  bracketed patterns (`[a]straide`) and separate invocations.
- `timeout`-killed Electron logs a scary `FATAL Failed to shutdown` — that's your
  SIGTERM, not a crash. `ss -ltn` is the only bind truth.
- pnpm in the fork: `mise x pnpm@10.24.0 -- pnpm …` (upstream-pinned; newer pnpm
  breaks the frozen lockfile). Never pipe away exit codes.
- Docs (Orca's and ours) can lag the code in both directions — `src/` is the
  contract; verify claims in source before building on them.
