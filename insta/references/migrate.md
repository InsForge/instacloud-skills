# Migrate an app in from another platform

Move a running app (Heroku, Railway, Fly, Render) onto InstaCloud: provision, move env and data,
cut over. The reader-facing walkthroughs are `docs.instacloud.com/migrate/render` and
`/migrate/railway`, and they are deliberately thin: they hand the user a prompt and point at this
runbook, so **this file is what actually gets followed.** Those pages deliberately do NOT list these
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
insta --agent setup agent --env <that env> -y       # NEVER bare
```

`--env` defaults to **prod**, and its own help says "switches and persists, like `insta env use`"
(`cli/src/index.ts`). `setup.ts` is explicit about what that costs: the switch "goes through
`env use` — the one path that persists the choice and **drops the now-foreign session**". So a bare
`insta setup agent` on a staging machine logs the whole machine out of staging, for every project,
and only a human can restore it with a browser flow. **That turns a one-project session error into
a machine-wide outage** — measured, on this machine, during the validation run this file came from.
If the login itself is gone (`insta --agent env` shows `user: (not logged in)`, and commands return
`unauthorized (HTTP 401)`), you cannot fix it: relay `insta login` to a human and stop.
**Never remove `--agent` to get past a governance refusal**; relay the approval command to a human
admin and retry the unchanged request.

**A stateless app is a supported shape, and the cutover is shorter for it.** Steps 2, 3 and 4 are
entirely Postgres and their pass conditions are `psql` diffs. An app with no database migrates in
steps 0, 1, 5, 6 and 7, dropping `services add postgres`, `secrets bind` and the psql lines from
step 1. Read literally the ordering below cannot be completed without a database; that is a gap in
the writing, not a claim the app is unsupported.

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
  list)? See the per-source table in the Render section for what each platform's apps actually do.

**`insta build <dir>` is the cheapest pre-flight and this file used not to mention it.** Local,
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
step 5.** If the answer was "a literal I must edit", make that edit NOW, before the deploy, so the
image is already right.

```bash
insta --agent services add postgres db                          # + redis/storage/… as the source needs
insta --agent services add compute app --port <n>               # REQUIRED: the bind below targets it
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
  and build scripts. Write the idiomatic multi-stage Dockerfile that copies only the binary and
  that app panics on boot **with a green TCP check**. The image also carries
  **`/app/.nixpacks/Dockerfile`**, which is the best post-hoc build audit available: base images,
  nixpkgs rev, build and start commands, copy semantics, in one `exec`.

**Two things about `connect-repo` that will cost you a migration if you do not know them.**

**It overwrites the port you set at `services add`.** `cli/src/commands/github.ts` builds the body as
`port: o.port !== undefined ? parsePort(o.port) : c.port`, where `c` is the *server-side detection
candidate* — the service's own configured port is never consulted. Measured: `0 → 8000` and
`8080 → 8000`, and it happens even when the build then fails. **So repeat the port on the connect:**

```bash
insta --agent compute connect-repo <owner/repo> <svc> --public --port <n>
```

It is invisible otherwise: `services add` does not echo the port, `connect-repo` does not, and
`services list` only shows it inside the `running <image>:<port>` fragment, so an imageless service
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
machine ever existed). **Reproduce locally to learn why:** `insta build <dir>`, then
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

**Which lane. `insta deploy <dir>` is now the migration default, on every plane.** The archive
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


