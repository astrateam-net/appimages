#!/usr/bin/env python3
"""Audit the patch series against upstream and against itself.

Consumes the symbol -> patch map from attribute.py and applies three lenses:

  A. patch <-> upstream   Which symbols are ours (absent from pristine) versus
                          upstream's that we merely extend? For each of ours, does
                          upstream already ship something equivalent under another
                          name? Reinvention is the expensive mistake.
  B. patch <-> patch      SIMILAR_TO (MinHash near-clone) edges whose two ends were
                          written by DIFFERENT patches: the same logic implemented
                          twice in one series.
  C. shape                Patches coupled through shared symbols, and patches so
                          small they are probably an edit to a neighbour.

Every row is a CANDIDATE for a human or a verify pass, never a verdict. Static
similarity and lexical search narrow where to look; they do not settle anything.

BM25 (`search_graph --query`), not `--semantic-query`: for a symbol you can spell, BM25
ranks the right one first, while per-keyword min-cosine returns confident wrong hits.

Usage:
  audit.py --map map.json [--fork-project orca-fork] [--pristine-project orca-pristine]
           [--out findings.json] [--max-lookups N]
"""

import argparse
import json
import re
import subprocess
import sys

ROW_LIMIT = 20000
STOP = {
    "get",
    "set",
    "is",
    "has",
    "to",
    "from",
    "on",
    "handle",
    "build",
    "create",
    "make",
    "new",
    "the",
    "for",
    "with",
    "of",
    "and",
    "a",
    "an",
    "web",
    "orca",
}


def cbm(project, tool, *flags):
    r = subprocess.run(
        ["mise", "exec", "--", "codebase-memory-mcp", "cli", tool, "--project", project, *flags],
        capture_output=True,
        text=True,
    )
    line = next((s for s in reversed(r.stdout.splitlines()) if s.startswith("{")), None)
    if not line:
        sys.exit(f"{tool} returned no JSON.\nstderr: {r.stderr.strip()[:400]}")
    return json.loads(line)


def query(project, cypher, limit=ROW_LIMIT):
    d = cbm(project, "query_graph", "--query", f"{cypher} LIMIT {limit}")
    if "rows" not in d:
        sys.exit(f"query_graph error: {json.dumps(d)[:400]}")
    if len(d["rows"]) >= limit:
        sys.exit(f"REFUSING TO CONTINUE: query hit LIMIT {limit} and would under-report.\n{cypher}")
    return d["rows"]


