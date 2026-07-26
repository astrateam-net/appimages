---
name: orca-coder-patch-ship
description: Ship a verified orca-coder patch — write the CHANGELOG entry, update CLAUDE.md if the contract changed, commit + push appimages main (CI republishes the AppImage), and refresh the workspace. Use after orca-coder-patch-verify passes.
paths: apps/orca-coder/**
---

# orca-coder — ship a patch

`<repo>` = this appimages repo root; `<fork>` = `<repo>/.upstream/orcaide-v2` (gitignored worktree,
branch `patch/trusted-proxy-v2`, base = the VERSION in `docker-bake.hcl`) — the only tree to read
Orca source in.

## 0. Entry gate — what "verify is green" means here

Verify has three steps and **step 3 (live) cannot run before this skill**, because it tests the
rebuilt AppImage that only pushing produces. So the gate is explicit rather than "green":

| Required before pushing | |
|---|---|
| verify **step 1** | typecheck clean + the derived test list all green |
| verify **step 2a** | every patch byte-identical to its boundary diff (exit 0) |
| verify **step 2b** | whole series applies on pristine, no `offset` lines (exit 0) |
| §1 below | CHANGELOG entry exists, including its **Placement** line |

Verify **step 3 (live)** runs in §4, after the rebuild. If it fails, the fix is a new pass through
author → verify → ship; nothing here is "already shipped, therefore done".

## 1. Changelog (what shipped, and why it is its own patch)

Prepend an entry to `apps/orca-coder/CHANGELOG.md` (newest first). The **Placement** line is
mandatory and is the whole point: `CLAUDE.md` §0 invariant 3 makes the CHANGELOG the only
committed, reviewable record of the placement decision. Without it the audit's verdict dies in
`/tmp` and the next agent repeats the mistake.

```
## 000N — <capability>

`patches/000N-<capability>.patch`

**Symptom:** <what the user saw>.
**Cause:** <the stub / gap>.
**Fix:** <RPC/method added, web reroute, scope decision, tests>.
**Placement:** new number — considered 000X, 000Y (share <file/area>); not an extension because
<why this is a distinct capability>.   ← or: extends 000X, restacked and series re-exported.
**Acceptance:** <test file(s) that fail without this patch and pass with it>.

Touch points: <files>.
```

`Acceptance` closes the other half: a patch with no test cannot later be shrunk, merged, or dropped
with any confidence, because nothing can prove the capability still works. If you genuinely cannot
test it, say so on that line and why — an explicit gap is reviewable, a silent one is not.

Do **not** hand-maintain a patch↔boundary table anywhere. It is derived data
(`orca-coder-patch-audit`'s `patch-map` resolves boundaries from diff content), and the copy that
used to live in the author skill was both mandated here and declared untrustworthy there.

## 2. Contract (only if it changed)

Update `apps/orca-coder/CLAUDE.md` ONLY when behavior or an invariant changed — durable learnings,
never a per-patch log (that is the changelog's job). Same commit as the code.

## 3. Push — CI republishes the AppImage

```bash
cd <repo>
git add apps/orca-coder/patches/ apps/orca-coder/CHANGELOG.md apps/orca-coder/CLAUDE.md
# and, whenever they changed, the tooling the contract depends on:
git add .claude/skills/ .mise/ ruff.toml mise.toml 2>/dev/null || true
git status --short   # nothing untracked that the chain references
git commit -m "feat(orca-coder): patch 000N — <capability>"
git push origin main      # a push to apps/** on main → CI rebuilds + re-publishes orca-coder-<VERSION>
```

`[skip ci]` only for docs-only pushes. Confirm the run started: `gh run list --limit 1`.

## 4. Refresh + live verify

Restart the workspace — the install script re-extracts on a same-version rebuild via the release
asset's changed ETag, and kills the old serve so the port guard relaunches the fresh build. Then
run **orca-coder-patch-verify** step 3 (live). Discover the workspace name each time
(`coder list -o json | jq -r '.[0].name'`) — a rebuild mints a new one.
