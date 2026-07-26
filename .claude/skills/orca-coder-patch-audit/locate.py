#!/usr/bin/env python3
"""Before writing a patch: find out whether an existing one already owns this area.

The failure this prevents: a capability is fixed, later a second problem shows up in
the SAME area, and it becomes a new patch number because nobody remembered the first.
Two patches then edit the same symbols — which is exactly the coupling audit.py
reports as a defect. Creating it deliberately is worse than finding it afterwards.

THE RULE (no tunable constant):

    SYMBOLS decide. If a symbol you are about to change is already owned by an
    existing patch, your change belongs in THAT patch — restack its boundary and
    re-export. FILES only inform: they produce a reading list, never a verdict.

Why files cannot decide, measured on this series: `web-preload-api.ts` is touched by
11 of 13 patches, `orca-runtime.ts` by 5, `mobile-rpc-allowlist.test.ts` by 6. The web
client is one god-file behind one god-factory, so "shared file" is true of nearly every
change. An earlier version counted files as ownership; every web-tile fix then came
back EXTEND_EXISTING -> 0001 (the trusted-proxy security patch), picked out of an
11-way tie by filename order. That would have folded the series into its most
review-sensitive patch.

Patch size does not enter into it either. Size affects how much work restacking is; it
never makes it correct to split one capability across two patches.

Usage:
  locate.py --map map.json --symbols createWebPreloadApi,pickDirectory   # decides
  locate.py --map map.json --files src/a.ts,src/b.ts                     # informs
  locate.py --map map.json --area "floating workspace"                   # informs
"""

import argparse
import json
import re
import sys


