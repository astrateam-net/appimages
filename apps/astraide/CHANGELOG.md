# astraide changelog

astraide ships as a **patch series** over pristine upstream Orca (see
[CLAUDE.md](CLAUDE.md) for the build + authoring contract). Each patch `000N` is an
independent capability and, in practice, a **release**: merging it to `appimages` main
rebuilds the `.AppImage` and re-publishes the same `astraide-<VERSION>` GitHub Release
asset (CLAUDE.md §3). The Dockerfile applies the series in filename order on the pristine
upstream tag.

This file is the skimmable "what shipped in each patch" list, newest first. The durable
invariants behind these capabilities live in CLAUDE.md §1.

Recurring root cause: Orca's web client replaces the Electron preload with
`web-preload-api.ts` and upstream **stubs most of it** — empty lists, `{available:false}`,
throw-on-call. Most "works on desktop, dead in the tile" reports are one of those stubs; the
`astraide-patch-author` skill has the diagnose/fix playbook.

---

## 0006 — web-client floating-workspace directory picker

`patches/0006-web-floating-workspace-dir-picker.patch`

**Symptom:** in the web tile, Settings → Floating Workspace → **Terminal Directory**'s
folder button did nothing — no picker, no error — and no directory could be applied. (Same
native-dialog class as the pet Import/Upload buttons, a separate follow-up.)

**Cause:** the desktop feature is a **three-part host operation**, and the web client had a
path for none of them. (1) The button calls `window.api.app.pickFloatingWorkspaceDirectory()`,
a **native OS dialog** — stubbed to `Promise.resolve(null)` in the browser. (2) The native
picker also **grants trust** — `grantFloatingWorkspaceDirectory` authorizes the directory and
records it in `floatingTerminalTrustedCwds`. (3) Both the settings input and the floating
terminal read the cwd through `getFloatingTerminalCwd` → `resolveFloatingTerminalCwd`, which
expands `~`, canonicalizes, and **only returns a custom path when it's trusted** — else falls
back to the default app workspace. In the web client `getFloatingTerminalCwd` was stubbed to
`''`. So even a saved path was neither trusted, resolved, nor displayed. The tile's floating
terminals run on the connected **server**, so all three must happen on the workspace host.

**Fix — wire the whole contract over runtime RPC:**
- Two runtime methods `floatingWorkspace.resolveCwd` / `grantDirectory` reuse the existing
  `ipc/floating-workspace-directory.ts` helpers via a minimal `FloatingWorkspaceDirectoryStore`
  adapter over the runtime's settings store (the desktop `Store` stays structurally
  assignable — its callers are untouched).
- Both **mutate/authorize host state**, so — exactly like `cli.*` (0005) — they stay **out of**
  `MOBILE_RPC_METHOD_ALLOWLIST`: a paired phone must never resolve or trust host directories.
  Test-enforced (not-allowlisted + registered).
- `app.grantFloatingWorkspaceDirectory` added to the preload contract (desktop IPC handler +
  web routing) so a browser-picked directory records the **same grant** the native picker does.
- Web client: Terminal Directory opens the existing `RemoteFileBrowser` (`files.browseServerDir`,
  the "Add a project → Browse folder" path); `onSelect` **grants then stores**;
  `getFloatingTerminalCwd` routes to `resolveCwd` so both the input **and** the terminal cwd
  resolve on the host. Gated on `settings.activeRuntimeEnvironmentId` (pure
  `shouldUseServerDirectoryBrowser` helper) — with no environment, it falls back to the native
  no-op. **Desktop is unchanged.**

Touch points: `main/runtime/rpc/methods/floating-workspace.ts` (+ `.test.ts`), `rpc/methods/index.ts`,
`main/runtime/orca-runtime.ts`, `main/ipc/floating-workspace-directory.ts`, `main/ipc/app.ts`,
`preload/{api-types,index}.ts`, `web/web-preload-api.ts`,
`renderer/src/components/settings/FloatingWorkspacePane.tsx` (+ `.test.tsx`),
`main/runtime/mobile-rpc-allowlist.test.ts`.

## 0005 — web-client agent-skill CLI registration

`patches/0005-web-cli-registration.patch`

**Symptom:** every agent-skill setup card (Orchestration, Browser Use, Computer Use,
Linear, Ephemeral VMs, Mobile Emulator, Settings → CLI) warned **"Orca CLI registration is
unavailable"** and could never register `orca-ide`.

