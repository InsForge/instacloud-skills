# Operate — status, triage, and recovery

## Reading the environment

```bash
insta --agent status --json        # target api · login · linked project · current branch
insta --agent manifest --json      # every branch's db/storage/compute + URLs — the ground truth
insta --agent services list --json # what the project has (postgres rows: pg_version = Postgres major)
insta --agent events --limit 50    # what happened (resources + govern + agent findings)
```

Before any `pg_dump` / `pg_restore` / `psql` against a postgres service, read that service's Postgres
major first: `pg_version` on its `services list --json` row (one per service — a branch with several
postgres services has one each), or `ref.pgVersion` on the manifest's database resources (root and
branch rows alike; the `pg 16` badge on the printed lines needs CLI ≥ 0.0.57). Use client tools of
that same major — a dump taken by a newer client (17 against a 16 server) emits statements the
server rejects, and a default restore keeps going past those errors and leaves the target partially
loaded (`pg_restore` and `psql -f` only roll back as a unit under `--single-transaction`, psql also
with `-v ON_ERROR_STOP=1`). Neither read wakes a suspended instance. Rows older than the field were
backfilled from the image every instance was born from, so if a restore still fails on version
grounds against an old instance, confirm with the exact version. A legacy row that never recorded a
major shows `pg_version: null` and no `ref.pgVersion`; a platform that predates the field sends no
`pg_version` key at all (and no `ref.pgVersion` on any row). For the exact version either way, on
the same branch and service as the DSN (`--group <g>` when the branch has several postgres services):
`psql "$(insta --agent db url --branch <b> [--group <g>])" -c 'show server_version'` answers in one step (it
wakes a suspended instance, like any connection); `insta --agent db stats --json --branch <b> [--group <g>]`
reports it as `serverVersion` but never wakes one, so the field is present only while the instance
is running.

`manifest` is the first stop whenever reality seems to disagree with expectations — it shows what
each branch *actually* has (including a legacy shared bucket, or a compute group that was never
deployed).

## Metrics & logs

```bash
insta --agent metrics compute [group] [--branch --from --to --step --json]
insta --agent logs compute [group] [--branch --limit --region --instance --json]
insta --agent logs compute [group] --since 2h     # time window (--from/--to also accepted) — pages ~7 days of history
insta --agent metrics redis|mysql|mongodb [group]   # managed DBs are Fly apps: same full metrics/logs
insta --agent logs redis|mysql|mongodb [group] [--deploy]
insta --agent metrics db · insta --agent logs db      # postgres: provider-limited — returns a note, not series
```

insta-oss: metrics/logs return a clear "cloud-only / coming" 501 today — use `docker logs`/`docker
stats` on the branch's containers directly if you must, and don't retry the CLI command.

## Idle modes & what an app costs

**Billing is always by actual app usage** — vCPU·min burned, GB·min of RAM resident, storage,
egress — never by machine size × hours. The idle mode only changes what "idle" consumes:

- **Always-on (the birth default for compute since 2026-09-07, all plans)**: machines never
  suspend, so there are **no cold starts** — but the idle app keeps its RAM resident (plus a
  trickle of vCPU), and that real usage bills continuously (roughly $1–2.50/month for an idle
  minimum-spec app, mostly RAM).
- **Scale-to-zero (opt-in for compute; the default for postgres)**: idle machines suspend and
  auto-wake on the next request. An idle service costs **nearly nothing**; the trade is a cold
  start (typically a few seconds) on the first request after idling. Note: a service whose work
  arrives only on outbound connections (a bot polling its platform, a cron) is never woken by
  anyone, so it needs always-on.

Flip it any time — it is a latency/cost dial, not a plan feature:

- `insta --agent services add compute <name> --no-always-on` — create scale-to-zero (`--always-on` states the default explicitly).
- `insta --agent compute always-on on|off [service]` — toggle a live service.
- `insta --agent db always-on on|off [--group <g>]` — the same dial for a postgres service:
  `off` (default) suspends the idle instance and cold-starts the first connection after idle;
  `on` keeps it warm.

## Resource ceilings (limits)

A service's size is **not** a price — billing is actual usage either way. It is a **ceiling**: the
most the app may burn, i.e. its blast radius. So it moves in both directions, and lowering one
costs the customer nothing.

