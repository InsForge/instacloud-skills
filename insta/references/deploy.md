# Deploy

Ship code to a branch's compute — image or source — and verify it actually serves.

## Two modes (pick exactly one)

```bash
insta --agent deploy --image <registry/img> --port <n>    # prebuilt image — ALWAYS pass --port
insta --agent deploy <dir> --port <n>                     # source dir — Dockerfile OPTIONAL on insta-compute, REQUIRED on Fly-backed compute
# both: [--branch <b>] targets another branch · [--group <g>] picks a compute service by name
```

Targets the **current branch's** sole compute service by default; the URL prints on success.

Before source deploys, run `insta --agent build <dir> --port <n>`. It is local/offline and catches the
common failures before the remote build: missing Dockerfile/start command, wrong or undetected port,
unexpected `.env.example` keys, and an oversized Docker context. Read the verdict against the target:
`deployable` (a Dockerfile in the dir) deploys on every plane. A dir with no Dockerfile stops at
`needs-attention` (⚠ Dockerfile check) when nixpacks is installed locally and detects the app, or at
`failed` when it is not installed — the command is local and cannot know which compute plane the
target runs on. On an **insta-compute** service both still deploy: the build gateway runs nixpacks
server-side, so do not add a Dockerfile only to satisfy the local check. On a **Fly-backed** service
the dir's own Dockerfile is required and the deploy exits 1 without one. `--explain` shows the
Dockerfile — yours, or the nixpacks one **for inspection only** (not standalone; do not save it as
`Dockerfile`); use `--json` when an agent needs structured output.

Never run a bare `insta --agent deploy <dir>` and assume the port: without `--port` older CLIs default
to 8080 regardless of the Dockerfile (boots "fine", every request refused — see below). Newer
CLIs default from the Dockerfile's `EXPOSE` and print what they picked — read that line and
confirm it matches the server's listen port.

## How source mode builds (what actually happens)

The CLI first asks the platform which lane serves the target service, then follows it. A CLI that predates this lane answers `source builds are not supported on the insta-compute provider yet` for such a target: run `insta --agent upgrade` and retry.

**insta-compute service (the default plane for new services):**

1. A `Dockerfile` is **optional**. The CLI packs the directory into a deterministic archive, honouring the root `.dockerignore` (docker semantics) or, without one, `.gitignore` files (git semantics); `.git` and `.insta` never ship. The archive is uploaded straight to the platform's object store (this mint is govern-gated: it can return `approval_required` before anything is uploaded).
2. One gated call (`deploy`) enqueues **build + deploy as a single operation** and returns at once; the CLI polls it (`queued → building → deploying → live`) for up to 30 minutes. The build gateway builds the dir's own `Dockerfile`, or **detects the runtime with nixpacks when there is none**, pushes the image **pinned by digest**, and deploys it into the service. No `fly` CLI, no local Docker. If it stalls or fails mid-build, `insta --agent build logs <build-id>` (the deploy operation id the CLI prints while polling; `--follow` to stream it live) reads the gateway's own build output — use `--source github` with the GitHub build id instead for a build that a GitHub push triggered.
3. Re-running the same unchanged directory resolves to the operation it already started and answers in seconds; a changed directory builds again. After an `approval_required`, approve and re-run the same command — the body is byte-identical, so the grant applies.
4. Do **not** save the nixpacks Dockerfile that `insta --agent build --explain` prints as your `Dockerfile`: it `COPY`s `.nixpacks/` support files the dir does not have. When you do want your own, start from the detected install/start commands or the framework recipes below.

**Fly-backed service (legacy compute):**

1. The dir **must** contain a `Dockerfile` — there is no nixpacks lane on this plane, and the CLI exits 1 without one, naming the options: add a Dockerfile (framework recipes below), use `--image`, or connect the repo to the service (`insta --agent compute connect-repo <owner/repo> [service]`), which builds Dockerfile-less repos with nixpacks server-side.
2. Needs the `fly` CLI locally (auto-installed via Homebrew on macOS) but **NO Fly account/login** — the platform mints a **short-lived, app-scoped deploy token** (govern-gated: it can return `approval_required` *before* any build runs).
3. The build runs on Fly's **remote builders** (no local Docker); the image is pushed and **pinned by digest** (tags race the registry), then deployed like any image.

**insta-oss:** source mode builds the image with your local Docker — same command; `insta --agent compute connect-repo` is cloud-only there (501).

## `--port` — the #1 deploy mistake