Without the `services add compute` line the bind fails with `service not found on branch:
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
insta --agent services list                    # read the compute row's host column
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
successful deploy** — measured on three separate services: `services add` leaves `domain: null`,
and the host is minted with the image, which is what the pre-flight above already says. (Both
`services add --help` and an earlier version of this note claimed `add` assigns one; they are
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
shell against `insta --agent db url`, and use step 5's redacted `printenv` for what the machine
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
`exec` — including a verification query in step 4 — re-animates the machine. Re-`stop` after using
it.
*Pass:* no write traffic at either end.

**3. Copy into a CLEAN target.**

**Read both majors first.** They decide which client you need, and whether the schema has hard
blockers.

```bash
insta --agent services list                       # target major, e.g. postgres/db [pg16], NOT selectable
psql "$SOURCE_URL" -c 'show server_version'
```

The one hard rule is `client_major >= source_major`. A newer server cannot be read by an older
client and there is no escape hatch: `pg_dump` 16 against an 18 server aborts with
`pg_dump: error: aborting because of server version mismatch`, and `--format=custom` makes it worse,
not better, because `pg_restore` 16 rejects an 18 archive at the header
(`unsupported version (1.16) in file header`). So always dump with a client at or above the source
major, and use plain format when the target is older, because plain text is the only form you can
filter.

**Upgrade or equal (source <= target).** Nothing special.

**Set `PG` first, and set it to the service you are actually restoring into.** If step 3 had you
add a **fresh** postgres service because the proving deploy dirtied the first one, then every
command from here to step 5 must name that new one:

```bash
export PG=db2        # ← the FRESH service; plain `db` only if you never re-added
```

This is the sharpest trap in the whole procedure. With two postgres services a bare
`insta --agent db url` fails loudly (`error: multiple postgres services — specify one: db, db2`),
which is the *good* outcome. The bad outcome is copy-pasting `--group db`: measured, that restores
into, verifies, and cuts over to the **old dirty database** while every check reports success —
`exit 0`, `grep -c '^ERROR'` → 0. Step 4's count diff does catch it (10 tables against 14), so it
costs a restore cycle rather than data, but only if you actually run step 4 against the same `$PG`.

```bash
set -o pipefail
pg_dump --no-owner --no-privileges "$SOURCE_URL" \
  | psql -v ON_ERROR_STOP=1 "$(insta --agent db url --group "$PG")" 2>&1 | tee restore.log
grep -c '^ERROR' restore.log              # must print 0
```

**Downgrade (source > target).** Today this is every documented source: Render pg18 and Railway
pg18 into InstaCloud pg16. **This works, at full fidelity, and it is a tested procedure**, not a
workaround. `pg_dump` from 18 emits exactly one statement pg16 does not know.

```bash
set -o pipefail
pg_dump --format=plain --no-owner --no-privileges "$SOURCE_URL" \
  | awk '!d && /^SET transaction_timeout/ {d=1; next} /^\\restrict / {next} /^\\unrestrict / {next} {print}' \
  | psql -v ON_ERROR_STOP=1 "$(insta --agent db url --group "$PG")" 2>&1 | tee restore.log
grep -c '^ERROR' restore.log              # must print 0
```

Why each piece is there:

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
  | psql -v ON_ERROR_STOP=1 "$(insta --agent db url --group "$PG")"
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
   `missing FROM-clause entry for table "old"`). **A clean restore proves nothing about functions.
   Call every one of them once** as part of step 4.

Also expect a catalog difference that is **not** a fidelity loss: PG18 materializes `NOT NULL` as
`contype='n'` rows in `pg_constraint` and pg16 has none, so exclude those rows when diffing
catalogs, after confirming `attnotnull` is set on every column.

**The target must be empty — confirm it, do not assume it.** If the app was up at any point in
step 1, check before restoring rather than trusting that it wrote nothing:

```bash
psql "$T" -At -f /tmp/counts.sql        # the count query from step 4; must return nothing at all
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
and **not** `pgcrypto` or `uuid-ossp`, so an app wanting `gen_random_uuid()` must create it. If you do add a fresh service the
DSN changes, so see step 5.