```bash
insta --agent compute limits                     # ceiling 4 vCPU / 4 GB  (plan max 4 vCPU / 4 GB on free; a new service is born AT its plan cap)
insta --agent compute limits --memory 1gb        # set it — cpu derives from memory
insta --agent db limits --memory 8Gi --cpu 4     # same dial for postgres
```

- **Memory is the dial.** It is the ceiling that actually bites (hitting it OOM-kills the app);
  vCPU only throttles, so it is derived unless `--cpu` is passed for a parallel workload. On
  compute, setting always requires `--memory` (`--cpu` is an override, never valid alone); on db,
  either flag alone works. Decimal (`mb`/`gb`) and binary (`Mi`/`Gi`) suffixes are both accepted.
- **Plan caps.** A new service is born at its plan's ceiling (free 4 vCPU / 4 GB, pro 8 / 8) and
  may move anywhere within it on any plan; raising ABOVE the free cap is the one thing a plan gates,
  precisely because usage billing means the size is no longer what you pay for.
- **Compute ceilings snap to the provider's sizes** (vCPU comes from a fixed ladder; memory in
  256 MB steps within a per-vCPU band). A request that cannot be honored exactly is REJECTED with
  the legal value named — never silently rounded.
- Raising or lowering a compute ceiling **restarts the machine**; a postgres resize restarts the
  instance only if it is awake (a suspended one applies the new ceiling on its next wake).

`insta --agent services upgrade` still exists but is the pre-usage-billing control for **compute**: named
specs, up-only. Prefer `limits`. For postgres it is not a fallback at all — an `upgrade` on a
postgres service is rejected outright; resize it with `insta --agent db limits` and grow its disk with
`insta --agent db volume`.

## Compute volumes

Compute persistent `/data` volumes are **not create-time only**:

```bash
insta --agent services add compute app --volume 1Gi  # attach at creation
insta --agent compute volume app --size 1Gi          # attach later if the service has no volume
insta --agent compute volume app                     # view size, mount path, and plan cap
insta --agent compute volume app --delete            # destroy the disk and all data
```

`--size` on a volumeless service attaches a volume, and it mounts when the machine is next created: the **next deploy, or `insta --agent compute restart`** (measured; no rebuild needed).
`--size` on an existing volume grows it only; volumes cannot shrink. Deleting is the only way off a
volume and is irreversible. A volume keeps machine count at 1 and changes scale-to-zero from suspend
to stop; those constraints lift after deletion.

## Pausing & resuming compute

