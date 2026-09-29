**Render.** Read `../migrate.md` first: its ordered cutover is the procedure and this file is only what
Render adds to it. Buildpack-built, so almost never a Dockerfile — `insta --agent compute connect-repo` is the
shortest path. **Its Postgres is 18, so step 3 is a downgrade** into insta's pg16. Step 3 has the tested
procedure for that; it is one filtered line, not a blocker.

**Translate `render.yaml` yourself — there is no importer, and you do not need one.** If the repo
has one, read it and provision from this table rather than interviewing the user. Every row is a
command you already have:

| In `render.yaml` | Do this |
|---|---|
| `databases: [{name: X}]` | `insta --agent service add postgres X` |
| `databases[].diskSizeGB` | nothing to do: database disk sizing is not addressable here |
| `services: [{type: web, name: X}]` | `insta --agent service add compute X --port <n>`. `--port` is optional and stores **`null`**, not `8080`; the 8080 default is applied at *deploy* time. Pass it anyway, and pass it again on `connect-repo` (the port-overwrite note in `../migrate.md`) |
| **nixpacks finds no start command** | **the repo has no `connect-repo` route at all** — every service connected to it fails identically with `build <id> failed: build command failed`, web services included. Measured on `render-examples/celery`, whose three roles live only in their `startCommand:`. Catch it with `insta --agent build <dir>` before touching the platform. **The cheap fix is a `Procfile`, not a Dockerfile** — but nixpacks honours exactly **one** entry (`web:` beats `worker:`), so one repo/root-dir yields one image and one start command for *every* service connected to it. Differentiating roles needs `--root-dir` per role, a Dockerfile per directory, or `deploy --image` per role |
| `type: worker` | a second compute service. **Portless is prebuilt-image-only**, so read the worker notes below before promising it: `service add compute X --port 0` and `connect-repo … --port 0` are both **rejected** (`port must be an integer between 1 and 65535, got: 0`), while `insta --agent deploy --image <ref> --port 0` is **accepted** and is the only path. A repo whose worker identity *is* its `startCommand`, with no Dockerfile, has **no route through `connect-repo`** ("Build and start commands come from detection and cannot be set"). Since the archive lane shipped, the worker does have a route through the local checkout: write a `Dockerfile` whose `CMD` is the worker command and `insta --agent deploy <dir>` it — that lane builds on every plane now. Whether `deploy <dir>` accepts `--port 0` is **unmeasured** (only `deploy --image --port 0` is), so test it before promising a portless worker. Say what you measured rather than improvising |
| `type: cron` | `insta --agent cron create <name> '<expr>' --service <compute> --path </your/endpoint>`. The source's cron runs a **command**; this calls an **HTTP endpoint**, so the work moves into a route on a compute service you already have and the schedule calls it. No always-on needed — a scale-to-zero service is woken for the run. Expressions are **UTC**; check the source's timezone before copying one across. Make the handler idempotent on the `insta-cron-run-id` header: delivery is at-least-once |
| `type: pserv` (private service) | a compute service, but **flag it to the user**: every compute service gets a public default domain — immediately when born empty (a best-effort reservation at creation, since 2026-09-17), otherwise with its first successful deploy (a service created with `--image`, or a plane too old/down to reserve; see `../migrate.md`) — so a Render private service stops being unreachable from the internet either way |
| `runtime: python` / `node` / `ruby` / `go` (any non-`image`; older blueprints spell it `env:`) | `insta --agent compute connect-repo <owner/repo> X` — nixpacks does what the buildpack did |
| `buildCommand:` | **nixpacks does not run the script**, but do not assume nothing in it happens: its Django provider runs `manage.py migrate` itself at start (measured — a full `admin, auth, contenttypes, sessions` migrate ran against the bound insta pg16 with no instruction from us). The **asset** half is what it skips, so read the script and re-home anything else: `collectstatic` or an `npm run build` needs a `Dockerfile` or nixpacks' own detected build step. A migration you want under your control rather than run at every boot belongs in `insta --agent compute exec` |
| `startCommand:` | nixpacks picks its own, which is often not this one. If the app needs a specific server invocation (`gunicorn mysite.asgi:application -k uvicorn.workers.UvicornWorker`, a `-w` count, an ASGI vs WSGI entrypoint), that is a `Dockerfile` `CMD`, so this row can turn the whole service into the Dockerfile lane |
| `runtime: image`, `image.url` | `insta --agent deploy --image <url> --port <n>` instead; do NOT reach for connect-repo |
| `envVars: [{fromDatabase: {...}}]` | `insta --agent secrets bind DATABASE_URL postgres/X --to compute/Y` |
| `envVars: [{fromService: {...}}]` | **bind it if the target is a credential-minting service** — `redis`, `mysql` and `mongodb` all are, so `insta --agent secrets bind <NAME> redis/X --to compute/Y --source-name REDIS_URL` is right and copying the DSN as a plain secret is the anti-pattern `../migrate.md` warns about. Only a `fromService` pointing at another **compute** service has to become a plain secret |
| `envVars: [{value: V}]` | `insta --agent secrets set KEY V` |
| `envVars: [{generateValue: true}]` | Render invented it. **Carry the existing value over, do not regenerate** — for a Django `SECRET_KEY` a new one logs out every session, and for an app's own signing keys it invalidates issued tokens |
| `envVars: [{sync: false}]` | never in the file. Read it from the API below, or ask the user |
| `maxmemoryPolicy:` on a redis | no insta knob. Render's own queue examples set `noeviction` deliberately, so tell the user their queue's eviction behaviour is not reproducible here |
| `ipAllowList: []` on a datastore | no insta knob, and the default runs the **other way**: a provisioned redis came back `public=true`. A Render datastore restricted to internal connections becomes publicly addressable here, so flag it like the `pserv` row |
| `envVarGroups:` | **not returned by the env-vars API** (see below); resolve these from the dashboard |
| `disk: {mountPath, sizeGB}` | `--volume <gi>` on `insta --agent service add`, or `insta --agent compute volume X --size <gi>` later. **The disk appears when the machine is next created, so `insta --agent compute restart X` is enough — no rebuild.** Measured twice on a running volumeless service: attach, restart only, and `/data` is mounted; the platform labels that event `wake`, not `deploy`, which is the mechanism. A volume attached *before* the first deploy is present on that first deploy. (The other skill files now say "deploy or restart"; the CLI's own string still says "the next deploy", which is true but not the cheapest path — on a nixpacks service that difference is a 10-second restart versus a full rebuild.) **Do not mirror Render's `sizeGB`:** attach at the free 10Gi cap, because growing is paid-plan-only even from 1Gi to 2Gi and shrinking is impossible, so a literal small size is a one-way door |
| `disk` holding **user uploads** | the volume is usually the wrong tool: prefer `insta --agent service add storage <n>` plus an S3 upload provider (see the addon table), which is the only option that survives scale-out. If you keep the volume, the path fix must be **in the image** — a `Dockerfile` symlink to `/data` — because a symlink made with `compute exec` is wiped on the next restart (measured). Check whether the framework can be pointed at the mount instead (Strapi: `server.dirs.public`), and note a fresh volume contains only `lost+found`, so a framework that requires its upload directory to pre-exist will crashloop until you create it |
| `healthCheckPath` | not a knob here; insta health-checks the port |
| `numInstances` | `insta --agent compute scale <n> X` (1 to 10, same region, paid plans) |
| `plan:` | `insta --agent compute limits` / `insta --agent postgres limits` |
| `region:` | `--region` on `insta --agent service add` for a single service, or `--region` on `insta --agent template deploy` for a whole template (values from `insta --agent config regions`) |
| `autoDeploy: false` | nothing to do, and the default runs the other way for a **public** repo: `connect-repo --public` prints `deploys are manual from here: pushes will not redeploy (public repo)`, so nothing auto-deploys until you ask. `builds.auto_deploy` is not implemented on the compute plane either |

**Check for platform-detection env vars before you deploy anything.** Apps routinely branch on
whether the *source platform's own* variable is present, and every one of those branches flips when
the app lands here. The idiom to grep for is a bare presence test on the platform name:

```bash
grep -rnE "RENDER|DYNO|HEROKU|RAILWAY|FLY_APP_NAME|FLY_ALLOC_ID|VERCEL" --include='*.py' \
  --include='*.js' --include='*.ts' --include='*.rb' --include='*.go' .
```

`render-examples/django` is the worked example, and it fails **both** ways:

```python
DEBUG = 'RENDER' not in os.environ            # no RENDER here, so DEBUG becomes True
ALLOWED_HOSTS = []
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME: ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
```

`ALLOWED_HOSTS` stays empty, so Django answers **HTTP 400 `DisallowedHost` to every request** on the
insta domain. **The platform reports the service as healthy while this happens**, because the check
is TCP on the port (`adapters/fly.ts`: `config.checks = { port: { type: 'tcp' } }`) and the app is
listening — it just refuses every request. `insta --agent compute status` looking fine proves nothing; curl
the URL.

All three outcomes below were **measured end to end** on this repo (prod, insta-compute, 2026-09-09),
after `connect-repo` built it with nixpacks and the `DATABASE_URL` binding worked:

| what you set | result |
|---|---|
| nothing | **400** `DisallowedHost` on every request |
| `RENDER_EXTERNAL_HOSTNAME=<insta domain>` **only** | **200**, the page serves |
| that **plus** `RENDER=1` | **500** |

Read the ladder before copying the middle row. It works because `DEBUG` keys off `RENDER`, which
stays unset, so the host list gets its entry while the manifest static-files backend never switches
on. Adding `RENDER=1` flips `DEBUG=False`, which activates that backend, whose manifest the
`collectstatic` in `buildCommand` was supposed to build — hence the 500. **So the middle row leaves
the app serving with `DEBUG=True`, which leaks tracebacks and is not an end state.** Use it to get a
cutover answering, then fix it properly: give the app its own way to set `ALLOWED_HOSTS` and `DEBUG`
from env instead of impersonating the platform it left, and re-home the static build per the
`buildCommand` row.

**Every source hits this, and the per-source table is in `../migrate.md` step 1, because it is
cross-source by construction.** Render is the mildest of the four.

**And there is nothing on this side for it to read.** `PORT` is the only variable the *control
plane* adds (`provisioning/deploy.ts`: `const env = { PORT: String(port), ...envBundle }`), and
everything else you set came from a secret or a binding. The machine env is not that short, though:
the orchestrator adds its own, measured on a live machine — `KUBERNETES_SERVICE_HOST`,
`KUBERNETES_PORT_443_TCP*`, `INTERNAL_DNS_*`, and per sibling service
`INSTA_SVC_<hex>_SERVICE_HOST` / `_SERVICE_PORT`. So there **is** in-cluster discovery for siblings,
and an app grepping its env for platform markers will see `KUBERNETES_*`. What none of them carry is
the service's **own public domain**, which is the point here. There is no
insta equivalent of `RENDER_EXTERNAL_HOSTNAME`, `RAILWAY_PUBLIC_DOMAIN` or `FLY_APP_NAME`, so an app
cannot discover its own public domain here. **Read the domain off `insta --agent service list` and set it
explicitly** into whatever name the app reads. Do not wait for the app to work it out.

Note this problem belongs to the *pair* of platforms, not to the target: an app leaving Fly for
Railway breaks the same way (`.fly.dev` is a literal in Fly's own example, and Railway serves it at
`*.up.railway.app`), and Railway's own Fly and Render guides do not mention it either. Nobody
documents this, so do not expect the source platform's migration docs to have warned the user.

A quieter cousin: a config helper with a **fallback default** hides a failed binding instead of
reporting it. `dj_database_url.config(default='postgresql://…@localhost:5432/…')` means a missing
`DATABASE_URL` degrades to localhost, so a bind you forgot looks like a network fault. Confirm the
value on the machine (step 5) rather than inferring it from the app's behaviour.

**Env var values come from the API, not the CLI.** The Render CLI has **no** env-var subcommand at
all (`deploys`, `jobs`, `keyvalues`, `logs`, `postgres`, `restart`, `services`, `workflows`,
`workspaces`, `blueprints`, `environments`, `projects`, plus auth and session commands — that is the
whole surface). The REST API does return values:

```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/$SVC/env-vars" | jq -r '.[] | "\(.envVar.key)"'
```

Each item carries `key` **and** `value`, so this is how a `generateValue` or `sync: false` secret is
recovered without the dashboard. Two limits: it returns only vars belonging **directly** to the
service, so an `envVarGroups` member is invisible here, and the user has to mint the API key
(Dashboard → Account Settings → API Keys) because there is no CLI login that yields one. **Ask for
that key at the start**, not after provisioning. Print keys only; never echo a value into the
transcript.

CLI shape, measured rather than read off the docs: `render services -o json --confirm` returns
services **and** databases together; `render psql <id> --command "…" -o json --confirm` is the
**only** non-interactive query path; `render postgres get` does **not** expose a connection string
(dashboard only); `render jobs create` covers one-offs and `render logs` / `render restart` /
`render deploys` exist, but **scaling and custom domains have no CLI command at all**. There is no
maintenance-mode switch, so step 2 means scaling each service to zero or suspending it by hand.
Render Key Value (`render kv`) is the Redis equivalent. A **free** Postgres carries an `expiresAt`
30 days out, is capped at 1 GB, defaults its `ipAllowList` to `0.0.0.0/0`, and has **no backups and
no logical exports** — the connection string is the only way data leaves.