def tokens(name):
    """Split camelCase / snake_case into meaningful lowercase tokens."""
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", name)
    return [p.lower() for p in parts if len(p) > 2 and p.lower() not in STOP]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="attribute.py output")
    ap.add_argument("--fork-project", default="orca-fork")
    ap.add_argument("--pristine-project", default="orca-pristine")
    ap.add_argument("--out")
    ap.add_argument(
        "--max-lookups",
        type=int,
        default=0,
        help="cap BM25 probes into pristine (0 = no cap, probe every new symbol)",
    )
    a = ap.parse_args()

    m = json.load(open(a.map))
    patch_of = {}  # (file, name) -> patch file name
    for p in m["patches"]:
        for s in p["symbols"]:
            patch_of.setdefault((s["file"], s["name"]), p["patch"])
    ours = {n for _, n in patch_of}

    findings = {
        "base": m["base"],
        "stale_exports": [
            {
                "patch": p,
                "why": "applies (git apply re-anchors by context) but is not byte-identical "
                "to what this boundary produces — re-export",
            }
            for p in m.get("stale_exports", [])
        ],
        "coupled_patches": [],
        "thin_patches": [],
        "ours_vs_upstream": {"extends_upstream": 0, "genuinely_new": 0, "new_symbols": []},
        "upstream_candidates": [],
        "cross_patch_clones": [],
        "patch_overlap": [],
    }

    # ---- C. shape ---------------------------------------------------------
    for s in m["shared"]:
        names = sorted({m["patches"][i - 1]["patch"] for i in s["patches"]})
        if len(names) > 1:
            findings["coupled_patches"].append(
                {"symbol": s["name"], "file": s["file"], "patches": names}
            )
    fo_pre = m.get("file_owners", {})
    for p in m["patches"]:
        owned_files = [f for f, qs in fo_pre.items() if p["patch"] in qs]
        if len(p["symbols"]) <= 2 and len(owned_files) <= 2:
            findings["thin_patches"].append(
                {
                    "patch": p["patch"],
                    "symbols": [f"{s['file']}:{s['name']}" for s in p["symbols"]],
                    "files": owned_files,
                    "why": "owns very little by either tier — NOT a verdict; look it up in "
                    "patch_overlap and fold it in only if it shares SYMBOLS with a neighbour",
                }
            )

    # ---- A. ours vs upstream ---------------------------------------------
    # A symbol whose name exists in pristine is an upstream symbol we extend.
    # One absent from pristine is ours outright — the reinvention risk lives there.
    #
    # MUST be per-label. A bare `MATCH (n) RETURN DISTINCT n.name` silently returns a
    # PARTIAL set: measured 49 680 of 90 246 distinct names — 45% dropped — with no
    # has_more and `total` equal to the truncated count, so the response advertises
    # itself as complete. The cut is alphabetical (it stops around `git-b`), so e.g.
    # `gitExecFileAsync` vanishes while anything earlier survives by luck. Labelled
    # queries are complete (Variable returns all 75 461 rows, so this is not a global
    # row cap). Built on the bare form, this lens would call 45% of the graph "new".
    pristine_names = set()
    for label in ("Function", "Method", "Class", "Type", "Interface", "Enum"):
        pristine_names |= {
            r[0]
            for r in query(a.pristine_project, f"MATCH (n:{label}) RETURN DISTINCT n.name", 60000)
        }
    new_syms = sorted({n for n in ours if n not in pristine_names})

    # Independent check of the lens: probe a sample of the "new" symbols through
    # search_graph, which resolves names by a different path than query_graph.
    # Any hit means the name set is incomplete and the lens is lying.
    for name in new_syms[:15]:
        d = cbm(
            a.pristine_project,
            "search_graph",
            "--name-pattern",
            f"^{re.escape(name)}$",
            "--limit",
            "1",
        )
        if d.get("total"):
            sys.exit(
                f"LENS A SELF-CHECK FAILED: '{name}' was classified as ours, but search_graph "
                f"finds it in {a.pristine_project}. The pristine name set is incomplete — "
                f"do not trust these findings."
            )
    findings["ours_vs_upstream"]["extends_upstream"] = len(ours) - len(new_syms)
    findings["ours_vs_upstream"]["genuinely_new"] = len(new_syms)
    findings["ours_vs_upstream"]["new_symbols"] = new_syms

    if a.max_lookups is not None:
        probed = 0
        for name in new_syms:
            if a.max_lookups and probed >= a.max_lookups:
                findings["upstream_candidates_truncated"] = (
                    f"stopped after {a.max_lookups} probes of {len(new_syms)} new symbols — "
                    f"raise --max-lookups for full coverage"
                )
                break
            tk = tokens(name)
            if len(tk) < 2:
                continue
            probed += 1
            d = cbm(
                a.pristine_project,
                "search_graph",
                "--query",
                " ".join(tk),
                "--label",
                "Function",
                "--limit",
                "5",
            )
            hits = []
            for r in (d.get("results") or [])[:5]:
                hn = r.get("name") or ""
                overlap = len(set(tokens(hn)) & set(tk))
                if overlap >= 2 and hn != name:
                    hits.append({"upstream": hn, "file": r.get("file_path"), "shared": overlap})
            if hits:
                where = next((f for (f, n) in patch_of if n == name), None)
                findings["upstream_candidates"].append(
                    {
                        "ours": name,
                        "patch": patch_of.get((where, name)),
                        "upstream_may_already_do_this": hits,
                    }
                )

    # ---- B. duplicated logic across patches -------------------------------
    # Labelled on both ends for the same reason as lens A: an unlabelled MATCH
    # under-returns without saying so.
    clone_rows = []
    for la in ("Function", "Method"):
        for lb in ("Function", "Method"):
            clone_rows += query(
                a.fork_project,
                f"MATCH (x:{la})-[:SIMILAR_TO]->(y:{lb}) "
                "RETURN x.file_path, x.name, y.file_path, y.name",
            )
    findings["similar_to_coverage"] = {
        "edges_in_graph": len(clone_rows),
        "our_symbols_touched_by_any_edge": len(
            ({(r[0], r[1]) for r in clone_rows} | {(r[2], r[3]) for r in clone_rows})
            & set(patch_of)
        ),
        "note": "if coverage is ~0, cross_patch_clones being empty says nothing about "
        "duplication — MinHash near-clone detection simply does not reach these "
        "symbols. Use name_twins instead.",
    }
    for af, an, bf, bn in clone_rows:
        pa, pb = patch_of.get((af, an)), patch_of.get((bf, bn))
        if pa and pb and pa != pb:
            findings["cross_patch_clones"].append(
                {"a": f"{an} [{af}]", "b": f"{bn} [{bf}]", "patches": sorted([pa, pb])}
            )

    # ---- B2. name twins across patches ------------------------------------
    # The working substitute for SIMILAR_TO on this series: two symbols WE wrote,
    # in different patches, whose names share most of their meaningful tokens.
    # Lexical and cheap, but it actually fires where near-clone detection does not.
    # NO similarity cutoff. An earlier version filtered pairs by a tuned ratio;
    # picking the constant that yields a small, tidy result is fitting the audit to
    # pass rather than measuring. Every pair of patches with ANY overlap is
    # reported, ranked by weight, and the reader decides. Deliberately over-reports.
    patches = [p["patch"] for p in m["patches"]]
    # Union the symbol tier with file_owners, or files with no symbol ownership —
    # registries, allowlists, import-only edits — are invisible to the overlap lens.
    fo = m.get("file_owners", {})
    files_of = {p["patch"]: {s["file"] for s in p["symbols"]} for p in m["patches"]}
    for f, owners_ in fo.items():
        for q in owners_:
            files_of.setdefault(q, set()).add(f)
    # (file, name), never the bare name. Keyed by name alone, `handler` — five distinct
    # functions in five files, 65 of them in pristine — made 10 of 29 overlap rows carry
    # phantom "shared symbols" and 5 rows entirely phantom, while `weight` let those
    # phantoms dominate the ranking and the skill said "shared symbols → merge".
    syms_of = {p["patch"]: {(s["file"], s["name"]) for s in p["symbols"]} for p in m["patches"]}
    toks_of = {
        p["patch"]: {t for s in p["symbols"] for t in tokens(s["name"])} for p in m["patches"]
    }
    for i, x in enumerate(patches):
        for y in patches[i + 1 :]:
            sf, ss = files_of[x] & files_of[y], syms_of[x] & syms_of[y]
            st = toks_of[x] & toks_of[y]
            if not (sf or ss):
                continue
            findings["patch_overlap"].append(
                {
                    "patches": [x, y],
                    "shared_symbols": sorted(f"{f}:{n}" for f, n in ss),
                    "shared_files": sorted(sf),
                    "shared_name_tokens": sorted(st),
                    "weight": len(ss) * 3 + len(sf),
                    "ask": "same subject area? then this is one capability split across two "
                    "patches — merge, or make the later one extend the earlier",
                }
            )
    findings["patch_overlap"].sort(key=lambda r: -r["weight"])

    text = json.dumps(findings, indent=1)
    if a.out:
        open(a.out, "w").write(text)
    else:
        print(text)

    f = findings
    print(
        f"stale exports: {len(f['stale_exports'])} | coupled: {len(f['coupled_patches'])} | "
        f"thin: {len(f['thin_patches'])} | ours-new: {f['ours_vs_upstream']['genuinely_new']} "
        f"(extends upstream: {f['ours_vs_upstream']['extends_upstream']}) | "
        f"upstream candidates: {len(f['upstream_candidates'])} | "
        f"cross-patch clones: {len(f['cross_patch_clones'])} "
        f"(SIMILAR_TO covers {f['similar_to_coverage']['our_symbols_touched_by_any_edge']} "
        f"of our symbols) | patch overlaps: {len(f['patch_overlap'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
