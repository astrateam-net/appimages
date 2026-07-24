---
name: astraide-patch-ship
description: Ship a verified astraide patch — write the CHANGELOG entry, update CLAUDE.md if the contract changed, commit + push appimages main (CI republishes the AppImage), and refresh the workspace. Use after astraide-patch-verify passes.
paths: apps/astraide/**
---

# astraide — ship a patch

Only after **astraide-patch-verify** is green. `<repo>` = this appimages repo root.

## 1. Changelog (what shipped)

Prepend an entry to `apps/astraide/CHANGELOG.md` (newest first), and add the boundary row to the
table in the `astraide-patch-author` skill:

```
## 000N — <capability>

`patches/000N-<capability>.patch`

**Symptom:** <what the user saw>.
**Cause:** <the stub / gap>.
**Fix:** <RPC/method added, web reroute, scope decision, tests>.

Touch points: <files>.
```

## 2. Contract (only if it changed)

Update `apps/astraide/CLAUDE.md` ONLY when behavior or an invariant changed — durable learnings,
never a per-patch log (that is the changelog's job). Same commit as the code.

## 3. Push — CI republishes the AppImage

```bash
cd <repo>
git add apps/astraide/patches/000N-*.patch apps/astraide/CHANGELOG.md apps/astraide/CLAUDE.md
git commit -m "feat(astraide): patch 000N — <capability>"
git push origin main      # a push to apps/** on main → CI rebuilds + re-publishes astraide-<VERSION>
```

`[skip ci]` only for docs-only pushes. Confirm the run started: `gh run list --limit 1`.

## 4. Refresh + live verify

Restart the workspace — the install script re-extracts on a same-version rebuild via the release
asset's changed ETag, and kills the old serve so the port guard relaunches the fresh build. Then
run **astraide-patch-verify** step 3 (live, CT 100).
