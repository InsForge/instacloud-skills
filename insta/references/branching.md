# Branching — environments with their data

**This is the capability other platforms don't have**: a branch is a disposable, fully isolated
copy of the whole environment — *including the database's data and the bucket's objects* — created
in seconds. Use it as the default unit of ALL work. Never develop on `main`.

**Services are branch-owned, not project-wide.** Each branch has its own service catalog —
`insta --agent services add/list/remove` all default to the **current** branch, and a service added on one
branch does **not** appear on any other branch, including its parent. `insta --agent branch create` **forks**
the parent's current services at creation time (below); after that, the two branches' catalogs
diverge independently — adding, removing, or scaling a service on one has no effect on the other.

**Secrets and compute env are explicit.** The full names-only inventory is
`project → branch → service → secrets` (`insta --agent secrets tree`; a branch's slice is
`insta --agent secrets list`). Provider-minted credentials live under the service that produced them with
canonical names (`DATABASE_URL`, `REDIS_URL`, `MYSQL_URL`, `MONGODB_URL`, `AWS_*`,
`BUCKET_NAME`, …). `insta --agent secrets` and `insta --agent run` carry one set per type from
that type's **primary** service on the branch, so a branch's `.env` works out of the box; they do
**not** automatically enter **compute deployments**, which receive a provider credential only
through an explicit binding. Bind the provider credentials each compute service needs:

```bash
insta --agent secrets sources --branch feat-x
insta --agent secrets bind DATABASE_URL postgres/db --to compute/app --branch feat-x
insta --agent secrets bindings --target compute/app --branch feat-x
```

For direct access to a branch's DB from outside compute (psql, migrations, local tools):
`insta --agent db url --branch feat-x` prints that branch's connection string; `insta --agent db connect --branch
feat-x` opens psql on it. Before any dump or restore, match the client major to the branch's
`pg_version` (`insta --agent services list --json --branch feat-x`; see [operate.md](operate.md)).

`insta --agent secrets set <NAME> --service compute/app` scopes a **user-defined** secret to that compute
service. It is separate from provider credential binding (`insta --agent secrets bind`). Removing a service
deletes secrets and bindings scoped to it; unbound and project-wide secrets are untouched.

## What `insta --agent branch create <name>` actually clones

| Resource | Mechanism | What the clone contains |
| --- | --- | --- |
| postgres (each) | copy-on-write DB branch | **the parent's data**, isolated — writes never touch the parent |
| storage (each) | copy-on-write bucket fork | **the parent's objects**, isolated |
| compute (each group) | a fresh isolated app + URL per group | **infrastructure only — no code running yet (cloud)** |
| user secrets + compute credential bindings | parent's branch-scoped `secrets set` values and `secrets bind` rules | copied to the new branch with service ids remapped |

Two consequences to internalize:

- **Data clones; code re-materializes.** On the cloud, the clone's compute is an empty app until
  you `insta --agent deploy --branch <name>` (insta-oss auto-redeploys the parent's image). Deploy is part
  of the branch loop, not an afterthought.
- A legacy project whose root bucket predates snapshots keeps one **shared** bucket — no storage
  isolation. `insta --agent manifest` shows what a branch really has.

**Limits:** ≤10 branches per project (hard). `branch create` does **NOT** switch you; the idle mode
is per service, not per branch — new compute is born always-on on every branch, `main` included, and
`--no-always-on` / `insta --agent compute always-on off` makes a service scale to zero when idle (a cost lever;
compute capacity stays fixed).

## The branch loop (one unit of work)

```bash
insta --agent branch create feat-x [--from <parent>]   # isolated env, parent's data
insta --agent branch switch feat-x                     # per-directory current branch
insta --agent secrets bindings --target compute/app    # confirm inherited compute credential bindings
insta --agent secrets                                  # .env: user secrets + the branch's primary provider credentials
insta --agent deploy . --port 8080                     # put the code on feat-x's compute
# → test against the printed URL (public; verify per deploy.md), iterate freely —
#   nothing you do here (schema, data, deploys) can touch main
```

## Parallel agents: 1 task ↔ 1 git worktree ↔ 1 insta branch

Per-branch isolation makes parallel agent development the natural mode. Bind each worktree to a
branch **before** dispatching:

```bash
git worktree add -b feat-x ../proj-feat-x main   # isolated CODE copy
cd ../proj-feat-x
insta --agent branch create feat-x && insta --agent branch switch feat-x
npm install     # fresh worktrees have NO node_modules — first build fails without this
```

Dispatch one subagent per worktree with a brief like: *"Work only in <dir>. Your environment is
insta --agent branch feat-x (already linked): build, `insta --agent deploy . --port <n>`, capture the printed URL,
verify it serves, then open a PR. Don't touch other branches or switch this directory's link."*
Each agent has its own DB/bucket/compute/URLs — zero collision. In a **shared** checkout, never
`branch switch`; pass `--branch <name>` explicitly instead (switch races the other agents).

## Promotion: merge → migrate → redeploy → validate

**Databases are never merged** — diverged Postgres can't be 3-way merged. Code merges in git;
schema travels as migration **files**:

1. Merge the branch's code in git (parallel-feature conflicts are usually additive — combine).
2. Verify the merged code builds locally *before* the slow deploy.
3. `insta --agent branch switch main` → `insta --agent deploy` the merged code → run the new migration files
   against **main's** DB with `insta --agent compute exec app -- <migrate-cmd>` (the bound credentials are
   already in the compute env; never gate startup on migrations — see deploy.md).
4. **Validate on main's URL** — promotion isn't done until the live result checks out.
5. `insta --agent branch delete feat-x` — tear down the branch env (may hit a `branch.delete` gate).

**Discipline that makes this work:** every schema change is a file under `migrations/` — it must
replay on a branch DB and again on main. Ad-hoc `psql` schema edits on a branch are lost at
promotion.

## Promote a service to main

Code promotion above doesn't create services — if `feat-x` added one `main` never had (a new
compute group, a storage bucket for a feature about to ship), bring it over **structurally** first:

```bash
insta --agent branch merge feat-x --into main     # or: insta --agent branch switch main && insta --agent branch merge feat-x
```

This creates, on `main`, every service `feat-x` has that `main` doesn't — **fresh and empty; no data
is copied** (same rule as code promotion: databases are never merged). Services `main` already has
are skipped (reason `exists` / `cap` / `secret-collision`, printed per service). It's additive only —
nothing on `main` is ever deleted, and re-running it is a no-op for services already merged. Deploy
and seed the newly-created service on `main` same as any other.

## Branch data is disposable by design

Treat branch DB/bucket contents as scratch: experiment, seed, corrupt, measure — then delete the
branch. If an experiment produced data worth keeping, extract it explicitly (dump/script) before
`branch delete`; nothing merges back automatically.
