# InstaCloud CLI reference

Command catalog with flags and gates. Task guidance lives in `references/` — setup, deploy,
frameworks, storage, branching, governance, operate, migrate (plus `migrate/` per source), mcp.

## Commands

Managed agent execution uses the global prefix `insta --agent …` (for example,
`insta --agent service add compute api`). High-confidence Codex/Claude Code/Cursor environments
also activate agent mode. `insta --agent agent setup` issues/refreshes a 24-hour project session in
`.insta/agent-session.json` and adds it to `.gitignore`; user login is still required. Missing or
invalid sessions fail closed with setup guidance. Agent examples include the global flag
explicitly. Bare approval commands below are for a human admin to run, never the agent.

| Agent policy command | Purpose |
| --- | --- |
| `insta --agent agent policy get [--json]` | mode, protected branch IDs, rules, session epoch, action catalog |
| `insta --agent agent policy set <full-access\|read-only\|branch-specific> [--json]` | change mode; admin required. Clears any rules — a preset carries none. `branch-developer` is still accepted as the old name for `branch-specific`. `customize` is not settable here: it is what `rule set` produces |
| `insta --agent agent policy rule set <action> <allow\|deny\|approve> [--json]` | override one unprotected-branch decision; moves the policy to `customize`, **snapshotting the preset first** so one edit cannot re-decide the others. Refuses an unknown action or a fixed invariant by name — read `actionCatalog` from `agent policy get --json` first. Leaving `full_access` is a narrowing cliff (project administration becomes denied, protected branches start applying); the command prints what else moved, on stderr |
| `insta --agent agent policy protect-branch <name-or-id> [--json]` | protect an explicitly selected branch |
| `insta --agent agent policy unprotect-branch <name-or-id> [--json]` | remove branch protection |
| `insta --agent agent policy revoke-sessions [--json]` | revoke ALL project CLI sessions by incrementing epoch |

`agent policy` is the only policy command; the old `policy` command is removed. Human requests
use normal RBAC without a policy gate. New/existing projects start with explicit
`full_access`. Restricted agents cannot edit their own policy or protection list. Agent approvals
bind the complete request and are single-use; a human admin runs `insta agent approvals approve <id>`,
then the agent retries unchanged. MCP cannot approve on the human's behalf. Session files/private
keys and raw request data must not be included in source control or approval reports.

