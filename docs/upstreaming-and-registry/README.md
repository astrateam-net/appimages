# Going public — personal factory, Coder Registry, and upstreaming

> ### ⚠️ Patch numbers in this document predate the 2026-07-27 renumbering
>
> The series was consolidated **14 → 11** (now 12) in `f218528`: two merges collapsed three patches.
> Every number below may name a different capability today. Authoritative map — old → current:
>
> | This doc says | Was | Today |
> |---|---|---|
> | floating-workspace owner, local-fallback floor, active-runtime pin | `0009` / `0011` / `0012`-ish | all **`0008`** (`web-execution-owner`) |
> | mobile pairing, runtime share links | two patches | both **`0002`** (`web-pairing-credentials`) |
> | directory picker | `0006` | **`0005`** |
> | seeded settings | `0007` | **`0006`** |
> | "Open in" browser-editor URLs | `0008` | **`0007`** |
> | usage analytics | `0013` | **`0010`** |
> | — | did not exist | **`0011`** agent-status bridge, **`0012`** headless agent cold restore |
>
> Resolve any number against `ls apps/orca-coder/patches/` before acting on it. The *reasoning* in
> this document is still good; only the labels rotted.

Options for taking orca-coder out of the astrateam sandbox: a personal AppImage factory, the
Coder module published somewhere public, and patches pushed back to `stablyai/orca`. Written
2026-07-25, after the proof-of-concept was verified end to end.

**This is a sketch of possibilities, not a commitment.** Nothing here is scheduled. It exists so
the reasoning survives to whenever the decision actually gets made.

---

## 0. Why we are worth something to upstream

Not the patches — the *build*. This factory compiles Orca from source with the project's own
full gate: `build:desktop` runs `pnpm typecheck` across node, web and cli before packaging.
Upstream's release pipeline evidently does not.

Evidence from a single afternoon: `v1.4.155` shipped a caller passing `tabIndex={0}` to a
component that never declared the prop. It does not compile. Three release candidates
(`v1.4.156-rc.0/1/2`) carried the same break forward unnoticed. We hit it within minutes of
bumping, because applying patches to a pristine tag and building it *is* a compile test of that
tag.

That makes this repo a free early-warning signal for `stablyai/orca` — every VERSION bump is an
independent from-source verification of a release they shipped. Worth offering as an issue on
its own, separately from any patch: a release that does not build from source is a bug they
want to know about.

The patches are the second contribution. This is the first, and it costs nothing extra.

## The target shape

| Piece | Where | Name |
|---|---|---|
| AppImage factory | `github.com/mrkhachaturov/orca-coder` | app dir `apps/orca/` |
| Orca fork (patch polygon) | `github.com/mrkhachaturov/orca` | branch per patch series |
| Coder module | `coder/registry` → `registry/mrkhachaturov/modules/orca/` | module `orca` |

Namespace `mrkhachaturov` matches the GitHub handle, which is the registry convention. The
*module* is called `orca`, not `orca-coder` — registry modules are named after the tool they
install (`code-server`, `jetbrains`, `cursor`), and the tile, slug and app identity are all
already `orca`. `orca-coder` stays the name of the **factory repo and its release asset**.

---

## 1. What the registry actually requires

From `coder/registry` `CONTRIBUTING.md` (checked against the clone at
`astrateam-control-plane/ref/coder-registry`, 25 namespaces, mostly individuals — third-party
contributions are the norm, not the exception):

```
registry/mrkhachaturov/
├── .images/avatar.png          # required, square, ≥400x400 (github.com/mrkhachaturov.png)
├── README.md                   # namespace bio, frontmatter: display_name, bio, avatar,
│                               #   github, status: "community"
└── modules/orca/
    ├── main.tf
    ├── README.md               # frontmatter: description, icon, tags, usage examples
    ├── orca.tftest.hcl         # you already have this — 10 passing
    └── scripts/install.sh
```

Mechanics: `./scripts/new_module.sh mrkhachaturov/orca` scaffolds it, `bun run fmt` before
committing, `terraform test -verbose` must pass. **The TypeScript test suite runs Docker with
`--network=host`, which does not work under Docker Desktop on macOS** — use Colima or OrbStack,
or run those on Linux. Terraform tests are fine on the Mac as-is.

Your existing module is already close: it has the tftest file, a README, and a scripts dir. The
port is mostly renaming the source path and adding the namespace scaffolding.

## 2. The one thing that will get pushed back on

**Your module would install a binary built in your personal repo.** Third-party modules are
absolutely the norm — 29 of them versus the `coder` namespace's own. But that is not the
distinction that matters. Every GitHub-releases URL across all 29 points at the **upstream
project's own repo**:

```
djarbz/copyparty              → github.com/9001/copyparty
BenraouaneSoufiane/rustdesk   → github.com/rustdesk/rustdesk
coder-labs/codex              → github.com/openai/codex
coder-labs/ttyd               → github.com/tsl0922/ttyd
cytoshahar/positron, anomaly/tmux, thezoker/nodejs, … → vendor installers / distro packages
```

`registry/coder/modules/code-server` does the same — `https://code-server.dev/install.sh`.

**Not one module in the registry installs a binary the module's author built.**
`djarbz/copyparty` is the exact shape of your case — an individual's module for someone else's
software — and it still pulls from the vendor. Yours would be the first to source a fork-build
from the author's own releases. That is not automatically a rejection, but it is the question
to walk in with an answer to, in the module README rather than in review comments.

A reviewer will reasonably ask: *why not install Orca from `stablyai/orca` releases directly?*

The honest answer is the whole reason this repo exists: **stock Orca cannot run behind a Coder
proxy.** `orca serve` mints a pairing token and delivers it only in the URL fragment, so a
fixed tile URL lands on a "paste a pairing code" form. That is patch 0001.

