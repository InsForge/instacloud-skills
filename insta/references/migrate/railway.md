**Railway.** Read `../migrate.md` first: its ordered cutover is the procedure and this file is only what
Railway adds to it. Closest model (services + variables + IaC), so the concept mapping is nearly 1:1 — but
the export has three traps, all measured:

- **`railway variable list` always RESOLVES references**, in both the table and `--json`, and no flag
  shows the raw form. You will never see a `${{…}}`. The hazard runs the other way: a resolved
  `DATABASE_URL` is a literal pointing at **Railway's** Postgres, so copying it verbatim leaves the
  migrated app talking to the database you are leaving. Skip every connection string you are
  binding. The raw form exists only via `railway api` with `variables(… unrendered: true)`, and that
  query returns a **smaller** key set — the `RAILWAY_*` built-ins exist only at render time and are
  not stored variables worth migrating.
- **`railway status` reflects only LIVE deployments.** A stopped Postgres whose volume still holds
  data is indistinguishable from one never provisioned (`latestDeployment: null` for both). Check
  `railway deployment list` per service before concluding a database is unused.
- **A volume cannot be read while its service is stopped** — no offline browse; `render`-style file
  listing refuses with "has no active deployment", so auditing one means starting the service.

**Ask for a project token before you start.** `railway link` and `railway service` are interactive
pickers, and you cannot answer a picker. `RAILWAY_TOKEN` is project-scoped (Project Settings →
Tokens) and `RAILWAY_API_TOKEN` is account-scoped; take the **project** one for a single migration.
Also note `railway link` writes the **global** `~/.railway/config.json` keyed by cwd, not a local
file, so "cd somewhere safe" is not isolation.

**Translate the project yourself.** There is no `render.yaml` equivalent declaring the services:
`railway.json` carries only build and deploy config, and the services live in the project, so read
`railway status --json` for the shape and `railway variable list` per service for the env.

| On Railway | Do this |
|---|---|
| a service, `builder: RAILPACK` or `NIXPACKS` | `insta --agent services add compute X --port <n>`, then `insta --agent compute connect-repo <owner/repo> X` |
| a service built from a Dockerfile | same, `connect-repo` builds the Dockerfile when there is one |
| a service deployed from an image | `insta --agent deploy --image <url> --port <n>` |
| the Postgres service | `insta --agent services add postgres X` |
| Redis / MySQL / MongoDB services | `insta --agent services add redis\|mysql\|mongodb X`. **`--source-name` is mandatory** when you bind one, and it fails closed: `sourceName must be one of REDIS_URL, REDIS_HOST, REDIS_PORT, REDIS_USERNAME, REDIS_PASSWORD`. That is the guard postgres lacks, which is why the `PGHOST` footgun has no redis equivalent. Also: insta's redis DSN is **`rediss://`** (TLS), where Render's is plain `redis://` — celery/kombu rejects a `rediss://` broker without `?ssl_cert_reqs=`, so a verbatim bind is not always sufficient |
| `deploy.startCommand` running migrations | do NOT carry it over as a startup gate; run migrations with `insta --agent compute exec` (see SKILL.md) |
| `${{Postgres.DATABASE_URL}}` and friends | `insta --agent secrets bind DATABASE_URL postgres/X --to compute/Y` |
| an app reading `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` / `PGPORT` | a code change to read `DATABASE_URL`, per step 1 of the cutover in `../migrate.md`. Railway injects these by default, so expect it |
| `RAILWAY_*` built-ins, `PORT` | skip: render-time only, and the platform supplies `PORT` here |
| any other variable | `insta --agent secrets set KEY` |
| a volume | `--volume <gi>` on `insta --agent services add`, or `insta --agent compute volume X --size <gi>`; it mounts at `/data` when the machine is next created, so a `restart` is enough (see the `disk:` row in `migrate/render.md`), and download the source contents while its service still runs |
| `numReplicas` | `insta --agent services scale compute X <n>` (1 to 10, same region, paid plans) |
| a cron service | **not supported yet** (the platform is expected to grow scheduling). Stopgaps, each needing something kept awake: `pg_cron` with `db always-on on`, an in-process scheduler in an always-on compute service, or scheduling from outside the platform |
| multi-region replicas | not available; one region per service, chosen with `--region` at add time |

Railway's Postgres template is **18**, so step 3 is a downgrade. Its volumes carry the same caveat
as any: creating a target volume does not copy contents.
