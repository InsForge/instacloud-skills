# InstaCloud CLI reference

Command catalog with flags and gates. Task guidance lives in `references/` — setup, deploy,
branching, governance, operate, mcp.

## Commands

Managed agent execution uses the global prefix `insta --agent …` (for example,
`insta --agent services add compute api`). High-confidence Codex/Claude Code/Cursor environments
also activate agent mode. `insta --agent setup agent` issues/refreshes a 24-hour project session in
`.insta/agent-session.json` and adds it to `.gitignore`; user login is still required. Missing or
invalid sessions fail closed with setup guidance. Agent examples include the global flag
explicitly. Bare approval commands below are for a human admin to run, never the agent.

| Agent policy command | Purpose |
| --- | --- |
| `insta --agent agent-policy get [--json]` | mode, protected branch IDs, rules, session epoch, action catalog |
| `insta --agent agent-policy set <full-access\|read-only\|branch-developer> [--json]` | change mode; admin required |
| `insta --agent agent-policy protect-branch <name-or-id> [--json]` | protect an explicitly selected branch |
| `insta --agent agent-policy unprotect-branch <name-or-id> [--json]` | remove branch protection |
| `insta --agent agent-policy rule set <action> <allow\|deny\|approve> [--json]` | change an eligible unprotected action rule |
| `insta --agent agent-policy revoke-sessions [--json]` | revoke ALL project CLI sessions by incrementing epoch |

`agent-policy` is the only policy command; the old `policy` command is removed. Human requests
use normal RBAC without a policy gate. New/existing projects start with explicit
`full_access`. Restricted agents cannot edit their own policy or protection list. Agent approvals
bind the complete request and are single-use; a human admin runs `insta approvals approve <id>`,
then the agent retries unchanged. MCP cannot approve on the human's behalf. Session files/private
keys and raw request data must not be included in source control or approval reports.

