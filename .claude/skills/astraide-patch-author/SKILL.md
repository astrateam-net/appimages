---
name: astraide-patch-author
description: Create an astraide patch — diagnose a stubbed web-client feature and implement the fix in the Orca fork, then export the boundary diff to apps/astraide/patches/. Use when adding or fixing an astraide capability. Hand to astraide-patch-verify when done.
paths: apps/astraide/**
---

# astraide — author a patch

astraide = patched upstream Orca → Linux AppImage. `apps/astraide/patches/` is a series of
`git diff`s applied in filename order on pristine `v1.4.153`. **Author in the fork, never in this
repo.** Invariants you must respect: `apps/astraide/CLAUDE.md`. History: `apps/astraide/CHANGELOG.md`.

Paths are operator-relative — resolve these on your machine:
- `<fork>` = your clone of `mrkhachaturov/orcaide` @ branch `patch/trusted-proxy-v2` (base `v1.4.153`).
  Ignore branch `patch/trusted-proxy` — phantom `v1.4.154` base.
- `<repo>` = this appimages repo root.

Each patch = diff between consecutive feature-boundary commits on the fork branch:

| Patch | Boundary |
|---|---|
| 0001 trusted-proxy session | `v1.4.153 → 3d65845c6` |
| 0002 web mobile pairing | `3d65845c6 → 7c145fb1a` |
| 0003 web runtime share links | `7c145fb1a → c94cca036` |
| 0004 web resource manager | `c94cca036 → 6375c2bf2` |
| 0005 web CLI registration | `6375c2bf2 → a50a20da2` |
| 0006 web floating-workspace dir picker | `a50a20da2 → 6c55cf070` |
| next | `<prev-boundary> → <new-commit>` → `0007-…` |

## Diagnose (the usual bug: a web-client stub)

Symptom: works on desktop, dead in the browser tile ("No interfaces found", zeros, "…unavailable").

1. **Confirm it's a stub.** Grep the error string / `window.api.<ns>` in `web-preload-api.ts`.
   Hardcoded return (`Promise.resolve({...})`, `createEmpty…()`, `reject`) = stub, not a bug.
2. **Read the desktop contract:** `src/preload/index.ts` (+`api-types.ts`), `src/main/ipc/*.ts`.
   Mirror names/shapes 1:1 so the renderer stays untouched.
3. **Existing runtime RPC?** Check `src/main/runtime/rpc/methods/` + `ALL_RPC_METHODS`. If one
   exists, the fix is one line: route the stub through `callRuntimeResult('<method>')` (0004).
4. **No RPC → add one:**
   - Host probe/op (not credential-minting): plain method reusing `ipc/*.ts`, like
     `diagnostics`/`preflight`. Scope gate = absence from `MOBILE_RPC_METHOD_ALLOWLIST` (0005).
   - Credential mint/revoke: authorize via the `trustedMobilePairing` ctx (runtime-scope only,
     injected in `handleWebSocketMessage`, fail closed). Strict zod params. Server callbacks in
     `buildTrustedMobilePairingContext()` (0002/0003).
5. **Scope (never regress):** new methods stay OUT of `MOBILE_RPC_METHOD_ALLOWLIST` unless phones
   need them; anything mutating the host or minting/revoking credentials is never phone-reachable.
   Add the not-allowlisted + registered assertions to `mobile-rpc-allowlist.test.ts`.
6. **UI:** branch on `isWebClientLocation()`; hide desktop-only affordances (interface pickers,
   custom addresses, Relay); advertised address is always server policy (`--pairing-address`);
   reframe copy (browser = client, "this app" = the workspace server).

Can't fix server-side: needs the STOCK phone/desktop client to change → upstream PR (e.g. offer
carries no server name → phone shows "Host 1"). Web needs data the runtime doesn't expose → the
RPC method is the patch.

## Implement + export

1. Edit + commit in `<fork>`. New capability → new number. A fix to existing patch logic →
   restack that boundary and re-export the series (never a new number).
2. Export the boundary diff:
   ```bash
   cd <fork>
   git diff <prev-boundary> HEAD > <repo>/apps/astraide/patches/000N-<capability>.patch
   ```

→ Hand to **astraide-patch-verify**.
