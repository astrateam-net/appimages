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

| Patch | Boundary |
|---|---|
| 0000 upstream tabIndex fix ⚠️ | `v1.4.155 → 0aa5de8de` |
| 0001 trusted-proxy session | `0aa5de8de → 5a7d91cdf` |
| 0002 web mobile pairing | `5a7d91cdf → b20a3c698` |
| 0003 web runtime share links | `b20a3c698 → 2dcb65770` |
| 0004 web resource manager | `2dcb65770 → 4cb98816b` |
| 0005 web CLI registration | `4cb98816b → 1c7f9328a` |
| 0006 web floating-workspace dir picker | `1c7f9328a → 704608cf1` |
| 0007 runtime-seeded settings | `704608cf1 → f8c81885b` |
| 0008 open-in browser editor URLs | `f8c81885b → a3f814cb5` |
| next | `<prev-boundary> → <new-commit>` → `0009-…` |

⚠️ **0000 is an upstream bugfix, not an orca-coder capability** — see `apps/orca-coder/CLAUDE.md` §3.
Drop it the moment a tag declares `tabIndex` on `DetachedHeadBadgeProps`.

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
