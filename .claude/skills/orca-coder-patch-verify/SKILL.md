---
name: orca-coder-patch-verify
description: >-
  Verify an orca-coder patch before shipping — typecheck, the series' own tests plus the
  directories it touches, every patch byte-identical to its boundary diff, the whole series
  applying on pristine, and the live tile check. Run after orca-coder-patch-author and before
  orca-coder-patch-ship. Steps 1 and 2 gate the push; step 3 runs after ship's rebuild.
when_to_use: >-
  After authoring or editing any orca-coder patch, before pushing, and to check the series
  independently after a VERSION bump or a re-export.
---

# orca-coder — verify a patch

Run this block first; every command below uses these and nothing is copy-paste-broken:

```bash
cd "$(git rev-parse --show-toplevel)"
REPO=$PWD
FORK=$REPO/.upstream/orcaide-v2
BASE=$(awk '/variable "VERSION"/{f=1} f && /default/{match($0,/v[0-9]+\.[0-9]+\.[0-9]+/); print substr($0,RSTART,RLENGTH); exit}' "$REPO/apps/orca-coder/docker-bake.hcl")
echo "base=$BASE  fork=$(git -C "$FORK" describe --tags)"   # must agree
```

`$BASE` is derived, never typed: it is the single source of truth (`docker-bake.hcl`), and a
hardcoded tag silently verifies against the previous release after a bump.

**Trace Orca source only in `$FORK`.** Never `…/containers/.upstream/orca` — another repo's clone,
pinned elsewhere, silently minors behind (`apps/orca-coder/CLAUDE.md` §4).

## 1. Typecheck + tests

```bash
cd "$FORK"
mise x pnpm@10.24.0 -- pnpm install --ignore-scripts --prefer-offline   # mise has no pnpm pinned
rm -f config/*.tsbuildinfo                                             # stale info hides/invents errors
mise x pnpm@10.24.0 -- pnpm run typecheck:tsc                          # must be clean
```

**Always pass `--config config/vitest.config.ts`.** It is the only config mapping the `@/` alias;
without it every file importing `@/…` fails to load — ~380 files, a fake mass regression, not a real
one. With it, `web-preload-api.test.ts` and `agent-skill-cli-prerequisite.test.ts` still fail to load;
that is pre-existing and identical with or without your change.

### 1a. The tests the series ships — derived, never hand-listed

```bash
cd "$REPO"
grep -h '^+++ b/' apps/orca-coder/patches/*.patch | sed 's|^+++ b/||' \
  | grep -E '\.test\.(ts|tsx)$' | sort -u > /tmp/series-tests.txt
# Guard the DERIVED part specifically: appending known-good files afterwards would make a
# `[ -s ]` check pass on an empty derivation, run 5 files, and report green while the 14
# tests the series wrote were skipped. That is the rot this derivation replaced.
[ "$(wc -l < /tmp/series-tests.txt)" -ge 10 ] || { echo "derivation returned $(wc -l < /tmp/series-tests.txt) test files — wrong cwd or patches dir"; exit 1; }
# pre-existing upstream tests the series does not add but depends on
printf '%s\n' \
  src/renderer/src/web/web-runtime-client.test.ts \
  src/renderer/src/web/web-pairing.test.ts \
  src/cli/runtime/launch.test.ts \
  src/cli/args.test.ts \
  src/main/runtime/rpc/methods/pairing.test.ts >> /tmp/series-tests.txt
sort -u -o /tmp/series-tests.txt /tmp/series-tests.txt

cd "$FORK"
# xargs, not `$(…)`: zsh does not word-split an unquoted variable, so `vitest run $LIST`
# passes the whole newline-joined list as ONE argument.
xargs < /tmp/series-tests.txt \
  mise x pnpm@10.24.0 -- pnpm exec vitest run --config config/vitest.config.ts
```

### 1b. The directories it touches — the named list is not sufficient

A patch can break tests it never mentions. `0013` broke **29 test files and 411 tests** in
`src/main/runtime` while every test the series names stayed green (`CLAUDE.md` §5).

```bash
cd "$REPO"
grep -h '^+++ b/' apps/orca-coder/patches/*.patch | sed 's|^+++ b/||' \
  | grep -E '^src/.*\.(ts|tsx)$' | cut -d/ -f1-3 | sort -u > /tmp/series-dirs.txt
[ -s /tmp/series-dirs.txt ] || { echo "no directory scope derived"; exit 1; }
cd "$FORK"
xargs < /tmp/series-dirs.txt \
  mise x pnpm@10.24.0 -- pnpm exec vitest run --config config/vitest.config.ts
```