**`--port` must equal the port the app LISTENS on inside the container** (`EXPOSE` / server bind).
A mismatch boots "successfully" but every request fails (`instance refused connection`). Bind to
`0.0.0.0`, never `127.0.0.1`. On insta-oss it's also the host port for direct deploys; branch
clones keep the listen port and shift the **host** mapping +1000.

## Secrets at runtime

Compute env is explicit. At deploy, the platform injects:

- `PORT`
- user-defined secrets visible to that compute service (`insta --agent secrets set`, project/branch or
  compute-scoped)
- provider credentials you explicitly bound with `insta --agent secrets bind`

Provider-minted credentials are **not** injected just because the project has a postgres, redis,
mysql, mongodb, or storage service. Bind each credential the app needs, then deploy/redeploy:

```bash
insta --agent secrets sources
insta --agent secrets bind DATABASE_URL postgres/db --to compute/app
insta --agent secrets bind REDIS_URL redis/cache --source-name REDIS_URL --to compute/app
insta --agent deploy . --group app --port 8080
```

If the source has a single credential (`postgres`), `--source-name` is optional. Sources with several
credential names (`storage`, `redis`, `mysql`, `mongodb`) need `--source-name`. Production code reads
`process.env`; **never bake `./.env` into the image** (it is the local-dev seam, and it carries
live provider credentials). A changed
**binding** takes effect on the **next deploy**, or on **`insta --agent compute restart`** (CLI ≥
0.0.51) for a service already running. A changed **user secret** needs neither **on CLI ≥ 0.0.78**:
`insta --agent secrets set`/`unset` redeploy the compute services that receive the value as part of
the same command, on the branch they target — do not follow one with a restart, it is a second
billable rollout. On an older build they only store the value and the restart is still required; the
applying build is the one that prints a per-service line (`~ … redeployed`) after the set. Either way
there is no hot reload: the machine takes a new config and restarts on it, in place. Whether an
*idle* machine is woken to do so depends on the compute provider; see [operate.md](operate.md) before
treating a restart as proof the app came back.

Provider credential **values** reach two places by different routes. The local seam
(`insta --agent secrets` / `insta --agent run`) carries user-defined secrets **plus** each type's
**primary** service credentials, so `.env` and a local run have a working `DATABASE_URL` as soon as
the branch has a postgres. A **compute container** gets nothing it was not explicitly bound. For a
**specific** (non-primary) postgres there is also a direct read — `insta --agent postgres url` /
`insta --agent postgres connect` (gated `secrets.read`) — for psql, migrations, and tools outside compute; pick
client tools of the server's Postgres major first (`pg_version` on `insta --agent service list --json`; a row
without one falls back to the exact-version read in [operate.md](operate.md)).
A non-primary service of **any other type** (storage, redis, mysql, mongodb) has no such read —
bind it, or read that service's own env with `insta --agent secrets --service compute/<name>`.
Otherwise its credentials run only where they are bound: the deployed app itself, or a one-shot
`insta --agent compute exec app -- <cmd>` (≤180s, no stdin) — migrations run either way (never as a
startup gate; see the gotchas below).

## Verify before reporting (non-negotiable)

The deploy command exiting ≠ the app serving. After every deploy:

```bash
curl -s -o /dev/null -w '%{http_code}' <printed-url>   # poll ~every 3s, up to ~60s
```

