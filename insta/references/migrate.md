# Migrate an app in from another platform

Move a running app (Heroku, Railway, Fly, Render) onto InstaCloud: provision, move env and data,
cut over. The reader-facing walkthroughs are `docs.instacloud.com/migrate/`, one page each for render,
railway, fly and insforge, and they are deliberately thin: they hand the user a prompt and point at
this runbook, so **this file is what actually gets followed.** Those pages deliberately do NOT list these
steps, so do not add detail there when it belongs here. The one thing they do promise the reader is
that the source stops taking writes before the target starts, which is the rollback boundary below.
Everything else lives here: the ordering and the pass conditions that keep a cutover from silently
losing writes.

**Running as an agent.** Every `insta` invocation below carries `--agent`, per SKILL.md's rule:
always pass it, including for read-only commands, and do not rely on environment detection. The
session is project-bound, so a command without one fails with `agent session missing, expired, or
for another project/environment`.

**Recovering from that error: always pass `--env`.**

```bash
insta --agent env                                   # read the env you are ON first
insta --agent agent setup --env <that env> -y       # NEVER bare
```

`--env` defaults to **prod**, and its own help says "switches and persists, like `insta env use`"
(`cli/src/index.ts`). `setup.ts` is explicit about what that costs: the switch "goes through
`env use` — the one path that persists the choice and **drops the now-foreign session**". So
`insta --agent agent setup` with no `--env` on a staging machine logs the whole machine out of
staging, for every project. **That turns a one-project session error into a machine-wide outage** —
measured, on this machine, during the validation run this file came from.
If the login itself is gone (`insta --agent status` shows `user: (not logged in)` — `env` prints no
login state — and commands return `unauthorized (HTTP 401)`), you can log back in yourself only if
you were handed credentials: `insta --agent login --api-key "$INSTA_API_KEY"` (an `insta_` token) or
`insta --agent login --email <email>` with `$INSTA_PASSWORD` set. Every other mode (`--device`, bare
`login`) needs a human at a browser: relay `insta login` and stop.
**Never remove `--agent` to get past a governance refusal**; relay the approval command to a human
admin and retry the unchanged request.

**A stateless app is a supported shape, and the cutover is shorter for it.** Steps 3 and 4 are
entirely Postgres and their pass conditions are `psql` diffs. An app with no database migrates in
steps 0, 1, 2, 5, 6 and 7, dropping `service add postgres`, `secrets bind` and the psql lines from
step 1. Step 2 stays: it is the writer barrier, not a Postgres check, and "no database" rarely means
"no state" — a worker posting to a third-party API or a cron sending mail is still a writer, so stop
the source's workers and cron (and the target's proving deploy) before cutting traffic. Read
literally the ordering below cannot be completed without a database; that is a gap in the writing,
not a claim the app is unsupported.

## Where the source-specific part lives

The cutover below is the same whatever you are migrating from. What differs is only how you get things **out of
the source**, and what that platform's apps assume about themselves. That part has a file each:

| Source | File | What it covers |
|---|---|---|
| **Render** | `migrate/render.md` | `render.yaml` and the env-vars API, the `ALLOWED_HOSTS` 400, the blueprint field mapping |
| **Railway** | `migrate/railway.md` | the project token, translating a project by hand, the volume caveat |
| **Fly** | `migrate/fly.md` | `fly.toml` as the source of `--port`, and secrets that can only be read off a running machine |
| **InsForge** (self-hosted or Cloud) | `migrate/insforge.md` | standing the backend itself up: init SQL, the five provider credentials, the Deno host |

**Read your source's file in addition to this one, never instead of it.** Everything those files say about steps,
`$PG`, the writer barrier or the rollback boundary refers back to the cutover here. Heroku is the exception: its
five lines are at the end of this file rather than in one of their own.

## The ordered cutover

Each step has a condition that must hold before the next one runs. **The ordering is the point:**
once the target accepts writes, "roll back to the source" silently discards them.

**Secret hygiene, for every step below.** A migration moves credentials by definition, so the
default is: **never let a value reach stdout.** Pipe it (`… | insta --agent secrets set NAME`), or set it
from a file, or have the user paste it into a prompt. When you must *check* a value, compare a
redacted form or a hash, not the value — the pattern used in step 5. Never write a resolved
credential to a file you leave behind, and if an intermediate file is unavoidable, delete it in the
same step that created it. Print **names**, never values.

**0. Link a project.** The cutover assumes one exists.

```bash
insta --agent project create <name>        # or: insta --agent project link <project-id>
```

**The link is per directory, but it is resolved by walking UP**, git-style: `findProjectRoot`
climbs until it finds a directory containing `.insta/project.json`, and `writeProject` writes to
whatever that search returns (`cli/src/config.ts`). The consequence is the part that bites. Once
`~/.insta/project.json` exists, **every directory under your home that has no `.insta/` of its own
resolves to your home directory**, so running this in a scratch directory silently repoints the
link that all of those directories share. Observed on prod, 2026-09-09: a create run in a fresh
temp dir created no local `.insta/` at all and rewrote `~/.insta/project.json`, while printing
`linked ./.insta/project.json`, which reads as local.

**So do not rely on the link at all when you are one of several workers.** Pass
`INSTA_PROJECT_ID` (plus `INSTA_ORG_ID`), which `readProject` honours ahead of any file: "an
explicit parameter outranks ambient state". If you do use the link, capture the resolved file first
and restore it after.

**`INSTA_PROJECT_ID` alone is not enough for parallel workers, though.** The **agent session** is a
second file found by the *same* walk-up — `loadAgentSession` and `saveAgentSession` both resolve
`findProjectRoot(cwd) ?? cwd` and read `.insta/agent-session.json` (`cli/src/agent.ts`) — and the
session is rejected unless `session.projectId` equals the project you are targeting. So N workers
sharing one home share **one** session file keyed to **one** project, and every worker but that one
fails with `agent session missing, expired, or for another project/environment` no matter what
`INSTA_PROJECT_ID` says. **Give each worker its own directory containing a `.insta/project.json`**
so the walk-up stops there and each gets its own session file. Note `~/.insta/project.json` is a different file from `~/.insta/config.json`,
which holds the env and session and carries no project link.

**1. Provision, bind, deploy.**

**Pre-flight, before you deploy anything: find out how the app learns its own hostname.** This is
pure code reading, it needs no platform access, and doing it now is the difference between a planned
step and a mystery 400 after the cutover. Open the app's settings and answer two questions:

