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

The CLI first asks the platform which lane serves the target service, then follows it. A CLI that predates this lane answers `source builds are not supported on the insta-compute provider yet` for such a target: run `insta upgrade` and retry.

**insta-compute service (the default plane for new services):**

1. A `Dockerfile` is **optional**. The CLI packs the directory into a deterministic archive, honouring the root `.dockerignore` (docker semantics) or, without one, `.gitignore` files (git semantics); `.git` and `.insta` never ship. The archive is uploaded straight to the platform's object store (this mint is govern-gated: it can return `approval_required` before anything is uploaded).
2. One gated call (`deploy`) enqueues **build + deploy as a single operation** and returns at once; the CLI polls it (`queued → building → deploying → live`) for up to 30 minutes. The build gateway builds the dir's own `Dockerfile`, or **detects the runtime with nixpacks when there is none**, pushes the image **pinned by digest**, and deploys it into the service. No `fly` CLI, no local Docker.
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
live provider credentials). Changing a
secret or binding takes effect on the **next deploy**, or on **`insta --agent compute restart`** (CLI ≥
0.0.51) for a service already running — no hot reload in either case: the machine takes a new config
and restarts on it, in place. Whether an *idle* machine is woken to do so depends on the compute
provider; see [operate.md](operate.md) before treating a restart as proof the app came back.

Provider credential **values** reach two places by different routes. The local seam
(`insta --agent secrets` / `insta --agent run`) carries user-defined secrets **plus** each type's
**primary** service credentials, so `.env` and a local run have a working `DATABASE_URL` as soon as
the branch has a postgres. A **compute container** gets nothing it was not explicitly bound. For a
**specific** (non-primary) postgres there is also a direct read — `insta --agent db url` /
`insta --agent db connect` (gated `secrets.read`) — for psql, migrations, and tools outside compute; pick
client tools of the server's Postgres major first (`pg_version` on `insta --agent services list --json`; a row
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
insta --agent compute set-domain app.example.com [--branch --group]   # prints the DNS records to add
insta --agent compute check-domain app.example.com                    # status once DNS propagates
```

The records live in **your** registrar (CNAME for a subdomain, A/AAAA for an apex, + a validation CNAME).

**You want to buy one** — InstaCloud registers it for you and attaches it itself:

```bash
insta domain contact set --first-name … --phone +14155550100   # once per org — HUMAN, admin, no --agent
insta --agent domain search myapp --tlds com,dev                # prices you pay, + renewal
insta --agent domain buy myapp.com --no-open                     # → a Stripe Checkout URL to relay
insta --agent domain status myapp.com                           # poll until active
```

Three things to get right as an agent:

1. **`buy` always ends with a human; whether it also starts with one depends on the policy.** The
   Checkout URL it answers has to be opened and paid by a person — that half is unconditional, so
   relay it verbatim and stop rather than reporting the domain as bought. Whether the ORDER needs
   approval first is the project's agent policy: `full_access`, which a new project starts on,
   allows `domain.purchase` outright and you get the URL immediately; `branch_developer` answers
   `approval_required` (relay that line too); `read_only` refuses.
2. **Nothing is registered before payment, and registrations are non-refundable.** A wrong name is
   real money, so read the quote back before ordering.
3. **The registrant is the customer, not us**, and setting the org default is a **human** step: the
   first line above has no `--agent` because that org-level write is unclassified for agents and is
   refused `403 unclassified_agent_action` under any policy. Relay it to an admin, or pass the
   contact the human gave you per purchase with `domain buy --contact-file c.json`.
   `--company-name` makes that organization the legal owner instead of the person.

Afterwards the platform registers the name, publishes the DNS in the zone it controls, and attaches
`myapp.com` **and** `www.myapp.com` to the compute service — no records for you to add. Delete that
service and the domain goes `detached`: the registration stands, and
`insta --agent domain attach myapp.com --group <service>` binds it somewhere else.

## Dockerfile templates → use the framework recipes

**Before hand-writing a Dockerfile, copy the recipe for your framework: [frameworks.md](frameworks.md).**
Next.js, Node/Express, Vite/SPA, and FastAPI each have a paste-and-deploy recipe with the four
first-deploy traps already solved (bind `::` not IPv4-only; `EXPOSE` == listen port so `--port`
auto-derives; `PORT` env matches; multi-stage build). Skipping this is why a first deploy boots
"fine" yet refuses every request. Full-stack = one container/one port (backend serves the built
frontend); separate SPA = its own tiny static-server compute service.
