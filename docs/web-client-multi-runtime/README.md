# The web client should hold several runtime environments, not one

**Question this answers:** the desktop app can keep many Orca servers side by side and switch
between them, but adding a second server in the Coder tile makes the first one vanish. Is that a
design limit of Orca, a bug, or something we can fix in our series — and what would it buy us?

**Short answer:** it is neither the design nor a bug — it is an assignment. The whole contract is
already list-shaped, calls are already addressed by selector, and the call queue pool is already
keyed by environment id. Only two things in the *web* shim are single: the localStorage slot that
holds the environment, and the one WebSocket client that gets closed whenever the environment
changes. `addFromPairingCode` overwrites rather than appends, which is literally why the first
server disappears.

**Parked, not scheduled.** Written 2026-07-26, right after `0011`–`0013` shipped. This is the
largest change the series would have taken on so far — it moves a storage schema and a connection
lifecycle — so it deserves a rested head and a real live check, not the tail of a long night.

---

## 1. Why this is worth doing

The value is not "more servers in a list". It is a specific topology that Coder makes possible and
nothing else does.

Coder is reachable from anywhere on the internet, and it authenticates before anything of ours is
touched. The workspace running `orca serve` sits inside a network contour that can reach machines
the internet cannot — a laptop at home among them. Put those two facts together and the browser
tile becomes a single safe entry point from which you can choose *which machine you are working
on*:

- the workspace's own head, for anything that should live on the server;
- a home Mac added as a second runtime, reached outward from the workspace rather than inward from
  the internet.

The desktop app already gives you exactly this, which is the tell that the model supports it. The
alternative Orca offers for reaching a laptop — its own VPN, or exposing the machine by IP — is
precisely what this topology avoids. Coder is already the authenticated door; the tile should be
able to stand behind it and address more than one host.

## 2. What is already multi-host — and must not be touched

This is the encouraging half, and it is why the change is contained.

| Layer | State |
|---|---|
| `PreloadApi.runtimeEnvironments` | already a list contract: `list()`, `addFromPairingCode`, `resolve`, `remove`, `disconnect`, `getStatus`, `call`, `subscribe` |
| RPC calls | `callEnvironmentEnvelope(selector, method, …)` — already addressed per environment |
| Call queues | `runtimeCallQueuePool.enqueue(environment.id, …)` — already keyed by environment id |
| Renderer | worktrees resolve their host through `getRuntimeEnvironmentIdForWorktree`; the whole ownership path we fixed in `0009`/`0011`/`0012` is host-aware |

A queue pool keyed by environment id is not something anyone writes for a single server. The
intent was there from the start; the web shim just never grew into it.

## 3. What is actually single

Two things, both in the web layer.

**The storage slot.** `web-runtime-environment.ts` keeps one object under one key:

```
const ENVIRONMENT_STORAGE_KEY = 'orca.web.runtimeEnvironment.v1'
readStoredWebRuntimeEnvironment(): StoredWebRuntimeEnvironment | null   // singular
saveStoredWebRuntimeEnvironment(env) → localStorage.setItem(KEY, JSON.stringify(env))
```

No array, no index, no add. So `list()` can only ever return zero or one entry, and
`resolveEnvironment(selector)` accepts nothing but that entry's id, its name, `'active'`, or an id
from `compatibleEnvironmentIds` — a list that exists to let *one* server be known by several ids
across re-keys, not to hold several servers.

**The connection.** `getClientForEnvironment` keeps a single `activeClient` plus
`activeClientEnvironmentId`, and closes the existing socket whenever the requested environment
differs. Two servers cannot be connected at once even in principle.

And the disappearance itself is four lines in `addFromPairingCode`:

```
const previousEnvironment = activeEnvironment
closeActiveRuntimeClients()
activeEnvironment = createStoredWebRuntimeEnvironment({ name, offer, previousEnvironment })
saveStoredWebRuntimeEnvironment(activeEnvironment)
```

Adding a server closes the connection and replaces the slot. Nothing is lost to a bug; the code is
doing what it says.

## 4. Shape of the change

| # | Change |
|---|---|
| 1 | `web-runtime-environment.ts`: keyed list under `orca.web.runtimeEnvironments.v2`, with a migration that adopts the existing `.v1` object so a live pairing survives the upgrade |
| 2 | `activeClient` → `Map<environmentId, WebRuntimeClient>`; close addressed, not wholesale |
| 3 | `addFromPairingCode` upserts into the set instead of replacing it |
| 4 | `resolveEnvironment` searches the set |
| 5 | `requireActiveEnvironment` selects by `settings.activeRuntimeEnvironmentId` — so this **depends on `0011`** |
| 6 | The trusted-session bootstrap and `attemptTrustedSessionRecovery` upsert *their own* same-origin environment and re-key only that one; a second server must never be disturbed by our re-pair path |
| 7 | Refine `0011`: with a set, the default must be the **same-origin** environment specifically. "The stored one" stops being well defined the moment there are two |

## 5. What to be careful about

- **Migration is the risk, not the feature.** The change rewrites how pairings are persisted. Get
  it wrong and a working tile logs out into the pairing form. The `.v1` read path should survive at
  least one release rather than being deleted on the same commit.
- **The threat-model note in `apps/orca-coder/CLAUDE.md` §1 widens.** Today the browser holds one
  device token; afterwards it holds one per server, so the "single-owner host only" rule stops
  being about this workspace alone and starts being about every machine the browser can reach.
  That belongs in the patch, not in a follow-up.
- **`0011` is a prerequisite, not a nice-to-have.** Without a pinned active environment there is no
  answer to "which of these is the default", and every ownership decision downstream falls back to
  local — the exact failure `0011` was written to end.
- **Live check, not a unit test.** Two real servers, a browser reload between them, and a terminal
  on each. The single-slot behaviour is invisible to typechecking and mostly invisible to unit
  tests too.

## 6. Same shape as everything else in this series

Worth recording, because it keeps being true: the web client is a reduced shim over a desktop-first
app, and nearly every "works on the Mac, dead in the tile" report resolves to a place where the
shim collapsed something the rest of the app already models properly. `0004` routed a stub to an
existing RPC. `0005` and `0013` added an RPC over handlers that already worked. `0009`, `0011` and
`0012` fixed ownership decisions that assumed a local machine the browser does not have. This one
is the same story told about storage: a registry flattened to a variable.