- **Does it gate anything on its public host?** Django `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`,
  Rails `config.hosts`, Phoenix `check_origin`, and any OAuth callback, cookie domain or absolute
  link builder.
- **Where does it read the host from?** A variable you can set (Render's
  `RENDER_EXTERNAL_HOSTNAME`), or a literal you must edit (Fly's `.fly.dev`, Heroku's fallback
  list)?

**Every source hits this, but the shape differs, and Render is the mildest case.** Read from each
platform's own official Django example, which is what real user code is derived from:

| source | what its example does | what you get here |
|---|---|---|
| **Render** | `ALLOWED_HOSTS` appended from `RENDER_EXTERNAL_HOSTNAME` | 400, and **one env var fixes it** (the ladder in `migrate/render.md`) |
| **Heroku** | `IS_HEROKU_APP = "DYNO" in os.environ`; then `["*"]` if set, else `[".localhost", "127.0.0.1", "[::1]", "0.0.0.0", "[::]"]` | 400, and **no env var can fix it** — both branches are literals, so the code must change. `DEBUG` keys off `ENVIRONMENT`, not the platform, so at least it stays off |
| **Fly** | hardcoded `['localhost', '127.0.0.1', '.fly.dev']` (their guide names no Fly variable) | 400, **code must change**. Do not go looking for `FLY_APP_NAME` in the settings; it is usually not there |
| **Railway** | `ALLOWED_HOSTS = ["*"]`, unconditional | **works as-is** — they bought that by giving up the check entirely |

So the useful expectation is not "grep for the platform variable" but **"assume the app cannot name
its own new hostname, and find out how it learns one."** Sometimes that is a variable you can set,
often it is a literal you have to edit, and occasionally (Railway) there is nothing to do.

**`insta --agent build <dir>` is the cheapest pre-flight and this file used not to mention it.** Local,
offline, no login. It prints the builder, the detected install/build/start commands, the port and
why, and the Dockerfile nixpacks would generate — and it **exits 1 on a repo that has no detectable
start command**, which is the celery blocker, before you touch the platform. **Caveat, measured:**
on a Dockerfile-less repo it needs a local `nixpacks` binary, which the CLI never installs; without
one it reports `verdict: failed` for the *wrong reason* (`nixpacks is not installed to generate
one`, start-command check `skipped`) on a repo the server lane builds fine. Install nixpacks first.

**Write down the variable name, or the file and line to change.** You cannot set the value yet —
on insta-compute the host is minted by the plane at first deploy, so it does not exist until after
the deploy below (`adapters/insta-compute.ts`: routeKey is "learned at first deploy", and
`access_host` "is the only source of truth"). **That is why this is two steps: decide here, apply in
step 5.** If the answer was "a literal I must edit", make that edit NOW, before the deploy — but you cannot put
the real host in it, because the host does not exist until that deploy succeeds. Replace the literal with a
neutral variable of your own (`APP_HOSTNAME`, `DJANGO_ALLOWED_HOSTS`), deploy, then set it in step 5 and
restart. Editing the code now is what makes step 5 a one-variable fix instead of a rebuild, so the
image is already right.

```bash
insta --agent service add postgres db                          # + redis/storage/… as the source needs
insta --agent service add compute app --port <n>               # REQUIRED: the bind below targets it
insta --agent secrets bind DATABASE_URL postgres/db --to compute/app
insta --agent deploy --image <registry/img> --port <n>          # works on every compute plane
# or: insta --agent deploy <dir> --port <n>                     # any plane, no GitHub needed; Dockerfile optional on insta-compute, required on Fly-backed
# or: insta --agent compute connect-repo <owner/repo> app       # attaches to THIS service; nixpacks if no Dockerfile; redeploys on push
```

**What nixpacks decides for you, and where that bites.** Three of its decisions are silent
regressions against the buildpack the app came from.

- **It pins the language toolchain from a fixed nixpkgs revision, not from your repo.** Confirmed in
  three languages. **Go**: `nixPkgs: ["go"]` at rev `e89cf1c9` (2024-04-07) → **Go 1.22.1**, with
  `go.mod`'s `go 1.14` never consulted; read it off the built binary
  (`grep -abo 'Go buildinf:'` then the adjacent string — a naive `grep 'go1\.'` also matches
  dependency strings). **Node** with no `engines` → **`nodejs_18`**, end-of-life. **Python** →
  **3.12.7**, which is what killed `render-examples/celery`: its 2022 pins die at `import celery`
  with `AttributeError: 'EntryPoints' object has no attribute 'get'`. **The only lever is a
  repo-side pin** (`.python-version`, `runtime.txt`, `engines`) — `connect-repo` exposes no build
  env or build-arg flag.
- **It sets its own env**: `NODE_ENV=production`, `CI=true`, `NPM_CONFIG_PRODUCTION=false` on Node;
  `CGO_ENABLED=0` on Go, which Render does not set and which breaks cgo-linked libraries for a
  reason no build log names.
- **The runtime image carries the whole source tree.** `COPY --from=0 /app/ /app/` under
  `WORKDIR /app/`, so a binary reading data files relative to cwd keeps working — measured on a Go
  app whose `LoadHTMLGlob("resources/*.templ.html")` panics if the glob misses. That is *why*
  buildpack-era apps survive with no Dockerfile, and it also means production images ship source
  and build scripts. Write the idiomatic multi-stage Dockerfile that copies only the binary, and
  that same app panics on boot, **with a green TCP check** masking it. The image also carries
  **`/app/.nixpacks/Dockerfile`**, which is the best post-hoc build audit available: base images,
  nixpkgs rev, build and start commands, copy semantics, in one `exec`.

**Two things about `connect-repo` that will cost you a migration if you do not know them.**

**It overwrites the port you set at `service add`.** `cli/src/commands/github.ts` builds the body as
`port: o.port !== undefined ? parsePort(o.port) : c.port`, where `c` is the *server-side detection
candidate* — the service's own configured port is never consulted. Measured: `0 → 8000` and
`8080 → 8000`, and it happens even when the build then fails. **So repeat the port on the connect:**

```bash
insta --agent compute connect-repo <owner/repo> <svc> --public --port <n>
```

