---
name: orca-coder-patch-ship
description: Ship a verified orca-coder patch — write the CHANGELOG entry, update CLAUDE.md if the contract changed, commit + push appimages main (CI republishes the AppImage), and refresh the workspace. Use after orca-coder-patch-verify passes.
paths: apps/orca-coder/**
---

# orca-coder — ship a patch

Only after **orca-coder-patch-verify** is green. `<repo>` = this appimages repo root.

## 1. Changelog (what shipped)

Prepend an entry to `apps/orca-coder/CHANGELOG.md` (newest first), and add the boundary row to the
table in the `orca-coder-patch-author` skill:

```
## 000N — <capability>

`patches/000N-<capability>.patch`

**Symptom:** <what the user saw>.
**Cause:** <the stub / gap>.
**Fix:** <RPC/method added, web reroute, scope decision, tests>.

Touch points: <files>.
```

## 2. Contract (only if it changed)

Update `apps/orca-coder/CLAUDE.md` ONLY when behavior or an invariant changed — durable learnings,
never a per-patch log (that is the changelog's job). Same commit as the code.

## 3. Push — CI republishes the AppImage

```bash
cd <repo>
git add apps/orca-coder/patches/000N-*.patch apps/orca-coder/CHANGELOG.md apps/orca-coder/CLAUDE.md
git commit -m "feat(orca-coder): patch 000N — <capability>"
git push origin main      # a push to apps/** on main → CI rebuilds + re-publishes orca-coder-<VERSION>
```

`[skip ci]` only for docs-only pushes. Confirm the run started: `gh run list --limit 1`.

## 4. Refresh + live verify

Restart the workspace — the install script re-extracts on a same-version rebuild via the release
asset's changed ETag, and kills the old serve so the port guard relaunches the fresh build. Then
run **orca-coder-patch-verify** step 3 (live, CT 100).
