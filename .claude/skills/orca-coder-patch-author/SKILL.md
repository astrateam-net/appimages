---
name: orca-coder-patch-author
description: Create an orca-coder patch — diagnose a stubbed web-client feature and implement the fix in the Orca fork, then export the boundary diff to apps/orca-coder/patches/. Use when adding or fixing an orca-coder capability. Hand to orca-coder-patch-verify when done.
paths: apps/orca-coder/**
---

# orca-coder — author a patch

orca-coder = patched upstream Orca → Linux AppImage. `apps/orca-coder/patches/` is a series of
`git diff`s applied in filename order on pristine `v1.4.155`. **Author in the fork, never in this
repo.** Invariants you must respect: `apps/orca-coder/CLAUDE.md`. History: `apps/orca-coder/CHANGELOG.md`.

Paths are operator-relative — resolve these on your machine:
- `<fork>` = your clone of `mrkhachaturov/orcaide` @ branch `patch/trusted-proxy-v2` (base `v1.4.155`).
  Ignore branch `patch/trusted-proxy` — phantom `v1.4.154` base. `backup/v153-series` holds the
  pre-bump series on `v1.4.153`.
- `<repo>` = this appimages repo root.

Each patch = diff between consecutive feature-boundary commits on the fork branch:

Base is **`v1.4.156`**. Patch `0000` was dropped on that bump (upstream landed the
`DetachedHeadBadge` `tabIndex` fix) — every patch in the series is now an orca-coder capability,
none carries an upstream fix. See `apps/orca-coder/CLAUDE.md` §3.

| Patch | Boundary |
|---|---|
| 0001 trusted-proxy session | `v1.4.156 → 9d6a7a312` |
| 0002 web mobile pairing | `9d6a7a312 → 9fb3a4713` |
| 0003 web runtime share links | `9fb3a4713 → 0044ff0b6` |
| 0004 web resource manager | `0044ff0b6 → 77df8c08d` |
| 0005 web CLI registration | `77df8c08d → 46e99470b` |
| 0006 web floating-workspace dir picker | `46e99470b → 8cb9c88a1` |
| 0007 runtime-seeded settings | `8cb9c88a1 → 113626f5a` |
| 0008 open-in browser editor URLs | `113626f5a → 847dc1a6e` |
| 0009 floating workspace runtime owner | `847dc1a6e → 3d6c32c68` |
| next | `<prev-boundary> → <new-commit>` → `0010-…` |

**Rebasing the series onto a new tag:** `git branch -f backup/<old> HEAD` first, then
`git rebase --onto <newtag> <oldtag> patch/trusted-proxy-v2`, re-export every boundary, and
`rm -f config/*.tsbuildinfo` before typechecking — stale incremental build info will happily
report an error you already fixed (and hide one you just introduced).

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
   git diff <prev-boundary> HEAD > <repo>/apps/orca-coder/patches/000N-<capability>.patch
   ```

→ Hand to **orca-coder-patch-verify**.