def tokens(name):
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", name)
    return {p.lower() for p in parts if len(p) > 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="attribute.py output")
    ap.add_argument("--files", default="", help="comma-separated paths you intend to edit")
    ap.add_argument("--symbols", default="", help="comma-separated symbols you intend to touch")
    ap.add_argument("--area", default="", help="free words describing the capability")
    a = ap.parse_args()

    want_files = {s.strip() for s in a.files.split(",") if s.strip()}
    want_syms = {s.strip() for s in a.symbols.split(",") if s.strip()}
    want_toks = {w.lower() for w in a.area.split() if len(w) > 2}
    if not (want_files or want_syms or want_toks):
        sys.exit("give at least one of --files / --symbols / --area")

    try:
        m = json.load(open(a.map))
    except OSError as e:
        sys.exit(f"cannot read --map {a.map}: {e}. Run `mise run patch-map --out <path>` first.")
    except json.JSONDecodeError as e:
        sys.exit(f"--map {a.map} is not valid JSON ({e}). Regenerate it with `mise run patch-map`.")
    if m.get("worktree_dirty"):
        print(
            "WARNING: this map was built over a dirty fork worktree — symbol ownership in it is "
            "unreliable. Commit/stash the fork and re-run `mise run patch-map`.",
            file=sys.stderr,
        )

    # Unrecognised input must never fall through to "new patch" — that is the exact
    # mistake this tool exists to prevent, and a mistyped or absolute path would
    # otherwise produce a confident NEW_PATCH with an empty candidate list.
    known_files = {s["file"] for p in m["patches"] for s in p["symbols"]}
    known_syms = {s["name"] for p in m["patches"] for s in p["symbols"]}
    # File tier straight from the patches: covers files with no symbol ownership
    # (registries, allowlists, import-only edits) that the graph tier cannot see.
    fo = m.get("file_owners", {})
    unknown_files = sorted(want_files - known_files - set(fo))
    # a `file:symbol` form is resolved in the hit loop, so do not call it unknown
    # A `file:symbol` whose SYMBOL is known but whose FILE is wrong must still be
    # reported: otherwise the verdict is a bare CANNOT_DECIDE blaming repo-relative
    # paths, when the path was the typo and the symbol was fine.
    pairs = {w for w in want_syms if ":" in w}
    known_pairs = {f"{s['file']}:{s['name']}" for p in m["patches"] for s in p["symbols"]}
    unknown_syms = sorted(
        [w for w in want_syms - pairs if w not in known_syms]
        + [w for w in pairs if w not in known_pairs]
    )

    # A bare name is not an identity. `handler` is five different functions in five
    # files; `constructor`, `start`, `call`, `install`, `getRuntimeId` and 20 more are
    # equally ambiguous. Resolving by name alone answered EXTEND_EXISTING with a patch
    # picked alphabetically out of the tie. So: collect every (patch, file) a name
    # resolves to, and refuse to decide when one name spans several files unless the
    # caller disambiguated with `file:symbol`.
    homes = {}
    for p in m["patches"]:
        for s in p["symbols"]:
            homes.setdefault(s["name"], set()).add(s["file"])
    # PER-SYMBOL, not per-call. An earlier version tested `not any(":" in w for w in
    # want_syms)` over the whole input, so passing one disambiguated `file:symbol`
    # alongside a bare ambiguous one silently restored the alphabetical pick for the
    # bare one — the exact failure this guard exists to stop.
    ambiguous = {
        n: sorted(homes[n]) for n in want_syms if ":" not in n and len(homes.get(n, ())) > 1
    }

    hits = {}
    for p in m["patches"]:
        by_file, by_sym, by_tok = set(), set(), set()
        for s in p["symbols"]:
            if s["file"] in want_files:
                by_file.add(s["file"])
            # accept either `symbol` or the disambiguated `file:symbol`
            if s["name"] in want_syms or f"{s['file']}:{s['name']}" in want_syms:
                by_sym.add(s["name"])
            if want_toks and want_toks & tokens(s["name"]):
                by_tok.add(s["name"])
        if by_file or by_sym or by_tok:
            hits[p["patch"]] = {
                "patch": p["patch"],
                "owns_your_symbols": sorted(by_sym),
                "also_touches_your_files": sorted(by_file),
                "same_area_symbols": sorted(by_tok)[:10],
                "patch_total_symbols": len(p["symbols"]),
                # ONLY symbols are ownership. Files and area words inform a reading
                # list; counting them decides nothing because the hub files are
                # shared by nearly every patch.
                "ownership": len(by_sym),
            }

    # Rank by ownership, then by how much of the patch is in play, then by name —
    # never leave the winner to be decided by list order.
    ranked = sorted(
        hits.values(), key=lambda h: (-h["ownership"], -len(h["same_area_symbols"]), h["patch"])
    )
    owners = [h for h in ranked if h["ownership"] > 0]
    also_files = sorted({q for f in want_files for q in fo.get(f, [])})

    # Unknown inputs are EXPECTED: a pre-authoring call names symbols you are about to
    # create, and upstream symbols no patch touches are unknown to the map by
    # definition. An earlier version discarded the whole verdict whenever any input was
    # unknown — its own documented example tripped it — and told the caller to "check
    # the spelling", which was not the problem. Unknowns are now a note, not a veto;
    # only a total miss can decide nothing.
    unresolved = {}
    if unknown_files:
        unresolved["not_in_series_files"] = unknown_files
    if unknown_syms:
        unresolved["not_in_series_symbols"] = unknown_syms

    if ambiguous:
        verdict = {
            "decision": "CANNOT_DECIDE",
            "why": "a bare symbol name is not an identity — these resolve to several "
            "files, so ownership is undecidable. Re-run with 'file:symbol' for each",
            "ambiguous_symbols": ambiguous,
        }
    elif not hits and not also_files and (want_files or want_syms):
        verdict = {
            "decision": "CANNOT_DECIDE",
            "why": "nothing you passed appears in the series map at all. If these are "
            "paths, check they are repo-relative as they appear in the patches "
            "(e.g. src/renderer/src/web/web-preload-api.ts)",
            **unresolved,
        }
    elif len(owners) > 1 and len({h["ownership"] for h in owners}) == 1:
        # Several patches own the SAME symbols equally. The previous sort fell through to
        # the filename and announced a winner — the "tie broken alphabetically" failure
        # this tool was rewritten to remove, reproduced one tier down. Ownership cannot
        # choose here; the capability can, and only a reader knows that.
        verdict = {
            "decision": "CANNOT_DECIDE",
            "why": "these patches own your symbols equally, so ownership cannot pick one. "
            "Read them and extend the one whose CAPABILITY your change belongs to — and "
            "raise merging them, because they are already coupled",
            "equal_owners": {h["patch"]: h["owns_your_symbols"] for h in owners},
        }
    elif owners:
        top = owners[0]
        verdict = {
            "decision": "EXTEND_EXISTING",
            "patch": top["patch"],
            "symbols": top["owns_your_symbols"],
            "why": "this patch already owns symbols you intend to change; a new number "
            "would split one capability across two patches",
            "how": "commit into the fork, then restack THAT boundary and re-export the "
            "whole series — do not add a new patch number",
        }
        if len(owners) > 1:
            verdict["also_own_some"] = {h["patch"]: h["owns_your_symbols"] for h in owners[1:]}
            verdict["warning"] = (
                "more than one patch owns symbols you are touching; they are already "
                "coupled. Extend the one whose capability your change belongs to, and "
                "raise merging the rest — do not add a third participant silently"
            )
    elif ranked or also_files:
        # Reachable two ways: the graph tier found related patches, or only the file
        # tier did (a registry / allowlist / import-only edit owns no symbol). Either
        # way the answer is "not decided by ownership — go read", never a clean
        # NEW_PATCH, which would contradict the very list printed beside it.
        verdict = {
            "decision": "NEW_PATCH_BUT_CHECK",
            "why": "no patch owns your symbols, but these already work in your files or "
            "area. That is normal here (the hub files are touched by nearly every patch) "
            "and decides nothing — read them, then justify the new number in the CHANGELOG",
            "read_first": sorted({h["patch"] for h in ranked} | set(also_files)),
        }
    else:
        verdict = {
            "decision": "NEW_PATCH",
            "why": "no existing patch touches these symbols, files, or area",
        }

    if also_files:
        verdict["patches_touching_your_files"] = also_files
    if unresolved and verdict["decision"] != "CANNOT_DECIDE":
        verdict["note"] = unresolved

    if not want_syms and verdict["decision"] != "CANNOT_DECIDE":
        verdict["weak_input"] = (
            "no --symbols given, so this verdict rests on files/area alone and cannot "
            "reach EXTEND_EXISTING. Finish diagnosis, then re-run with the symbols you "
            "will actually change."
        )

    print(json.dumps({"verdict": verdict, "candidates": ranked}, indent=1))


if __name__ == "__main__":
    main()
