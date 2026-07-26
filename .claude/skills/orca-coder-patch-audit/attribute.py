#!/usr/bin/env python3
"""Attribute graph symbols to the patch that introduced or touched them.

The linchpin of the audit: diffs alone cannot say "this symbol came from patch N",
because later commits shift line numbers. `git blame` gives line -> commit robustly;
the code graph gives symbol -> line range. Intersecting them gives symbol -> patch.

Nothing here is specific to the current series: the patch count comes from
`git log <base>..HEAD`, the file set from `git diff --name-only`, and the base tag
and project are arguments. It scales with the series without edits.

FAIL LOUD, NEVER UNDER-REPORT. A truncated query would make the audit say "clean"
where it is not, so every query is chunked and its row count checked against the
limit; hitting the limit is a hard error, not a silent short read.

Output (JSON):
  {"base","project","patches":[{seq,sha,subject,symbols:[{name,file,label}]}],
   "shared":[{name,file,patches:[seq,...]}], "stats":{...}}

Usage:
  attribute.py --fork <path> --base <tag> [--project orca-fork] [--out map.json]
  attribute.py ... --self-check      # validate attribution against git ground truth
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

SHA_RE = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")
ROW_LIMIT = 5000  # per chunk; chunks are sized so this is never the binding constraint
FILES_PER_CHUNK = 40  # keeps the generated Cypher well under any statement-length limit


def git(fork, *args, check=True):
    r = subprocess.run(["git", "-C", fork, *args], capture_output=True, text=True)
    if r.returncode != 0:
        if not check:
            return None
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def git_paths(fork, *args):
    """Path list from git, NUL-separated.

    Never parse newline-separated path output: git C-quotes any path with non-ASCII
    bytes (`"src/\\303\\274n.ts"`), which then matches no graph file_path, and a
    whitespace `.split()` shreds any path containing a space. Both failures are
    silent — the file simply vanishes from the map. `-z` avoids both.
    """
    out = git(fork, *args, "-z")
    return [p for p in out.split("\0") if p]


def cbm_query(project, query, limit):
    r = subprocess.run(
        [
            "mise",
            "exec",
            "--",
            "codebase-memory-mcp",
            "cli",
            "query_graph",
            "--project",
            project,
            "--query",
            query,
        ],
        capture_output=True,
        text=True,
    )
    line = next((s for s in reversed(r.stdout.splitlines()) if s.startswith("{")), None)
    if not line:
        sys.exit(f"query_graph returned no JSON.\nstderr: {r.stderr.strip()[:500]}")
    d = json.loads(line)
    if "rows" not in d:
        sys.exit(f"query_graph error: {json.dumps(d)[:500]}")
    rows = d["rows"]
    if len(rows) >= limit:
        sys.exit(
            f"REFUSING TO CONTINUE: query hit LIMIT {limit} ({len(rows)} rows) and would "
            f"silently under-report. Lower FILES_PER_CHUNK or raise ROW_LIMIT."
        )
    return rows


def cypher_str(s):
    """Quote a string literal for the openCypher subset (single-quoted, backslash-escaped)."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def norm_label(lab):
    """labels(n) shape is not contractual — accept list, str, or JSON-ish string."""
    if isinstance(lab, list):
        return lab[0] if lab else "?"
    if isinstance(lab, str):
        return lab.strip("[]\"' ").split(",")[0].strip("\"' ") or "?"
    return str(lab)