**Cause:** the skill-setup prerequisite (`ensureOrcaCliAvailableForAgentSkillTerminal`)
probes `window.api.cli.getInstallStatus()` and, if the CLI isn't on PATH, calls
`cli.install()` so the terminal it opens can resolve the Orca command. In the web client
`createCliApi()` was a hardcoded `supported:false` stub. But that terminal runs on the
connected **server** (like every web PTY), where `orca-ide` genuinely exists (serve
installs it on first run — CLAUDE.md §2).

**Fix:**
- New runtime RPC `cli.getInstallStatus` / `cli.install` / `cli.remove` reuse the exact
  `CliInstaller` behind the `cli:` IPC handlers (extracted as
  `{get,install,remove}CliInstallStatusWithShellPathHydration` in `ipc/cli.ts`; same
  shell-path hydration so `pathConfigured` matches what a PTY sees).
- `createCliApi()` routes those three through `callRuntimeResult`; the status probe falls
  back on transient failure, `install`/`remove` surface real server errors (like desktop).
  No active environment → honest `supported:false`.
- **Scope:** `install`/`remove` mutate the host (`~/.local/bin` symlink), so all three stay
  **out of `MOBILE_RPC_METHOD_ALLOWLIST`** — a paired phone can never register/remove host
  commands; runtime-scope only, like `terminal.*`/`files.*`. Not credential-minting, so no
  `trustedMobilePairing` context — a plain runtime method like `diagnostics`/`preflight`.
- Test-enforced: `mobile-rpc-allowlist.test.ts` (not-allowlisted + registered),
  `rpc/methods/cli.test.ts` (routing). WSL registration stays a Windows-desktop concern.

Touch points: `src/main/runtime/rpc/methods/cli.ts` (+test), `src/main/ipc/cli.ts`,
`src/main/runtime/rpc/methods/index.ts`, `src/main/runtime/mobile-rpc-allowlist.test.ts`,
`src/renderer/src/web/web-preload-api.ts`.

## 0004 — web-client resource manager

`patches/0004-web-resource-manager.patch`

Resource Manager in the web client showed all zeros — the web preload `memory.getSnapshot`
was an empty-snapshot stub. Now routes to runtime `diagnostics.memory` (which phones
already poll), so the tile shows the **workspace's** processes + host RAM/CPU. One-line
stub→RPC reroute; falls back to the empty snapshot only when no environment is connected.

## 0003 — web-client runtime share links

`patches/0003-web-runtime-share-links.patch` · contract: CLAUDE.md §1

Upstream's "Advertise this app as a server → New Link" surface (runtime-scope grants) is
desktop-only, so a headless serve's grants were mintable by nobody. Adds
`mobile.getRuntimePairingUrl` / `listRuntimeAccessGrants` / `revokeRuntimeAccess` (same
`trustedMobilePairing` runtime-scope gate; never mobile-allowlisted — a phone minting a
runtime grant would be scope escalation), and reframes Settings → Remote Orca Servers as
"Share the connected server" in the web client.

## 0002 — web-client mobile pairing

`patches/0002-web-mobile-pairing.patch` · contract: CLAUDE.md §1 · **went live 2026-07-24**

Stock Orca's "Pair this computer" screen is desktop-only — in the web client every
`window.api.mobile.*` call was a stub, and the LAN-interface model is wrong behind Coder.
Adds runtime-RPC minting (`mobile.createPairingOffer` / `listDevices` / `revokeDevice`,
runtime-scope only, strict params), pins connection mode `local-only`, and advertises the
Coder subdomain wss URL (`?coder_session_token=…`) as the pairing endpoint — Coder is
authn, Orca is authz + E2EE. Phone survives workspace restarts via the durable token minted
by the install script (CLAUDE.md §4).

## 0001 — trusted-proxy web session

`patches/0001-serve-trusted-proxy-web-session.patch` · contract: CLAUDE.md §1

The foundation: `serve --trusted-proxy` binds the runtime WS listener to `127.0.0.1` and
exposes a loopback-gated `GET /trusted-session` offer, so the Coder subdomain tile loads
the full Orca web UI with **no pairing prompt** (code-server's `--auth none` + loopback
trust model), keeping Orca's E2EE intact. The web client dials same-origin from
`window.location`, with stale-credential recovery on serve re-key.

Also folds in **web-session device naming**: trusted-session devices are named
`Web session <date>` (fixes 0001's own mint, which previously leaked the upstream
`CLI <date>` default) so the shared-access list reads honestly: Web session / Runtime /
Mobile.
