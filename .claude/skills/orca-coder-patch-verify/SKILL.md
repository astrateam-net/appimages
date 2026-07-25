---
name: orca-coder-patch-verify
description: Verify an orca-coder patch — typecheck, focused tests, whole-series-applies-on-pristine, and live checks in the workspace. Use after orca-coder-patch-author, before orca-coder-patch-ship, or to verify an orca-coder change independently.
paths: apps/orca-coder/**
---

# orca-coder — verify a patch

Operator-relative paths: `<fork>` = your `mrkhachaturov/orcaide` clone (branch
`patch/trusted-proxy-v2`, base `v1.4.153`); `<repo>` = this appimages repo root.

## 1. Typecheck + focused tests (run in `<fork>`)

```bash
cd <fork>
mise x pnpm@10.24.0 -- pnpm install --ignore-scripts --prefer-offline   # mise has no pnpm pinned
mise x pnpm@10.24.0 -- pnpm run typecheck:tsc                           # must be clean
mise x pnpm@10.24.0 -- pnpm exec vitest run --config config/vitest.config.ts \
  src/renderer/src/web/web-runtime-client.test.ts \
  src/renderer/src/web/web-pairing.test.ts \
  src/cli/runtime/launch.test.ts src/cli/args.test.ts \
  src/main/runtime/rpc/methods/mobile-pairing.test.ts \
  src/main/runtime/rpc/methods/pairing.test.ts \
  src/main/runtime/rpc/methods/cli.test.ts \
  src/main/runtime/mobile-rpc-allowlist.test.ts \
  <any test files your patch touched>                                   # all green
```

**Always pass `--config config/vitest.config.ts`.** It's the only config that maps the `@/`
alias; there is no root config, so a bare `vitest run` (or one you forgot the flag on) fails to
load every file that imports `@/…` — renderer-component tests especially (`../ui/button` →
`@/lib/utils`). Widen the run without the flag and you get a fake mass regression (~380 files,
`Cannot find package '@/...'`), NOT a real failure. With the flag, only these two still fail to
load and are safe to IGNORE (pre-existing, identical with/without your change):
`web-preload-api.test.ts`, `agent-skill-cli-prerequisite.test.ts`.

## 2. Whole series applies on pristine (same mechanism as the Dockerfile)

```bash
cd <fork>
git worktree add --detach /tmp/orca-pristine v1.4.153
for p in <repo>/apps/orca-coder/patches/*.patch; do
  git -C /tmp/orca-pristine apply "$p" || break
done && echo CLEAN
git worktree remove --force /tmp/orca-pristine
```

Any FAIL = the series drifted from `v1.4.153`; the Dockerfile build will fail the same way.

## 3. Live (after the ship rebuild) — workspace LXC **CT 100** (`astradev`) on host `coder01`

```bash
ssh coder01 'sudo pct exec 100 -- runuser -l coder -c "<cmd>"'
# workspace module dir: /home/coder/.coder-modules/astrateam/orca-coder/  (extract, VERSION, logs/serve.log)
```

Pass criteria: `ss -ltn` shows `LISTEN 127.0.0.1:<PORT>` (never `0.0.0.0:6768`);
`curl …/web-index.html` → 200; `curl …/trusted-session` (loopback) → 200; the tile loads with
**no pairing prompt**. Bind truth is `ss` only — ready-JSON strings are derived.