def load_symbols(project, files):
    """Symbol table for `files`, chunked so no single query can be truncated."""
    by_file, total = {}, 0
    for i in range(0, len(files), FILES_PER_CHUNK):
        chunk = files[i : i + FILES_PER_CHUNK]
        q = (
            "MATCH (n) WHERE n.file_path IN ["
            + ", ".join(cypher_str(f) for f in chunk)
            + "] AND (n:Function OR n:Method OR n:Class OR n:Type) "
            "RETURN n.file_path, n.name, n.start_line, n.end_line, labels(n) "
            f"LIMIT {ROW_LIMIT}"
        )
        for fp, name, s, e, lab in cbm_query(project, q, ROW_LIMIT):
            total += 1
            if s is None or e is None:
                continue
            by_file.setdefault(fp, []).append((name, int(s), int(e), norm_label(lab)))
    return by_file, total


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def norm_diff(text, *, hunk_offsets=False):
    """Normalise a diff so two spellings of the same change compare equal.

    Dropped: blob hashes (`index abc..def`) and trailing whitespace.

    Hunk headers are reduced to `@@ @@` unless `hunk_offsets=True`. Their line
    numbers are derived metadata that `git apply` ignores — it re-anchors by
    context — so an exported patch can carry a stale offset and still apply
    cleanly. Boundary identity is about CONTENT, so offsets must not decide it.
    Comparing with and without them tells the two cases apart.
    """
    out = []
    for line in text.splitlines():
        if line.startswith("index "):
            continue
        if not hunk_offsets:
            line = HUNK_RE.sub("@@ @@", line)
        out.append(line.rstrip())
    return "\n".join(out)


def file_owners_from_git(fork, base, boundaries):
    """file -> [patch, ...] asked of git, per boundary pair.

    Do NOT parse `+++ b/…` out of the patch text. Measured failures of that approach:
    git appends a TAB after a path containing a space; it C-quotes non-ASCII paths as
    `+++ "b/src/\\303\\274n.ts"` which the pattern misses entirely; pure renames emit
    only `rename from/to` and no `+++` line at all; and an ADDED content line that
    happens to read `++ b/evil.ts` is indistinguishable from a header, inventing files
    that do not exist. `git diff --name-only -z` has none of those problems.

    The symbol tier cannot cover everything: ownership there comes from
    Function/Method/Class/Type line ranges, so a patch that only edits imports, a
    module-level constant, a registry array, an allowlist, or a `describe` body owns no
    symbol. This tier informs; it never decides — see locate.py.
    """
    owners = {}
    prev = base
    for name, boundary in boundaries:
        for f in git_paths(fork, "diff", "--name-only", f"{prev}..{boundary}"):
            owners.setdefault(f, [])
            if name not in owners[f]:
                owners[f].append(name)
        prev = boundary
    return owners