| Command | Purpose |
|---|---|
| `insta --agent login` [`--api-url <url>`] [`--env <prod\|staging>`] · `insta --agent login --email <e> --password <p>` · `insta --agent login --oauth <github\|google>` · `insta --agent login --device` · `insta --agent login --api-key <insta_…>` · `insta --agent login --claim <email>` · `insta --agent logout` | auth (api-url + tokens persist; tokens auto-refresh). **Bare `insta --agent login` signs in from the browser** (any account type — email, GitHub, Google): it opens the console approval link locally, prints it as fallback, and polls until the human approves (~15 min window). `--device` is the same grant, print-only, for a machine with no usable browser (VMs, SSH, CI): the human approves **from a browser on any other machine**. `--oauth` opens a browser straight into the named provider (loopback capture). Agents use email/password or an API token; a password (`--password`/`$INSTA_PASSWORD`) needs `--email`. An `insta_` token can also come from ID-JAG registration at `POST https://api.instacloud.com/agent/auth` when the agent runs inside a participating provider (preview, see https://instacloud.com/auth.md), then `insta --agent login --api-key insta_…`. **`--claim <email>`** (CLI ≥ the release carrying `--claim`, check `insta --agent login --help`) is the auth.md user claimed flow for agents that cannot mint an ID-JAG: it prints a console link and a 6-digit code, the named user signs in **as that email** and types the code on the console `/claim` page, and the CLI stores the resulting `insta_` key. Only that user can complete it, the code never travels in the URL, and in agent mode no browser is opened here. **It blocks until the human confirms, so run it in the background and read the link out of a log file, never through a pipe** (`tail`/`head` buffer, so the link never reaches you and the step times out): `insta --agent login --claim <e> > /tmp/insta-claim.log 2>&1 &` then poll that file until the link and code appear, show them to the user, and keep polling until it prints `logged in as`. See https://instacloud.com/auth.md. `--env` targets a named deployment (see [Environments](#environments)); `--api-url` wins if both are given. **For CI, log in with an org- or project-scoped token** (`insta --agent tokens create`, below) rather than an account-wide one; after `--api-key` the CLI records the token's scope from `/me`, so a project token resolves its project without listing orgs |
| `insta --agent env` [`--json`] · `insta --agent env use <prod\|staging>` [`--json`] | show or switch the deployment environment. **Switching drops the stored session** — prod and staging are separate deployments, so the old token cannot authenticate. See [Environments](#environments) |
| `insta --agent status` [`--json`] | environment + login + linked project + current branch |
| `insta --agent org list` [`--json`] · `insta --agent org create <name>` [`--json`] | organizations (**one free org per user** — upgrade an existing org before creating another) |
| `insta --agent tokens list` [`--json`] · `insta --agent tokens create <name>` [`--org <id>` \| `--project <id>` \| `--account`] [`--read-only`] [`--expires <30d\|90d\|1y\|never>`] [`--json`] · `insta --agent tokens revoke <id>` [`--json`] | API tokens (`insta_…`) for CI and other automations (CLI ≥ the release carrying `tokens`; check `insta --agent tokens --help`). **A token is bound to one org by default** (the linked project's org, or the caller's only org — several orgs need `--org`); `--project <id>` binds it to one project; `--account` is the explicit, account-wide choice (everything the account can do — avoid for CI). `--read-only` = GET only (it cannot run SQL or change anything). Default expiry 90 days. `create` prints the plaintext ONCE on stdout (`$(insta --agent tokens create ci)` captures exactly the token; the note goes to stderr); with `--json` stdout is one `{ token, record }` document. An org token can mint tokens inside its org (e.g. a project token after creating the project), never a wider one; a project token cannot mint. Outside its binding a token gets **HTTP 403 `token_scope`** — that is the credential being narrow, NOT a missing role: mint a wider token from an account login, don't go changing memberships. Tokens outlive nothing: the creator leaving the org kills them |
| `insta --agent project create <name>` [`--org <id>`] [`--json`] | create an **empty** project (no services), link this dir. With `--json`, a missing/unresolvable name is a hard error even on a terminal (never prompts) |
| `insta --agent project list` [`--org`] [`--json`] · `insta --agent project link <id>` [`--json`] | list / link existing |
| `insta --agent project delete` [`--json`] | tear down ALL resources + unlink (gated: `project.delete`, approval by default) |
| `insta --agent service add <postgres\|storage\|compute\|redis\|mysql\|mongodb> <name>` [`--branch <b>`] [`--region <r>`] [`--image <url>`] [`--port <n>`] [`--always-on`\|`--no-always-on`] [`--volume <gi>`] [`--mount-path <path>`] [`--json`] | provision a service **on a branch** (default: current/linked branch) — services are **branch-scoped**: adding one on a branch does not add it to any other branch; postgres/compute get a default access domain — postgres synchronously; compute via a best-effort reservation made at creation when the service is born **empty** (no `--image`; since 2026-09-17) — a plane too old to reserve, or simply down, does not fail the create and instead leaves it to the first deploy (as does a service created **with** `--image`, which skips the reservation and always gets its domain from that first deploy) (gated: `service.add`). **compute only:** `--image` runs that image immediately at creation (otherwise compute starts as an empty, unreachable app until `insta --agent deploy`); `--port` sets the listening port (default `8080`); **new compute services are born always-on** (never scale to zero; since 2026-09-07) — `--no-always-on` creates it scale-to-zero instead (idle machines suspend, the next request wakes it), `--always-on` states the default explicitly (all plans, billing is actual usage either way); `--volume <gi>` attaches a persistent volume (default `/data`; choose a path on attachment with `--mount-path <path>`) (also attachable later via `insta --agent compute volume --size` — see [Volumes](#volumes)). The image is **persisted** on the service — shown in `service list`, re-run when the branch is forked, and updated later via `insta --agent deploy --image`. Both positional arguments are optional in the parser: a **terminal** given **no type** picks from the same four kinds the dashboard's Add Service menu offers — **Docker Image** (asks for the ref, suggests a name from it, then the port), **Postgres** (`main-db`), **Storage** (`assets`), **Empty Service** (`compute`) — and is asked for a name after; given a **type but no name**, only the name is asked, for that type's plain kind. **Anything without a TTY errors and creates nothing** — with no type, all four kinds, each printed as the command to run instead (Docker Image as `insta --agent service add compute <name> --image <ref> --port <n>`); with a type but no name, that kind's naming usage — so always pass both here. Docker Image is a *kind*, not a follow-up question: non-interactively it is just `--image` on a compute service. `--json` prints the created service object (id, type, name, domain, region, …) instead of the human line, and opts out of the prompts, so a missing positional errors the same way even on a terminal |
| `insta --agent config regions` [`--json`] | list regions available for postgres/compute services |
| `insta --agent service list` [`--json`] [`--branch <b>`] · `insta --agent service rename <type> <name> <new-name>` [`--json`] [`--branch <b>`] · `insta --agent service remove <type> <name>` [`--branch <b>`] [`--json`] | list / rename / remove a branch's services (default: current branch; bindings keep pointing at renamed services; gated: `service.rename` / `service.remove`). `list --json` rows carry `pg_version` on postgres services (a platform field — any CLI passes it through; one per service row — a branch with several postgres services has one each) — the Postgres **major** the instance runs (e.g. `16`), known without waking it — so pick `pg_dump`/`pg_restore`/`psql` of the **same major** before you connect (a newer client's dump emits statements the server rejects, and a default restore continues past them). **(CLI ≥ 0.0.57)** the human line shows it as `pg 16`; `service add postgres` and `agent manifest` print the same badge. Rows older than the field were backfilled from the image every instance was born from, so if a restore still fails on version grounds against an old instance, confirm with `serverVersion`. `null` = a legacy row that never recorded one; key absent = a platform that predates the field. Either way, read the exact version instead, selecting the same branch and service as the DSN: `insta --agent postgres stats --json --branch <b> [service]` reports `serverVersion` but never wakes a suspended instance (field present only while it runs), and `psql "$(insta --agent postgres url --branch <b> [service])" -c 'show server_version'` answers in one step, waking it |
| `insta --agent postgres url [service]` [`--branch <b>`] [`--json`] | print a postgres service's **connection string** (DSN). Default output is the bare URL alone on stdout, pipe-friendly (`psql "$(insta --agent postgres url)"`); `--json` replaces it with a `{service, branch, url}` envelope. The bundle carries only the **primary** postgres service's `DATABASE_URL`, so this is the command that yields a *specific* service's DSN (gated: `secrets.read`). `[service]` picks one when the branch has several postgres services |
| `insta --agent postgres connect [service]` [`--branch <b>`] | open an **interactive psql session** on a postgres service (needs `psql` on PATH; gated: `secrets.read`). A suspended instance wakes on connect — the first prompt can take a few seconds. Exits with psql's own exit code |
| `insta --agent postgres stats [service]` [`--branch <b>`] [`--json`] | point-in-time **postgres stats snapshot**: connections vs the server's max (active count), cache hit rate, database size. Read-only; insta-db-backed services answer from the control plane without waking a suspended instance — `serverVersion` (rendered `PG 16.4`) is present only while the instance is running, like `cacheHitRatio`. Same read as the `insta_db_stats` MCP tool's `metrics` kind (its `insight`/`activity`/`query-stats` kinds are MCP-only) |
| `insta --agent compute scale <count> [service]` [`--region <r>`] [`--branch <b>`] [`--json`] | set the compute service's same-region replica count (**1–10**) — **paid plans only** (free → 403); gated: `service.scale`. `--region` is an InstaCloud slug (e.g. `us-east`; see `insta --agent config regions`), **not** a raw Fly code |
| `insta --agent compute limits [service]` [`--memory <size>`] [`--cpu <n>`] [`--branch <b>`] [`--json`] | show or set a compute service's **resource ceiling** — **any plan within the free cap; raising ABOVE the free cap needs a paid plan** (free → 403 beyond it; lowering is free on every plan). A new service is born AT its plan cap (free 4 vCPU / 4 GB, pro 8 / 8). Bare = read (prints the ceiling **and** the plan max). Setting **requires `--memory`** (`512mb`, `1gb` — decimal `mb/gb` and binary `Mi/Gi` suffixes both accepted); cpu derives from it, and `--cpu` is only an optional override for parallel workloads (never valid alone). Moves **both directions**: billing is actual usage, so the ceiling caps what the app may burn — it is not a price. **`services upgrade` is removed** (was the pre-usage-billing, up-only legacy control); `--memory` here is the control, for postgres `insta --agent postgres limits` (cpu/memory) |
| `insta --agent postgres limits [service]` [`--cpu <n>`] [`--memory <size>`] [`--branch <b>`] [`--json`] | same ceiling control for a postgres service — any plan within the free cap, paid above it; both directions. A new postgres is also born AT its plan cap (free 4 vCPU / 4Gi, pro 8 / 8Gi), volume included (10Gi free, 50Gi pro, 100Gi team; insta-platform #438). Takes provider quantities (`--cpu 2` or `2500m`; `--memory 4Gi`); either flag alone works. Bare = read the current ceiling |
| `insta --agent compute volume [service]` [`--size <Gi>`] [`--mount-path <path>`] [`--delete`] [`--branch <b>`] [`--json`] | show, **attach**, grow, or **delete** a compute service's persistent volume (default `/data`; choose a path on attachment with `--mount-path <path>`). Bare = read (size, mount path, plan cap — any plan). `--size` on a volumeless service **attaches** one (any plan up to its own plan cap — 10Gi free, 50Gi paid — the size a disk with no size named is born at; the bare read prints it as plan max; mounts on the next deploy or `compute restart`); on a volume-bearing one it grows — **paid plans, grow-only** (a provisioned disk cannot shrink). `--delete` **destroys the disk and ALL its data immediately** (any plan; irreversible; no detach exists — billing stops now, and suspend fast-wake + scale-out return; gated `service.remove`). Phase 2 (release-gated below): `--mount-path` without `--size` stages an existing path; `appliedMountPath` / `pending` distinguish runtime state. See [Volumes](#volumes) |
| `insta --agent compute start-command` [`<service>`] [`--set <command>` / `--clear`] [`--branch <name>`] [`--json`] | **Phase 2, unreleased — see the release gate in [Volumes](#volumes).** Read or stage a runtime command override; deploy or restart to apply. |
| `insta --agent postgres volume [service]` [`--size <Gi>`] [`--branch <b>`] [`--json`] | show or grow a postgres service's provisioned volume (block disk). Bare = read (size + plan cap — any plan); `--size` grows it — **paid plans, grow-only**. Postgres has its volume by default — there is nothing to attach |
| `insta --agent storage list` [`--prefix <p>`] [`--cursor <c>`] [`--limit <n>`] [`--service <name>`] [`--branch <b>`] [`--json`] | list the objects in a storage service's bucket — one `size  modified  key` row each, in key order (S3 lists lexicographically). **Prefix filter only**: S3 has no substring search, so `--prefix` is applied **server-side** and there is nothing to match mid-key. Pagination is by cursor — the `nextCursor` a page prints is what `--cursor` takes; `--limit` is 1..1000 (default 100). `--service` picks one when the branch has several storage services (gated: `storage.read`) |
| `insta --agent storage get <key>` [`-o <file>`] [`--service <name>`] [`--branch <b>`] [`--json`] | download one object. The platform returns a **short-lived presigned URL** (~60s) and the bytes come **straight from the provider** — nothing streams through the control plane. Writes to the key's **last segment** by default (never a path, so no key can write outside cwd); `-o` names the file. `--json` prints `{url, expiresAt}` and downloads nothing (gated: `storage.read`) |
| `insta --agent storage delete <key>` [`--service <name>`] [`--branch <b>`] [`--json`] | delete one object — **irreversible**, and it runs immediately with no prompt (like every other destructive command here, the governance gate is the guard; a data operation stages nothing for a deploy). Deleting a key that is already gone still succeeds, so success is no proof it existed (gated: `storage.delete`, `allow` by default) |
| `insta --agent storage set-access <public\|private>` [`--service <name>`] [`--branch <b>`] [`--json`] | set the bucket's whole-bucket access mode — `public` (anonymous public-read) or `private` (the default) (gated: `service.setAccess`, **approve** by default) |
| `insta --agent branch create <name>` [`--from <parent>`] [`--json`] | isolated env: **forks the parent branch's current services** — a CoW database branch per postgres, a CoW-forked bucket per storage (snapshot-enabled projects), a clone of every compute service (re-running the parent's persisted image, if any) — then the two branches' service catalogs diverge independently (services are **branch-owned, not project-wide**). **≤10 branches/project.** Does NOT switch |
| `insta --agent branch switch <name>` [`--json`] · `insta --agent branch list` [`--json`] | set current branch / list |
| `insta --agent branch merge <source>` [`--into <target>`] [`--json`] | **structural** merge: creates on the target branch (default: current) every service present on `<source>` but missing there — fresh & **empty, no data copied**. Services the target already has are skipped (reason: `exists`\|`cap`\|`secret-collision`). Additive only — never deletes target services; idempotent |
| `insta --agent branch delete <name>` [`--json`] | tear down the branch's resources (gated: `branch.delete`) |
| `insta --agent secrets` [`--branch <name>`] [`--service <compute/name>`] [`-o <file>`] [`--print`] [`--json`] | secret seam → write the branch's secrets to `./.env` (gated: `secrets.read`). Carries user-defined project/branch secrets **plus the branch's canonical provider credentials** — one `DATABASE_URL` / `REDIS_URL` / `AWS_*` set from the **primary** service of each type (see **Provider credentials** below). **`--service <compute/name>` (CLI ≥ 0.0.65)** answers with **one compute service's own** env instead of the branch-wide merge: that service's user secrets, the unbound ones, its explicit bindings, and the same canonical credentials. Needed when several services define the same name — see **Same-name variables** below |
| `insta --agent secrets list` [`--branch <b>`] [`--json`] | secret names for the branch, **grouped by service** — each service's bound secrets, plus a branch-level "unbound" group and a project-wide group |
| `insta --agent secrets tree` [`--json`] | the whole project as `project → branch → service → secrets` (names only) |
| `insta --agent secrets set <NAME> [value] [--branch <b>] [--service <compute/name>] [--json]` | Set a user secret (project-wide by default; value from stdin if omitted). `--service` scopes it to that branch's compute service (e.g. `compute/api`) — binding **requires a branch** (defaults to the current branch when `--service` is given); omit `--service` for an unbound secret (as before). **(CLI ≥ 0.0.78) Applies it, not just stores it**: the same command redeploys the compute services **on the target branch** that receive this secret — a stopped one is **started** by that redeploy (billed). The write scope and the deploy scope differ: a project-wide secret is *written* to every branch but *deployed* only on the branch this command targets (`--branch`, else the linked branch). Services on other branches print as `(other-branch)` and keep serving the old value until their own deploy or `compute restart` |
| `insta --agent secrets unset <NAME> [--branch <b>] [--service <compute/name>] [--json]` | Remove a user secret. **`--service` (CLI ≥ 0.0.65)** removes **only that service's copy**, leaving a sibling's same-name value alone; without it the original name-keyed delete removes every matching copy at the scope. **(CLI ≥ 0.0.78) Applies it, not just stores it**: the same command redeploys the compute services **on the target branch** that received this secret — a stopped one is **started** by that redeploy (billed). Same scope split as `set`: a project-wide removal lands on every branch but redeploys only the target branch's services |
| `insta --agent secrets sources` [`--branch <b>`] [`--json`] | List provider credential sources available for explicit compute binding, e.g. `postgres/db: DATABASE_URL` or `redis/cache: REDIS_URL, ...` (names only; gated: `secrets.read`) |
| `insta --agent secrets bind <ENV_NAME> <source>` [`--source-name <name>`] `--to <compute/name>` [`--branch <b>`] [`--json`] | Bind one provider credential from `<source>` (`postgres/db`, `redis/cache`, `mysql/orders`, `mongodb/catalog`, `storage/assets`, …) into a compute service's runtime env var. `--source-name` is required when the source exposes multiple credential names. Takes effect on the next deploy — or immediately on a running service with `insta --agent compute restart` (CLI ≥ 0.0.51) (gated: `secrets.write`) |
| `insta --agent secrets bindings --target <compute/name>` [`--branch <b>`] [`--json`] | List provider credential bindings for one compute service (names only; gated: `secrets.read`) |
| `insta --agent run [--branch <b>] [--service <compute/name>] [--ignore-collisions] -- <cmd> [args…]` | run a command with the branch's secret bundle injected into **its environment only** — nothing written to disk, so there is no `.env` to leak, stale out or commit. The bundle lives exactly as long as the process. `--service` injects **one compute service's own** env (the unambiguous read). **On a collision it REFUSES (CLI ≥ 0.0.65): nothing is spawned and it exits 2.** Warning would not be enough — `run` spawns with `{...process.env, ...bundle}`, so a name the platform withheld would fall through to whatever your shell exported, and clearing it is not observable either since the child may hold its own default. `--ignore-collisions` runs anyway with every colliding name **removed** from the child env. No `--json` (its stdout belongs to the child; the banner and any collision report are on stderr) |
| `insta --agent secrets unbind <ENV_NAME> --from <compute/name>` [`--branch <b>`] [`--json`] | Remove one provider credential binding from a compute service; takes effect on the next deploy — or immediately on a running service with `insta --agent compute restart` (CLI ≥ 0.0.51) (gated: `secrets.write`) |
| `insta --agent cron list` [`--branch <b>`] [`--json`] · `insta --agent cron show <name>` [`--json`] | **(CLI ≥ the release that carries `insta cron`; check with `insta cron --help`)** the branch's schedules / one of them. `show` lists header **names** only — values are encrypted at rest and the API never returns them, so an empty value column would read as "unset" rather than "not shown" (gated: `cron.read`) |
| `insta --agent cron create <name> <expression>` `--url <https://…>` \| `--service <name>` [`--path </api/cron>`] [`--method GET\|POST`] [`--body <json>`] [`--header k=v`]… [`--timeout <ms>`] [`--branch <b>`] [`--json`] | schedule an HTTP call. Five-field cron, **UTC**, one-minute floor. `--service` targets a compute service in the **same org** — not merely the same project, since sharing one across an org's projects is legitimate. The CLI, though, resolves `--service <name>` only among the **current branch's** services and has no id form, so from the command line the target is always a service on this branch; a cross-project target is legal on the wire but has to be created through the API. `--url` any external https endpoint. `--method` defaults to GET, or POST when `--body` is given; `--timeout` is `1000`–`300000` ms. Per-org quota by plan: **free 5, pro 100, team/enterprise 1000** — a full org answers 403 (gated: `cron.write`, **approve** by default) |
| `insta --agent cron edit <name>` [same flags as create, all optional] [`--json`] | change a schedule — `--name <new>` renames it. **The request is REPLACED, not merged.** Header values are write-only and cannot be read back, so `--header X=y` alone **drops every other header**, drops a POST body, and flips the method back to GET unless you restate them; the CLI warns on stderr and then proceeds. Restate the whole request, or leave the request flags off entirely to change only the name/expression/timeout. Sends `If-Match` on the revision it just read — a 409 means someone else changed it meanwhile, and the CLI says so rather than re-reading and clobbering (gated: `cron.write`, **approve** by default) |
| `insta --agent cron pause <name>` · `insta --agent cron resume <name>` [`--json`] | stop / restart firing. **This is the kill switch** for a misbehaving schedule — per job, immediate, no redeploy. It stops the CLOCK: `cron run` still works on a paused job. Resume anchors the next run in the future; the pause window is never backfilled (gated: `cron.write`, **approve** by default) |
| `insta --agent cron run <name>` [`--json`] | fire once now, in addition to the schedule. Returns `202` + a run id; does not wait. Carries an idempotency key minted once per invocation, so a retried command cannot double-fire. Works on a **paused** schedule and leaves it paused — pause governs the clock, not the operator, which is what lets you test a fix without resuming the job (gated: `cron.run`, **approve** by default) |
| `insta --agent cron runs <name>` [`--limit <n>`] [`--json`] | run history: status, trigger, attempts, the **wake/request split**, HTTP status. `--limit` is `1`–`100` (default 20). Where you look when a schedule misbehaves (gated: `cron.read`) |
| `insta --agent cron delete <name>` [`--yes`] [`--json`] | delete the schedule — it stops firing immediately, run history is retained, and the **name is released** for reuse. `--yes` is required without a terminal, so an agent must always pass it (gated: `cron.delete`, **approve** by default) |
| `insta --agent cron preview <expression>` [`--json`] | validate an expression and print the next five fire times in UTC — before `create`, rather than discovering a typo a day later. **Needs a linked project** like every other command: the route is project-scoped, which is what keeps an open parser endpoint off the internet. Exits non-zero on an invalid expression, so a script can branch on it (gated: `cron.read`) |
| `insta --agent build [dir]` [`--explain`] [`--port <n>`] [`--json`] | **verify before you deploy** — local, offline, deploys nothing, needs no login: prints the detection plan (builder, install/build/start commands, port **with the reason it was chosen**, `.env.example` keys), the Dockerfile (yours, or — **if nixpacks is installed**, never auto-installed — the one nixpacks would generate; `--explain` includes its content), and static checks each with a next action (missing Dockerfile/start command, port mismatch, `node_modules` shipping in the build context). **Verdict semantics (CLI ≥ 0.0.48): only a Dockerfile IN the directory can make a dir `deployable`.** A dir with no Dockerfile where nixpacks detects the app gets `builder: nixpacks` but its Dockerfile check is a ⚠ warning and the verdict stops at `needs-attention` (exit 0) — the command is local and cannot know which compute plane the target runs on, and the answer differs: an insta-compute service deploys such a dir as-is (the gateway runs nixpacks), a Fly-backed one refuses it. Read `needs-attention` as "depends on the target", not as "will fail". The nixpacks Dockerfile shown by `--explain` is **for inspection, not standalone** (it `COPY`s `.nixpacks/` support files the dir does not have) — do NOT save it as `Dockerfile`; use the detected install/start commands as the starting point for your own. Verdict `failed` (exit 1) = no Dockerfile and nixpacks missing/undetected, or no start command. For a Dockerfile-less dir that `failed` says only that nixpacks is not installed on THIS machine: an insta-compute target still deploys it, because the gateway runs nixpacks, so do not add a Dockerfile just to satisfy the local check. Run it before `insta --agent deploy <dir>` instead of finding out from a burned remote build |
| `insta --agent build logs <build-id>` [`--source <archive\|github>`] [`--follow`] [`--json`] | read output from a **source build** — the remote build a `deploy`/`compute connect-repo` push kicked off, not the local, offline `build` check above. `--source archive` (default) reads a **deploy operation's** build: `<build-id>` is that operation id, printed as soon as `insta --agent deploy` accepts the operation (stderr with `deploy --json`). `--source github` reads a **GitHub-triggered** build: `<build-id>` is the GitHub build id — read `build.buildId` from `insta --agent compute connect-repo <owner/repo> --json`, or `builds[].id` from `GET /projects/{id}/github/builds`. Prints one snapshot by default; `--follow` polls while building and briefly after it ends, for output that lands late (cannot be combined with `--json`). Governed by `logs.read`; no Depot credentials needed locally. Needs login and a linked project — unlike the offline `build` check above |
| `insta --agent deploy <dir>` / `--image <url>` [`--branch <b>`] [`--group <g>`] [`--port <n>`] [`--replace-source`] [`--json`] | deploy to a compute service — a **source dir** (**whether it needs a `Dockerfile` depends on where the service runs**: on an insta-compute service one is *optional* — the CLI packs the directory, uploads it, and the build gateway builds it with nixpacks when there is no Dockerfile; on a Fly-backed service one is still *required*, and without it the command exits 1 naming the options: write a Dockerfile, `--image <url>`, or connect the repo to the service (`insta --agent compute connect-repo <owner/repo> [service]`). The CLI asks the platform which lane serves the target rather than guessing. A CLI that predates this lane answers `source builds are not supported on the insta-compute provider yet` for such a target: run `insta --agent upgrade` and retry. Either way the build is remote — no local Docker; against a local insta-oss daemon the CLI builds with your local docker instead, same command) or a **prebuilt image**. Defaults to the branch's sole compute service; `--group` picks by name (gated: `deploy`). A service connected to a GitHub repo refuses a dir/image deploy (409) unless `--replace-source` is passed (admin): the image then replaces the repo connection. `--json` prints one `{image, machineId, url, branch, group, nextActions}` document on stdout — build progress moves to stderr so stdout stays parseable |
| `insta --agent template list` [`--json`] · `insta --agent template info <code>` [`--json`] | browse the platform **template registry**: one row per template (code / version / category / required-var count / deploy count / name — tagline), and the detail view — version, maintainer, source, upstream pin, a services summary (types, ports, volumes), and every required/optional variable with its description, generator or default |
| `insta --agent template deploy <code\|./dir\|github-url>` [`--branch <b>`] [`--region <r>`] [`--set <NAME=value>`] [`-y`, `--yes`] [`--json`] | deploy a template's whole service set onto a branch (default: current) — a **registry code**, a **local directory** carrying `insta.template.yaml`, or a **github.com URL** (⚠️ **preview**, needs a recent CLI and `git` on `PATH` — see [Templates](#templates); `https://github.com/<owner>/<repo>`, `/tree/<ref>`, `/tree/<ref>/<dir>`, or a `/blob/…/insta.template.yaml` file link). A bare word is **always** a registry code; local mode needs a path-looking target (`./dir`, `/abs/dir`, `~/dir`, `sub/dir`), so a same-named directory in the working dir can never shadow a registry template. The GitHub form shallow-clones on **your machine** with **your** git credentials — private repositories work when git can already read them (`gh auth login` then `gh auth setup-git`) — reads the manifest from the named directory (never scanning the tree, never following a symlink out of the clone), deletes the clone, and sends the manifest inline. Missing required variables are prompted for on a terminal; `--yes` or no TTY fails with the exact `--set NAME=value` list instead. `secret:N`-generated and defaulted variables are resolved **by the platform** — generated secrets never transit. Renders the 4-step pipeline (create services → write variables → deploy → health check), then the per-service URLs; `--json` replaces all of that with one document, which in GitHub mode carries a leading `source: {repo, ref, path, commit}` where `commit` is the commit that was checked out. May come back `approval_required` (hint on stderr, envelope on stdout with `--json`, **exit 2** — as every gated command). `--region <r>` places **every** service the template creates in that region (a slug from `insta --agent config regions`, default `us-east`). One region per template deployment, not per service, and it cannot be changed afterwards. A retry (same deployment) may omit it or repeat it, a different value is refused with 409. See [Templates](#templates) |
| `insta --agent domain search <keyword>` [`--tlds com,dev`] [`--org <id>`] [`--json`] | **buy a domain THROUGH InstaCloud** (a developer-owned/BYO domain skips `search`/`buy` entirely — go straight to `domain attach` below): purchasable names with the price you pay and the yearly renewal. A label (`myapp`) covers every sellable TLD; a full name (`myapp.com`) is guaranteed in the answer when its own TLD is sellable — the registrar's search alone can omit it. The sellable list is per deployment, and a request whose TLDs are all unsellable is a 400 naming what is sold. A full `name.tld` also comes back when its extension is one this deployment does **not** sell, so a plain name you typed is never answered with silence — but only a plain one: a pasted `www.myapp.com`, or a trailing dot, is answered for the label alone and the string you typed is absent. **Read `reason`** — a premium name, one with no price, and a registrar refusal each say so in their own words. `unavailable` is the fallback, and the one to be careful with: it does **not** distinguish "the registrar says it is taken" from "we do not sell that extension", so do not report either as the reason when that is all you have |
| `insta --agent domain buy <name>` [`--years n`] [`--no-open`] [`--json`] | **(CLI ≥ 0.0.80 — older builds call routes the platform has removed)** order it. **A domain belongs to the ORG** — the one your linked project is in. `list`, `status`, `search` and `records` take `--org <id>` to name another; `buy` and `attach` do not, because both bind the linked project: buying spends that org's money under that project's policy, and attaching names one of its services. Your agent policy is read at the project your session is bound to (`insta agent setup`), and that project must be in the org paying. A credential that names no project — an `insta_` key, MCP — is judged on the whole org instead: every project in it must be `full_access`. **Buying binds nothing**: the registered name serves nothing until `domain attach` says what it should serve. Answers a **Stripe Checkout URL a human must open** — nothing is registered until they pay, and registrations are **non-refundable**, so relay the URL and stop. Gated: `domain.purchase` — **`full_access`, which a new project starts on, allows it outright**; `branch_specific` answers `approval_required` (202 + exit 2, see [Approval relay](SKILL.md#approval-relay-critical--gated-actions)); `read_only` refuses. Paying the Checkout link needs a human either way. Some registries take fixed terms (`.ai` is 2-year only) — a term they refuse is a 400 **before** any payment. **Pass `--no-open`**: by default this spawns the host's browser at the Checkout link, which on an agent's machine opens a window nobody is watching — you want the URL printed so you can relay it |
| `insta --agent domain status <name>` [`--org <id>`] [`--json`] · `insta --agent domain list` [`--org <id>`] [`--json`] | **(CLI ≥ 0.0.80 — older builds call routes the platform has removed)** every domain the ORG owns, not just ones this project uses — `--org <id>` targets one other than the linked project's default (see the `buy` row above for which verbs take it). After payment the platform registers the name and stops — the domain is inventory, listed with no hostnames, until an `attach`. Poll `status`: the order runs `pending_payment` → `paid` → `registering` → `registered`, and then, once something is attached, → `attaching` → `active`; each hostname runs `pending` → `attached` → `active` (`failed` carries the reason; `insta --agent domain attach <hostname>` on that hostname retries it). Each hostname names **its own** service, because one domain can serve several. Minutes, not seconds |
| `insta --agent domain attach <hostname>` [`--branch <b>`] [`--group <g>`] [`--json`] | **(CLI ≥ 0.0.80 — older builds look the hostname up on a route the platform has removed)** attach any hostname to a compute service — **one command covers both origins**: for a name **bought through InstaCloud** or **any subdomain of one**, the platform publishes the DNS in the zone it controls, so there are no records for you to set — `abc.com` binds `abc.com` **and** `www.abc.com`; `api.abc.com` binds only that, and every other hostname of the domain is left exactly as it is (the **apex** `abc.com` itself verifies only once the domain's DNS is on a managed zone — see `domain delegate` below; subdomains verify either way); for a **developer-owned (BYO) domain** the command instead prints the DNS records to add **at your own registrar** (a `CNAME` for a subdomain plus a validation record — for a subdomain, Fly issues the cert and routes once DNS propagates, poll with `domain check`; the **apex** prints `A`/`AAAA` placeholders but **verifies only once the domain's DNS is on a managed zone**, exactly like the bought-domain apex) — so delegate the whole BYO domain once (`domain zone delegate`, below) and attach publishes the records for you, **apex included**. So `api.abc.com` → one service and `docs.abc.com` → another is two calls, and both keep serving. A hostname **this domain** already put on another service is moved: the platform unbinds it there before binding the new one (the hostname is down between the two). A hostname the compute plane holds from outside this domain's list — bound by an earlier `domain attach`, or another tenant's — still lands `failed` (`already attached to another compute service`): release it at that service first (`insta --agent domain detach <hostname> --group <that service>`), then attach. A 409 whose message says to retry means it (a sweep or a move still landing, or the row changed under the request); the one that does not is asking for what already serves that same service. Also how a `detached` domain — its compute service was deleted, the registration stands — is bound again. Gated: `deploy` |
| `insta --agent domain check <hostname>` [`--branch <b>`] [`--group <g>`] [`--json`] · `insta --agent domain detach <hostname>` [`--branch <b>`] [`--group <g>`] [`--json`] | `check` reports a hostname's attach state — ownership TXT, routing CNAME, edge certificate, where it resolves — and what each still needs; works for a bought or BYO hostname alike, ungated. `detach` removes a hostname from its compute service — gated: `deploy` |
| `insta --agent domain records list <domain>` · `records add <domain> <type> <name> <content>` [`--ttl <s>`] [`--priority <n>`] · `records set <domain> <id>` [`--type <t>`] [`--name <host>`] [`--content <value>`] [`--ttl <s>`] [`--priority <n>`] · `records remove <domain> <id>` — all take [`--org <id>`] [`--json`] | **(CLI ≥ 0.0.77)** the DNS records of a domain **bought through InstaCloud** — the zone InstaCloud holds at the registrar (a domain you own elsewhere is edited at your own registrar; nothing here touches it). The org is `--org` or the linked project's, as `search` resolves it. `list` prints every record with its id (no header row; `--json` is `{ items: [...] }`, `add`/`set` answer the record itself, `remove` answers `{ ok: true }`), and marks a record **managed**: published by `domain attach` for the hostname it names — read-only, `set`/`remove` answer 409 saying so — or, with no hostname, a leftover no hostname claims any more: `remove` is allowed, `set` is still 409. `add`: type `A\|AAAA\|CNAME\|ANAME\|MX\|TXT\|SRV\|NS`; name `@` for the domain itself, a label (`www`), or the full hostname under it; content is the answer — an IP, a target hostname, `"<weight> <port> <target>"` for SRV, text for TXT — **quote anything with spaces**; `--ttl` defaults to 300 and must be 300–604800; `--priority` is 0–65535, **required for MX and SRV and refused for every other type**. A full hostname **outside** the domain is not refused — it is taken as labels under the domain (`www.other.com` on `myapp.com` creates `www.other.com.myapp.com`). A routing record (A/AAAA/ANAME/CNAME) or an NS at a hostname an attach is serving — or an NS anywhere above one — is a 409: those are the platform's; anything else there (TXT, MX, SRV) is yours. A CNAME or an NS at the domain itself is a 400 naming the fix (use ANAME; NS records delegate a subdomain only). A refusal prints its reason (the platform's sentence, or the schema's for a value out of range) — **read it, it names the fix**; do not retry the same body. `set` sends only the flags you pass; the rest keep their value. A `--type` change away from MX/SRV drops the priority; a change **to** MX/SRV needs `--priority` in the same call. A content that starts with `-` needs `--` before it, and every flag before the `--` (`… add ex.com TXT @ --json -- "-…"`). **Agent credentials: `list` works; `add`/`set`/`remove` answer 403 `unclassified_agent_action`** — org-scoped writes have no agent policy yet — so hand the exact command to the user; retrying cannot change it. **Under managed custody (`domain delegate`, below), every `records` verb answers 409 — `list` included**: they all read the registrar's zone, which is inert while the domain's DNS lives on InstaCloud's own nameservers, so an answer from it would be a lie. For an agent that means the writes still 403 as above (refused before custody is consulted), but `list`, a GET, reaches the handler and gets the 409 too — "list works" holds only under registrar custody. |
| `insta --agent domain delegate <domain>` [`--org <id>`] [`--json`] | **(CLI ≥ 0.1.3; the platform route exists on older CLIs as `POST /orgs/:org/domains/:name/delegate`)** move a **bought** domain's DNS onto an **InstaCloud-managed zone** — the way an **apex** gets an edge certificate and serves. Under the registrar's nameservers the apex flattens to shared proxy addresses the edge will not certify, so `myapp.com` itself sits `pending` and eventually fails while `www.myapp.com` serves; delegation is the fix, not another attach. Every record is copied into the managed zone **first** — the platform's and yours (MX, TXT, …) — and the nameservers switch after, so a hostname that was serving keeps serving; a hostname that failed **because the zone had been delegated away** (its reason says to point back at the registrar) revives to `pending` on its own. A `pending`/`attached` hostname then re-verifies on the platform's own loop — **watch `domain status`** — but `failed` is terminal for every reason other than the delegation one, **including the 48-hour deadline the never-verifying apex usually hits first**: a hostname still `failed` after delegation with a non-delegation reason needs one `insta --agent domain attach <hostname>` to retry it (that is the one re-attach that IS the remedy). `list`/`status` show `zone managed by InstaCloud (…)` — managed custody is **not** the delegated-away state, so `attach` keeps working; the `--json` object says `custody: "managed"` with `delegated: false`. Needs **org admin** (a member gets 403 `requires admin role`). First-time registry NS propagation can take ~15–20 min — a `pending` that outlives it is worth reading `status` reasons over, not re-running. **While managed, the `records` API is closed** (every verb 409s — managed-zone record editing is future work), so a domain carrying the customer's own MX/SPF keeps serving them but cannot EDIT them until `nameservers reset`, which is the way back: zone returns to the registrar's own nameservers and record custody with it. **Agent credentials: `domain.delegate` follows the project's agent policy, exactly like `domain.purchase` on the `buy` row** — `full_access` (a new project's default) allows it outright and **the delegation executes with no approval**; `branch_specific` answers 202 `approval_required`, the answer to relay, not an error; `customize` follows its explicit `domain.delegate` rule (allow/deny/approve) and falls back to that same approval only when the rule is unnamed; `read_only` refuses. The gate is read from the linked project's session; a project-less agent credential (an `insta_` API key, an MCP assertion) is judged on the whole org instead: org admin plus *every* project in the org on `full_access` executes it with no gate at all, anything less is refused with a misleading `project.billing.update` denial — run it from a linked project. |
| `insta domain nameservers set <domain> <nameservers...>` · `nameservers reset <domain>` — both take [`--org <id>`] [`--json`] | **(CLI ≥ 0.1.1)** delegate a **bought** domain's zone away from InstaCloud **to nameservers of yours**, or put it back (for InstaCloud's own nameservers use `domain delegate`, above — it keeps hostnames serving; `set` does not). The nameservers are space- or comma-separated and **must already host the zone**, because some registries verify before accepting the change. **`set` takes down every hostname the domain serves**, unless the ones you name are the registrar's own: the records `domain attach` published live in the zone you are leaving, so the platform marks each hostname `failed` with the reason and the CLI prints it — that is the answer, not an error. The published records are **left in place**, because a zone nothing answers from is inert; `reset` un-delegates and `domain attach` re-adopts them, so a hostname `set` took down comes back with an attach, not with the reset alone. While a domain is delegated **away** like this, **`domain attach` is refused** (409), and `domain list`/`status` say so on the domain's own line — a domain on a *managed* zone is not in this state. `reset` from a **managed** zone is the mirror move: record custody returns to the registrar and hostnames a managed zone was serving re-verify on their own. `--json` on both is the whole purchased-domain object. **Agent credentials: both answer 403 `unclassified_agent_action`** — the same org-scoped-write rule as `records` above — so hand the exact command to the user. |
| `insta --agent domain zone delegate <domain>` · `zone list` · `zone records <domain>` · `zone release <domain>` — all take [`--org <id>`] [`--json`] | **(CLI ≥ 0.1.4; platform BYO zones)** bring-your-own domains on **nameserver delegation** — the BYO twin of `domain delegate`, for a domain owned at an **outside** registrar (a bought domain has its own `delegate` verb above; the two never mix — a BYO claim of a bought name is a 409 naming the right door). `zone delegate` builds an InstaCloud-managed zone for the domain, seeds it from the provider's public-record **scan** (a HEURISTIC: common type/name combinations, not everything) and answers the **two nameservers** to set at the domain's registrar. From then on `domain attach` publishes its records into the zone itself — **apex included**, which the print-the-records path can never serve. **The contract is review-then-switch**: read `zone records <domain>` (every type shows — CAA, SRV included), add anything missing at your **CURRENT** DNS provider, re-run `zone delegate` (idempotent for the owning org; the re-run re-triggers the import), and only then switch the nameservers — records the review misses drop at the switch. A domain carrying **live MX records is refused outright** (moving mail-bearing DNS can drop mail) — as is a domain bought through InstaCloud, one overlapping an existing delegated tree (one zone covers a whole domain tree), one with an open purchase order, the 201st live zone (a 200-per-org quota), a billing-suspended org (release stays available), and a domain whose registry ALREADY answers from InstaCloud's pair with nothing on file (a TXT proof at `_instacloud-zone-challenge.<domain>` is demanded — fails closed on resolver trouble, so it is reachable on a blip). **Every refusal sentence names its fix — read it and relay it**; note two are TRANSIENT retries, not verdicts: "could not be checked for mail records just now" and the resolver-blip proof demand. `zone list` shows `waiting for nameservers` (with the pair) vs `delegated`; activation is the platform's ~minutely sweep noticing the registry switch, not a live probe. `zone release <domain>` prunes what the platform published, deletes the zone, and prints the next step — point the nameservers back at your own provider; hostnames re-verify on the records path. `zone delegate` and `zone release` need **org admin** (a member gets 403 `requires admin role`); `zone list` and `zone records` are member-level reads — any member can run the review step. The platform answers 501 when managed DNS is not enabled on the deployment. **Agent credentials: `zone delegate` AND `zone release` are both gated `zone.delegate` and follow the project's agent policy exactly like `domain.delegate`** — `full_access` executes outright, `branch_specific` answers 202 `approval_required` (relay it, not an error), `read_only` refuses; the two reads follow the ordinary member read path. **The projectless-credential rule on the `domain delegate` row applies here verbatim**: an `insta_` key or MCP assertion with no linked project is judged org-wide and anything less than every-project-`full_access` is refused with a misleading `project.billing.update` denial — run it from a linked project. |
| `insta domain transfer lock <domain> <on\|off>` · `transfer code <domain>` — both take [`--org <id>`] [`--json`] | **(CLI ≥ 0.1.1)** take a **bought** domain to another registrar. Two steps on purpose: `lock off` opens the **registrar** transfer lock, `code` reads the **EPP authorization code** the gaining registrar asks for, and the code alone moves nothing. **Both need org `admin`** — a `member` gets 403 — because either hands the domain to someone else. **ICANN's own 60-day lock** on a new registration outranks `lock off` and nothing here can waive it: `lock off` prints the date it is held until, when that is still in force. **Nothing refreshes the row after a transfer completes — not even a read** — so do not report the domain as gone. `--json` is the purchased-domain object for `lock` and `{ authCode }` for `code`; plain output for `code` is the bare code alone on a line, so it can be captured. **Agent credentials: both answer 403**, so hand the commands to the user. |
| `insta --agent compute start\|stop\|suspend [service]` · `insta --agent compute status [service]` [`--json`] | control a compute service's lifecycle — **persistent override** of auto scale-to-zero: `stop`/`suspend` take it offline and traffic will **not** wake it until `start`; `status` shows desired vs. live state. All plans; ungated. `[service]` defaults to the project's sole compute service |
| `insta --agent compute restart [service]` [`--branch <b>`] [`--json`] | **(CLI ≥ 0.0.51)** **re-run the image reference the service already runs**, against a freshly resolved env bundle — it asks for no new version and no new spec, though it does **not pin a digest**: a service recorded against a moving tag (`app:latest`) gets whatever that tag resolves to now (source deploys record a unique label and are unaffected). The two reasons to use it: a binding changed and the running app hasn't picked it up (env is baked into the machine at deploy time — a user secret set with `secrets set`/`unset` redeploys itself and does not need this), or the machine is up but **wedged** (`start` no-ops on a machine that is already `started`). The service must be **running**: a deliberately stopped/suspended one 400s and points at `insta --agent compute start`. A never-deployed service 400s like `exec` does. **A running machine is health-gated coming back up** — if the app doesn't answer on its port the machines are rolled back (best-effort) to the config they were serving and the failure is reported (that verdict means the app is broken, not the platform). Whether an **idle machine (a scale-to-zero service between requests) is woken and gated at all depends on the compute plane** (`insta --agent agent manifest --json` names it per compute row — `fly`, `microvm`, or a neutral `compute` when the platform reported none) — the Fly-backed one hands it the new config without waking, so the command returns fast, bills no uptime, and proves nothing about whether the app boots. Send it a request if you need that proof; see [operate.md](references/operate.md). All plans; **gated: `deploy`** — it lands configuration the way a deploy does, so a policy denying deploys denies this too; `start`/`stop` stay ungated and cycle a wedged machine without one. Refused while the org is billing-suspended; any machine it wakes bills as ordinary uptime, an idle one it leaves asleep costs nothing. WebSocket concurrency **is** re-asserted (it is recorded on the service), so a socket app does not need a redeploy to stay one |
| `insta --agent compute exec [service] -- <command> [args...]` [`--branch <b>`] [`--timeout <sec>`] [`--json`] | run a **one-shot** command on the service's live machine — no interactive shell, no stdin. Wakes a scaled-to-zero machine first (the wake counts as billed uptime). `--timeout` bounds the run, **1–180s** (default 30). The CLI's **exit code is the remote command's exit code** — safe for scripts/agents to branch on. stdout/stderr stream to their own local streams verbatim, each capped at **1 MiB** (truncation noted on stderr); `--json` returns the raw response instead of split streams. Gated on **both** `deploy` and `secrets.read` — a deny on either is a 403. A service with no image ever deployed 400s: "this service has no machines yet — deploy an image first, then retry". **`--api-url <url>` must come before `compute`** here (`insta --api-url <url> --agent compute exec …`) — everything after `--` is the remote command's own argv |
| `insta compute ssh [service]` [`--setup`] [`-b, --branch <b>`] [`--json`] | **(CLI ≥ 0.0.71)** issue a **short-lived SSH certificate** for a compute service and print the `ssh` command that uses it. **It does not open a session** — it makes `ssh` work; you then run the printed command yourself. **Agents cannot use this: it requires an interactive login and refuses API keys (403) — use `insta --agent compute exec` for one-shot commands.** Gated on **both** `compute.shell` and `secrets.read` (a shell inherits the service's decrypted env), and `compute.shell` **defaults to `approve`** for branch-specific agents. Bare = mint a certificate (default **1h**, max 24h) and print a self-contained `ssh -i … -o CertificateFile=… -o IdentitiesOnly=yes <user>@<host>`. `--setup` additionally does the **one-time client setup**: generates a dedicated key at `~/.insta/ssh/id_ed25519` (your own keys are never touched), adds one `@cert-authority` line to `~/.ssh/known_hosts` so every region is trusted without per-node fingerprint prompts, and writes a block **at the TOP of `~/.ssh/config`** (first-obtained-value wins in ssh_config) giving the service the alias **`<service>.insta`**. After that it is plain `ssh api.insta`, `scp` and `-L`: the block renews the certificate while OpenSSH parses the config, so the alias keeps working unattended. An alias already pointing at a **different** project/branch/service is **refused**, not silently repointed. **Compute-plane dependent** — a Fly-backed service has no SSH gateway and 400s naming `compute exec` instead (`insta --agent agent manifest --json` names the plane per compute row). On **Windows** the block omits connection multiplexing, which Win32-OpenSSH does not implement. A fourth flag, `--ensure-cert <alias>`, exists but is **internal**: it is the renewal hook the generated config invokes (as `insta __ssh-ensure-cert <alias>`) and is silent by design — never call it yourself |
| `insta --agent compute always-on on\|off [service]` [`--branch --json`] | idle-mode dial: `on` = machines never scale to zero (no cold starts; idle RAM bills at actual usage), `off` = scale-to-zero (idle costs ~nothing, first request cold-starts). New compute services are born `on` since 2026-09-07. All plans; billing is actual usage either way |
| `insta --agent compute repo [service]` [`--branch <b>`] [`--json`] | show what a compute service deploys from: the image it runs, or the GitHub repository — `owner/repo`, the branch it builds, root directory, which repo-root paths a push must change to redeploy it (`insta --agent compute watch-paths`), and whether pushes redeploy it at all (never for a public repo). `[service]` defaults to the branch's sole compute service. Cloud-only (insta-oss 501s) |
| `insta --agent compute connect-repo <owner/repo> [service]` [`--public`] [`--root-dir <dir>`] [`--repo-branch <name>`] [`--no-auto-deploy`] [`--watch-paths <patterns>`] [`--port <n>`] [`--branch <b>`] [`--json`] | connect a GitHub repository to an **existing** compute service: the repo is built (its Dockerfile, or nixpacks when there is none) and deployed **into that service**, and every later push to the tracked branch redeploys it. `<owner/repo>` also accepts a github.com URL. **Requires CLI ≥ 0.0.73 for guided setup.** Run without `--json`: existing GitHub user authorization is reused; otherwise the CLI opens GitHub and prints a device code to approve. If the owning personal account or organization has no App installation, it opens installation; if the installation lacks the repository, it opens its configuration page. Select the owner and grant access to the target repository, then save. The CLI prints every URL for remote terminals and waits up to 15 minutes for repository access, then automatically continues connecting and queues the build. You must also have access to the repository through your own GitHub account; an account owner or organization admin may need to change App access. `--json` and non-agent pipes require authorization and repository access beforehand; missing access fails promptly without opening a browser or waiting. Public repositories can use `--public` without App installation or user authorization; deploys are manual and pushes cannot redeploy. **Build and start commands come from detection and cannot be set**; `--root-dir` picks the directory in a monorepo with several deployable ones (the command lists them and exits 1 otherwise); `--repo-branch` picks the repository branch to build (default: the repo's default branch) — detection scans that branch; `--no-auto-deploy` stops pushes redeploying (redeploy by connecting again or from the console); `--watch-paths` narrows which pushes redeploy it (same patterns as `insta --agent compute watch-paths`); `--port` overrides the detected listen port. Connecting again **replaces** the service's current source. `--branch` is the InstaCloud environment the service is on. Gated: `deploy`; needs admin. Cloud-only (insta-oss 501s) |
| `insta --agent compute watch-paths [service]` [`--set <patterns>`] [`--clear`] [`--branch <b>`] [`--json`] | show or change which paths make a push redeploy a compute service. No flag prints them — an ordinary member read (gated `service.read`). `--set` takes a **comma-separated** list of gitignore patterns — quote them, or the shell expands the `*` — matched against paths **relative to the repository root, not to the service's root directory**: a monorepo push that touched nothing on the list leaves this service alone. A leading `!` excludes, under git's own rule that a path cannot be re-included once an earlier pattern took its directory (so "everything but one tree" is `'**,!docs,!docs/**'`, not `'**,!docs/**'`). **Two shapes are a 400**, and they are the natural first attempts: a list of *only* exclusions (`'!docs/**'` — nothing is watched until a pattern includes something), and `{}` braces (`'src/**/*.{ts,tsx}'` — gitignore has no brace expansion, so write one pattern per alternative). `--clear` removes the filter: every push that deploys this service deploys it again. Both writes are gated `deploy` and need admin; neither rebuilds the service — this changes which pushes deploy, not what a deploy builds. **Fails open**: when GitHub cannot report what a push changed (a force-push, or a comparison of **300 or more** files, which is where its list stops being complete) every tracked service deploys, rather than risk skipping a real change. Cloud-only (insta-oss 501s) |
| `insta --agent compute disconnect-repo [service]` [`--branch <b>`] [`--json`] | disconnect the GitHub repository from a compute service — it keeps running its current image, pushes no longer deploy it, its build history stays. Run it before an `insta --agent deploy` onto that service, or pass `--replace-source` there: a dir/image deploy onto a repo-connected service is otherwise refused (409). Gated: `deploy`; needs admin. Cloud-only (insta-oss 501s) |
| `insta --agent postgres always-on on\|off [service]` [`--branch --json`] | same dial for a postgres service: `off` (default) suspends the idle instance — first connection after idle cold-starts; `on` keeps it warm |
| `insta --agent agent manifest` [`--json`] | agent-legible env view: each branch's db / storage / compute + URLs. Database resources carry `ref.pgVersion` (`--json`; the Postgres major, root and branch rows alike) and **(CLI ≥ 0.0.57)** a `pg 16` badge on the printed line |
| `insta --agent <compute\|postgres\|redis\|mysql\|mongodb> metrics [service]` [`--branch --from --to --step --json`] | service metrics, under every service group — last value per series (`--json` for the points); compute + managed DBs (redis/mysql/mongodb) are Fly-backed and full, postgres is provider-limited |
| `insta --agent <compute\|postgres\|redis\|mysql\|mongodb> logs [service]` [`--branch --limit --region --instance --deploy --json`] [`--from <t>`] [`--to <t>`] [`--since <dur>`] | logs, under every service group (compute + managed DBs=Fly, full; postgres=provider-limited). **Without a window, one recent provider page (~100 lines) comes back regardless of `--limit`** (the provider cursor only pages forward) — the answer says so in a `note` when cut. `--from`/`--to` (unix seconds or ISO-8601) or `--since` (`90s`/`30m`/`2h`/`1d`) page a time window (~7-day retention, up to 5000 lines). `--deploy` shows **deploy events** (Fly machine lifecycle: created/started/…) instead of runtime logs — any Fly-backed group (compute/redis/mysql/mongodb), not postgres; window flags don't apply to it |
| `insta --agent <redis\|mysql\|mongodb> status [service]` [`--branch --json`] | a managed-DB service's live runtime health: `healthy` \| `crashed` \| `starting` \| `standby` (scaled to zero, wakes on request — normal) \| `none` \| `unknown`. Reads `runtime-health`, filtered to the resolved service; `--json` prints that service's entry verbatim. Ungated |
| `insta --agent <redis\|mysql\|mongodb> limits [service]` [`--memory <size>`] [`--cpu <n>`] [`--branch --json`] | show or set a managed-DB service's **resource ceiling** — **any plan within the free cap; raising ABOVE the free cap needs a paid plan** (free → 403 beyond it; lowering is free on every plan). Same shape as `compute limits`: `--memory` is the dial, `--cpu` an optional override. Bare = read (ceiling + plan max) |
| `insta --agent <redis\|mysql\|mongodb> volume [service]` [`--size <Gi>`] [`--branch --json`] | show or grow a managed-DB service's data volume (mounted at the image's data directory; no separate attach step — it exists from creation). Bare = read (size, plan cap — any plan). `--size` grows it — **paid plans, grow-only**. **No `--delete`**: a managed database's volume is its data directory and cannot be removed on its own (the platform refuses it — "delete the service instead"); `insta --agent service remove <type> <name>` is the only way off one |
| `insta --agent <redis\|mysql\|mongodb> always-on on\|off [service]` [`--branch --json`] | idle-mode dial, same semantics as `compute always-on`: `on` = machines never scale to zero, `off` = scale-to-zero. **All plans**; billing is actual usage either way |
| `insta --agent <redis\|mysql\|mongodb> query <service> [args...]` [`--branch --json`] [`--database <db>`] | run one command/statement against the service via the console exec API — redis takes a pre-tokenized argv (e.g. `GET mykey`), mysql/mongodb take one quoted statement. `--database <db>` (**mongodb only**) picks the database to run against (default `admin`). Not for postgres — use `insta --agent postgres url\|connect` / the SQL editor |
| `insta --agent billing usage` [`--from --to --json`] [`--proj [id]`] | usage aggregated by meter, with `costUsd` (snapshotted at collection); org-wide by default, `--proj` narrows to one project (the linked one, or a given id) |
| `insta --agent billing` [`--org <id>`] [`--json`] | current cycle summary: tier / **included usage** / used / overage / **credits** / forecast / status. The last two are separate figures and must never be added: `included usage` is the plan's allowance for this cycle and feeds the **usage** calculation; `credits` is the org's wallet balance and feeds the **amount payable** (it can pay the subscription fee as well as usage beyond the allowance). A `creditsUsd` field still on the JSON wire sums the two — it is legacy, means neither thing, and should not be read |
| `insta --agent billing subscribe <pro\|team>` [`--org`] [`--no-open`] [`--json`] · `insta --agent billing portal` [`--org`] [`--no-open`] [`--json`] | Stripe Checkout to subscribe / Customer Portal to manage (opens a browser; `--no-open` prints the URL; both take the same three flags) |
| `insta --agent agent events` [`--branch <b>`] [`--limit <n>`] [`--json`] | audit + agent-event timeline |
| `insta --agent agent approvals list` [`--status`] [`--json`] · `insta agent approvals approve <id>` [`--json`] · `insta agent approvals deny <id>` [`--json`] | manage gated actions |
| `insta --agent agent observe install` · `report` [`--json`] · `sync` | local credential-audit hook (see below) |
| `insta --agent feedback --type <bug\|feature-request\|friction\|other> --component <cli\|mcp\|platform\|skills\|docs\|other> --title <t> --detail <d>` [`--file <path>`] [`--area <a>`] [`--command <c>`] [`--error <e>`] [`--expected <x>`] [`--workaround <w>`] [`--doc <ref>`] [`--severity <blocker\|major\|minor>`] [`--json`] | report an **InstaCloud-side** hurdle to the team (see [Feedback](#feedback)) — never for the user's own app. **(CLI ≥ 0.1.5)** needs a login on InstaCloud — signed out it **exits 2**; works unlinked and on insta-oss; ungated. Non-TTY with missing flags errors (never prompts); transport failures **exit 0** — continue the task, don't retry |
| `insta --agent upgrade` · `insta --agent config autoupdate [on\|off]` | self-update the CLI (binary re-runs the installer; npm uses `npm i -g`). Auto-update is **on by default** pre-1.0; `config autoupdate off` / `INSTA_NO_AUTOUPDATE=1` disables. (CLI ≥ 0.0.5) |
| `insta --agent agent setup` [`--env <prod\|staging>`] [`--mcp-token`] [`--project <id>`] [`--create [name]`] | one-step agent onboarding: **self-installs the CLI globally first** when running from the npx cache with no durable `insta` on PATH (`npm i -g insta@<running version>`; best-effort — a failed install prints the manual fallback and setup continues; CLI ≥ 0.0.37), making `npx -y insta@latest --agent agent setup` a complete cross-platform one-liner (bash / zsh / PowerShell / cmd; see [setup.md](references/setup.md) for the still-accepted old word order); then installs the insta skill user-globally for every coding agent, then registers the **remote MCP server** — Claude Code via `claude mcp add` (user scope) plus a config-file entry for every other detected MCP-capable agent. Default = **OAuth**, no credential written (browser auth on first `/mcp` use); `--mcp-token` requests a durable `insta_` token named `mcp-<hostname>` (Claude Code only; requires login **and token-creation permission**, not a login bypass). Signed agents currently receive `403 unclassified_agent_action` when minting; report it and stop this registration attempt, never retry as human. Incomplete token registration exits nonzero; CLI 0.0.66 and earlier can incorrectly print a login hint and exit 0. Existing registrations are left unchanged, not converted to token auth. Idempotent; `INSTA_MCP_URL` / `INSTA_SKILLS_REPO` override the URL / skill source. **Environment (CLI ≥ 0.0.38): bare `agent setup` always targets prod** — a machine previously switched to staging is switched back (persisted via the `env use` path, foreign session dropped, announced). Staging is the explicit form `--env staging` (also persists the switch); `$INSTA_ENV` counts as explicit; a deliberate custom host (`$INSTA_API_URL`, or a persisted custom apiUrl) is left alone unless `--env` is given. The skill source, the MCP host and its registration name all resolve from that one environment, so a staging setup installs `InsForge/insta-skills#devel` and registers `insta-cloud-staging` → `mcp.staging.instacloud.com` (both environments can coexist on one machine). Ends with a status-aware `next:` hint (login / project create / the prompt.md fetch prompt). **`--project <id>` (CLI ≥ 0.0.48) also links the working directory to that project** after setup — same code path as `insta --agent project link <id>` (writes `./.insta/project.json`, installs per-project stack skills + the observe hook), flowing through the interactive login offer first when there's no session. With no session available (declined login, `-y`, non-TTY) the link is skipped with the manual `insta --agent login` + `insta --agent project link` hint (exit 0); a failed link (bad id / no access) exits 1. This is the flag behind the console Connect panel's single-line CLI setup. **`--create [name]` (CLI ≥ 0.0.52) instead creates a NEW project** and links it — same code path as `insta --agent project create`, with the same login flow, skip-with-hint and exit-1-on-failure behaviour as `--project`; the name is optional and resolves exactly as that command's does — a directory with no usable name (`~`, `~/projects`, `/tmp`) gets that command's guidance and no project, not an error. `--create` and `--project` are mutually exclusive, rejected before anything is installed. See [mcp.md](references/mcp.md) and [Environments](#environments) |
| `insta --agent config install-mcp` [`--agent <claude-code\|cursor\|codex\|opencode\|copilot\|factory-droid>`] [`--mcp-token`] | register the remote MCP server only (no skill install) — default: Claude Code + all detected agents; `--agent` targets one. `--mcp-token` applies only to Claude Code and is rejected with another explicit client; token-creation permission is required (see [MCP authentication](references/mcp.md#connecting)). Failed Claude registration exits nonzero and stops further client registration. Config merges never clobber existing entries; restart the tool afterwards and verify authentication with a tool call |

**`--json` contract (CLI ≥ 0.0.37):** every mutating command an agent chains from takes `--json` —
one JSON document on stdout, progress/diagnostics on stderr, so `$(insta --agent … --json)` always parses.
Deliberate exceptions: `insta --agent run` has no `--json` (its stdout belongs to the child command — its
"injected secrets" banner is on stderr); `insta --agent agent setup` and `insta --agent upgrade` don't have it yet
(their stdout is a live installer stream).

**Approval gate exit code (CLI ≥ 0.0.37):** when a gated command returns `approval_required`, the
hint prints to **stderr** and the CLI **exits 2** — distinct from 1 (error), so scripts/agents can
branch on "approvable: have an admin `insta agent approvals approve <id>`, then re-run". Previously this
printed to stdout and exited 0, which read as success in pipelines.

**Exit 2 is not only approvals (CLI ≥ 0.0.65).** `insta --agent run` reuses it to refuse on a
same-name collision, and `insta --agent feedback` (CLI ≥ 0.1.5) to refuse a signed-out or staging
report, for the same reason — nothing ran, and it is re-runnable once the caller
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
  `insta --agent postgres url <name>`; **no other type does** — bind it, or read the env of a
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
type's **primary** service credentials, and `insta --agent postgres url` / `insta --agent postgres connect` for a
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
`secrets.write`. The new value is visible on the next `insta --agent secrets` fetch immediately, and
**on CLI ≥ 0.0.78** the same command also **applies** it: `set`/`unset` route through the platform's apply step, which
redeploys the compute services that receive the secret, so a running machine picks the change up
without a separate `insta --agent compute restart`. A stopped service that receives it is **started**
by that redeploy (ordinary billed uptime from then on), and the command reports **per service** what
happened. There is still no hot reload: applying a value means replacing the machine, so a redeploy
is the mechanism — it now just happens automatically as part of `set`/`unset` instead of waiting for
a deploy or a manual restart.

**On an older CLI, `set`/`unset` only STORE the value** — they were a bare write with no deploy, so
on one of those you must still follow them with `insta --agent compute restart` (or a deploy) or the
running machine keeps serving the old value. Do not assume the build: auto-update is on by default
pre-1.0 but `insta --agent config autoupdate off` and `INSTA_NO_AUTOUPDATE=1` turn it off, so an agent can be
on an old one indefinitely. Check what the command itself printed rather than the version — the
applying build reports **one line per affected compute service** (`~ … redeployed`, `+ … started`,
`= … (other-branch)`), and its `--json` carries a **`services`** array; a build that prints neither is
the older one, and its value has not been applied anywhere.

**Where the value is written and where a machine restarts are two different scopes.** A `secrets set`
with no `--branch` and no `--service` is written **project-wide** — every branch sees the new value —
but one batch **deploys on exactly one branch**: the one `--branch` names, or the linked branch.
Compute services on every *other* branch hold the new value while still running the old one. They are
listed in the command's own output as `= <service> (other-branch)`, the command still exits 0, and
they pick the value up on their next deploy or on `insta --agent compute restart --branch <name>`.
So "project-wide" says where the value landed, never where a machine restarted — do not read a clean
exit as "every branch is live". `--service` on `secrets set` scopes a user-defined secret to a branch
compute service; it is separate from provider credential binding (`secrets bind`), which is
**unchanged** — a binding still takes effect only on its own deploy or `compute restart` (see
**Provider credentials** above). `secrets list`, `secrets tree`, `secrets
sources`, and `secrets bindings` are all **names only** (`secrets list` covers what the removed `services secrets` used to answer, grouped by service).

## Cron

Scheduled HTTP calls owned by a branch. `cron_schedules` rows, not machines — nothing is provisioned
and nothing is billed for the schedule itself; a run that wakes a scale-to-zero compute service bills
that service's ordinary uptime, same as a request would.

**Everything is UTC.** Five fields, one-minute floor. A schedule pinned to UTC does not keep a fixed
local time, so a job written as `0 0 * * *` moves by an hour in any zone that observes DST — the
console shows both readings for exactly this reason, and `cron preview` prints UTC so the two
surfaces agree.

Two target shapes:

| target | resolution |
|---|---|
| `--service <name>` `--path </api/cron>` | the **service id** is stored, never a URL: the route is resolved at send time, so a redeploy or a region move between two runs is followed rather than papered over. The platform wakes a suspended service first and times that separately, so the request timeout covers your handler and not the cold start. The service must be in the **same org** — not necessarily the same project, though `--service <name>` resolves only among the current branch's services, so a cross-project target needs the API |
| `--url <https://…>` | any external https endpoint. Private, loopback, link-local and cloud-metadata addresses are refused, and DNS is **pinned** between the check and the connection |

Every send carries two headers the tenant's own headers cannot forge, because the platform writes
them last:

```
insta-cron-run-id       stable across retries of the same run — dedupe on this
insta-cron-attempt-id   different every attempt
```

**Make the handler idempotent on `insta-cron-run-id`.** Retries are real, and precisely two things
are retried: a failed **wake**, and a **transport** failure where no byte reached the target. Both are
self-evidently undelivered, so re-sending is safe. A non-2xx answer is retried only if you nominated
that status in the retry policy — which is **API-only today**: there is no `--retry` flag on `create`
or `edit`, and `cron show` only displays the policy. So from the CLI a non-2xx is always terminal. Everything else stops on the first attempt — in particular, once the
request has gone out and no complete answer comes back the run is recorded `unknown` and is **never**
retried, because the platform cannot tell a lost reply from work that ran. For a scale-to-zero service
the wake and the request are deliberately not atomic, so a service that sleeps again in between
produces exactly that. Treat delivery as at-least-once with a stable id.

**An edit replaces the request; it does not merge it.** See the `cron edit` row above: because header
values can never be read back, restating one header is not "changing one header" — it is declaring the
whole request.

Run outcomes worth telling apart in `cron runs`:

| status | meaning |
|---|---|
| `succeeded` | 2xx. Note `202` means the target accepted, not that async work finished |
| `failed` | **anything that went wrong and is yours to see.** A non-2xx that was not retryable or ran out of retries; a wake or transport failure that exhausted its retries; a run that outlived its age cap or attempt cap; and a send the platform refused for a reason that was not your own intent — a frozen org, a stopped machine, a target it will not connect to, or a secret it could not resolve. Most of these carry no HTTP status, so do not read `failed` as "my endpoint answered badly" |
| `retry_wait` | a retryable failure, waiting out its backoff — still counts as an active run, so the next tick is skipped rather than overlapping |
| `unknown` | the request went out and no complete answer came back, or a newer attempt took the run over. **Never retried**: the platform cannot tell a lost reply from work that ran. This is what the run id is for |
| `skipped` | the tick was not sent, with the reason printed beside it. `overlap` — the previous run of this schedule had not finished; schedules do not overlap by default. `late` — the tick was already more than 5 minutes stale when the platform got to it, so it was recorded and abandoned. **A tick past the window is never backfilled** either way. Inside the 5 minutes it is not skipped at all: the most recent missed tick still fires, late, which is the case a handler has to tolerate |
| `cancelled` | nothing was sent because **you** removed the work: the schedule was deleted or paused, its branch or project was deleted, or the run was cancelled, between the run being created and the send boundary re-reading it. Only these count as `cancelled` — a refusal for any other reason is `failed`, so this status never hides a problem you need to act on |

## Volumes

A **volume** is a service's persistent block disk — always a **service attribute**, never a
standalone resource (nothing to create or list separately; it lives and dies with its service):

- **postgres** has one by default — view/grow only: `insta --agent postgres volume` [`--size <Gi>`].
- **compute** opts in at creation (`insta --agent service add compute <name> --volume <gi>`) **or any
  time later** (`insta --agent compute volume <name> --size <gi>` on a volumeless service attaches one;
  the disk mounts when the machine is next created: the **next deploy, or `insta --agent compute restart`**). Mount path defaults to **`/data`**; add `--mount-path /app/storage` to either creation or attachment to choose it. The configured path survives deploys and restarts. Phase 2 changes to an existing path are staged until the next deploy or `insta --agent compute restart` (see the release gate below). Configure the application to use that directory; existing container files are not migrated. Constraints: machine count stays **1** (scale to 1 before attaching), idle
  scale-to-zero uses **stop** (cold wake) instead of suspend, and a volume **never detaches** —
  but it **can be deleted** (`insta --agent compute volume <name> --delete`): the disk and **all its
  data** are destroyed immediately (irreversible — download anything you need first), billing
  stops, and both constraints lift. View/grow/delete: `insta --agent compute volume` [`--size <Gi>`]
  [`--delete`].
- **Any plan may attach up to its plan cap** (10Gi free, 50Gi paid — the platform's sizeless default on every plan since insta-platform #438; the bare read prints it as plan max); viewing is every plan. Only **growth is paid** and
  plan-capped — don't pre-check the plan, just run the command: the backend's 403 carries the
  upgrade hint. **Grow-only** — a provisioned disk cannot shrink.
- Billing is **actual data stored**; the size is a cap, not a price.

### Custom Compute mount paths

```sh
insta --agent service add compute web --volume 1 --mount-path /app/storage
# Or attach to an existing volumeless service, then deploy/restart:
insta --agent compute volume web --size 1 --mount-path /app/storage
insta --agent compute restart web
```

**Phase 2 release gate:** Existing-volume path edits and `compute start-command` require a CLI release containing [CLI #264](https://github.com/InsForge/instacloud-cli/pull/264), plus deployed [Platform #504](https://github.com/InsForge/instacloud-platform/pull/504) and [Compute #291](https://github.com/InsForge/instacloud-compute/pull/291). No minimum released CLI version has been assigned yet. Do not use these commands with `insta@latest` until that release is confirmed; `--help` must show `start-command` and path-only volume editing. Hold this documentation PR's merge until those dependencies are released. The Console workflow additionally requires [Console #502](https://github.com/InsForge/instacloud-console/pull/502).

`--mount-path` requires `--volume` on creation. Confirm `compute volume web --json` reports a non-null volume first. A path-only command against a service without a volume is rejected; use an explicit `--size` to attach one. On an existing volume, `insta --agent compute volume web --mount-path /app/storage` stages a path-only change without creating or resizing the disk. The response reports the configured path, `appliedMountPath` and `pending`; an unchanged normalized path is a no-op. Run Deploy (or `insta --agent compute restart web`) to apply it. This stops the application, mounts the same volume at the new path, and starts it again. Data and permissions stay on the original volume. Failed deployments report failure and attempt to restore the previous runtime configuration; inspect the error if recovery also fails.

Use `insta --agent compute start-command web --set 'exec docker-entrypoint.sh postgres -D /app/storage/pg'` to stage a startup command, `--clear` to restore the image default, or no flag to read it. This command supports `--branch` and `--json`. Stage the mount path and command before deploying once. CLI `secrets set` / `unset` apply immediately and redeploy; they do not stage variables for this transaction. Use Console when variable, path and command changes must land together.

Application configuration is **not** rewritten automatically. In Console, stage the mount path together with environment variables and the Startup Command, then Deploy once. Startup Command is a runtime override through `sh -c`, including for source-built images; it overrides the built image command, rather than changing the build configuration. Leave it empty to use the image default. It is persisted and readable as service settings: keep credentials in secrets, not command text. Avoid deploying new database settings against the old mount path. Omit `--mount-path` on resize to preserve the configured path. Managed database paths remain platform-controlled. Invalid or reserved paths are rejected by the platform.

## Environments

`prod` and `staging` are **separate deployments** — different regions, databases, and auth. A
session minted by one can never authenticate against the other, so `insta --agent env use` drops the stored
session and you log in again. Default is `prod`; nothing changes unless you switch. `--api-url <url>`
on any command overrides the resolved environment for that single invocation only (never persisted;
see the root `--help` Options) — the runtime-debugging escape hatch, distinct from `env use`.

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
npx -y insta@latest --agent agent setup                         # production (any OS — ALWAYS prod, CLI >= 0.0.38)
npx -y insta@latest --agent agent setup --env staging           # staging (any OS; persists the env switch)
npx -y insta@latest --agent agent setup --project <id>          # + link this directory to a project (CLI >= 0.0.48; the console Connect panel's one-liner)
npx -y insta@latest --agent agent setup --create [name]         # + create a NEW project (CLI >= 0.0.52; name defaults to this directory)
curl -fsSL agents.instacloud.com | sh            # production (macOS/Linux, no Node needed)
curl -fsSL agents.staging.instacloud.com | sh    # staging
```

Staging via npx is the `--env staging` one-liner above (CLI ≥ 0.0.38) — it persists the env switch
itself, so no separate `insta --agent env use staging` is needed (and a bare `agent setup` afterwards would
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
#     `insta --agent upgrade`, then retry.
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
`insta --agent domain attach app.example.com` attaches it to a branch's compute service and prints
the DNS records to add **at your registrar** (a `CNAME` for a subdomain, `A`/`AAAA` for an apex, plus a
validation record). The cert + routing are handled for you; `insta --agent domain check <host>`
shows status once DNS propagates. The DNS lives in your zone — you set it, not InstaCloud.

You want to **buy** one → `insta --agent domain search`/`buy`. InstaCloud registers it under its own
registrar account and owns the zone, so nobody is asked for a registrant contact. **Payment registers
the name and nothing else** — `insta --agent domain attach <hostname>` says what it serves, and the
platform then publishes that DNS itself with nothing for you to set. `buy` answers a Stripe Checkout
URL — **a human must pay**; an agent's job is to relay that URL, poll `insta --agent domain status
<name>` until the order is `registered`, then attach.

> Multiple services of every type (postgres/storage/compute, up to 5 each), `insta --agent compute
> scale`/`limits`, and **source-directory deploy** (`insta --agent deploy <dir>` → remote build, no local Docker: the build gateway
> with the dir's Dockerfile or nixpacks on insta-compute, Fly's remote builder of the dir's own Dockerfile on Fly-backed compute) are
> all implemented.

## Dockerfile templates

Moved to [references/deploy.md](references/deploy.md) (backend / full-stack / SPA patterns).

## Templates

A **template** is a whole service set (images, ports, volumes, env) published as one unit —
`insta --agent template deploy <code>` creates those services on a branch, writes their variables, deploys
and health-checks them, instead of a hand-rolled `service add` + `secrets set` + `deploy` sequence.

- **Three modes, chosen by the target.** A bare word (`plausible`) is **always** a registry code. A
  path-looking target (`./plausible`, `/srv/tpl`, `~/tpl`, `sub/dir`) is **always** a local directory and must
  contain `insta.template.yaml` (validated locally, then sent inline). A `github.com` URL fetches
  that file from the repository with your own git credentials and sends it the same way. So a local
  directory never shadows a registry template — `./` is how you opt into the local one.
- **One region for the whole template.** `--region <slug>` (values from `insta --agent config regions`) puts every service the template creates in that region, postgres and compute alike. Omitted, the platform default `us-east` applies. The region is fixed at deploy: there is no change-region operation, so a template wanted elsewhere is a fresh deployment. Deploying the same template again into the branch mints an independent copy, which may take a different region.
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
  the log tail, then re-run the deploy to retry or `insta --agent service remove <type> <name>` to clean up.

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

**(CLI ≥ 0.1.5)** Signed in to InstaCloud (a session or an `insta_` key), the report opens a support
ticket, and the team's reply reaches the user in the console's Support — unless it warns `could not
confirm who you are`, in which case the report is stored but opens no ticket. Signed out, it
**refuses with exit 2** (`{"status":"refused"}` under `--json`): run `insta --agent login`, then send it
again. From staging it always refuses. On insta-oss it sends without an identity and opens no ticket.

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
  `insta agent approvals approve <id>`, then
  you **re-run the unchanged request** (single-use grant). In `branch-specific`, project deletion
  is denied and unprotected service deletion requires approval. Approval never changes policy;
  a human must explicitly update `agent policy` for a lasting rule change.
- `insta --agent agent approvals list` — inspect pending gates. Relay `insta agent approvals approve <id>`
  or `insta agent approvals deny <id>` to a human admin; agents cannot execute either decision.
- `insta --agent agent events [--branch] [--limit]` — timeline of resource side-effects (project/branch creates,
  deploys + URLs, govern decisions) plus ingested agent events.
- **`insta --agent agent observe`** — the local credential-audit hook (a PostToolUse hook for Claude Code / Codex,
  auto-installed on `project create`/`link`). It scans each tool-use for credential exposure
  (AWS / GitHub / Stripe / LLM / DB / JWT / private keys) and appends **redacted fingerprints** (never
  raw secrets) to `./.insta/audit.jsonl`. `insta --agent agent observe report` renders it; `insta --agent agent observe sync`
  uploads findings into the project timeline (idempotent). **(CLI ≥ 0.0.59)** The install
  gitignores its own local state (`.insta/observe/`, `.insta/audit.jsonl`) and writes a
  shell-neutral `.codex/hooks.json` entry with no machine-specific path, so the hook *entries* in
  `.claude/settings.json` / `.codex/hooks.json` are committable while the generated hook files
  under `.insta/observe/` are not; never hide `./.insta/project.json` behind a blanket `.insta/`
  ignore. Paths git already tracks are reported with a `git rm -r --cached …` hint (an ignore
  entry cannot un-track them).