| Command | Purpose |
|---|---|
| `insta --agent login` [`--api-url <url>`] [`--env <prod\|staging>`] · `insta --agent login --email <e> --password <p>` · `insta --agent login --oauth <github\|google>` · `insta --agent login --device` · `insta --agent login --api-key <insta_…>` · `insta --agent logout` | auth (api-url + tokens persist; tokens auto-refresh). **Bare `insta --agent login` signs in from the browser** (any account type — email, GitHub, Google): it opens the console approval link locally, prints it as fallback, and polls until the human approves (~15 min window). `--device` is the same grant, print-only, for a machine with no usable browser (VMs, SSH, CI): the human approves **from a browser on any other machine**. `--oauth` opens a browser straight into the named provider (loopback capture). Agents use email/password or an API token; a password (`--password`/`$INSTA_PASSWORD`) needs `--email`. An `insta_` token can also come from ID-JAG registration at `POST https://api.instacloud.com/agent/auth` when the agent runs inside a participating provider (preview, see https://instacloud.com/auth.md), then `insta --agent login --api-key insta_…`. `--env` targets a named deployment (see [Environments](#environments)); `--api-url` wins if both are given |
| `insta --agent env` [`--json`] · `insta --agent env use <prod\|staging>` [`--json`] | show or switch the deployment environment. **Switching drops the stored session** — prod and staging are separate deployments, so the old token cannot authenticate. See [Environments](#environments) |
| `insta --agent status` [`--json`] | environment + login + linked project + current branch |
| `insta --agent org list` [`--json`] · `insta --agent org create <name>` [`--json`] | organizations (**one free org per user** — upgrade an existing org before creating another) |
| `insta --agent project create <name>` [`--org <id>`] [`--json`] | create an **empty** project (no services), link this dir. With `--json`, a missing/unresolvable name is a hard error even on a terminal (never prompts) |
| `insta --agent project list` [`--org`] [`--json`] · `insta --agent project link <id>` [`--json`] | list / link existing |
| `insta --agent project delete` [`--json`] | tear down ALL resources + unlink (gated: `project.delete`, approval by default) |
| `insta --agent services add <postgres\|storage\|compute\|redis\|mysql\|mongodb> <name>` [`--branch <b>`] [`--region <r>`] [`--image <url>`] [`--port <n>`] [`--always-on`\|`--no-always-on`] [`--volume <gi>`] [`--json`] | provision a service **on a branch** (default: current/linked branch) — services are **branch-scoped**: adding one on a branch does not add it to any other branch; postgres/compute get a default access domain (gated: `service.add`). **compute only:** `--image` runs that image immediately at creation (otherwise compute starts as an empty, unreachable app until `insta --agent deploy`); `--port` sets the listening port (default `8080`); **new compute services are born always-on** (never scale to zero; since 2026-09-07) — `--no-always-on` creates it scale-to-zero instead (idle machines suspend, the next request wakes it), `--always-on` states the default explicitly (all plans, billing is actual usage either way); `--volume <gi>` attaches a persistent `/data` volume (also attachable later via `insta --agent compute volume --size` — see [Volumes](#volumes)). The image is **persisted** on the service — shown in `services list`, re-run when the branch is forked, and updated later via `insta --agent deploy --image`. Both positional arguments are optional in the parser: a **terminal** given **no type** picks from the same four kinds the dashboard's Add Service menu offers — **Docker Image** (asks for the ref, suggests a name from it, then the port), **Postgres** (`main-db`), **Storage** (`assets`), **Empty Service** (`compute`) — and is asked for a name after; given a **type but no name**, only the name is asked, for that type's plain kind. **Anything without a TTY errors and creates nothing** — with no type, all four kinds, each printed as the command to run instead (Docker Image as `insta --agent services add compute <name> --image <ref> --port <n>`); with a type but no name, that kind's naming usage — so always pass both here. Docker Image is a *kind*, not a follow-up question: non-interactively it is just `--image` on a compute service. `--json` prints the created service object (id, type, name, domain, region, …) instead of the human line, and opts out of the prompts, so a missing positional errors the same way even on a terminal |
| `insta --agent regions` [`--json`] | list regions available for postgres/compute services |
| `insta --agent services list` [`--json`] [`--branch <b>`] · `insta --agent services rename <type> <name> <new-name>` [`--json`] [`--branch <b>`] · `insta --agent services remove <type> <name>` [`--branch <b>`] [`--json`] | list / rename / remove a branch's services (default: current branch; bindings keep pointing at renamed services; gated: `service.rename` / `service.remove`). `list --json` rows carry `pg_version` on postgres services (a platform field — any CLI passes it through; one per service row — a branch with several postgres services has one each) — the Postgres **major** the instance runs (e.g. `16`), known without waking it — so pick `pg_dump`/`pg_restore`/`psql` of the **same major** before you connect (a newer client's dump emits statements the server rejects, and a default restore continues past them). **(CLI ≥ 0.0.57)** the human line shows it as `pg 16`; `services add postgres` and `manifest` print the same badge. Rows older than the field were backfilled from the image every instance was born from, so if a restore still fails on version grounds against an old instance, confirm with `serverVersion`. `null` = a legacy row that never recorded one; key absent = a platform that predates the field. Either way, read the exact version instead, selecting the same branch and service as the DSN: `insta --agent db stats --json --branch <b> [--group <g>]` reports `serverVersion` but never wakes a suspended instance (field present only while it runs), and `psql "$(insta --agent db url --branch <b> [--group <g>])" -c 'show server_version'` answers in one step, waking it |
| `insta --agent services secrets <type> <name>` [`--branch <b>`] [`--json`] | secret **names** bound to one service (e.g. `insta --agent services secrets postgres db`) — default: current branch |
| `insta --agent db url` [`--branch <b>`] [`--group <g>`] [`--json`] | print a postgres service's **connection string** (DSN). Default output is the bare URL alone on stdout, pipe-friendly (`psql "$(insta --agent db url)"`); `--json` replaces it with a `{service, branch, url}` envelope. The bundle carries only the **primary** postgres service's `DATABASE_URL`, so this is the command that yields a *specific* service's DSN (gated: `secrets.read`). `--group` picks one when the branch has several postgres services |
| `insta --agent db connect` [`--branch <b>`] [`--group <g>`] | open an **interactive psql session** on a postgres service (needs `psql` on PATH; gated: `secrets.read`). A suspended instance wakes on connect — the first prompt can take a few seconds. Exits with psql's own exit code |
| `insta --agent db stats` [`--branch <b>`] [`--group <g>`] [`--json`] | point-in-time **postgres stats snapshot**: connections vs the server's max (active count), cache hit rate, database size. Read-only; insta-db-backed services answer from the control plane without waking a suspended instance — `serverVersion` (rendered `PG 16.4`) is present only while the instance is running, like `cacheHitRatio`. Same read as the `insta_db_stats` MCP tool's `metrics` kind (its `insight`/`activity`/`query-stats` kinds are MCP-only) |
| `insta --agent services scale compute <name> <number>` [`region`] | set the compute service's same-region replica count (**1–10**) — **paid plans only** (free → 403); gated: `service.scale`. `region` is an InstaCloud slug (e.g. `us-east`; see `insta --agent regions`), **not** a raw Fly code |
| `insta --agent compute limits [service]` [`--memory <size>`] [`--cpu <n>`] [`--branch <b>`] [`--json`] | show or set a compute service's **resource ceiling** — **any plan within the free cap; raising ABOVE the free cap needs a paid plan** (free → 403 beyond it; lowering is free on every plan). A new service is born AT its plan cap (free 4 vCPU / 4 GB, pro 8 / 8). Bare = read (prints the ceiling **and** the plan max). Setting **requires `--memory`** (`512mb`, `1gb` — decimal `mb/gb` and binary `Mi/Gi` suffixes both accepted); cpu derives from it, and `--cpu` is only an optional override for parallel workloads (never valid alone). Moves **both directions**: billing is actual usage, so the ceiling caps what the app may burn — it is not a price |
| `insta --agent db limits` [`--cpu <n>`] [`--memory <size>`] [`--branch <b>`] [`--group <g>`] [`--json`] | same ceiling control for a postgres service — any plan within the free cap, paid above it; both directions. A new postgres is also born AT its plan cap (free 4 vCPU / 4Gi, pro 8 / 8Gi); its volume is the free cap on every plan. Takes provider quantities (`--cpu 2` or `2500m`; `--memory 4Gi`); either flag alone works. Bare = read the current ceiling |
| `insta --agent compute volume [service]` [`--size <Gi>`] [`--delete`] [`--branch <b>`] [`--json`] | show, **attach**, grow, or **delete** a compute service's persistent `/data` volume. Bare = read (size, mount path, plan cap — any plan). `--size` on a volumeless service **attaches** one (any plan up to the default 10Gi, the free cap; mounts on the next deploy); on a volume-bearing one it grows — **paid plans, grow-only** (a provisioned disk cannot shrink). `--delete` **destroys the disk and ALL its data immediately** (any plan; irreversible; no detach exists — billing stops now, and suspend fast-wake + scale-out return; gated `service.remove`). See [Volumes](#volumes) |
| `insta --agent db volume` [`--size <Gi>`] [`--branch <b>`] [`--group <g>`] [`--json`] | show or grow a postgres service's provisioned volume (block disk). Bare = read (size + plan cap — any plan); `--size` grows it — **paid plans, grow-only**. Postgres has its volume by default — there is nothing to attach |
| `insta --agent storage list` [`--prefix <p>`] [`--cursor <c>`] [`--limit <n>`] [`--service <name>`] [`--branch <b>`] [`--json`] | list the objects in a storage service's bucket — one `size  modified  key` row each, in key order (S3 lists lexicographically). **Prefix filter only**: S3 has no substring search, so `--prefix` is applied **server-side** and there is nothing to match mid-key. Pagination is by cursor — the `nextCursor` a page prints is what `--cursor` takes; `--limit` is 1..1000 (default 100). `--service` picks one when the branch has several storage services (gated: `storage.read`) |
| `insta --agent storage get <key>` [`-o <file>`] [`--service <name>`] [`--branch <b>`] [`--json`] | download one object. The platform returns a **short-lived presigned URL** (~60s) and the bytes come **straight from the provider** — nothing streams through the control plane. Writes to the key's **last segment** by default (never a path, so no key can write outside cwd); `-o` names the file. `--json` prints `{url, expiresAt}` and downloads nothing (gated: `storage.read`) |
| `insta --agent storage delete <key>` [`--service <name>`] [`--branch <b>`] [`--json`] | delete one object — **irreversible**, and it runs immediately with no prompt (like every other destructive command here, the governance gate is the guard; a data operation stages nothing for a deploy). Deleting a key that is already gone still succeeds, so success is no proof it existed (gated: `storage.delete`, `allow` by default) |
| `insta --agent services upgrade <compute\|postgres> <name> <spec>` | **legacy** (pre-usage-billing): raise a named spec, up-only — **paid plans only**; gated: `service.upgrade`. Prefer `insta --agent compute limits` (and, for postgres, `insta --agent db limits`), which also lower. **Compute-only in practice**: a postgres `upgrade` is rejected outright (400) — resize a postgres service with `insta --agent db limits` (cpu/memory) and grow its disk with `insta --agent db volume` |
| `insta --agent branch create <name>` [`--from <parent>`] [`--json`] | isolated env: **forks the parent branch's current services** — a CoW database branch per postgres, a CoW-forked bucket per storage (snapshot-enabled projects), a clone of every compute service (re-running the parent's persisted image, if any) — then the two branches' service catalogs diverge independently (services are **branch-owned, not project-wide**). **≤10 branches/project.** Does NOT switch |
| `insta --agent branch switch <name>` [`--json`] · `insta --agent branch list` [`--json`] | set current branch / list |
| `insta --agent branch merge <source>` [`--into <target>`] [`--json`] | **structural** merge: creates on the target branch (default: current) every service present on `<source>` but missing there — fresh & **empty, no data copied**. Services the target already has are skipped (reason: `exists`\|`cap`\|`secret-collision`). Additive only — never deletes target services; idempotent |
| `insta --agent branch delete <name>` [`--json`] | tear down the branch's resources (gated: `branch.delete`) |
| `insta --agent secrets` [`--branch <name>`] [`--service <compute/name>`] [`-o <file>`] [`--print`] [`--json`] | secret seam → write the branch's secrets to `./.env` (gated: `secrets.read`). Carries user-defined project/branch secrets **plus the branch's canonical provider credentials** — one `DATABASE_URL` / `REDIS_URL` / `AWS_*` set from the **primary** service of each type (see **Provider credentials** below). **`--service <compute/name>` (CLI ≥ 0.0.65)** answers with **one compute service's own** env instead of the branch-wide merge: that service's user secrets, the unbound ones, its explicit bindings, and the same canonical credentials. Needed when several services define the same name — see **Same-name variables** below |
| `insta --agent secrets list` [`--branch <b>`] [`--json`] | secret names for the branch, **grouped by service** — each service's bound secrets, plus a branch-level "unbound" group and a project-wide group |
| `insta --agent secrets tree` [`--json`] | the whole project as `project → branch → service → secrets` (names only) |
| `insta --agent secrets set <NAME> [value] [--branch <b>] [--service <compute/name>] [--json]` | Set a user secret (project-wide by default; value from stdin if omitted). `--service` scopes it to that branch's compute service (e.g. `compute/api`) — binding **requires a branch** (defaults to the current branch when `--service` is given); omit `--service` for an unbound secret (as before) |
| `insta --agent secrets unset <NAME> [--branch <b>] [--service <compute/name>] [--json]` | Remove a user secret. **`--service` (CLI ≥ 0.0.65)** removes **only that service's copy**, leaving a sibling's same-name value alone; without it the original name-keyed delete removes every matching copy at the scope |
| `insta --agent secrets sources` [`--branch <b>`] [`--json`] | List provider credential sources available for explicit compute binding, e.g. `postgres/db: DATABASE_URL` or `redis/cache: REDIS_URL, ...` (names only; gated: `secrets.read`) |
| `insta --agent secrets bind <ENV_NAME> <source>` [`--source-name <name>`] `--to <compute/name>` [`--branch <b>`] [`--json`] | Bind one provider credential from `<source>` (`postgres/db`, `redis/cache`, `mysql/orders`, `mongodb/catalog`, `storage/assets`, …) into a compute service's runtime env var. `--source-name` is required when the source exposes multiple credential names. Takes effect on the next deploy — or immediately on a running service with `insta --agent compute restart` (CLI ≥ 0.0.51) (gated: `secrets.write`) |
| `insta --agent secrets bindings --target <compute/name>` [`--branch <b>`] [`--json`] | List provider credential bindings for one compute service (names only; gated: `secrets.read`) |
| `insta --agent run [--branch <b>] [--service <compute/name>] [--ignore-collisions] -- <cmd> [args…]` | run a command with the branch's secret bundle injected into **its environment only** — nothing written to disk, so there is no `.env` to leak, stale out or commit. The bundle lives exactly as long as the process. `--service` injects **one compute service's own** env (the unambiguous read). **On a collision it REFUSES (CLI ≥ 0.0.65): nothing is spawned and it exits 2.** Warning would not be enough — `run` spawns with `{...process.env, ...bundle}`, so a name the platform withheld would fall through to whatever your shell exported, and clearing it is not observable either since the child may hold its own default. `--ignore-collisions` runs anyway with every colliding name **removed** from the child env. No `--json` (its stdout belongs to the child; the banner and any collision report are on stderr) |
| `insta --agent secrets unbind <ENV_NAME> --from <compute/name>` [`--branch <b>`] [`--json`] | Remove one provider credential binding from a compute service; takes effect on the next deploy — or immediately on a running service with `insta --agent compute restart` (CLI ≥ 0.0.51) (gated: `secrets.write`) |
| `insta --agent build [dir]` [`--explain`] [`--port <n>`] [`--json`] | **verify before you deploy** — local, offline, deploys nothing, needs no login: prints the detection plan (builder, install/build/start commands, port **with the reason it was chosen**, `.env.example` keys), the Dockerfile (yours, or — **if nixpacks is installed**, never auto-installed — the one nixpacks would generate; `--explain` includes its content), and static checks each with a next action (missing Dockerfile/start command, port mismatch, `node_modules` shipping in the build context). **Verdict semantics (CLI ≥ 0.0.48): only a Dockerfile IN the directory can make a dir `deployable`.** A dir with no Dockerfile where nixpacks detects the app gets `builder: nixpacks` but its Dockerfile check is a ⚠ warning and the verdict stops at `needs-attention` (exit 0) — the command is local and cannot know which compute plane the target runs on, and the answer differs: an insta-compute service deploys such a dir as-is (the gateway runs nixpacks), a Fly-backed one refuses it. Read `needs-attention` as "depends on the target", not as "will fail". The nixpacks Dockerfile shown by `--explain` is **for inspection, not standalone** (it `COPY`s `.nixpacks/` support files the dir does not have) — do NOT save it as `Dockerfile`; use the detected install/start commands as the starting point for your own. Verdict `failed` (exit 1) = no Dockerfile and nixpacks missing/undetected, or no start command. For a Dockerfile-less dir that `failed` says only that nixpacks is not installed on THIS machine: an insta-compute target still deploys it, because the gateway runs nixpacks, so do not add a Dockerfile just to satisfy the local check. Run it before `insta --agent deploy <dir>` instead of finding out from a burned remote build |
| `insta --agent deploy <dir>` / `--image <url>` [`--branch <b>`] [`--group <g>`] [`--port <n>`] [`--replace-source`] [`--json`] | deploy to a compute service — a **source dir** (**whether it needs a `Dockerfile` depends on where the service runs**: on an insta-compute service one is *optional* — the CLI packs the directory, uploads it, and the build gateway builds it with nixpacks when there is no Dockerfile; on a Fly-backed service one is still *required*, and without it the command exits 1 naming the options: write a Dockerfile, `--image <url>`, or connect the repo to the service (`insta --agent compute connect-repo <owner/repo> [service]`). The CLI asks the platform which lane serves the target rather than guessing. A CLI that predates this lane answers `source builds are not supported on the insta-compute provider yet` for such a target: run `insta upgrade` and retry. Either way the build is remote — no local Docker; against a local insta-oss daemon the CLI builds with your local docker instead, same command) or a **prebuilt image**. Defaults to the branch's sole compute service; `--group` picks by name (gated: `deploy`). A service connected to a GitHub repo refuses a dir/image deploy (409) unless `--replace-source` is passed (admin): the image then replaces the repo connection. `--json` prints one `{image, machineId, url, branch, group, nextActions}` document on stdout — build progress moves to stderr so stdout stays parseable |
| `insta --agent template list` [`--json`] · `insta --agent template info <code>` [`--json`] | browse the platform **template registry**: one row per template (code / version / category / required-var count / deploy count / name — tagline), and the detail view — version, maintainer, source, upstream pin, a services summary (types, ports, volumes), and every required/optional variable with its description, generator or default |
| `insta --agent template deploy <code\|./dir\|github-url>` [`--branch <b>`] [`--set <NAME=value>`] [`-y`, `--yes`] [`--json`] | deploy a template's whole service set onto a branch (default: current) — a **registry code**, a **local directory** carrying `insta.template.yaml`, or a **github.com URL** (⚠️ **preview**, needs a recent CLI and `git` on `PATH` — see [Templates](#templates); `https://github.com/<owner>/<repo>`, `/tree/<ref>`, `/tree/<ref>/<dir>`, or a `/blob/…/insta.template.yaml` file link). A bare word is **always** a registry code; local mode needs a path-looking target (`./dir`, `/abs/dir`, `~/dir`, `sub/dir`), so a same-named directory in the working dir can never shadow a registry template. The GitHub form shallow-clones on **your machine** with **your** git credentials — private repositories work when git can already read them (`gh auth login` then `gh auth setup-git`) — reads the manifest from the named directory (never scanning the tree, never following a symlink out of the clone), deletes the clone, and sends the manifest inline. Missing required variables are prompted for on a terminal; `--yes` or no TTY fails with the exact `--set NAME=value` list instead. `secret:N`-generated and defaulted variables are resolved **by the platform** — generated secrets never transit. Renders the 4-step pipeline (create services → write variables → deploy → health check), then the per-service URLs; `--json` replaces all of that with one document, which in GitHub mode carries a leading `source: {repo, ref, path, commit}` where `commit` is the commit that was checked out. May come back `approval_required` (hint on stderr, envelope on stdout with `--json`, **exit 2** — as every gated command). See [Templates](#templates) |
| `insta --agent compute set-domain <host>` / `check-domain <host>` / `remove-domain <host>` [`--branch --group --json`] | attach / check / detach a **developer-owned custom domain** on a compute service — Fly issues the cert + routes; prints the DNS records to set in **your own** registrar (set/remove gated: `deploy`) |
| `insta --agent domain search <keyword>` [`--tlds com,dev`] [`--org <id>`] [`--json`] | **buy a domain THROUGH InstaCloud** (distinct from the BYO row above): purchasable names with the price you pay and the yearly renewal. A label (`myapp`) covers every sellable TLD; a full name (`myapp.com`) is guaranteed in the answer when its own TLD is sellable — the registrar's search alone can omit it. The sellable list is per deployment: a TLD it does not sell is simply **absent** from the answer (`unavailable` means the registrar says the name is taken), and a request whose TLDs are all unsellable is a 400 naming what is sold |
| `insta --agent domain buy <name>` [`--years n`] [`--branch --group`] [`--contact-file c.json`] [`--no-open`] [`--json`] | order it. Answers a **Stripe Checkout URL a human must open** — nothing is registered until they pay, and registrations are **non-refundable**, so relay the URL and stop. Gated: `domain.purchase` — **`full_access`, which a new project starts on, allows it outright**; `branch_developer` answers `approval_required` (202 + exit 2, see [Approval relay](SKILL.md#approval-relay-critical--gated-actions)); `read_only` refuses. Paying the Checkout link needs a human either way. Needs a registrant contact: the org default (`domain contact set`) or `--contact-file`. Some registries take fixed terms (`.ai` is 2-year only) — a term they refuse is a 400 **before** any payment. **Pass `--no-open`**: by default this spawns the host's browser at the Checkout link, which on an agent's machine opens a window nobody is watching — you want the URL printed so you can relay it |
| `insta --agent domain status <name>` · `insta --agent domain list` [`--json`] | after payment the platform registers the name, publishes the DNS in the registrar zone it controls, and attaches it to the compute service as `<name>` **and** `www.<name>` — no records for you to set. Poll `status`: the order runs `pending_payment` → `paid` → `registering` → `registered` → `attaching` → `active`, and each hostname runs `pending` → `attached` → `active` (`failed` carries the reason, e.g. the name is already attached to another service). Minutes, not seconds |
| `insta --agent domain attach <name>` [`--branch --group`] [`--json`] | a bought domain whose compute service was deleted goes `detached` (the registration stands, nothing routes) — this binds it to another compute service. Gated: `deploy` |
| `insta --agent domain contact` [`--org`] [`--json`] | read the org's default **registrant contact** — the legal owner of every domain bought with it |
| `insta domain contact set` [flags \| `--contact-file c.json`] [`--org`] | **no `--agent`, ever**: this org-level write is unclassified for agents, so the agent form is refused `403 unclassified_agent_action` under any policy, full access included. Relay this exact line to a human **admin** and wait. `--company-name` makes that organization the registrant instead of the person (ICANN). An agent that has been given contact details can instead pass them per purchase with `domain buy --contact-file` |
| `insta --agent compute start\|stop\|suspend [service]` · `insta --agent compute status [service]` [`--json`] | control a compute service's lifecycle — **persistent override** of auto scale-to-zero: `stop`/`suspend` take it offline and traffic will **not** wake it until `start`; `status` shows desired vs. live state. All plans; ungated. `[service]` defaults to the project's sole compute service |
| `insta --agent compute restart [service]` [`--branch <b>`] [`--json`] | **(CLI ≥ 0.0.51)** **re-run the image reference the service already runs**, against a freshly resolved env bundle — it asks for no new version and no new spec, though it does **not pin a digest**: a service recorded against a moving tag (`app:latest`) gets whatever that tag resolves to now (source deploys record a unique label and are unaffected). The two reasons to use it: a secret/binding changed and the running app hasn't picked it up (env is baked into the machine at deploy time), or the machine is up but **wedged** (`start` no-ops on a machine that is already `started`). The service must be **running**: a deliberately stopped/suspended one 400s and points at `insta --agent compute start`. A never-deployed service 400s like `exec` does. **A running machine is health-gated coming back up** — if the app doesn't answer on its port the machines are rolled back (best-effort) to the config they were serving and the failure is reported (that verdict means the app is broken, not the platform). Whether an **idle machine (a scale-to-zero service between requests) is woken and gated at all depends on the compute plane** (`insta --agent manifest --json` names it per compute row — `fly`, `microvm`, or a neutral `compute` when the platform reported none) — the Fly-backed one hands it the new config without waking, so the command returns fast, bills no uptime, and proves nothing about whether the app boots. Send it a request if you need that proof; see [operate.md](references/operate.md). All plans; **gated: `deploy`** — it lands configuration the way a deploy does, so a policy denying deploys denies this too; `start`/`stop` stay ungated and cycle a wedged machine without one. Refused while the org is billing-suspended; any machine it wakes bills as ordinary uptime, an idle one it leaves asleep costs nothing. WebSocket concurrency **is** re-asserted (it is recorded on the service), so a socket app does not need a redeploy to stay one |
| `insta --agent compute exec [service] -- <command> [args...]` [`--branch <b>`] [`--timeout <sec>`] [`--json`] | run a **one-shot** command on the service's live machine — no interactive shell, no stdin. Wakes a scaled-to-zero machine first (the wake counts as billed uptime). `--timeout` bounds the run, **1–180s** (default 30). The CLI's **exit code is the remote command's exit code** — safe for scripts/agents to branch on. stdout/stderr stream to their own local streams verbatim, each capped at **1 MiB** (truncation noted on stderr); `--json` returns the raw response instead of split streams. Gated on **both** `deploy` and `secrets.read` — a deny on either is a 403. A service with no image ever deployed 400s: "this service has no machines yet — deploy an image first, then retry" |
| `insta --agent compute always-on on\|off [service]` [`--branch --json`] | idle-mode dial: `on` = machines never scale to zero (no cold starts; idle RAM bills at actual usage), `off` = scale-to-zero (idle costs ~nothing, first request cold-starts). New compute services are born `on` since 2026-09-07. All plans; billing is actual usage either way |
| `insta --agent compute repo [service]` [`--branch <b>`] [`--json`] | show what a compute service deploys from: the image it runs, or the GitHub repository — `owner/repo`, the branch it builds, root directory, which repo-root paths a push must change to redeploy it (`insta --agent compute watch-paths`), and whether pushes redeploy it at all (never for a public repo). `[service]` defaults to the branch's sole compute service. Cloud-only (insta-oss 501s) |
| `insta --agent compute connect-repo <owner/repo> [service]` [`--public`] [`--root-dir <dir>`] [`--repo-branch <name>`] [`--no-auto-deploy`] [`--watch-paths <patterns>`] [`--port <n>`] [`--branch <b>`] [`--json`] | connect a GitHub repository to an **existing** compute service: the repo is built (its Dockerfile, or nixpacks when there is none) and deployed **into that service**, and every later push to the tracked branch redeploys it. `<owner/repo>` also accepts a github.com URL. The repo must be reachable through the org's **GitHub App installation** — connect GitHub once in the console (Add Service → GitHub Repo → Connect GitHub); no CLI path installs the App — or be public (`--public`: deploys are manual, pushes cannot redeploy). **Build and start commands come from detection and cannot be set**; `--root-dir` picks the directory in a monorepo with several deployable ones (the command lists them and exits 1 otherwise); `--repo-branch` picks the repository branch to build (default: the repo's default branch) — detection scans that branch; `--no-auto-deploy` stops pushes redeploying (redeploy by connecting again or from the console); `--watch-paths` narrows which pushes redeploy it (same patterns as `insta --agent compute watch-paths`); `--port` overrides the detected listen port. Connecting again **replaces** the service's current source. `--branch` is the InstaCloud environment the service is on. Gated: `deploy`; needs admin. Cloud-only (insta-oss 501s) |
| `insta --agent compute watch-paths [service]` [`--set <patterns>`] [`--clear`] [`--branch <b>`] [`--json`] | show or change which paths make a push redeploy a compute service. No flag prints them — an ordinary member read (gated `service.read`). `--set` takes a **comma-separated** list of gitignore patterns — quote them, or the shell expands the `*` — matched against paths **relative to the repository root, not to the service's root directory**: a monorepo push that touched nothing on the list leaves this service alone. A leading `!` excludes, under git's own rule that a path cannot be re-included once an earlier pattern took its directory (so "everything but one tree" is `'**,!docs,!docs/**'`, not `'**,!docs/**'`). **Two shapes are a 400**, and they are the natural first attempts: a list of *only* exclusions (`'!docs/**'` — nothing is watched until a pattern includes something), and `{}` braces (`'src/**/*.{ts,tsx}'` — gitignore has no brace expansion, so write one pattern per alternative). `--clear` removes the filter: every push that deploys this service deploys it again. Both writes are gated `deploy` and need admin; neither rebuilds the service — this changes which pushes deploy, not what a deploy builds. **Fails open**: when GitHub cannot report what a push changed (a force-push, or a comparison of **300 or more** files, which is where its list stops being complete) every tracked service deploys, rather than risk skipping a real change. Cloud-only (insta-oss 501s) |
| `insta --agent compute disconnect-repo [service]` [`--branch <b>`] [`--json`] | disconnect the GitHub repository from a compute service — it keeps running its current image, pushes no longer deploy it, its build history stays. Run it before an `insta --agent deploy` onto that service, or pass `--replace-source` there: a dir/image deploy onto a repo-connected service is otherwise refused (409). Gated: `deploy`; needs admin. Cloud-only (insta-oss 501s) |
| `insta --agent db always-on on\|off` [`--branch --group --json`] | same dial for a postgres service: `off` (default) suspends the idle instance — first connection after idle cold-starts; `on` keeps it warm |
| `insta --agent manifest` [`--json`] | agent-legible env view: each branch's db / storage / compute + URLs. Database resources carry `ref.pgVersion` (`--json`; the Postgres major, root and branch rows alike) and **(CLI ≥ 0.0.57)** a `pg 16` badge on the printed line |
| `insta --agent metrics <db\|compute\|redis\|mysql\|mongodb>` [`group`] [`--branch --from --to --step --json`] | service metrics (compute + managed DBs=Fly, full; db=provider-limited) |
| `insta --agent logs <db\|compute\|redis\|mysql\|mongodb>` [`group`] [`--branch --limit --region --instance --deploy --json`] [`--from <t>`] [`--to <t>`] [`--since <dur>`] | logs (compute + managed DBs=Fly; db=provider-limited). **Without a window, one recent provider page (~100 lines) comes back regardless of `--limit`** (the provider cursor only pages forward) — the answer says so in a `note` when cut. `--from`/`--to` (unix seconds or ISO-8601) or `--since` (`90s`/`30m`/`2h`/`1d`) page a time window (~7-day retention, up to 5000 lines). `--deploy` shows **deploy events** (Fly machine lifecycle: created/started/…) instead of runtime logs — any Fly-backed target, not db; window flags don't apply to it |
| `insta --agent usage` [`--from --to --json`] | usage aggregated by meter, with `costUsd` (snapshotted at collection) |
| `insta --agent billing` [`--org <id>`] [`--json`] | current cycle summary: tier / **included usage** / used / overage / **credits** / forecast / status. The last two are separate figures and must never be added: `included usage` is the plan's allowance for this cycle and feeds the **usage** calculation; `credits` is the org's wallet balance and feeds the **amount payable** (it can pay the subscription fee as well as usage beyond the allowance). A `creditsUsd` field still on the JSON wire sums the two — it is legacy, means neither thing, and should not be read |
| `insta --agent billing upgrade <pro\|team>` · `insta --agent billing portal` [`--org`] [`--no-open`] [`--json`] | Stripe Checkout to subscribe / Customer Portal to manage (opens a browser; `--no-open` prints the URL) |
| `insta --agent events` [`--branch <b>`] [`--limit <n>`] [`--json`] | audit + agent-event timeline |
| `insta --agent approvals list` [`--status`] [`--json`] · `insta approvals approve <id>` [`--json`] · `insta approvals deny <id>` [`--json`] | manage gated actions |
| `insta --agent observe install` · `report` [`--json`] · `sync` | local credential-audit hook (see below) |
| `insta --agent feedback --type <bug\|feature-request\|friction\|other> --component <cli\|mcp\|platform\|skills\|docs\|other> --title <t> --detail <d>` [`--file <path>`] [`--area <a>`] [`--command <c>`] [`--error <e>`] [`--expected <x>`] [`--workaround <w>`] [`--doc <ref>`] [`--severity <blocker\|major\|minor>`] [`--json`] | report an **InstaCloud-side** hurdle to the team (see [Feedback](#feedback)) — never for the user's own app. Works logged-out/unlinked/oss; ungated. Non-TTY with missing flags errors (never prompts); transport failures **exit 0** — continue the task, don't retry |
| `insta --agent upgrade` · `insta --agent autoupdate [on\|off]` | self-update the CLI (binary re-runs the installer; npm uses `npm i -g`). Auto-update is **on by default** pre-1.0; `autoupdate off` / `INSTA_NO_AUTOUPDATE=1` disables. (CLI ≥ 0.0.5) |
| `insta --agent setup agent` [`--env <prod\|staging>`] [`--mcp-token`] [`--project <id>`] [`--create [name]`] | one-step agent onboarding: **self-installs the CLI globally first** when running from the npx cache with no durable `insta` on PATH (`npm i -g insta@<running version>`; best-effort — a failed install prints the manual fallback and setup continues; CLI ≥ 0.0.37), making `npx -y insta@latest --agent setup agent` a complete cross-platform one-liner (bash / zsh / PowerShell / cmd); then installs the insta skill user-globally for every coding agent, then registers the **remote MCP server** — Claude Code via `claude mcp add` (user scope) plus a config-file entry for every other detected MCP-capable agent. Default = **OAuth**, no credential written (browser auth on first `/mcp` use); `--mcp-token` requests a durable `insta_` token named `mcp-<hostname>` (Claude Code only; requires login **and token-creation permission**, not a login bypass). Signed agents currently receive `403 unclassified_agent_action` when minting; report it and stop this registration attempt, never retry as human. Incomplete token registration exits nonzero; CLI 0.0.66 and earlier can incorrectly print a login hint and exit 0. Existing registrations are left unchanged, not converted to token auth. Idempotent; `INSTA_MCP_URL` / `INSTA_SKILLS_REPO` override the URL / skill source. **Environment (CLI ≥ 0.0.38): bare `setup agent` always targets prod** — a machine previously switched to staging is switched back (persisted via the `env use` path, foreign session dropped, announced). Staging is the explicit form `--env staging` (also persists the switch); `$INSTA_ENV` counts as explicit; a deliberate custom host (`$INSTA_API_URL`, or a persisted custom apiUrl) is left alone unless `--env` is given. The skill source, the MCP host and its registration name all resolve from that one environment, so a staging setup installs `InsForge/insta-skills#devel` and registers `insta-cloud-staging` → `mcp.staging.instacloud.com` (both environments can coexist on one machine). Ends with a status-aware `next:` hint (login / project create / the prompt.md fetch prompt). **`--project <id>` (CLI ≥ 0.0.48) also links the working directory to that project** after setup — same code path as `insta --agent project link <id>` (writes `./.insta/project.json`, installs per-project stack skills + the observe hook), flowing through the interactive login offer first when there's no session. With no session available (declined login, `-y`, non-TTY) the link is skipped with the manual `insta --agent login` + `insta --agent project link` hint (exit 0); a failed link (bad id / no access) exits 1. This is the flag behind the console Connect panel's single-line CLI setup. **`--create [name]` (CLI ≥ 0.0.52) instead creates a NEW project** and links it — same code path as `insta --agent project create`, with the same login flow, skip-with-hint and exit-1-on-failure behaviour as `--project`; the name is optional and resolves exactly as that command's does — a directory with no usable name (`~`, `~/projects`, `/tmp`) gets that command's guidance and no project, not an error. `--create` and `--project` are mutually exclusive, rejected before anything is installed. See [mcp.md](references/mcp.md) and [Environments](#environments) |
| `insta --agent mcp install` [`--agent <claude-code\|cursor\|codex\|opencode\|copilot\|factory-droid>`] [`--mcp-token`] | register the remote MCP server only (no skill install) — default: Claude Code + all detected agents; `--agent` targets one. `--mcp-token` applies only to Claude Code and is rejected with another explicit client; token-creation permission is required (see [MCP authentication](references/mcp.md#connecting)). Failed Claude registration exits nonzero and stops further client registration. Config merges never clobber existing entries; restart the tool afterwards and verify authentication with a tool call |

**`--json` contract (CLI ≥ 0.0.37):** every mutating command an agent chains from takes `--json` —
one JSON document on stdout, progress/diagnostics on stderr, so `$(insta --agent … --json)` always parses.
Deliberate exceptions: `insta --agent run` has no `--json` (its stdout belongs to the child command — its
"injected secrets" banner is on stderr); `insta --agent setup agent` and `insta --agent upgrade` don't have it yet
(their stdout is a live installer stream).

**Approval gate exit code (CLI ≥ 0.0.37):** when a gated command returns `approval_required`, the
hint prints to **stderr** and the CLI **exits 2** — distinct from 1 (error), so scripts/agents can
branch on "approvable: have an admin `insta approvals approve <id>`, then re-run". Previously this
printed to stdout and exited 0, which read as success in pipelines.

**Exit 2 is not only approvals (CLI ≥ 0.0.65).** `insta --agent run` reuses it to refuse on a
same-name collision, for the same reason — nothing ran, and it is re-runnable once the caller
chooses. So do **not** read exit 2 as "ask an admin to approve": read the stderr message. An
approval names an id to approve; a collision names the services that define the variable and the
two ways through (`--service`, `--ignore-collisions`).

Provider-minted credentials are **per-branch and per-service**. They live under the service that
created them with canonical names (`DATABASE_URL`, `REDIS_URL`, `MYSQL_URL`, `MONGODB_URL`,
`AWS_ACCESS_KEY_ID`, `BUCKET_NAME`, …).

Two destinations, opposite defaults — do not conflate them:

- **The local-dev seam** (`insta --agent secrets` → `.env`, and `insta --agent run`) **does** carry
  them: one set per credential-minting service type, from that type's **primary** service on the
  branch. So a `.env` has a working `DATABASE_URL` as soon as the branch has a postgres. A
  non-primary same-type service is not in the bundle. **Postgres** has a direct read for it,
  `insta --agent db url --group <name>`; **no other type does** — bind it, or read the env of a
  compute service it is bound to with `insta --agent secrets --service compute/<name>`.
- **A compute deployment does not.** A container receives a provider credential **only** through an
  explicit binding. Decide what each service should get:

```bash
insta --agent secrets sources
insta --agent secrets bind DATABASE_URL postgres/db --to compute/app
insta --agent secrets bind REDIS_URL redis/cache --source-name REDIS_URL --to compute/app
insta --agent secrets bindings --target compute/app
insta --agent deploy . --group app --port 8080
```

**Same-name variables across services (CLI ≥ 0.0.65).** Per-service env is allowed, so two compute
services on one branch may each hold their own `ADMIN_PASSWORD`. **A template deployed twice into
the same branch produces exactly this** — the second deploy builds an independent copy (`app`,
`app-2`) with its own generated variables under the same names, and re-deploying is the only way to
update a template. A `.env` file and a process environment are flat `name=value` maps, so they
cannot hold two values for one name:

```bash
insta --agent secrets                     # colliding names are OMITTED, and named on stderr
insta --agent secrets --service compute/hermes   # hermes' own values — the unambiguous read
insta --agent run --service compute/hermes -- npm run dev
```

`insta --agent secrets list` and `secrets tree` have always been accurate here — they group names by
service. It is only the **value** reads that cannot answer such a name, and they now say so instead
of picking one: the platform reports every colliding name with the services that define it, the CLI
prints that to **stderr**, and `insta --agent run` refuses outright rather than injecting a value it
cannot attribute. `--json` stdout is unchanged (still the bare `{NAME: value}` map); the collision
report rides stderr as one JSON line.

If a source exposes exactly one credential (`postgres` → `DATABASE_URL`), `--source-name` is
optional. If it exposes several (`storage`, `redis`, `mysql`, `mongodb`), pass the source credential
name to bind. Binding overwrites the target env var's previous binding; an env name that collides
with a user secret visible to the same compute service is rejected (409). Binding itself does not
expose plaintext. Two reads do: `insta --agent secrets` / `insta --agent run`, which carry each
type's **primary** service credentials, and `insta --agent db url` / `insta --agent db connect` for a
**specific** postgres DSN (both gated `secrets.read`). What binding decides is what a **compute
service** receives — a non-primary same-type service's credentials reach code only that way, or
through `insta --agent compute exec` on the machine itself.
Changes apply on the next deploy — **or on `insta --agent compute restart`** (CLI ≥ 0.0.51), which re-runs
the image reference the service already runs against a freshly resolved bundle. There is still no hot reload:
either way the machine takes a new config and restarts on it, in place (the machine id survives). An
idle machine may take the config without waking — see the `insta --agent compute restart` row and
[operate.md](references/operate.md). A project may have **multiple services of every type**, up to
`INSTA_MAX_SERVICES_PER_TYPE` (default 5) per type.

`insta --agent secrets set <NAME>` / `unset <NAME>` manage **user-defined** secrets. A user secret cannot
collide with a provider credential binding visible to the same compute service. Gated:
`secrets.write`. Changes apply on the next
`insta --agent secrets` fetch, the next deploy, or an `insta --agent compute restart` (CLI ≥ 0.0.51) — no hot reload either way. `--service` on `secrets set` scopes a
user-defined secret to a branch compute service; it is separate from provider credential binding
(`secrets bind`). `secrets list`, `secrets tree`, `services secrets`, `secrets sources`, and
`secrets bindings` are all **names only**.

## Volumes

A **volume** is a service's persistent block disk — always a **service attribute**, never a
standalone resource (nothing to create or list separately; it lives and dies with its service):

- **postgres** has one by default — view/grow only: `insta --agent db volume` [`--size <Gi>`].
- **compute** opts in at creation (`insta --agent services add compute <name> --volume <gi>`) **or any
  time later** (`insta --agent compute volume <name> --size <gi>` on a volumeless service attaches one;
  the disk mounts on the **next deploy**). Fixed mount path **`/data`** (survives deploys and
  restarts). Constraints: machine count stays **1** (scale to 1 before attaching), idle
  scale-to-zero uses **stop** (cold wake) instead of suspend, and a volume **never detaches** —
  but it **can be deleted** (`insta --agent compute volume <name> --delete`): the disk and **all its
  data** are destroyed immediately (irreversible — download anything you need first), billing
  stops, and both constraints lift. View/grow/delete: `insta --agent compute volume` [`--size <Gi>`]
  [`--delete`].
- **Any plan may attach up to the default 10Gi** (the free cap — the platform's sizeless default on every plan, insta-platform #327, kept by #378); viewing is every plan. Only **growth is paid** and
  plan-capped — don't pre-check the plan, just run the command: the backend's 403 carries the
  upgrade hint. **Grow-only** — a provisioned disk cannot shrink.
- Billing is **actual data stored**; the size is a cap, not a price.

## Environments

`prod` and `staging` are **separate deployments** — different regions, databases, and auth. A
session minted by one can never authenticate against the other, so `insta --agent env use` drops the stored
session and you log in again. Default is `prod`; nothing changes unless you switch.

| | `prod` (default) | `staging` |
|---|---|---|
| control plane | `api.instacloud.com` (us-east-2) | `api.staging.instacloud.com` (us-west-1) |
| MCP server | `mcp.instacloud.com/mcp` | `mcp.staging.instacloud.com/mcp` |
| registers as | `insta-cloud` | `insta-cloud-staging` |
| agent skills | `InsForge/insta-skills` | `InsForge/insta-skills#devel` |
| CLI channel | latest stable release | newest prerelease (`v*-rc.N`), else stable |

Install one-liners — each installs a complete stack for its environment (control plane, MCP
registration, and skill text all match). The npx form works on **every OS and shell** (Node 18+;
CLI ≥ 0.0.37 self-installs globally); the curl form is the no-Node native-binary path for
macOS/Linux only — **never run it on native Windows**, where PowerShell's `curl` alias and the WSL
`bash` shim break it:

```bash
npx -y insta@latest --agent setup agent                         # production (any OS — ALWAYS prod, CLI >= 0.0.38)
npx -y insta@latest --agent setup agent --env staging           # staging (any OS; persists the env switch)
npx -y insta@latest --agent setup agent --project <id>          # + link this directory to a project (CLI >= 0.0.48; the console Connect panel's one-liner)
npx -y insta@latest --agent setup agent --create [name]         # + create a NEW project (CLI >= 0.0.52; name defaults to this directory)
curl -fsSL agents.instacloud.com | sh            # production (macOS/Linux, no Node needed)
curl -fsSL agents.staging.instacloud.com | sh    # staging
```

Staging via npx is the `--env staging` one-liner above (CLI ≥ 0.0.38) — it persists the env switch
itself, so no separate `insta --agent env use staging` is needed (and a bare `setup agent` afterwards would
switch the machine back to prod, by design). The npm route always installs the **stable** CLI
build; staging's prerelease channel is the curl installer's concern (npm's `next` tag can lag
behind `latest`, so `insta@next` is only for deliberately testing a prerelease newer than stable).

> **`agents.staging.instacloud.com` is not live yet** (its DNS/CloudFront ships separately). Until
> it resolves, use the raw URL, which is exactly what the short host will serve:
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/InsForge/insta-cli/main/install.sh | sh -s -- --agents --staging -y
> ```
>
> If the environment cannot be applied (a CLI older than `insta --agent env`), the installer **fails with a
> non-zero exit** rather than silently leaving you on production.

```bash
insta --agent env                      # current environment + its hosts
insta --agent env use staging          # switch; persisted to ~/.insta/config.json
insta --agent login --env staging      # or --email/--oauth as usual
```

Control plane, MCP host **and** skill source are resolved **together** from one switch, so this
machine's CLI and its agents can never end up on different environments — including the case where
the CLI talks to staging while the agent reads prod's skill text.

Resolution order, most specific first:

1. `INSTA_API_URL` — a literal URL; the only way to reach a host no environment name covers
   (`insta-oss` on localhost, a preview deployment). `INSTA_MCP_URL` and `INSTA_SKILLS_REPO` do the
   same for the MCP host and the skill source.
2. `INSTA_ENV` — `prod` | `staging`. An unrecognised value is an **error**, never a silent fallback
   to prod.
3. the persisted `apiUrl` in `~/.insta/config.json`.
4. `prod`.

Prereleases never take the `latest` GitHub release or npm's `latest` dist-tag (they ship
`--prerelease` and under npm `next`), so a staging CLI build can't reach production installers.

**Agents:** don't switch environments as a debugging step. If a command fails, check `insta --agent env`
first — targeting staging when the user meant prod (or vice versa) produces confusing "project not
found" errors, because the two have entirely separate project lists.

## Deploy

```
insta --agent build ./app --port <n>               # first: verify — `deployable` with a Dockerfile IN ./app; `needs-attention`/`failed` without one means "depends on the target", not "will fail"
insta --agent deploy ./app --port <n>              # build ./app remotely, push, deploy — the CLI asks the platform which lane serves the target
#   on an insta-compute service: a Dockerfile is OPTIONAL — the dir is packed and uploaded, the build gateway builds it
#     (its Dockerfile, or nixpacks when there is none), one gated call enqueues build+deploy, the CLI polls to live. No `fly` CLI.
#   on a Fly-backed service: a Dockerfile is REQUIRED — no Dockerfile → exits 1 naming the options (write one, --image, or
#     `insta --agent compute connect-repo <owner/repo>`); the build runs on Fly's remote builder via a short-lived deploy token
#     minted by the platform (needs the `fly` CLI, auto-installed via Homebrew on macOS, NO Fly login).
#   a CLI that predates the insta-compute lane answers "source builds are not supported on the insta-compute provider yet":
#     `insta upgrade`, then retry.
insta --agent deploy --image <url> --port <n>      # or deploy a pre-built / already-pushed image
# targets the CURRENT branch's sole compute service (or --group <name> when there are several);
# --branch targets another branch; the URL prints on success.
```

`--port` must match the port the image actually listens on (`ENV PORT` / `EXPOSE` / server bind) — a
mismatch boots fine but every request fails with `instance refused connection on 0.0.0.0:<port>`.
At deploy, compute receives `PORT`, user-defined secrets visible to that compute service, and
provider credentials you explicitly bound with `insta --agent secrets bind`. It does **not** receive every
platform credential by default. Read env vars from `process.env` in production; **never bake
`./.env` into the image**. A compute service serves one app on one port at `https://<app>.fly.dev`.

**Two domain paths, and they are not interchangeable.** You already own the name →
`insta --agent compute set-domain app.example.com` attaches it to a branch's compute service and prints
the DNS records to add **at your registrar** (a `CNAME` for a subdomain, `A`/`AAAA` for an apex, plus a
validation record). The cert + routing are handled for you; `insta --agent compute check-domain <host>`
shows status once DNS propagates. The DNS lives in your zone — you set it, not InstaCloud.

You want to **buy** one → `insta --agent domain search`/`buy`. InstaCloud is the reseller and you are
the registrant, so it owns the zone: after payment it publishes the records itself and attaches the
apex plus `www` with nothing for you to set. `buy` answers a Stripe Checkout URL — **a human must
pay**; an agent's job is to relay that URL and then poll `insta --agent domain status <name>`.

> Multiple services of every type (postgres/storage/compute, up to 5 each), `insta --agent services
> scale`/`upgrade`, and **source-directory deploy** (`insta --agent deploy <dir>` → remote build, no local Docker: the build gateway
> with the dir's Dockerfile or nixpacks on insta-compute, Fly's remote builder of the dir's own Dockerfile on Fly-backed compute) are
> all implemented.

## Dockerfile templates

Moved to [references/deploy.md](references/deploy.md) (backend / full-stack / SPA patterns).

## Templates

A **template** is a whole service set (images, ports, volumes, env) published as one unit —
`insta --agent template deploy <code>` creates those services on a branch, writes their variables, deploys
and health-checks them, instead of a hand-rolled `services add` + `secrets set` + `deploy` sequence.

- **Three modes, chosen by the target.** A bare word (`plausible`) is **always** a registry code. A
  path-looking target (`./plausible`, `/srv/tpl`, `~/tpl`, `sub/dir`) is **always** a local directory and must
  contain `insta.template.yaml` (validated locally, then sent inline). A `github.com` URL fetches
  that file from the repository with your own git credentials and sends it the same way. So a local
  directory never shadows a registry template — `./` is how you opt into the local one.
- **GitHub URLs** (⚠️ **preview**, see the note below). `insta --agent template deploy https://github.com/<owner>/<repo>/tree/<ref>/<dir>` reads
  `insta.template.yaml` from exactly that directory (the repository root when the URL names none),
  and a `/blob/…/insta.template.yaml` link works too. The clone happens on your machine and is
  deleted before the deploy starts, so private repositories need no InstaCloud GitHub
  authorization — only git credentials that can already read them (`gh auth login`, then
  `gh auth setup-git`). A URL for any other host is refused by name, not mistaken for a directory.
  The manifest's images must still be **public**: the platform pulls anonymously.

  > ⚠️ **Preview — the GitHub URL target only.** Registry codes and local directories are
  > unaffected. Two things make it unavailable, and both fail in ways worth recognising.
  > **A CLI without it:** an older `insta` has no URL mode, so it resolves the URL as a *directory*
  > and reports `no insta.template.yaml at <cwd>/https:/github.com/…` — a local path carrying
  > `https:/` with a single slash is the tell, not a missing file. `insta --agent upgrade` fixes it.
  > **No `git` on `PATH`:** the fetch shells out to git and says so (`git is required to deploy a
  > template from a GitHub URL`); install git, or clone the repository yourself and deploy the
  > directory. The contract may also still move — which scheme-less hosts count as addresses, and
  > whether a commit SHA may stand in for a ref, are both open.
- **Variables.** `--set NAME=value` (repeatable) answers them up front. Required variables with no
  answer are prompted for on a terminal; with `--yes` or no TTY the command fails listing exactly
  what to pass. Variables carrying a `secret:N` generator or a default are resolved **by the
  platform** — generated secrets never leave it.
- **Outcomes.** `succeeded` prints each service's URL — then run `insta --agent secrets` to refresh `./.env`.
  `partial` is **terminal**: the healthy services stay up and the created resources are kept, so read
  the log tail, then re-run the deploy to retry or `insta --agent services remove <type> <name>` to clean up.

### Writing `insta.template.yaml`

Any repository can carry one, public or private, and `insta --agent template deploy <dir|github-url>`
deploys it without publishing anything. A complete minimal manifest:

```yaml
code: my-app                    # a-z 0-9 -, ≤39 chars; becomes the service/branch name prefix
version: "1.0"                  # your own; bump it when the manifest changes
services:
  db:                           # a managed postgres: declare it BARE and the platform owns it
    type: postgres              # no image, port, volume or env — anything else here is refused
  web:                          # the key is the service name
    type: web
    image: ghcr.io/me/my-app:1.4.0   # MUST be publicly pullable, and MUST be pinned
    port: 8080
    healthcheck: /healthz       # required on a web service; an absolute path that returns 2xx
    volume: true                # optional: mounts a persistent disk at /data
    env:
      platform:                 # credentials the platform mints, wired in at deploy time
        DATABASE_URL: ${{services.db.DATABASE_URL}}
      fixed:
        DATA_DIR: /data         # baked in, the deployer never sees or sets it
      required:
        ADMIN_PASSWORD:
          description: Shown at the prompt, so write it for whoever deploys this
      optional:
        SMTP_HOST: One-line description, the shorthand for a var with no other keys
```

**`env.platform` is how a managed service reaches the app, and a template with a database needs
it.** The value is a reference, `${{services.<service>.<KEY>}}`, naming another service in this
same manifest and the credential key it mints (a postgres service mints `DATABASE_URL`). The
platform resolves it while writing variables, before the app starts.

Do not plan to run `insta --agent secrets bind` afterwards instead: `template deploy` creates the services
and immediately deploys and health-checks the web one, so an app that needs `DATABASE_URL` would
start without it and fail the gate. Binding after the fact then needs a redeploy, which defeats
the point of shipping the service set as one unit.

Generated secrets are declared once and referenced, so the value never leaves the platform:

```yaml
generated:
  session-key: secret:32        # secret:N is the only generator family, N = 1..999
services:
  web:
    env:
      generated:
        SESSION_SECRET: ${session-key}
```

Other optional top-level keys: `maintainer`, `sourceRepo`, `upstream` (what you packaged and its
pin), `constraints` (`oneOf` / `allOf` over variable names, for variables that only make sense
together), and `meta` (`name`, `tagline`, `category`, `tags`) which only the registry renders.

**Four rules that are easy to get wrong, and where you find out:**

| Rule | Where it bites |
|---|---|
| The image must be **publicly pullable**. A private repository is fine, a private image is not: the platform pulls anonymously, with no credential field anywhere. | Not at validation. The deploy creates services, then the machine fails to pull and the health gate fails. GHCR package visibility is separate from repository visibility, so a private repo can publish a public package. |
| Use `image:`, never `build:`. The platform does not build from source for template deploys. Push the image yourself first. | Server-side, immediately: `services.<name> uses build: — server-side template deploys support image services only`. |
| Deployable types are `web` and `postgres`. `worker` parses locally but the platform refuses it in v1. | **Local validation passes**, then the server rejects it: `services.<name> is a worker — server-side template deploys support web services only in v1`. |
| A `postgres` service must be **bare** (`{ type: postgres }`) and needs **CLI ≥ 0.0.62**. Older CLIs reject it locally, `services.<name>.type must be web or worker`, even though the platform accepts it. | Locally on an old CLI, which is why the error names a type the platform does in fact take. `insta --agent upgrade`. |

Validate before you push by deploying the directory: `insta --agent template deploy ./my-template -y`
reports manifest problems first, so getting past them to the `--set` list (or, for a manifest with
no unset required variables, to the deploy itself) means it parsed and validated. That covers
structure, pinned images (`:latest` and tagless are rejected) and described variables. It does
**not** cover the first three rows above, which pass locally and fail later: a private image, a
`build:` key, and `type: worker`.

## Feedback

`insta --agent feedback` reports a hurdle in the **InstaCloud toolkit itself** to the InstaCloud team.
File it when InstaCloud got in *your* way, then **continue the user's task with a workaround** —
never block on the report, and never file feedback for problems in the app the user is building.

```bash
insta --agent feedback --json --type bug --component cli --area deploy \
  --title "deploy --branch deploys to main" \
  --detail "insta --agent deploy --branch feat accepted the flag but the release landed on main" \
  --command "insta --agent deploy . --branch feat --port 8080" \
  --error "deployed ... (branch main)" \
  --expected "release lands on branch feat, per this reference" \
  --doc "skills/insta/cli-reference.md" --workaround "insta --agent branch switch feat, then deploy"
```

Situation → `--type`:

- **"This should work (per docs / the stated contract), but doesn't"** → `bug`.
- **"I was instructed to do X, but reality required Y"** → also `bug`, **with `--doc` +
  `--expected` + `--workaround`** — you can't know whether the instructions are stale or the
  product regressed, and those three fields let the team disambiguate.
- **"What I need is not supported"** → `feature-request`.
- **"Works, but confusing or awkward"** → `friction`.

`--component` is which piece of the toolkit (`cli|mcp|platform|skills|docs|other`); `--area` is
the product domain (deploy, branch, secrets, db, storage, compute, governance, billing, …). Free
text is **redacted locally** (tokens, emails, home paths) before sending and re-scrubbed
server-side; repeat reports of the same title within a week **fold into one record**
(`status: duplicate`). Project/org/branch context, CLI version, and OS attach automatically when
available. Via MCP: the `insta_feedback` tool takes the same fields (plus explicit
`projectId`/`branch`).

## Govern & observe

- **Policy** gates `secrets.read`, `secrets.write`, `deploy`, `branch.delete`, `project.delete`,
  `storage.read` (`storage list` + `storage get`), `storage.delete`,
  `service.add` / `service.remove` / `service.rename` / `service.scale` / `service.upgrade` /
  `service.setAccess`, and `domain.purchase` (`domain buy`, **approve** by default — it spends money).
  `approve` = require a
  human: the action returns `approval_required` — the hint prints to **stderr** and the command
  **exits 2** (CLI ≥ 0.0.37; distinct from exit 1 = error, so treat exit 2 **on an
  `approval_required` response** as "pending, not failed" — `insta run` also exits 2 to refuse a
  same-name collision, where no approval is coming and the stderr message names the two ways
  forward instead; see the exit-2 note under [Commands](#commands)); an admin runs
  `insta approvals approve <id>`, then
  you **re-run the unchanged request** (single-use grant). In `branch-developer`, project deletion
  is denied and unprotected service deletion requires approval. Approval never changes policy;
  a human must explicitly update `agent-policy` for a lasting rule change.
- `insta --agent approvals list` — inspect pending gates. Relay `insta approvals approve <id>`
  or `insta approvals deny <id>` to a human admin; agents cannot execute either decision.
- `insta --agent events [--branch] [--limit]` — timeline of resource side-effects (project/branch creates,
  deploys + URLs, govern decisions) plus ingested agent events.
- **`insta --agent observe`** — the local credential-audit hook (a PostToolUse hook for Claude Code / Codex,
  auto-installed on `project create`/`link`). It scans each tool-use for credential exposure
  (AWS / GitHub / Stripe / LLM / DB / JWT / private keys) and appends **redacted fingerprints** (never
  raw secrets) to `./.insta/audit.jsonl`. `insta --agent observe report` renders it; `insta --agent observe sync`
  uploads findings into the project timeline (idempotent). **(CLI ≥ 0.0.59)** The install
  gitignores its own local state (`.insta/observe/`, `.insta/audit.jsonl`) and writes a
  shell-neutral `.codex/hooks.json` entry with no machine-specific path, so the hook *entries* in
  `.claude/settings.json` / `.codex/hooks.json` are committable while the generated hook files
  under `.insta/observe/` are not; never hide `./.insta/project.json` behind a blanket `.insta/`
  ignore. Paths git already tracks are reported with a `git rm -r --cached …` hint (an ignore
  entry cannot un-track them).