A scale-to-zero service (`--no-always-on` at create, or `insta --agent compute always-on off`) cold-starts on the first request — allow a slow first hit; new compute services are born always-on (since 2026-09-07) and skip this. `200` (or the
app's expected status) → report deployed **with the URL**. Anything else → triage per
[operate.md](operate.md); never claim success you didn't observe.

## Deploy gotchas (each has burned real deploys)

- **Never gate container startup on migrations.** `CMD migrate && server` + a hung migration =
  a "successful" deploy that serves nothing, with empty logs. Run migrations non-blocking:
  `timeout 30 <migrate> || echo skipped; <start-server>`.
- **Cold start ≠ down.** A scale-to-zero compute service (`--no-always-on`, or switched off with `insta --agent compute always-on off`) suspends when idle; the first request wakes it. New compute is born always-on and does not.
- **Redeploy replaces.** Compute is stateless — anything written to the container filesystem is
  gone on the next deploy. State belongs in the branch's postgres/storage.

## Custom domains

**You already own the name** — you set the DNS, InstaCloud does the cert and routing:

```bash
insta --agent domain attach app.example.com [--branch --group]   # prints the DNS records to add
insta --agent domain check app.example.com                    # status once DNS propagates
```

The records live in **your** registrar (CNAME for a subdomain, A/AAAA for an apex, + a validation CNAME).

**You want to buy one** — InstaCloud registers it and owns the zone; you say what it serves:

```bash
insta --agent domain search myapp --tlds com,dev   # prices you pay, + renewal
insta --agent domain buy myapp.com --no-open       # CLI ≥ 0.0.80 — → a Stripe Checkout URL to relay
insta --agent domain status myapp.com              # CLI ≥ 0.0.80 — poll until the order is registered
insta --agent domain attach myapp.com              # CLI ≥ 0.0.80 — bind it, and its www
insta --agent domain status myapp.com              # poll until www serves — the APEX stays pending here
insta --agent domain delegate myapp.com            # CLI ≥ 0.1.3 — the apex verifies only on a managed zone (details below)
insta --agent domain status myapp.com              # poll until every hostname you bound is active
```

Three things to get right as an agent:

1. **`buy` always ends with a human; whether it also starts with one depends on the policy.** The
   Checkout URL it answers has to be opened and paid by a person — that half is unconditional, so
   relay it verbatim and stop rather than reporting the domain as bought. Whether the ORDER needs
   approval first is the project's agent policy: `full_access`, which a new project starts on,
   allows `domain.purchase` outright and you get the URL immediately; `branch_specific` answers
   `approval_required` (relay that line too); `read_only` refuses.
2. **Nothing is registered before payment, and registrations are non-refundable.** A wrong name is
   real money, so read the quote back before ordering.
3. **Nobody is asked for a registrant contact.** InstaCloud registers under its own registrar
   account, so there is no contact to collect and no step before `search`.

Payment registers the name and nothing else — **buying is not attaching**, so the domain sits as
inventory until you say what it should serve. The domain belongs to the **org**: any project in it
can attach a hostname, and `domain list` shows the org's whole inventory. `domain attach myapp.com` binds `myapp.com` **and**
`www.myapp.com`; the platform publishes the DNS in the zone it controls, so there are no records for
you to add.

**The apex needs the managed zone.** Only `www` (and other subdomains) can verify while the zone
sits at the registrar: the apex flattens to shared proxy addresses no certificate is issued for, so
`myapp.com` itself stays `pending` and eventually fails. Move the domain's DNS onto an
InstaCloud-managed zone and it serves:

```bash
insta --agent domain delegate myapp.com   # CLI ≥ 0.1.3; org admin. Policy decides (see below); 202 approval_required is relayed, not an error
insta --agent domain status myapp.com     # hostnames re-verify on their own; no re-attach
```

Whether it runs or waits is the project's agent policy, exactly as with `buy`: `full_access`, which
a new project starts on, allows `domain.delegate` outright — **the delegation just executes, no
approval stands in the way** — `branch_specific` answers `approval_required` (relay that line),
`read_only` refuses. That gate is read from the linked project; a project-less credential (an
`insta_` key, an MCP assertion) is judged on the whole org instead — org admin plus **every**
project in the org on `full_access` executes it with no gate at all, and anything less is refused
with a misleading `project.billing.update` denial. Run it from the linked project.

Records are copied first — the platform's and yours — and the nameservers switch after, so a
serving `www` stays up (a domain carrying the customer's own MX/SPF keeps serving them, but the
`records` API is closed while managed, so their DNS cannot be *edited* until the reset — surface
that trade-off before delegating a domain with live mail); a hostname that had failed *because*
the zone was delegated away revives by itself. First-time registry propagation can take ~15–20 min
(17 measured on the first live delegation, 2026-09-22). The way back is
`insta domain nameservers reset myapp.com` — agent credentials answer 403 on the nameserver verbs,
so relay that exact command to the user rather than running it.

Any subdomain works, and each one is its own call, so one name can serve several services:

```bash
insta --agent domain attach api.myapp.com  --group api    # CLI ≥ 0.0.80 — only api.myapp.com moves
insta --agent domain attach docs.myapp.com --group web    # CLI ≥ 0.0.80 — docs.myapp.com joins it
```

Delete a service and only ITS hostnames go: the rest keep serving, and a domain left with nothing
goes `detached` — the registration stands, and `domain attach` binds it somewhere else.

## Dockerfile templates → use the framework recipes

**Before hand-writing a Dockerfile, copy the recipe for your framework: [frameworks.md](frameworks.md).**
Next.js, Node/Express, Vite/SPA, and FastAPI each have a paste-and-deploy recipe with the four
first-deploy traps already solved (bind `0.0.0.0`; `EXPOSE` == listen port so `--port`
auto-derives; `PORT` env matches; multi-stage build). Skipping this is why a first deploy boots
"fine" yet refuses every request. Full-stack = one container/one port (backend serves the built
frontend); separate SPA = its own tiny static-server compute service.