It is invisible otherwise: `service add` does not echo the port, `connect-repo` does not, and
`service list` only shows it inside the `running <image>:<port>` fragment, so an imageless service
shows none. Only `--json` reveals it. Benign for an app that reads `$PORT`; a **silent, guaranteed
dead service** for anything with a hardcoded 3000, 5000 or 4000.

**It is asynchronous, and a failed build looks like a pending one.** It exits 0 printing
`building main now` while the build may already be dead. Confirm before you curl:

```bash
insta --agent compute repo <svc> --json      # → source.last_build.{status,error,image_ref}
```

Nothing else tells you. Plain `insta --agent compute repo` **hides** the build result;
`compute status` sits at `desired=running live=none` indefinitely; and both `logs compute <svc>` and
`logs compute <svc> --deploy` answer `note: operations unavailable (insta-compute 404: not found)`
whenever no machine has ever existed — which reads as a broken logging subsystem rather than a
failed build. If `last_build.status` is `failed`, there is **no host to curl**, so step 1's pass
condition is unreachable rather than failing.

**Do not stop at the `error` string — it is not diagnostic.** All you get is
`build <id> failed: build command failed`, and there is no build-log surface at all
(`logs … --deploy` answers `operations unavailable (insta-compute 404: not found)` because no
machine ever existed). **Reproduce locally to learn why:** `insta --agent build <dir>`, then
`nixpacks build <dir>` for the full output. That is how the celery cause (no detectable start
command) was found.

**Before reaching for a different lane: almost no migration blocker is a lane problem.** Measured
across six real repos, the things that stopped a migration were **app-side** (an `ALLOWED_HOSTS`
that only reads the old platform's variable; a missing `APP_KEY`; a DSN parser that drops
`sslmode`) or **builder-side** (nixpacks detecting no start command; nixpacks pinning a language
version the app predates). None were about how the source reached the builder. The build request
carries only `source`, `build` and `target` — **there is no start-command field at all**, and on
the nixpacks type "only `context_path` is configurable" — so no choice of lane can supply one. When
a build fails, fix the repo (a `Procfile`, a version pin, a committed `Dockerfile`), not the
transport.

**Which lane. `insta --agent deploy <dir>` is now the migration default, on every plane.** The archive
lane shipped (insta-cli#197, and the `source-build` discovery endpoint is on platform main and on
prod), and it changes the answer this file used to give. Measured on staging, 2026-09-11: a
Dockerfile-less `render-examples/express-hello-world` checkout, `insta --agent deploy . --port 3000`,
**HTTP 200** — packed 7 files, `deploying … via the gateway (nixpacks)`, built, deployed. **66
seconds with a warm builder, 6m28s cold** (the remote builder is Fly's; warm it with a throwaway
build before anything time-sensitive).

How the CLI decides, so you can predict it: it asks `GET /projects/:id/source-build?branch=&group=`
and the **platform** answers `flyctl`, `archive`, `local-docker` or `none`. Measured: a Fly-backed
service answers `{"lane":"flyctl"}`, an insta-compute service answers `{"lane":"archive"}` with the
server's own limits (256 MiB archive, 1 GiB extracted, 10,000 files). A platform too old to have
the endpoint answers 404 and the CLI falls back to the old flyctl path unchanged. So:

- **insta-compute target:** `deploy <dir>` packs the directory and the gateway builds it — with the
  Dockerfile if one is present, **nixpacks if not.** No GitHub, no App authorization: this removes
  the one step in this runbook only a human could perform for a private repo.
- **Fly-backed target:** `deploy <dir>` still needs a Dockerfile (the flyctl lane builds it). A Fly
  app has one, so it works; a buildpack app does not, so use `connect-repo` there.

**`connect-repo` is still right for three things:** a private repo the user wants redeployed on
push; a tree the archive lane refuses — symlinks are rejected **at pack time**, by path
(`a deploy archive cannot contain symlinks — the build gateway rejects them: link.txt -> real.txt`),
and so are trees over the three limits; and any case where the code is not checked out locally.

**Neither lane changes what nixpacks does.** Measured: `render-examples/celery` fails through the
archive lane with the identical `build … failed: build command failed` it produced through
`connect-repo`. Same builder, same detection, same pins. The lane is only how the source arrives.