Which guard catches what: **`ON_ERROR_STOP=1` catches SQL errors** (psql is the last stage, so its
status is the pipeline's), **`pipefail` catches a `pg_dump` failure**. You need both.
*Pass:* `grep -c '^ERROR'` is 0 **and** step 4's fidelity checks match. Exit 0 alone proves nothing.
**4. Verify the data.**

**Count every table exactly, and never from `pg_stat_user_tables`.** `n_live_tup` is an estimate:
it reads **0 for a fully populated table** once statistics have been reset (measured — 3,000 rows,
`pg_stat_reset()`, estimate `0`), and stats are also lost across some restarts. Two sides both
reporting 0 would compare equal and verify nothing. This query counts each table for real, in one
round trip, and covers **all** schemas rather than a top-N slice:

```bash
cat > /tmp/counts.sql <<'SQL'
select n.nspname || '.' || c.relname as tbl,
       (xpath('/row/c/text()',
              query_to_xml(format('select count(*) as c from %I.%I', n.nspname, c.relname),
                           false, true, '')))[1]::text::bigint as rows
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r'
  and n.nspname not in ('pg_catalog', 'information_schema')
  and n.nspname not like 'pg_toast%'
order by 1;
SQL

T="$(insta --agent db url --group "$PG")"             # scriptable; `insta --agent db connect` is interactive
psql "$T"          -At -F, -f /tmp/counts.sql | sort > /tmp/target.csv
psql "$SOURCE_URL" -At -F, -f /tmp/counts.sql | sort > /tmp/source.csv
diff /tmp/source.csv /tmp/target.csv && echo "row counts identical"
```

If you test the diff by deleting rows, pick **unreferenced** ones: a correctly restored foreign key
refuses the delete (`update or delete on table "auth_user" violates foreign key constraint …`),
which is itself evidence the restore worked.

It enumerates from `pg_class`, not from a stats view, so a reset cannot hide a table from it either.
Verified after `pg_stat_reset()`: exact counts for a 1,000-row table, a 7-row table, an **empty**
table and a table in a non-`public` schema, with views excluded. An empty table is worth having in
the diff: a top-N-by-size query never shows one, and "the table is there but empty" is a migration
failure that looks like nothing at all.

Then the rest:

```bash
psql "$T" -c "select sequencename, last_value from pg_sequences order by sequencename"
psql "$T" -c "select extname from pg_extension order by extname"
psql "$T" -c "select max(id), max(created_at) from <append_only_table>"
```

Run those against the source too and diff. **"Extensions present" cannot fail** on its own — a
fresh insta postgres already ships several, so the dump's `CREATE EXTENSION IF NOT EXISTS` is a
no-op for those. **Read the set, do not assume it** — measured on staging pg16:
`pg_stat_monitor`, `pg_stat_statements`, `pgaudit`, `plpgsql`, `vector`, with **no `pgcrypto` and no
`uuid-ossp`**, despite an earlier version of this file listing both. Compare the
**sets** source-vs-target instead of asserting presence.

**After a major-version downgrade, add the schema checks**, because that is where a downgrade loses
things quietly:

```bash
psql "$T" -At -F'|' -c "select n.nspname||'.'||c.conname, c.contype, c.convalidated
      from pg_constraint c join pg_namespace n on n.oid = c.connamespace
      where n.nspname not in ('pg_catalog','information_schema') and n.nspname not like 'pg_toast%'
        and c.contype <> 'n' order by 1"
psql "$T" -At -F'|' -c "select schemaname||'.'||indexname, indexdef from pg_indexes
      where schemaname not in ('pg_catalog','information_schema') order by 1"
psql "$T" -At -F'|' -c "select format('%I.%I(%s)', n.nspname, p.proname,
                                     pg_get_function_identity_arguments(p.oid)),
             case when p.prorettype = 'trigger'::regtype then 'trigger' else 'callable' end
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname not in ('pg_catalog','information_schema')
        and not exists (select 1 from pg_depend d
                        where d.objid = p.oid and d.classid = 'pg_proc'::regclass
                          and d.deptype = 'e')
      order by 1"
```

**All three cover every non-system schema, not just `public`.** An app with its own schema can lose
a constraint, an index definition or a callable function there and still pass a `public`-only check,
which is the same blind spot the row counts had. The function query builds its name with `format`
rather than `oid::regprocedure`, because the latter omits the schema for anything on the
`search_path` — so a source and target with different search paths would diff as different while
being identical. Verified: identical output across a `set search_path` change, with objects in both
`public` and a second schema.

Exclude `contype = 'n'` rows, since PG18 records `NOT NULL` there and pg16 does not. Diff `indexdef`
as text, and confirm `convalidated` is true rather than merely that the constraint exists.
**The `pg_depend … deptype = 'e'` exclusion is not optional.** Extensions install their functions
into `public`, so without it the target lists every extension's functions while the source lists
none: measured **139 rows against 2** on a real insta postgres, a 137-line false-positive diff on
*every* migration. A throwaway pg16 with only `pgcrypto` present already went from 2 rows to **38**.
An agent facing that either escalates for nothing or learns to ignore the check.

Then **call every function the third query lists, once** — their bodies were never parsed during the
restore, so this is the only thing that catches PG17/18 SQL inside them. **Except those marked
`trigger`:** calling one directly fails with `trigger functions can only be called as triggers`.
Exercise those with DML against the table whose trigger owns them.
*Pass:* the per-table count diff is **empty** (every table, exact, both sides); latest rows match;
sequences at or above the source's; extension sets reconciled as a **subset** (source minus target empty — a plain diff is non-empty on every migration, since the target always carries the preinstalled ones);
after a downgrade, constraints validated, `indexdef`s equal, and every function callable.

**5. Bring the app onto the target — and `start` does NOT re-resolve env.**

```bash
# binding unchanged (you restored into the same postgres service):
insta --agent compute start <service>

# binding CHANGED (you restored into a fresh postgres service):
insta --agent compute start <service> && insta --agent compute restart <service>
```

`insta --agent compute start` is a machine-lifecycle operation only. On a stopped-and-rebound service it
brings the machine back **with the env it was deployed with**, so the app keeps writing to the
pre-migration database — while `insta --agent secrets bindings` already reports the new source. `restart`
does re-resolve (`restarted … — env re-resolved from the current secrets`) but is **refused on a
stopped service**, so the changed-binding case is `start` *then* `restart`.

**Now apply the pre-flight finding**, because the host finally exists. Read it off the service row
and set it into the name the app actually reads — its own name, never ours; the app has no idea
`INSTA_*` exists:

```bash
insta --agent services list                                   # the compute row's host column
# NOTE: this is PROJECT-WIDE, not per-service (`set RENDER_EXTERNAL_HOSTNAME (project-wide)`).
# Two compute services needing different hostnames need `--service compute/<name>`.
insta --agent secrets set RENDER_EXTERNAL_HOSTNAME <that host>   # ONLY if that is the name AND shape it reads
insta --agent compute restart <service>                       # env is materialized at deploy time
```

**Match the name *and the shape*.** The pre-flight told you which variable; it also has to tell you
whether the app wants a bare host or a full URL. Render's own Django example reads
`RENDER_EXTERNAL_HOSTNAME` (a host); its own Strapi example reads **`RENDER_EXTERNAL_URL`** and
feeds it to `server.url`, which needs `https://…`. Setting the wrong one of those two is silent:
the app reads nothing and keeps its default.

Set only what the app needs. Faking a *second* variable to make it believe it is still on the old
platform is how the Render case turns a 400 into a 500 (the ladder in the Render section). Treat
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
insta --agent compute set-domain <host> --group <service>       # host is positional; service is --group
insta --agent compute check-domain <host> --group <service>
```

`set-domain <service> <host>` fails with `invalid domain`. It returns the DNS records for you to
publish at your provider — it does not change your DNS.

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
| **No app-level scheduler — but the DB has one** | There is no `insta schedule`. Two options. In-process (node-cron, APScheduler, whenever) inside a **web** service: keep it always-on, since a suspended service stops firing, and remember **replicas multiply every tick** (`insta --agent services scale` allows 1–10, so two replicas run each job twice). Or **`pg_cron`**, which is **preloaded but not created**: measured on prod, `shared_preload_libraries` is `pg_stat_monitor,pgaudit,pg_cron,pg_stat_statements` and `pg_available_extensions` lists `pg_cron 1.6` with a null `installed_version`, so you must run `CREATE EXTENSION pg_cron` yourself (it succeeds). One schedule, no replica problem, SQL-only — **and it needs `insta --agent db always-on on`**, because postgres defaults to scale-to-zero ("off = default scale-to-zero (idle instance suspends)") and a suspended database fires nothing. **None of this is a scheduling feature**; the platform is expected to grow one, so present these as stopgaps. |
| **Workers** | `port === 0` is the platform's own worker convention, but `insta --agent services add --port 0` is rejected and `insta --agent template deploy` refuses `type: worker`. **Until that path is verified end to end**, give the worker a port and let it listen — the machine check is **TCP, not HTTP**, so `require('net').createServer().listen(process.env.PORT)` is enough (no framework, no `/health`). Never `--no-always-on`: a suspended worker has no inbound traffic to wake it. |

## Command mapping

| Need | Heroku | Render | InstaCloud |
|---|---|---|---|
| dump all env | `heroku config -s` | dashboard, or read `render.yaml` | `insta --agent secrets --print` |
| set one env | `heroku config:set K=V` | dashboard | `insta --agent secrets set K` (value on stdin) |
| DB connection string | `heroku config:get DATABASE_URL` | dashboard only — `render postgres get` does NOT expose it | `insta --agent db url` |
| psql session | `heroku pg:psql` | `render psql <id> --command "…" -o json --confirm` (only non-interactive form) | `insta --agent db connect` |
| one-off task | `heroku run <cmd>` | `render jobs create` | `insta --agent compute exec [service] -- <cmd>` (argv, no shell) |
| stop traffic | `heroku maintenance:on` | no switch — scale to zero or suspend, per service | `insta --agent compute stop [service]` |
| scale | `heroku ps:scale web=2` | dashboard only — no CLI command | `insta --agent services scale compute <name> 2` |
| custom domain | `heroku domains:add` | dashboard only — no CLI command | `insta --agent compute set-domain <host> --group <svc>` |
| logs | `heroku logs -t` | `render logs` | `insta --agent logs compute` (target is required) |

## Addon → service

| Source | Provision | Bound as |
|---|---|---|
| Heroku / Railway Postgres | `insta --agent services add postgres <n>` | `DATABASE_URL` |
| Heroku / Railway Redis, **Render Key Value** (`render kv`) | `insta --agent services add redis <n>` | `REDIS_URL` |
| JawsDB, PlanetScale | `insta --agent services add mysql <n>` | `MYSQL_URL` |
| MongoDB Atlas | `insta --agent services add mongodb <n>` | `MONGODB_URL` |
| S3 bucket, Railway bucket | `insta --agent services add storage <n>` | `AWS_*`, `BUCKET_NAME` |
| Heroku Scheduler, Railway cron | none — see the table above | |

Bind every credential the app needs; nothing is auto-injected into compute.

## Per-source deltas

**Render.** Buildpack-built, so almost never a Dockerfile — `insta --agent compute connect-repo` is the
shortest path. **Its Postgres is 18, so step 3 is a downgrade** into insta's pg16. Step 3 has the tested
procedure for that; it is one filtered line, not a blocker.

**Translate `render.yaml` yourself — there is no importer, and you do not need one.** If the repo
has one, read it and provision from this table rather than interviewing the user. Every row is a
command you already have:

| In `render.yaml` | Do this |
|---|---|
| `databases: [{name: X}]` | `insta --agent services add postgres X` |
| `databases[].diskSizeGB` | nothing to do: database disk sizing is not addressable here |
| `services: [{type: web, name: X}]` | `insta --agent services add compute X --port <n>`. `--port` is optional and stores **`null`**, not `8080`; the 8080 default is applied at *deploy* time. Pass it anyway, and pass it again on `connect-repo` (see above) |
| **nixpacks finds no start command** | **the repo has no `connect-repo` route at all** — every service connected to it fails identically with `build <id> failed: build command failed`, web services included. Measured on `render-examples/celery`, whose three roles live only in their `startCommand:`. Catch it with `insta build <dir>` before touching the platform. **The cheap fix is a `Procfile`, not a Dockerfile** — but nixpacks honours exactly **one** entry (`web:` beats `worker:`), so one repo/root-dir yields one image and one start command for *every* service connected to it. Differentiating roles needs `--root-dir` per role, a Dockerfile per directory, or `deploy --image` per role |
| `type: worker` | a second compute service. **Portless is prebuilt-image-only**, so read the worker notes below before promising it: `services add compute X --port 0` and `connect-repo … --port 0` are both **rejected** (`port must be an integer between 1 and 65535, got: 0`), while `insta --agent deploy --image <ref> --port 0` is **accepted** and is the only path. A repo whose worker identity *is* its `startCommand`, with no Dockerfile, has **no route** on insta-compute: `connect-repo` cannot set commands ("Build and start commands come from detection and cannot be set") and `deploy <dir>` is refused on this plane. Say so rather than improvising |
| `type: cron` | **not supported yet** (the platform is expected to grow scheduling). Stopgaps, each needing something kept awake: `pg_cron` with `db always-on on`, an in-process scheduler in an always-on compute service, or scheduling from outside the platform |
| `type: pserv` (private service) | a compute service, but **flag it to the user**: `insta --agent services add` assigns a default domain to every compute service, so a Render private service stops being unreachable from the internet |
| `runtime: python` / `node` / `ruby` / `go` (any non-`image`; older blueprints spell it `env:`) | `insta --agent compute connect-repo <owner/repo> X` — nixpacks does what the buildpack did |
| `buildCommand:` | **nixpacks does not run the script**, but do not assume nothing in it happens: its Django provider runs `manage.py migrate` itself at start (measured — a full `admin, auth, contenttypes, sessions` migrate ran against the bound insta pg16 with no instruction from us). The **asset** half is what it skips, so read the script and re-home anything else: `collectstatic` or an `npm run build` needs a `Dockerfile` or nixpacks' own detected build step. A migration you want under your control rather than run at every boot belongs in `insta --agent compute exec` |
| `startCommand:` | nixpacks picks its own, which is often not this one. If the app needs a specific server invocation (`gunicorn mysite.asgi:application -k uvicorn.workers.UvicornWorker`, a `-w` count, an ASGI vs WSGI entrypoint), that is a `Dockerfile` `CMD`, so this row can turn the whole service into the Dockerfile lane |
| `runtime: image`, `image.url` | `insta --agent deploy --image <url> --port <n>` instead; do NOT reach for connect-repo |
| `envVars: [{fromDatabase: {...}}]` | `insta --agent secrets bind DATABASE_URL postgres/X --to compute/Y` |
| `envVars: [{fromService: {...}}]` | **bind it if the target is a credential-minting service** — `redis`, `mysql` and `mongodb` all are, so `insta --agent secrets bind <NAME> redis/X --to compute/Y --source-name REDIS_URL` is right and copying the DSN as a plain secret is the anti-pattern this file warns about elsewhere. Only a `fromService` pointing at another **compute** service has to become a plain secret |
| `envVars: [{value: V}]` | `insta --agent secrets set KEY V` |
| `envVars: [{generateValue: true}]` | Render invented it. **Carry the existing value over, do not regenerate** — for a Django `SECRET_KEY` a new one logs out every session, and for an app's own signing keys it invalidates issued tokens |
| `envVars: [{sync: false}]` | never in the file. Read it from the API below, or ask the user |
| `maxmemoryPolicy:` on a redis | no insta knob. Render's own queue examples set `noeviction` deliberately, so tell the user their queue's eviction behaviour is not reproducible here |
| `ipAllowList: []` on a datastore | no insta knob, and the default runs the **other way**: a provisioned redis came back `public=true`. A Render datastore restricted to internal connections becomes publicly addressable here, so flag it like the `pserv` row |
| `envVarGroups:` | **not returned by the env-vars API** (see below); resolve these from the dashboard |
| `disk: {mountPath, sizeGB}` | `--volume <gi>` on `insta --agent services add`, or `insta --agent compute volume X --size <gi>` later. **The disk appears when the machine is next created, so `insta --agent compute restart X` is enough — no rebuild.** Measured twice on a running volumeless service: attach, restart only, and `/data` is mounted; the platform labels that event `wake`, not `deploy`, which is the mechanism. A volume attached *before* the first deploy is present on that first deploy. (Both this file and the CLI's own string said "the next deploy"; on a nixpacks service that difference is a 10-second restart versus a full rebuild.) **Do not mirror Render's `sizeGB`:** attach at the free 10Gi cap, because growing is paid-plan-only even from 1Gi to 2Gi and shrinking is impossible, so a literal small size is a one-way door |
| `disk` holding **user uploads** | the volume is usually the wrong tool: prefer `insta --agent services add storage <n>` plus an S3 upload provider (see the addon table), which is the only option that survives scale-out. If you keep the volume, the path fix must be **in the image** — a `Dockerfile` symlink to `/data` — because a symlink made with `compute exec` is wiped on the next restart (measured). Check whether the framework can be pointed at the mount instead (Strapi: `server.dirs.public`), and note a fresh volume contains only `lost+found`, so a framework that requires its upload directory to pre-exist will crashloop until you create it |
| `healthCheckPath` | not a knob here; insta health-checks the port |
| `numInstances` | `insta --agent services scale compute X <n>` (1 to 10, same region, paid plans) |
| `plan:` | `insta --agent compute limits` / `insta --agent db limits` |
| `region:` | `--region` on `insta --agent services add` (values from `insta --agent regions`) |
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

**Every source hits this, but the shape differs, and Render is the mildest case.** Read from each
platform's own official Django example, which is what real user code is derived from:

| source | what its example does | what you get here |
|---|---|---|
| **Render** | `ALLOWED_HOSTS` appended from `RENDER_EXTERNAL_HOSTNAME` | 400, and **one env var fixes it** (the ladder above) |
| **Heroku** | `IS_HEROKU_APP = "DYNO" in os.environ`; then `["*"]` if set, else `[".localhost", "127.0.0.1", "[::1]", "0.0.0.0", "[::]"]` | 400, and **no env var can fix it** — both branches are literals, so the code must change. `DEBUG` keys off `ENVIRONMENT`, not the platform, so at least it stays off |
| **Fly** | hardcoded `['localhost', '127.0.0.1', '.fly.dev']` (their guide names no Fly variable) | 400, **code must change**. Do not go looking for `FLY_APP_NAME` in the settings; it is usually not there |
| **Railway** | `ALLOWED_HOSTS = ["*"]`, unconditional | **works as-is** — they bought that by giving up the check entirely |

So the useful expectation is not "grep for the platform variable" but **"assume the app cannot name
its own new hostname, and find out how it learns one."** Sometimes that is a variable you can set,
often it is a literal you have to edit, and occasionally (Railway) there is nothing to do.

**And there is nothing on this side for it to read.** `PORT` is the only variable the *control
plane* adds (`provisioning/deploy.ts`: `const env = { PORT: String(port), ...envBundle }`), and
everything else you set came from a secret or a binding. The machine env is not that short, though:
the orchestrator adds its own, measured on a live machine — `KUBERNETES_SERVICE_HOST`,
`KUBERNETES_PORT_443_TCP*`, `INTERNAL_DNS_*`, and per sibling service
`INSTA_SVC_<hex>_SERVICE_HOST` / `_SERVICE_PORT`. So there **is** in-cluster discovery for siblings,
and an app grepping its env for platform markers will see `KUBERNETES_*`. What none of them carry is
the service's **own public domain**, which is the point here. There is no
insta equivalent of `RENDER_EXTERNAL_HOSTNAME`, `RAILWAY_PUBLIC_DOMAIN` or `FLY_APP_NAME`, so an app
cannot discover its own public domain here. **Read the domain off `insta --agent services list` and set it
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

**Heroku.** The richest export surface: `config -s` yields `KEY=value` lines, `pg:backups` and
`maintenance:on` are single commands, and the `Procfile`'s `web:` / `worker:` map straight onto
compute services. No volumes. `app.json`, if present, declares the addons — read it to enumerate
what to provision.

**Railway.** Closest model (services + variables + IaC), so the concept mapping is nearly 1:1 — but
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
| an app reading `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` / `PGPORT` | a code change to read `DATABASE_URL`, per step 1 above. Railway injects these by default, so expect it |
| `RAILWAY_*` built-ins, `PORT` | skip: render-time only, and the platform supplies `PORT` here |
| any other variable | `insta --agent secrets set KEY` |
| a volume | `--volume <gi>` on `insta --agent services add`, or `insta --agent compute volume X --size <gi>`; it mounts at `/data` when the machine is next created, so a `restart` is enough (see the Render `disk:` row), and download the source contents while its service still runs |
| `numReplicas` | `insta --agent services scale compute X <n>` (1 to 10, same region, paid plans) |
| a cron service | **not supported yet** (the platform is expected to grow scheduling). Stopgaps, each needing something kept awake: `pg_cron` with `db always-on on`, an in-process scheduler in an always-on compute service, or scheduling from outside the platform |
| multi-region replicas | not available; one region per service, chosen with `--region` at add time |

Railway's Postgres template is **18**, so step 3 is a downgrade. Its volumes carry the same caveat
as any: creating a target volume does not copy contents.

**Fly.** The easiest source of the four, and the only one that is not a Postgres downgrade: Fly
Managed Postgres runs **16**, the same major as insta's, so step 3 needs no filter. A Fly app also
already has a `Dockerfile` and a `fly.toml`, so `insta --agent deploy . --port <n>` from the local
checkout works **on every plane** — the flyctl lane builds the Dockerfile on Fly-backed compute, the
archive lane builds it on the build gateway for insta-compute — and needs no GitHub connection. A CLI
that predates the archive lane answers `source builds are not supported on the insta-compute
provider yet`: `insta upgrade`. `internal_port` in `fly.toml` is the `--port` value, and `[env]`
entries become plain secrets. Note the builder **ignores the repo's `fly.toml`** on the insta-compute
lane (`instaflybuilder` writes its own; the comment says caller config never reaches it), so nothing
in that file affects the build here. `[processes]` maps onto compute services, and
volumes carry the same caveat as any. **The one real obstacle is secrets:** `fly secrets list`
returns names and digests only, because "the actual value of the secret is only available to the
application", so there is no export. Read them off the running machine before you stop it — **one name at a
time, never the whole env**, and piped so the value never reaches your terminal:
**pipe it, never print it** — one name at a time, straight into the target, so the value never
reaches your output:

```bash
fly ssh console -a <app> -C 'printenv <NAME>' | tr -d '\r\n' | insta --agent secrets set <NAME>
```

`insta --agent secrets set` reads stdin, so nothing is displayed and nothing enters shell history. **Never
`fly ssh console -C env`**: it dumps every credential the app holds into your transcript at once.
And never run the `printenv` on its own to "check" a value first; that is the leak. If you cannot
pipe, have the user re-enter the value instead.

> **Verified as of 2026-09-09**, by executing this runbook against a throwaway project with a seeded
> Postgres: the cutover ordering, the guard behaviour in step 3, `start` not re-resolving env, the
> `secrets set` stdin/argument asymmetry, and the refusal messages quoted above. **Not verified:** any
> end-to-end migration from a real source platform, the portless-worker path, and object-storage or
> volume data movement.
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