Which points at the real strategic move.

## 3. Upstream first — it is the higher-leverage path

If `stablyai/orca` accepts trusted-proxy mode, the registry module installs the **official**
Orca AppImage, and:

- no personally-built binary in anyone's supply chain — the review objection disappears
- no rebuild treadmill on every upstream release
- the module keeps working when you are not looking at it

Today measured the carrying cost of *not* doing this. In one session: upstream shipped a
release that does not compile from source (patch `0000`), four of our forty-one touched files
churned between two patch releases, and the series needed a rebase. That is the recurring tax
on eight patches held privately, forever.

### What is actually contributable

| Patch | Upstream? | Notes |
|---|---|---|
| `0000` tabIndex | **No — already fixed** | Upstream fixed it on `main` after v1.4.155. Nothing to send; it evaporates on the next tag. Not a useful test of the contribution flow. |
| `0004` resource manager | **Yes — easy** | Routes a stubbed web call to an existing RPC. Small, obviously correct. |
| `0005` CLI registration | **Yes — easy** | Same shape. |
| `0006` floating-workspace dir picker | **Yes — easy** | Same shape. |
| `0007` runtime-seeded settings | **Yes — medium** | Needs the "defaults not policy" rationale explained, but it is a real gap: a headless workspace cannot declare its own appearance. |
| `0001` trusted-proxy | **Yes — big** | Architecture + threat model. Open a discussion first, not a surprise PR. |
| `0002`/`0003` mobile pairing, share links | **Partly** | Entangled with our Coder-specific address policy; split the generic part out if upstreaming. |

`0004`–`0006` are the right first PRs. They are self-contained, they fix a class of bug
upstream already acknowledges (the web client is deliberately stubbed — see `apps/orca-coder/
CLAUDE.md` §1), and landing them builds the credibility that a trusted-proxy discussion needs.

`0001` is the one that matters. Frame it as *"code-server solves this with `--auth none` +
loopback bind; here is the same model with Orca's E2EE intact"* — that framing is already
written up in CLAUDE.md §1 and is the strongest version of the argument.

## 4. Suggested sequencing

1. **Stand up `mrkhachaturov/orca-coder`.** Copy this repo's `apps/orca-coder/` → `apps/orca/`,
   the CI, the skills, the docs. Fork `stablyai/orca` properly as the patch polygon (today it
   is `mrkhachaturov/orcaide`, a name with the same invented-product problem — worth fixing in
   the move).
2. **Publish the module to the registry** pointing at your releases. It works today and it
   unblocks Coder users now. Be upfront in the module README about where the binary comes from
   and why — reviewers respond better to a stated rationale than to a discovered one.
3. **Upstream `0004`–`0006`.** Small, quick, credibility-building.
4. **Open the trusted-proxy discussion**, then the PR.
5. **If it lands, switch the module to official `stablyai/orca` releases.** The factory becomes
   optional — kept only for patches upstream declines.

Steps 2 and 3 are independent; run them in parallel.

## 5. Publishing the module without the Coder Registry

The Coder Registry is a *catalog* — discoverability, not distribution. Three independent ways to
ship the module, and they are not mutually exclusive.

**a. Direct git source — works today, no ceremony.**

```hcl
module "orca" {
  source = "git::https://github.com/mrkhachaturov/orca-coder.git//modules/orca?ref=v1.0.0"
}
```

No naming rules, no publishing step, private repos work with credentials. Pin with `?ref=<tag>`
— git sources take no `version` argument. Already proven: the control-plane template consumes
`code.astrateam.net/registry/orca/coder` today, so Coder does not care where a module lives.

**b. Public Terraform Registry (`registry.terraform.io`).** Requirements, per HashiCorp's
publish docs:

- repository must be **public**
- repository must be named **`terraform-<PROVIDER>-<NAME>`** → `terraform-coder-orca`
- at least one **semver tag** (`v1.0.0`); releases are tracked by tags
- standard structure (`main.tf`, `variables.tf`, `outputs.tf`, README) for docs generation
- published through the registry website after GitHub sign-in

Consumers then get `source = "mrkhachaturov/orca/coder"` + `version = "1.0.0"`.

**The naming rule forces a repo split.** The module cannot sit inside a repo called
`orca-coder`. That is arguably correct anyway: the AppImage factory and the Terraform module are
different artifacts on different cadences, and coupling them means every patch rebuild churns
the module's version tags. Revised target shape if this path is taken:

| Piece | Repo |
|---|---|
| AppImage factory | `mrkhachaturov/orca-coder` (app dir `apps/orca/`) |
| Terraform module | `mrkhachaturov/terraform-coder-orca` |
| Orca fork (patch polygon) | `mrkhachaturov/orca` |

**c. Coder Registry** — §1 above.

Doing (b) and (c) together is the sensible default: (b) costs one repo and a tag, gives real
versioning and a docs page, and is unilateral. (c) adds reach. If (c) is declined over binary
provenance, nothing is lost — the module is already published and installable, and the answer to
the objection is upstreaming `0001`, which is worth doing on its own merits.

## 6. Licensing

Orca is MIT. Redistributing a patched build is permitted, and the obligation is to preserve the
copyright notice and license text in the distributed artifact. Keep upstream's `LICENSE` in the
AppImage, state plainly in both READMEs that this is upstream Orca plus patches rather than an
independent product, and keep the app's own identity (`productName` `Orca`, `appId`
`com.stablyai.orca`) unchanged — which the build already does.

That last point is not just legal hygiene. The `astraide` name cost real debugging time this
session: a screenshot could not be attributed to "our Orca" versus upstream's, and the settings
investigation went looking in `~/.config/astraide` for a directory that has always been
`~/.config/orca`.