def map_commits_to_patches(fork, base, patches_dir, commits):
    """Map each commit to the exported patch file that ships it.

    Patch files are INCREMENTAL boundary diffs, because the build applies them in
    filename order, each on top of the last: patch k == `git diff <boundary k-1>..<boundary k>`.
    (Only patch 1 also equals a diff from the base, since its left boundary IS the base —
    do not generalise from it.) Several commits can land in one patch, a feature plus its
    follow-up fixes, which is why the commit index is not the patch number.

    Boundaries are derived exactly, by comparing normalised diff content — no heuristics.
    A patch matching no boundary means the exported series has drifted from the fork's
    history, which is itself an audit finding, so it is a hard error.
    """
    patch_files = sorted(p for p in patches_dir.glob("*.patch"))
    if not patch_files:
        sys.exit(f"no *.patch files in {patches_dir}")

    patch_of, start, left, stale, boundaries = {}, 0, base, [], []
    for pf in patch_files:
        raw = pf.read_text()
        want = norm_diff(raw)
        end, exact = None, False
        for i in range(start, len(commits)):
            gen = git(fork, "diff", f"{left}..{commits[i][0]}")
            if norm_diff(gen) == want:
                end = i
                exact = norm_diff(gen, hunk_offsets=True) == norm_diff(raw, hunk_offsets=True)
                break
        if end is None:
            sys.exit(
                f"DRIFT: {pf.name} matches no commit boundary after {left[:9]}. The exported "
                f"patches and the fork's history disagree — re-export before auditing."
            )
        if not exact:
            # Same change, different hunk offsets: the patch was exported from a
            # different tree state. It still applies (git apply re-anchors by
            # context), so CI never notices — but the file is not what this
            # boundary produces today. Re-export to keep them honest.
            stale.append(pf.name)
        for i in range(start, end + 1):
            patch_of[commits[i][0]] = pf.name
        boundaries.append((pf.name, commits[end][0]))
        left = commits[end][0]
        start = end + 1

    if start != len(commits):
        trailing = [s[:9] for s, _ in commits[start:]]
        sys.exit(
            f"DRIFT: {len(commits) - start} commit(s) after the last patch boundary "
            f"({', '.join(trailing)}) are not exported to any patch file."
        )
    return patch_files, patch_of, stale, boundaries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fork", required=True)
    ap.add_argument("--base", required=True, help="upstream tag the series sits on")
    ap.add_argument("--project", default="orca-fork")
    ap.add_argument(
        "--patches",
        default="apps/orca-coder/patches",
        help="directory of exported *.patch files (the shipping unit)",
    )
    ap.add_argument("--out")
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="validate every attribution against git as ground truth",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="proceed even though the fork worktree has uncommitted or untracked changes",
    )
    a = ap.parse_args()

    if git(a.fork, "rev-parse", "--verify", f"{a.base}^{{commit}}", check=False) is None:
        sys.exit(f"base tag {a.base} does not exist in {a.fork}")

    # A dirty fork poisons the map in two ways at once: the graph indexes the WORKING
    # TREE (untracked files included), and blame reports uncommitted lines as the null
    # sha, which belongs to no patch and shifts every symbol below it. Neither shows up
    # in the output, so the map silently describes a tree nobody shipped.
    # `-c status.showUntrackedFiles=all` is load-bearing: a repo configured with
    # showUntrackedFiles=no hides untracked files from --porcelain, and the graph
    # indexes them anyway — the guard would pass while the map was already poisoned.
    dirty = [
        ln
        for ln in git(
            a.fork, "-c", "status.showUntrackedFiles=all", "status", "--porcelain"
        ).splitlines()
        if ln.strip()
    ]
    if dirty and not a.allow_dirty:
        sys.exit(
            f"REFUSING: the fork worktree has {len(dirty)} uncommitted/untracked path(s), which "
            f"the graph indexes and blame cannot attribute:\n  "
            + "\n  ".join(dirty[:10])
            + "\ncommit or stash them, or pass --allow-dirty and distrust the result."
        )
    if dirty:
        print(
            f"WARNING: building the map over a DIRTY worktree ({len(dirty)} path(s)). "
            f"Symbol attribution is unreliable: uncommitted lines belong to no patch and "
            f"shift every symbol below them. worktree_dirty=true is recorded in the map.",
            file=sys.stderr,
        )

    # Our commits, oldest first.
    log = git(a.fork, "log", "--reverse", "--format=%H\t%s", f"{a.base}..HEAD").strip()
    commits = [c.split("\t", 1) for c in log.splitlines() if c.strip()]
    if not commits:
        sys.exit(f"no commits in {a.base}..HEAD — wrong base tag?")

    # The audit unit is the PATCH FILE, not the commit — that is what ships and
    # what a bump has to re-justify.
    patch_files, patch_of, stale, boundaries = map_commits_to_patches(
        a.fork, a.base, pathlib.Path(a.patches), commits
    )
    order = {pf.name: i + 1 for i, pf in enumerate(patch_files)}
    seq_of = {sha: order[patch_of[sha]] for sha, _ in commits}

    files = git_paths(a.fork, "diff", "--name-only", f"{a.base}..HEAD")
    by_file, rows_seen = load_symbols(a.project, files)

    # Ground truth for --self-check: the files each PATCH actually touched, i.e. the
    # union over the commits that patch ships.
    patch_touched = {}
    if a.self_check:
        for sha, _ in commits:
            touched = set(git_paths(a.fork, "show", "--pretty=", "--name-only", sha))
            patch_touched.setdefault(seq_of[sha], set()).update(touched)

    per_patch, shared, unindexed, violations = {}, {}, [], []
    for fp in files:
        syms = by_file.get(fp)
        if not syms:
            # deleted, binary, or structurally unindexable (e.g. the extensionless shims)
            unindexed.append(fp)
            continue
        # -M/-C help blame survive reformatting and in-file moves. NOTE: they do NOT
        # credit the original author across a cross-file move — measured, blame names
        # the MOVER. So a patch that relocates upstream code is recorded as owning it.
        # That matches "touched", which is what ownership means here, but do not read
        # it as "wrote".
        blame = git(a.fork, "blame", "-M", "-C", "--line-porcelain", "--", fp, check=False)
        if blame is None:
            unindexed.append(fp)
            continue
        line2sha = {}
        for ln in blame.splitlines():
            m = SHA_RE.match(ln)
            if m:
                line2sha[int(m.group(2))] = m.group(1)
        for name, s, e, label in syms:
            owners = {line2sha.get(i) for i in range(s, e + 1)}
            mine = sorted({seq_of[o] for o in owners if o in seq_of})
            if not mine:
                continue
            for q in mine:
                per_patch.setdefault(q, []).append({"name": name, "file": fp, "label": label})
                if a.self_check and fp not in patch_touched.get(q, ()):
                    violations.append(
                        f"{patch_files[q - 1].name} attributed {name} in {fp}, "
                        f"but none of its commits touched that file"
                    )
            if len(mine) > 1:
                shared[(fp, name)] = mine

    out = {
        "base": a.base,
        "project": a.project,
        # Provenance: a map is only meaningful for the tree it was built from.
        "fork_head": git(a.fork, "rev-parse", "HEAD").strip(),
        "worktree_dirty": bool(dirty),
        "file_owners": file_owners_from_git(a.fork, a.base, boundaries),
        "patches": [
            {
                "seq": i + 1,
                "patch": pf.name,
                "commits": [
                    {"sha": sha, "subject": subj}
                    for sha, subj in commits
                    if patch_of[sha] == pf.name
                ],
                "symbols": sorted(per_patch.get(i + 1, []), key=lambda d: (d["file"], d["name"])),
            }
            for i, pf in enumerate(patch_files)
        ],
        "shared": [{"name": n, "file": f, "patches": p} for (f, n), p in sorted(shared.items())],
        "stale_exports": stale,
        "stats": {
            "patches": len(patch_files),
            "commits": len(commits),
            "files_touched": len(files),
            "symbol_rows": rows_seen,
            # Files the symbol tier cannot speak for — no symbol of theirs is OWNED by
            # any patch — so only file_owners can answer for them. Counting "files with
            # no graph symbols at all" instead under-reported this by half.
            "files_file_tier_only": len(
                [f for f in files if not any(s["file"] == f for v in per_patch.values() for s in v)]
            ),
            # `attributions` counts (patch, file, symbol) rows, so a symbol owned by
            # two patches is counted twice; `distinct_owned_symbols` counts (file,
            # symbol) pairs. Both are reported because they answer different questions
            # and mixing them up produced three irreconcilable denominators.
            "attributions": sum(len(v) for v in per_patch.values()),
            "distinct_owned_symbols": len(
                {(s["file"], s["name"]) for v in per_patch.values() for s in v}
            ),
        },
    }

    if a.self_check:
        if violations:
            print(
                f"SELF-CHECK FAILED — {len(violations)} attribution(s) contradict git:",
                file=sys.stderr,
            )
            for v in violations[:20]:
                print("  " + v, file=sys.stderr)
            sys.exit(1)
        print(
            f"self-check OK: {out['stats']['attributions']} attributions, "
            f"every one lands in a file its commit actually touched",
            file=sys.stderr,
        )

    text = json.dumps(out, indent=1)
    if a.out:
        open(a.out, "w").write(text)
        print(f"wrote {a.out}: {out['stats']}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