If anything fails, re-run the same scope on **pristine + patches `0001..N-1`** before blaming your
patch — upstream's own suite is not clean (`CLAUDE.md` §3).

Patches with **no** acceptance test cannot be dropped, shrunk or merged later. Recompute rather than
trusting a list: `for p in apps/orca-coder/patches/*.patch; do grep -h '^+++ b/' "$p" | grep -qE '\.test\.(ts|tsx)$' || echo "no test: $(basename "$p")"; done`

## 2. Exports ARE their boundaries, and the series applies

`git apply` re-anchors by context, so 2b alone passes on patches that are not what their boundary
produces — that is why `CLAUDE.md` §0 invariant 5 calls it insufficient. 2a is the real gate.

### 2a. Byte-identity — runs anywhere, no local index needed

```bash
cd "$REPO"
bad=0; prev=$BASE
for p in apps/orca-coder/patches/*.patch; do
  found=
  for c in $(git -C "$FORK" log --reverse --format=%H "$BASE"..HEAD); do
    if git -C "$FORK" diff "$prev" "$c" | diff -q - "$p" >/dev/null 2>&1; then found=$c; break; fi
  done
  if [ -n "$found" ]; then
    echo "OK   $(basename "$p")  ($(git -C "$FORK" rev-parse --short "$prev")..$(git -C "$FORK" rev-parse --short "$found"))"
    prev=$found
  else
    echo "STALE $(basename "$p") — not byte-identical to any boundary after $(git -C "$FORK" rev-parse --short "$prev")"; bad=1; break
  fi
done
[ "$bad" -eq 0 ] || { echo "re-export with BOTH ends explicit: git diff <prev-boundary> <this-boundary>"; exit 1; }
```

A patch that matches only after ignoring `index` lines and `@@` offsets is a **stale export**: same
change, wrong provenance. Re-export it. With the local index, `mise run patch-map --out /tmp/m.json`
reports the same thing in its `stale_exports` key — an accelerator, not a prerequisite.

### 2b. Series applies on pristine (same mechanism as the Dockerfile)

```bash
cd "$REPO"
git -C "$FORK" worktree add --detach /tmp/orca-pristine "$BASE"
ok=1
for p in apps/orca-coder/patches/*.patch; do
  echo "applying $(basename "$p")"
  # --verbose so re-anchoring shows: any "offset N lines" means 2a is failing
  git -C /tmp/orca-pristine apply --verbose "$PWD/$p" || { echo "FAILED: $p"; ok=0; break; }
done
git -C "$FORK" worktree remove --force /tmp/orca-pristine
[ "$ok" -eq 1 ] || { echo DRIFTED; exit 1; }   # MUST exit non-zero, not merely print
echo CLEAN
```

**Both `exit 1`s are load-bearing.** Three forms that look right and are not: `… || break` then
`&& echo CLEAN` (break exits the loop 0); `( set -e; … ) && echo CLEAN` (`set -e` is suspended
inside a `&&` list); `[ $ok -eq 1 ] && echo CLEAN || echo DRIFTED` (exits 0 in **both** branches, so
the gate is prose a human must read, not a status a wrapper can check).

This pristine worktree is also the only correct place to compare patched vs stock behaviour.

## 3. Live — after ship's rebuild

Steps 1 and 2 gate the push. Step 3 tests the rebuilt AppImage, which only pushing produces, so it
runs after `orca-coder-patch-ship`. A failure here starts a new author → verify → ship pass; it is
never "already shipped, therefore done".

Discover the workspace each time — a rebuild mints a new name:

```bash
WS=$(coder list -o json | jq -r '.[0].name')
coder ssh "$WS" -- 'ss -ltn; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:6799/web-index.html'
```

Pass criteria:

1. `ss -ltn` shows **`LISTEN 127.0.0.1:<PORT>`** — loopback, right port, no `0.0.0.0:6768`.
2. `GET /web-index.html` → **200**.
3. `GET /trusted-session` from loopback → **200** with the offer JSON.
4. The Coder subdomain tile loads the Orca UI with **no pairing prompt**.

The workspace is a privileged Debian/amd64 LXC on Proxmox node `coder01` (`nesting=1`, `fuse=1`,
4 cores, 24 GiB). Module dir `/home/coder/.coder-modules/astrateam/orca/` holds the extract,
`VERSION`, `ASSET_ETAG` and `logs/serve.log` — the Coder module is named `orca`; `orca-coder` names
only the release asset. Launch traps and the gotcha list are in `CLAUDE.md` §2 and §5.