Without the `service add compute` line the bind fails with `service not found on branch:
compute/app`. A deploy materializes env into the machine config, so the binding takes effect with
it. **`insta --agent compute restart` is refused while a service has no image** ("this service has no
machines yet — deploy an image first, then retry"), so a first migration is bind → **deploy**, never
bind → restart.

**Postgres exposes exactly one credential: `DATABASE_URL`.** If the source app reads the discrete
components instead — `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` / `PGPORT`, which is what
Railway injects by default and what `railwayapp-templates/django` reads via `os.environ[...]` —
**point the app at the single DSN rather than trying to reproduce the five.** In Django that is
`dj-database-url`; most stacks accept a DSN directly. Do this as part of the migration, not after.

**A near neighbour: an app that parses the DSN and drops what it does not recognise.** Insta's
postgres DSN ends `?sslmode=require`. An app that does
`const { host, port, database, user, password } = parse(env('DATABASE_URL'))` and passes only those
five to its driver discards the SSL requirement, and the connection is then refused with
**`FATAL: instadb: database "instadb" does not exist`** (measured, same DSN, only `sslmode`
differing) — an error that names the wrong cause entirely and sends people hunting a provisioning
fault. Grep for a DSN parser, not just for `PG*` names.

The reason it must be a code change is that the alternative fails *silently*. `insta --agent secrets bind`
validates the env name only against `^[A-Z][A-Z0-9_]{0,63}$`, and for a postgres source
`--source-name` defaults to the only allowed key, so

```bash
insta --agent secrets bind PGHOST postgres/db --to compute/app    # accepted, and WRONG
```

is accepted and sets `PGHOST` to the **whole connection string**. Nothing complains at bind time;
the app fails later trying to resolve a hostname that is actually a URL. (From
`insta-platform/src/provisioning/userSecrets.ts:78,88` and `secretNames.ts:5`, read at `a79b067`;
not executed.) Splitting the DSN into five plain secrets with `insta --agent secrets set` does work, but
they are then static copies that no longer follow a rotation, which is the whole point of a
binding. Note this asymmetry is postgres-only: `redis`, `mysql` and `mongodb` each expose their
components alongside the URL, so binding `REDIS_HOST` or `MYSQL_USERNAME` is fine.

Deploy an image that carries a **psql client** if you intend to verify from inside the app in step 5
— `nginx:alpine` and friends cannot.
*Pass:* **curl the URL and read the status** — not `insta --agent compute status`, which reports a service
healthy whenever the port accepts TCP, so an app that refuses every request looks identical to one
that works.

```bash
insta --agent service list                    # read the compute row's host column
curl -s -o /dev/null -w '%{http_code}\n' "https://<that host>"
```

Read the host rather than parsing it out of the row: the column position shifts on a service that
has no image yet, so a clever one-liner can hand you the wrong string silently.

Any 2xx/3xx, or a 5xx from the app's own code, means it is serving and step 5 can proceed. **A 400
here is the hostname problem from the pre-flight**, not a database or build fault, and it is fixed
in step 5 rather than by redeploying. Working against an empty database is expected at this point.

**Then stop it again, before anything else.**

```bash
insta --agent compute stop <service>
```

This deploy exists to prove the image builds, the binding resolves and the app serves. It must not
leave a **second writable system standing.** A compute service has **no domain until its first
successful deploy** — measured on three separate services: `service add` leaves `domain: null`,
and the host is minted with the image, which is what the pre-flight above already says. (Both
`service add --help` and an earlier version of this note claimed `add` assigns one; they are
wrong.) But domain and machine arrive together, so the moment this deploy succeeds the app **is**
reachable on the public internet, and any write it takes — a session row, a signup, an analytics insert — lands in
the target database *before* the restore. That breaks the cutover twice over: step 3 requires an
empty target and would now collide, and step 2's promise that only one side accepts writes is no
longer true. `compute stop` takes it offline and, per the CLI, "traffic will NOT wake it until
`start`". Step 5 brings it back with `start` then `restart`, which is the sequence it already
prescribes for a stopped service.

**But the stop cannot prevent the write that matters most.** nixpacks bakes migrations into the
start command: measured on a Django repo, the build record's `start_command` is
`python manage.py migrate && gunicorn mysite.wsgi`. That runs at **container start**, and measured on prod it lands while status is still
**`deploying`** — before the build ever reports `live`. So it precedes step 1's *pass condition*,
not merely the curl: `live` is not a checkpoint you can get ahead of. Nothing prevents it either,
since `compute stop` is only reachable after the deploy that causes it. On a real cutover it left the target
holding **10 tables and 48 rows** (18 `django_migrations`, 24 `auth_permission`, 6 `django_content_type`). The stop prevents *traffic-driven* writes only.

**Read the start command as soon as the build starts — you cannot read it earlier.** Before
`connect-repo` the record is only `{"source":{"type":"image","image":null}}`, with no
`start_command` at all, so this is not a pre-flight check. Measured: the field appears **~14s
after** `connect-repo` while status is still `building`, and the write lands **1m57s later**, so
there is a usable two-minute window:

```bash
insta --agent compute repo <svc> --json     # → source.start_command
```

If it migrates at boot, then **step 3's emptiness check will fail and re-adding the postgres service
is the expected path, not an exception.** **Do not react by trying to strip the migrate out of the
start command** (you cannot anyway — `connect-repo` cannot set commands): measured, once the target
holds a faithful restore the boot-migrate is **idempotent**, because `django_migrations` travels in
the dump. After `start`+`restart` the app re-ran `manage.py migrate` against the restored database
and the count diff was still identical. The boot-migrate is only dangerous *before* the restore,
which is exactly why the ordering works. Prefer a fresh postgres service after this proving deploy
over trying to clean the one it touched.

**A deploy also defeats the stop.** Measured: after an explicit `compute stop`, an
`insta --agent deploy --image …` brought the service live and answering **200** on its public URL
while `compute status` still reported `desired=stopped  live=running`. The status is not a safety
check. Do not redeploy anything during steps 3 and 4. (`compute exec` does the same, which this
file already warns about.)

**The nixpacks image has no psql client** (measured), so any advice to verify the database from
inside the app's container does not apply on the lane this file prescribes. Verify from your own
shell against `insta --agent postgres url`, and use step 5's redacted `printenv` for what the machine
holds.

**`compute stop` is accepted on a service with no machine** (`stop → desired=stopped (live: none)`),
unlike `restart`, so it is safe to run even after a failed build.

**2. Stop the writers — on BOTH sides.**

Source: maintenance/read-only **and** stop its workers and cron. A read-only web tier with a live
worker is still writing. Heroku: `heroku maintenance:on` plus `heroku ps:scale worker=0`.
Railway / Fly / Render: no single maintenance switch — stop or scale each service by hand.

Target: `insta --agent compute stop <service>` for what step 1 deployed, plus any worker.
**Do not infer target quiescence from "nothing has been rebound yet"** — after step 1 the target
app is live and can write.

**`stop` is a traffic barrier, not an execution barrier.** `insta --agent compute exec` succeeds on a
stopped service and leaves it **live** (`status` then reads `desired=stopped live=running`), so any
`exec` — including any query you run against the target — re-animates the machine. Re-`stop` after
using it.
*Pass:* no write traffic at either end.

**3. Copy into a CLEAN target.**

**Read both majors first.** They decide which client you need, and whether the schema has hard
blockers.

```bash
insta --agent service list                       # target major, e.g. postgres/db [pg16], NOT selectable
psql "$SOURCE_URL" -c 'show server_version'
```

The one hard rule is `client_major >= source_major`. A newer server cannot be read by an older
client and there is no escape hatch: `pg_dump` 16 against an 18 server aborts with
`pg_dump: error: aborting because of server version mismatch`, and `--format=custom` makes it worse,
not better, because `pg_restore` 16 rejects an 18 archive at the header
(`unsupported version (1.16) in file header`). So always dump with a client at or above the source
major, and use plain format when the target is older, because plain text is the only form you can
filter.

**Upgrade or equal (source <= target).** Not "nothing special", which is what this said until a
regression run disproved it. **The CLIENT major decides, not the source server.** Measured: a pg16
source into a pg16 target, dumped with a local `pg_dump` 18.3, aborts the restore with
`ERROR: unrecognized configuration parameter "transaction_timeout"` (exit 3) in the preamble, before
a single table is created. The same bites a self-hosted InsForge, whose PG15 image ships a pg_dump 18.
**So every dump goes through the same `awk`, whichever direction you are going** — it is already in the
restore command below, and the downgrade section explains each line of it. It costs nothing when there
is nothing to strip, and `pg_dump --version` tells you whether there is.

**Two things about `service add postgres` that will look like your mistake and are not.** It can
answer `HTTP 504` after the provisioning has already failed and rolled the service back, so the name
is simply absent from `service list` — re-run it, it is not a duplicate. And `secrets bind` against
a postgres still showing `[creating]` fails with
`credential not found: postgres/<name>.DATABASE_URL (HTTP 404)`: the credential is minted when the
service goes `[active]`, so wait for that rather than assuming the bind syntax is wrong.

**Set `PG` first, and set it to the service you are actually restoring into.** If step 3 had you
add a **fresh** postgres service because the proving deploy dirtied the first one, then every
command from here to step 5 must name that new one:

```bash
export PG=db2        # ← the FRESH service; plain `db` only if you never re-added
insta --agent service add postgres "$PG"            # FRESH path only — skip when $PG is the step-1 service, it exists
insta --agent secrets bind DATABASE_URL "postgres/$PG" --to compute/<service>   # BOTH paths — an upsert, a no-op when unchanged
```

The `bind` is an upsert on the env name (`provisioning/userSecrets.ts` → `upsertBinding`), so on
the fresh path it replaces the `postgres/db` source from step 1 with no `unbind` first, and on the
plain path it re-asserts what step 1 bound; it refuses only when a *user secret* of the same name
exists. `service add`, by contrast, is not idempotent — run it only for a service that does not
exist yet. It is rules-only until step 5's `restart`, so the stopped app is
not touched by it — but without it step 5 restarts the app onto the **old dirty database** while
every check from here on reports success against `$PG`.

This is the sharpest trap in the whole procedure. With two postgres services a bare
`insta --agent postgres url` fails loudly (`error: multiple postgres services — specify one: db, db2`),
which is the *good* outcome. The bad outcome is copy-pasting the literal `db` positional instead of
`"$PG"`: measured, that restores into, verifies, and cuts over to the **old dirty database** while every check reports success —
`exit 0`, `grep -c '^ERROR'` → 0 — and since step 4 no longer diffs anything, **nothing downstream
catches it either**: the app is rebound and restarted onto the dirty database with every gate green.
Set `PG` once, at the top, and use it for every command from here to step 5.

```bash
set -o pipefail
pg_dump --no-owner --no-privileges "$SOURCE_URL" \
  | awk '!d && /^SET transaction_timeout/ {d=1; next} /^\\restrict / {next} /^\\unrestrict / {next} {print}' \
  | psql -v ON_ERROR_STOP=1 "$(insta --agent postgres url "$PG")" 2>&1 | tee restore.log
grep -c '^ERROR' restore.log              # must print 0
```

**That `awk` is in the command in both directions**, upgrade and downgrade alike, which is why it is
here rather than only in the downgrade block: what it strips depends on the **client** major, not on
which way the majors run. It is a no-op when there is nothing to strip. What each line is for, and
why the ordering inside it matters, is in the downgrade section below.

**Downgrade (source > target).** Render pg18 and Railway pg18 into InstaCloud pg16, which is the
common case but not a universal one: Fly Managed Postgres runs 16, and a self-hosted InsForge runs 15,
which is an upgrade. Read both majors before assuming which way you are going. **This works, at full
fidelity, and it is a tested procedure**, not a workaround. `pg_dump` from 18 emits exactly one
statement pg16 does not know.

**The command is the one above** — there is no separate downgrade pipeline, because the `awk` that
makes a downgrade work is the same `awk` a pg17-or-newer client needs in any direction. Add
`--format=plain` explicitly if your `pg_dump` might default otherwise: **plain text is the only form
you can filter**, and a custom-format archive has no hook for it.

Why each piece of that `awk` is there:

- `SET transaction_timeout = 0;` is a PG17 GUC. Of the 12 `SET`s a PG18 `pg_dump` emits, this is the
  **only** one pg16 rejects. In a 1,400 line realistic dump it is the single offending line.
- `\restrict` / `\unrestrict` are psql meta-commands added by the CVE-2025-8714 fix. They fail only
  on psql older than 15.14 / 16.10 / 17.6 (`invalid command \restrict`, exit 3). Filtering them
  makes the command work on any psql, at the cost of that guard. Acceptable when the source is the
  user's own database, not acceptable for a dump from a third party.
- `--no-owner --no-privileges` is **not optional** against Render or Railway. Without it the restore
  dies on `ERROR: role "render_app" does not exist`.

Custom-format archives have no filter hook, so route them through text:

```bash
pg_restore --no-owner --no-privileges -f - source.dump \
  | awk '!d && /^SET transaction_timeout/ {d=1; next} /^\\restrict / {next} /^\\unrestrict / {next} {print}' \
  | psql -v ON_ERROR_STOP=1 "$(insta --agent postgres url "$PG")"
```

The streamed form above needs no `--exit-on-error`: `pg_restore -f -` only writes SQL, and the
guard is `psql -v ON_ERROR_STOP=1` at the end of the pipe. **What you must never do is run
`pg_restore` directly into the database without `--exit-on-error`.** It reaches full fidelity on a
clean schema, but "ignore all errors" equally swallows every blocker below.

**Hard blockers: PG17/18 constructs that cannot be filtered.** If any appears, the restore stops
there and the schema needs reworking by hand. Escalate to the user with the specific construct
rather than improvising a rewrite.

| Construct | Introduced | Error |
|---|---|---|
| `CREATE COLLATION … provider = builtin` | 17 | `unrecognized collation provider: builtin`, then cascading "collation does not exist" |
| Virtual generated column | 18 | dumped without `STORED`/`VIRTUAL`, so `syntax error at or near ")"` |
| `NOT NULL … NO INHERIT` | 18 | `syntax error at or near "NO"` |
| `ADD CONSTRAINT … NOT NULL … NOT VALID` | 18 | `syntax error at or near "NOT"` |
| `PRIMARY KEY (id, valid_at WITHOUT OVERLAPS)` | 18 | `syntax error at or near "WITHOUT"` |
| `FOREIGN KEY (…, PERIOD valid_at)` | 18 | `syntax error at or near "valid_at"` |
| `CHECK (…) NOT ENFORCED` | 18 | `syntax error at or near "ENFORCED"` |
| `DEFAULT uuidv7()` | 18 | `function uuidv7() does not exist` |
| `JSON_TABLE(…)` in a view | 17 | `syntax error at or near "AS"` |
| `now() AT LOCAL` in a view | 17 | `syntax error at or near "LOCAL"` |
| `random(1, 10)` | 17 | `function random(integer, integer) does not exist` |
| `xmltext(…)` | 17 | `function xmltext(text) does not exist` |
| An extension the target lacks | any | `extension "…" is not available` |

**Two failures that restore with exit 0 and break later.** These are the dangerous ones, because
every guard above passes.

1. **Named `NOT NULL` constraints (PG18).** `c text CONSTRAINT c_must_exist NOT NULL` restores
   clean, and `attnotnull` is set so enforcement survives, but pg16 records **no `pg_constraint`
   row**, so the constraint name is silently gone. A later migration doing
   `ALTER TABLE … DROP CONSTRAINT c_must_exist` will fail on the migrated database only.
2. **PG17/18 SQL inside function bodies.** `pg_dump` emits `SET check_function_bodies = false`, so
   plpgsql bodies are never parsed during a restore. `MERGE … RETURNING` and `RETURNING OLD.*`
   restore silently and fail at call time (`syntax error at or near "RETURNING"`,
   `missing FROM-clause entry for table "old"`). **A clean restore proves nothing about functions** —
   say so when you hand the database over (step 4).

Also expect a catalog difference that is **not** a fidelity loss: PG18 materializes `NOT NULL` as
`contype='n'` rows in `pg_constraint` and pg16 has none, so exclude those rows when diffing
catalogs, after confirming `attnotnull` is set on every column.

**The target must be empty — confirm it, do not assume it.** If the app was up at any point in
step 1, check before restoring rather than trusting that it wrote nothing:

```bash
T="$(insta --agent postgres url "$PG")"        # the target DSN; `$PG` is the service you restore INTO
# A real count(*) per table across every non-system schema — NOT `n_live_tup`, which is an estimate and
# reads 0 for a fully populated table after a stats reset (measured). Must return nothing at all.
psql "$T" -At -c "select string_agg(format(
    'select %L::text, count(*) from %I.%I having count(*) > 0', n.nspname||'.'||c.relname, n.nspname, c.relname),
    ' union all ')
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind = 'r' and n.nspname not in ('pg_catalog','information_schema') and n.nspname not like 'pg_toast%'" \
  | psql "$T" -At        # HAVING does the filtering IN SQL: no delimiter to parse, so a table whose name
                         # contains the separator cannot hide its own row count from an awk filter
```

A single row from a health check or a session store is enough to collide the restore. If anything
is there, drop and re-add the postgres service (below) rather than trying to clean it by hand.

A full dump restored into a populated database is not an incremental
sync: it collides on existing objects and primary keys. **Prefer adding a fresh postgres service**
over dropping the database. `DROP DATABASE` needs a DSN retargeted to `/postgres`, is blocked by
insta's own `pg_cron` session until you `pg_terminate_backend` it, and the recreated database
**loses the platform's preinstalled extensions** — read the set with
`psql "$T" -c "select extname from pg_extension order by 1"` rather than assuming it; measured on a
fresh staging pg16 it was `pg_stat_monitor`, `pg_stat_statements`, `pgaudit`, `plpgsql`, `vector`,
and **not** `pgcrypto` or `uuid-ossp`, so an app calling `crypt()`, `gen_salt()` or `uuid_generate_v4()`
must create the extension that owns it. (`gen_random_uuid()` is **not** an example of this: it has been core
since PG13 and needs no extension on pg16.) If you do add a fresh service the
DSN changes: bind it in step 3 (the `$PG` block) and re-resolve it in step 5.

Which guard catches what: **`ON_ERROR_STOP=1` catches SQL errors** (psql is the last stage, so its
status is the pipeline's), **`pipefail` catches a `pg_dump` failure**. You need both. The `^ERROR`
pattern above is correct **for these two restores because they are piped** — psql reading stdin emits
a bare `ERROR:`. Restoring from a file instead (`psql -f dump.sql`, as `migrate/insforge.md` does)
prefixes every one with `psql:<file>:<line>:`, so match both spellings when you are not sure which
form you ran: `grep -cE '^(psql:.*)?ERROR'`.
*Pass:* `grep -c '^ERROR'` is 0. Exit 0 alone does not prove it — the guards above are what make that
count trustworthy.
**4. Confirm the restore, and hand verification back.**

*Pass:* **the restore reported zero errors.** That is the whole of step 4. On the restore log,
`grep -cE '^(psql:.*)?ERROR' restore.log` is `0` — **both spellings, because the prefix depends on how
psql was invoked**: a piped restore emits bare `ERROR:`, `psql -f dump.sql` emits
`psql:dump.sql:<line>: ERROR:`, and a pattern anchored to only one of them reports a clean restore for
a failed one. The step-3 guards (`ON_ERROR_STOP`, `pipefail`) are what make that count trustworthy.
Nothing else here is yours to assert.

**Whether the application is correct on the new database is the developer's call, not this runbook's.**
We move the bytes and prove the move did not error; only they know which rows matter, which behaviour
is load-bearing, and what "working" means for their product. Do not invent acceptance criteria on their
behalf, and do not claim the migration is verified — say the restore completed clean, then hand them
the connection and let them check.

**Three things to tell them to look at**, because each has bitten a real migration and none of them
raises an error at restore time:

1. **Functions are never parsed during a restore.** `pg_dump` emits `SET check_function_bodies = false`,
   so a body holding PG17/18 SQL (`MERGE … RETURNING`, `RETURNING OLD.*`) restores silently and fails
   the first time it is called. After a **major-version downgrade**, tell them to exercise their
   functions before they trust the database.
2. **Named `NOT NULL` constraints from PG18 lose their names** on the way to pg16 (the column stays
   `NOT NULL`; the `pg_constraint` row does not survive), so a later
   `ALTER TABLE … DROP CONSTRAINT <name>` will fail on the migrated database only.
3. **The target's extension set is not the source's.** insta preinstalls its own (measured on a fresh
   staging pg16: `pg_stat_monitor`, `pg_stat_statements`, `pgaudit`, `plpgsql`, `vector`) and does
   **not** ship `pgcrypto` or `uuid-ossp`, so an app calling something those own — `crypt()`, `gen_salt()`,
   `uuid_generate_v4()` — needs `CREATE EXTENSION` even though the restore was clean. Not
   `gen_random_uuid()`, which is core from PG13 on.

If they want a fidelity check of their own, the cheapest honest one is a per-table row count on both
sides — `select relname, n_live_tup` is **not** it (`n_live_tup` is an estimate and reads `0` for a
fully populated table after `pg_stat_reset()`, measured), so a real `count(*)` per table, from
`pg_class` across every non-system schema. Offer that query if asked; do not run it as a gate.

**5. Bring the app onto the target — and `start` does NOT re-resolve env.**

```bash
# binding unchanged (you restored into the same postgres service):
insta --agent compute start <service>

# binding CHANGED (you restored into a fresh postgres service):
insta --agent secrets bindings --target compute/<service>   # MUST print: DATABASE_URL <- postgres/$PG.DATABASE_URL
insta --agent compute start <service> && insta --agent compute restart <service>
```

`insta --agent compute start` is a machine-lifecycle operation only. On a stopped-and-rebound service it
brings the machine back **with the env it was deployed with**, so the app keeps writing to the
pre-migration database — while `insta --agent secrets bindings` already reports the new source. `restart`
does re-resolve (`restarted … — env re-resolved from the current secrets`) but is **refused on a
stopped service**, so the changed-binding case is `start` *then* `restart`. If `bindings` still names `postgres/db`,
the step-3 rebind never happened: run it now, before `start`, or the app comes up on the dirty
database with every earlier check green.

**Now apply the pre-flight finding**, because the host finally exists. Read it off the service row
and set it into the name the app actually reads — its own name, never ours; the app has no idea
`INSTA_*` exists:

```bash
insta --agent service list                                   # the compute row's host column
# NOTE: this is PROJECT-WIDE, not per-service (`set RENDER_EXTERNAL_HOSTNAME (project-wide)`).
# Two compute services needing different hostnames need `--service compute/<name>`.
insta --agent secrets set RENDER_EXTERNAL_HOSTNAME <that host>   # ONLY if that is the name AND shape it reads
                                                # CLI >= 0.0.78: this redeploys the branch's compute itself.
                                                # On an older build add: insta --agent compute restart <service>
```

**Match the name *and the shape*.** The pre-flight told you which variable; it also has to tell you
whether the app wants a bare host or a full URL. Render's own Django example reads
`RENDER_EXTERNAL_HOSTNAME` (a host); its own Strapi example reads **`RENDER_EXTERNAL_URL`** and
feeds it to `server.url`, which needs `https://…`. Setting the wrong one of those two is silent:
the app reads nothing and keeps its default.

Set only what the app needs. Faking a *second* variable to make it believe it is still on the old
platform is how the Render case turns a 400 into a 500 (the ladder in `migrate/render.md`). Treat
this as an expedient that gets the cutover serving, and open a follow-up to give the app a neutral
way to read its host, since the value you just set is named after a platform it has left.

*Pass:* **check the machine, not the intent.**

```bash
# Compare the HOST only. Never print a DSN: it carries the password, and it lands in the
# terminal and in your transcript.
insta --agent compute exec <service> -- sh -c 'printenv DATABASE_URL | sed -E "s#^([a-z+]+://)[^@]*@#\\1***@#"'
# ⚠ `compute exec` runs in `/`, NOT the image's WORKDIR. Any file check needs ABSOLUTE paths:
#   insta --agent compute exec <svc> -- sh -c 'ls -la /app; cat /app/.nixpacks/Dockerfile'
# A relative `ls resources` reports "No such file" on an image that has it.
```

`insta --agent secrets bindings --target compute/<service>` (the flag is **required**; bare it fails
with `--target <compute/name> is required`, and note it is `--target` here but `--to` on `bind`)
reports what *should* be bound and will show the new source even while the
machine holds the old DSN — a false pass at the exact moment the rollback boundary is crossed. Then
confirm the app reads **and writes** the new database.

**6. Cut traffic.**

```bash
insta --agent domain attach <host> --group <service>       # host is positional; service is --group
insta --agent domain check <host> --group <service>
```

The hostname is the positional argument, the service is `--group` — reversing them fails with
`invalid domain`. It returns the DNS records for you to publish at your provider — it does not
change your DNS.

**7. Decommission the source** — after a soak period, not before.

**Rollback boundary.** Through step 4, returning to the source is a clean revert. **From step 5 the
target may hold writes the source does not** — rollback then needs a reverse copy or an accepted
data loss. "If verification fails, just point back at the source" is wrong once the target is live.

## What no source-platform guide will tell you

| | |
|---|---|
| **A binding is not live until a deploy** | Env is materialized into machine config at deploy time. `insta --agent secrets bind` changes the rules only; the running machine keeps its old env until `insta --agent deploy` (first time) or `insta --agent compute restart` (already running). Until then **the app still writes to the old database.** |
| **`--port` must equal the listen port** | `PORT` is injected as the routed port. An app reading `$PORT` is fine; a hardcoded port boots "successfully" and refuses every request. Source deploys default from the Dockerfile's last `EXPOSE` — read the line the CLI prints and confirm it. |
| **Four routes get code in** | `insta --agent deploy --image` (every plane); `insta --agent deploy <dir>` — on **insta-compute** the directory is packed, uploaded and built by the build gateway, with its Dockerfile or with nixpacks when there is none, so a checkout of the source app deploys as-is; on **Fly-backed** compute it needs the dir's own Dockerfile. `insta --agent compute connect-repo <owner/repo> <service>` (attaches to an EXISTING service and builds its Dockerfile, or detects the runtime with nixpacks when there is none — `--public` needs no GitHub App, `--root-dir` handles a monorepo); or the console's repo binding, which CREATES a service rather than attaching. A CLI that predates this lane answers `source builds are not supported on the insta-compute provider yet` for such a target: run `insta upgrade` and retry. |
| **Postgres scales to zero** | Keep the pool's `idleTimeoutMillis` under the suspend window, or the first request after a wake fails on a dead pooled connection. |
| **No bulk env import** | `insta --agent secrets set <name>` takes one variable per call (value as an argument or on stdin). Loop over the source's export, and drop the platform's own vars — `HEROKU_*`, `RAILWAY_*`, `DYNO`, `PORT`. |
| **Reading secrets back adds quotes** | both `insta --agent secrets --print` and `-o <file>` emit `NAME="value"`. `docker run --env-file` does **not** strip them, so the value arrives with a literal `"` and the app fails obscurely (measured: celery's `KeyError: 'No such transport: '`). Strip the quotes, or get the value another way. |
| **`insta --agent secrets list` prints names only** | It cannot reveal a truncated or mis-escaped value. To compare values, use `insta --agent secrets --print --json` — **not** bare `--print`, which double-quotes every value and does not escape embedded newlines, so a multi-line value breaks line-oriented parsing and every key then digests differently from the source export. |
| **No app-level scheduler — but the DB has one** | There is no `insta schedule`. Two options. In-process (node-cron, APScheduler, whenever) inside a **web** service: keep it always-on, since a suspended service stops firing, and remember **replicas multiply every tick** (`insta --agent compute scale` allows 1–10, so two replicas run each job twice). Or **`pg_cron`**, which is **preloaded but not created**: measured on prod, `shared_preload_libraries` is `pg_stat_monitor,pgaudit,pg_cron,pg_stat_statements` and `pg_available_extensions` lists `pg_cron 1.6` with a null `installed_version`, so you must run `CREATE EXTENSION pg_cron` yourself (it succeeds). One schedule, no replica problem, SQL-only — **and it needs `insta --agent postgres always-on on`**, because postgres defaults to scale-to-zero ("off = default scale-to-zero (idle instance suspends)") and a suspended database fires nothing. **None of this is a scheduling feature**; the platform is expected to grow one, so present these as stopgaps. |
| **Workers** | `port === 0` is the platform's own worker convention, but `insta --agent service add --port 0` is rejected and `insta --agent template deploy` refuses `type: worker`. **Until that path is verified end to end**, give the worker a port and let it listen — the machine check is **TCP, not HTTP**, so `require('net').createServer().listen(process.env.PORT)` is enough (no framework, no `/health`). Never `--no-always-on`: a suspended worker has no inbound traffic to wake it. |

## Command mapping

| Need | Heroku | Render | InstaCloud |
|---|---|---|---|
| dump all env | `heroku config -s` | dashboard, or read `render.yaml` | `insta --agent secrets --print` |
| set one env | `heroku config:set K=V` | dashboard | `insta --agent secrets set K` (value on stdin) |
| DB connection string | `heroku config:get DATABASE_URL` | dashboard only — `render postgres get` does NOT expose it | `insta --agent postgres url` |
| psql session | `heroku pg:psql` | `render psql <id> --command "…" -o json --confirm` (only non-interactive form) | `insta --agent postgres connect` |
| one-off task | `heroku run <cmd>` | `render jobs create` | `insta --agent compute exec [service] -- <cmd>` (argv, no shell) |
| stop traffic | `heroku maintenance:on` | no switch — scale to zero or suspend, per service | `insta --agent compute stop [service]` |
| scale | `heroku ps:scale web=2` | dashboard only — no CLI command | `insta --agent compute scale 2 <name>` |
| custom domain | `heroku domains:add` | dashboard only — no CLI command | `insta --agent domain attach <host> --group <svc>` |
| logs | `heroku logs -t` | `render logs` | `insta --agent compute logs` |

## Addon → service

| Source | Provision | Bound as |
|---|---|---|
| Heroku / Railway Postgres | `insta --agent service add postgres <n>` | `DATABASE_URL` |
| Heroku / Railway Redis, **Render Key Value** (`render kv`) | `insta --agent service add redis <n>` | `REDIS_URL` |
| JawsDB, PlanetScale | `insta --agent service add mysql <n>` | `MYSQL_URL` |
| MongoDB Atlas | `insta --agent service add mongodb <n>` | `MONGODB_URL` |
| S3 bucket, Railway bucket | `insta --agent service add storage <n>` | `AWS_*`, `BUCKET_NAME` |
| Heroku Scheduler, Railway cron | none — see the table above | |

Bind every credential the app needs; nothing is auto-injected into compute.

## Heroku

**Heroku.** The richest export surface: `config -s` yields `KEY=value` lines, `pg:backups` and
`maintenance:on` are single commands, and the `Procfile`'s `web:` / `worker:` map straight onto
compute services. No volumes. `app.json`, if present, declares the addons — read it to enumerate
what to provision.

> **Verified as of 2026-09-09**, by executing this runbook against a throwaway project with a seeded
> Postgres: the cutover ordering, the guard behaviour in step 3, `start` not re-resolving env, the
> `secrets set` stdin/argument asymmetry, and the refusal messages quoted above. **Not verified:** any
> end-to-end migration from Render, Railway, Fly or Heroku itself, the portless-worker path, and volume data
> movement. (The self-hosted InsForge path above was migrated end to end on 2026-09-14, files and edge functions
> included. The one step inside it that is **not** measured is the `system.secrets` re-encrypt that repoints
> `INSFORGE_BASE_URL`.)
>
> **InsForge Cloud is a supported source too**, measured on the same day: a real cloud project migrated with
> every table row-for-row identical, keys byte-identical and no user forced to log in again. The seven things
> that differ are in `migrate/insforge.md`, and two of them stay **unproven** and are marked there: a cloud
> source that actually holds storage objects (the tested project held none, so the S3-gateway export is verified
> on the target side only), and any source whose user schedules keep writing, because a cloud project cannot be
> quiesced. A cloud source also arrives having lost what the control plane, not the container, provided: shared
> OAuth keys, the managed OpenRouter and webscraper credentials, and analytics, whose history lives in InsForge's
> PostHog rather than in the dump. **Enumerate that for the user before the cutover, not after.**
>
> **The pg18→pg16 downgrade in step 3 is verified end to end** against a seeded PG 18.6 source and a
> real InstaCloud PG 16.15 target: restore exited 0 with empty stderr, and a catalog and data diff
> came back identical apart from the extensions insta preinstalls. Sequences kept their positions
> (identity sequence at 900001, next insert returned 900002), 2 FKs and 4 CHECKs were `convalidated`
> and actually rejected violating rows, all 8 index `indexdef`s were byte equal including a GIN on
> jsonb and a partial index, view and trigger definitions were md5 equal, and
> `COPY … WITH (FORMAT binary)` from both sides was `cmp` identical at 123,405 bytes, covering
> microsecond `timestamptz` and nested `jsonb`. The blocker table and the two silent failures in
> step 3 were each reproduced individually.
