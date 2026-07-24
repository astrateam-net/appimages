---
name: astraide-patch-workflow
description: Author, test, changelog, and ship astraide AppImage patches (the patch-over-upstream Orca series), and fix the next broken web-client feature. Use when working in apps/astraide — adding or fixing a patch, or fixing a stubbed web-client feature ("works on desktop, dead in the tile").
paths: apps/astraide/**
---

# astraide patch workflow

`apps/astraide/patches/` is a **series** of `git diff`s applied in filename order on pristine
upstream Orca (`v1.4.153`) by the Dockerfile. One patch = one capability = one release.
Contract lives in `apps/astraide/CLAUDE.md`; release notes in `apps/astraide/CHANGELOG.md`.

## Where things live

- Fork (author here, never a build input): `mrkhachaturov/orcaide` @ `patch/trusted-proxy-v2`,
  worktree `/Volumes/Devops/Git/Github/mrkhachaturov/orcaide-v2`. Base = `v1.4.153`.
  (Ignore branch `patch/trusted-proxy` — phantom `v1.4.154` base.)
- Patches out: `apps/astraide/patches/000N-<capability>.patch`.
- Each patch = diff between consecutive feature-boundary commits on the fork branch:

  | Patch | Boundary |
  |---|---|
  | 0001 trusted-proxy session | `git diff v1.4.153 3d65845c6` |
  | 0002 web mobile pairing | `git diff 3d65845c6 7c145fb1a` |
  | 0003 web runtime share links | `git diff 7c145fb1a c94cca036` |
  | 0004 web resource manager | `git diff c94cca036 6375c2bf2` |
  | 0005 web CLI registration | `git diff 6375c2bf2 a50a20da2` |
  | next | `git diff <prev-boundary> <new-commit>` → `0006-…` |

## Make the patch

1. Edit + commit in the fork worktree. New capability → new number. A fix to existing patch
   logic → restack that boundary and re-export the series (never a new number).
2. Export the boundary diff:
   ```bash
   cd /Volumes/Devops/Git/Github/mrkhachaturov/orcaide-v2
   git diff <prev-boundary> HEAD > <appimages>/apps/astraide/patches/000N-<capability>.patch
   ```

## Test (in the fork worktree)

```bash
mise x pnpm@10.24.0 -- pnpm install --ignore-scripts --prefer-offline   # mise has no pnpm pinned
mise x pnpm@10.24.0 -- pnpm run typecheck:tsc                           # must be clean
mise x pnpm@10.24.0 -- pnpm exec vitest run \
  src/renderer/src/web/web-runtime-client.test.ts \
  src/renderer/src/web/web-pairing.test.ts \
  src/cli/runtime/launch.test.ts src/cli/args.test.ts \
  src/main/runtime/rpc/methods/mobile-pairing.test.ts \
  src/main/runtime/rpc/methods/pairing.test.ts \
  src/main/runtime/rpc/methods/cli.test.ts \
  src/main/runtime/mobile-rpc-allowlist.test.ts                         # all green
```

Then verify the **whole series** applies on the pristine tag (same as the Dockerfile):

```bash
git worktree add --detach /tmp/orca-pristine v1.4.153
for p in <appimages>/apps/astraide/patches/*.patch; do
  git -C /tmp/orca-pristine apply "$p" || break
done && echo CLEAN
git worktree remove --force /tmp/orca-pristine
```

Pre-existing failures to ignore (env `@/`-alias quirk, not yours): `web-preload-api.test.ts`,
`agent-skill-cli-prerequisite.test.ts` fail to load. Identical with/without your changes.

## Add the changelog entry

Prepend a section to `apps/astraide/CHANGELOG.md` (newest first), and add the boundary row to
the table above. Entry shape:

```
## 000N — <capability>

`patches/000N-<capability>.patch`

**Symptom:** <what the user saw>.
**Cause:** <the stub / gap, one line>.
**Fix:** <bullets: RPC/method added, web reroute, scope decision, tests>.

Touch points: <files>.
```

## Ship

1. Update `apps/astraide/CLAUDE.md` if behavior/contract changed (same commit as code).
2. Commit patch + docs in the `appimages` repo. `[skip ci]` only for docs-only pushes.
3. Push `appimages` main → CI rebuilds and republishes the same-tag `astraide-<VERSION>` asset.
4. Restart the workspace (ETag refresh picks up the same-version rebuild), verify live in CT 100
   (recipes in CLAUDE.md §4).

## Fix a broken web feature

Symptom: works on desktop, dead in the browser tile ("No interfaces found", zeros,
"…unavailable"). Cause: upstream stubs most of `web-preload-api.ts` (`createWebPreloadApi`).

1. **Confirm it's a stub.** Grep the error string or `window.api.<ns>` in `web-preload-api.ts`.
   Hardcoded return (`Promise.resolve({...})`, `createEmpty…()`, `reject`) = stub, not a bug.
2. **Read the desktop contract:** `src/preload/index.ts` (+`api-types.ts`) and
   `src/main/ipc/*.ts`. Mirror names/shapes 1:1 so the renderer stays untouched.
3. **Existing runtime RPC?** Check `src/main/runtime/rpc/methods/` + `ALL_RPC_METHODS`. If one
   exists, the fix is one line: route the stub through `callRuntimeResult('<method>')` (0004).
4. **No RPC → add one:**
   - Host probe/op (not credential-minting): plain method reusing `ipc/*.ts`, like
     `diagnostics`/`preflight`. Scope gate = absence from `MOBILE_RPC_METHOD_ALLOWLIST` (0005).
   - Credential mint/revoke: authorize via the `trustedMobilePairing` ctx (runtime-scope only,
     injected in `handleWebSocketMessage`, fail closed). Strict zod params. Server callbacks in
     `buildTrustedMobilePairingContext()` (0002/0003).
5. **Scope (never regress):** new methods stay OUT of `MOBILE_RPC_METHOD_ALLOWLIST` unless
   phones need them; anything minting/revoking credentials or mutating the host is never
   phone-reachable. Add the not-allowlisted + registered assertions to `mobile-rpc-allowlist.test.ts`.
6. **UI gating:** branch on `isWebClientLocation()`. Hide desktop-only affordances (interface
   pickers, custom addresses, Relay); advertised address is always server policy
   (`--pairing-address`). Reframe copy: browser is a client, "this app" = the workspace server.
7. Then: Test → Changelog → Ship (above).

Can't fix server-side: anything needing the STOCK phone/desktop client to change → upstream PR
(e.g. offer carries no server name, phone shows "Host 1"). Web needs data the runtime doesn't
expose → the RPC method is the patch. Client app needs new behavior → upstream's court.