To take a service **offline on purpose** — a maintenance window, cost control, or parking a
preview branch — use the lifecycle controls, which are a *persistent* override: a stopped/suspended
service will **not** be re-woken by incoming traffic (unlike scale-to-zero's auto-wake).

- `insta --agent compute stop [service]` — clean shutdown; stays down until `start`.
- `insta --agent compute suspend [service]` — snapshot RAM for a faster resume; stays down until `start`.
- `insta --agent compute start [service]` — bring it back online and re-enable auto-wake.
- `insta --agent compute status [service]` — desired (your intent) vs. live runtime state.

`[service]` is optional when the project has exactly one compute service. These work on all plans and
require no approval. A billing suspension is separate: you can't `start` while an org is billing-
suspended, and a manual `stop` is preserved across a billing pause/resume cycle. A billing
suspension force-stops always-on machines too — pinned-warm does not outlive the org's credit.

## Restarting a compute service

`insta --agent compute restart [service]` (**CLI ≥ 0.0.51**; older builds answer with commander's unknown-command
error) re-runs the image reference the service **already** runs, against a freshly resolved env
bundle. Reach for it in exactly two situations:

1. **A binding changed and the running app hasn't picked it up.** `insta --agent secrets bind` and
   `insta --agent secrets unbind` change what the app *would* receive, not what the running machine
   holds — env is baked into the machine at deploy time. `restart` is how that change lands without
   shipping a new version. **`insta --agent secrets set`/`unset` are not in this list any more, on
   CLI ≥ 0.0.78:** they redeploy the compute services that receive the value themselves, as part of
   the same command, so following one with a `restart` buys nothing and bills a second rollout. On an
   OLDER build they still only store the value and a `restart` is still required — tell the two apart
   by whether the command printed a per-service line (`~ … redeployed`), not by assuming the version:
   `autoupdate off` / `INSTA_NO_AUTOUPDATE=1` mean an agent can sit on an old build indefinitely.
2. **The machine is up but wedged.** A crash-looped or hung process is still `started`, so
   `insta --agent compute start` is a no-op on it — it only flips desired state and wakes a machine that is
   *down*. `restart` cycles it.

What it is **not**: a new deploy. It asks for no new version and no new spec — the image
*reference*, port and resource ceiling are exactly the ones already recorded on the service.

One qualification, and it is the only way a restart can change what runs: **it does not pin a
digest.** A service recorded against a moving tag (`app:latest`, `nginx:1.27`) gets whatever that
tag resolves to *now* — the same as redeploying that tag would. Source deploys (`insta --agent deploy <dir>`)
record a unique `insta-<timestamp>` label and are unaffected; only `--image` with a moving tag is.
If you are restarting a production app to cycle a wedged machine, that is worth knowing before you
run it.

Rules worth knowing before you call it:

- **The service must be running.** A deliberately stopped or suspended one is refused (400) and
  pointed at `insta --agent compute start`, which is also what re-enables auto-wake. A restart would
  otherwise silently undo the persistent override `stop` gives you.
- **A service that has never been deployed** is refused the same way `exec` refuses it — deploy an
  image first.
- **A machine that was already running is health-gated on the way back up.** If it doesn't answer on
  its port, the machines are rolled back — best-effort — to the config they were serving and the
  command reports the failure. That verdict is the useful part: a restart that "fails" here is
  telling you the app itself is broken, not the platform.
- **An idle machine may not be booted or gated at all — and a scale-to-zero service is idle between requests** (new compute is born always-on since 2026-09-07, so this applies to services switched to scale-to-zero). What happens to a
  scaled-to-zero machine depends on the compute plane behind your deployment — `insta --agent manifest
  --json` names it on each compute row (`provider`: `fly` or `microvm`, or the neutral `compute`
  when the platform did not report one, in which case assume neither behaviour). On the Fly-backed one it
  takes the new config *without waking*, coming up on it at the next request: nothing is
  health-checked and no uptime is billed for the restart itself. On the microVM plane the deploy
  waits for the service to be running and gates it.
  So do not read a fast, green restart of an idle service as proof the app still boots. If that
  proof is what you were after, **send it a request** and check the response — that is the one step
  that means the same thing on both. (`insta --agent compute always-on on` does *not* substitute: it changes
  the idle policy without starting a suspended machine, so it leaves you ungated and pinned warm.)
- **Gated under `deploy`** (unlike `start`/`stop`/`suspend`, which are ungated). Those change whether
  the service is running; this changes what it runs — it lands configuration through the same path a
  deploy does. So a project with `deploy` set to `deny` refuses it, and one set to `approve` relays it (`insta approvals approve
  <id>`; see governance.md). **If you only need to cycle a wedged machine under such a policy, use
  `insta --agent compute stop` then `insta --agent compute start`** — that force-stops and relaunches the machine
  without going through a deploy. What it will *not* do is pick up new configuration.
- All plans. Refused while the org is billing-suspended — the same door `start` stands behind. Any
  machine it wakes bills as ordinary uptime; one left asleep (see above) costs nothing.
- **WebSocket apps keep their concurrency.** The connections-based concurrency `insta --agent deploy
  --websocket` sets — and the 512 MB guest floor that rides with it — is recorded on the service, so
  a restart re-asserts it, as does any redeploy given no flag. A service deployed before that became
  a recorded setting has it recovered from its running machine. You do not need to redeploy a socket
  app just to keep it a socket app.

## Running a one-shot command on a compute machine

`insta --agent compute exec [service] -- <command> [args...]` runs a single command on the service's live
machine and returns — **no interactive shell, no stdin**. Use it for a one-off migration, a debug
`ls`/`cat`, or confirming a process is actually up.

- Targets **a single machine** — the first `started` machine, else the first live one. If a service
  has been scaled out to multiple machines, `exec` runs on exactly one of them, not all.
- A **scaled-to-zero machine wakes first** — adds a few seconds, and that wake time bills as normal
  compute uptime, same as any other request.
- `--timeout <sec>` bounds the run, **1–180s** (default 30); the remote command is killed if it
  doesn't finish in time.
- The CLI's **exit code is the remote command's exit code** — safe to check in a script (`&&`,
  `$?`). stdout/stderr stream to their own local streams verbatim; each is capped at **1 MiB**, with
  a truncation notice on stderr if hit. `--json` returns the raw response instead of split streams.
- Gated on **both** `deploy` and `secrets.read` — a deny on either is a 403; an approve on either
  triggers the usual relay (`insta approvals approve <id>`; see governance.md).
- A compute service with no image ever deployed 400s ("this service has no machines yet — deploy an
  image first, then retry") — `insta --agent deploy` it, then retry.

`[service]` is optional under the same rule as `start`/`stop`/`status` above.

## Getting an interactive shell (humans only)

When `exec`'s "no interactive shell, no stdin" is the thing in your way, `insta compute ssh [service]`
(CLI >= 0.0.71) mints a short-lived SSH certificate and prints the `ssh` command that uses it. It does
not open the session itself.

- **An agent cannot use it.** It requires an interactive login and refuses API keys with a 403,
  pointing at `compute exec`. That is deliberate: the certificate is a bearer credential for a root
  shell, and a shell is not a reviewable action the way one argv is. When you need a machine-run
  command, `exec` remains the answer.
- `--setup` does the one-time client setup and gives the service the alias `<service>.insta`, after
  which plain `ssh api.insta`, `scp` and `-L` work and the certificate renews itself while OpenSSH
  parses its config. Without `--setup` you get a self-contained `ssh -i ... <user>@<host>` line
  instead, and nothing is written to `~/.ssh`.
- Gated on **both** `compute.shell` and `secrets.read` (a shell inherits the service's decrypted
  env), and `compute.shell` **defaults to `approve`** rather than `allow` — see governance.md.
- **Compute-plane dependent**: a Fly-backed service has no SSH gateway and 400s naming `compute exec`
  instead. `insta --agent manifest --json` names the plane per compute row.

## Deploy triage (URL not serving after deploy)

Work the list in order — these cover ~all real failures seen so far:

1. **Port mismatch** (most common): `--port` ≠ the port the app listens on. Symptom: deploy
   "succeeds", every request refused/000. Fix: redeploy with the app's actual listen port; bind
   `0.0.0.0`.
2. **Cold start**: a scale-to-zero compute service (`--no-always-on`, or `insta --agent compute always-on
   off`; new compute is born always-on) suspends when idle — its first request can take seconds.
   Poll up to ~60s before concluding failure.
3. **Migration-gated startup**: `CMD migrate && server` with a hung migration = nothing listening,
   empty logs. Fix the CMD to start the server regardless (see deploy.md).
4. **Read the logs**: `insta --agent logs compute [group] --branch <b> --limit 100` — crash loops, missing
   env, bad image arch. A bare read is ONE provider page (~100 lines); when the failure is older
   than that, window it: `--since 2h`, or `--from <unix|ISO>` / `--to`.
5. **Stale CLI**: unrecognized command / odd 4xx → `insta --agent upgrade` (or re-run the installer), retry.
6. **Gate, not failure**: a 202 "approval required" is not an error — relay it (governance.md).

## Failure-reporting discipline

Report the exact observed state (HTTP code, log line, gate id) — never an assumed one. A deploy
isn't "done" until the URL served; a promotion isn't "done" until main's URL validated; a teardown
isn't "done" until `manifest`/`events` reflect it.

## Cloud vs insta-oss behavior differences

| Surface | Cloud | insta-oss |
| --- | --- | --- |
| login | required | doesn't exist (localhost trust) |
| usage / billing | real (billing dimensions) | 501 — no billing locally |
| metrics / logs | served (compute full, db limited) | 501 today (docker-stats planned) |
| source deploy (`deploy <dir>`) | ✅ remote build | not yet — use `--image` |
| services add postgres/storage | ✅ (≤5 each) | 501 — one of each, auto-provisioned |
| branch compute | fresh empty app — deploy to it | parent's image auto-redeployed |
| branch app URL | own subdomain | host port +1000 |
