**InsForge.** Read `../migrate.md` first: its ordered cutover is the procedure and this
file is only what InsForge adds to it. **Both source shapes are supported.** The worked example is a
self-hosted one; a hosted InsForge Cloud project runs the same sequence, and the **From InsForge Cloud** block at the
end of this file is the whole delta. Read it **before** step 0, because that is where the two diverge.
The self-hosted source is `docker compose` with four published images (`ghcr.io/insforge/postgres`,
`postgrest/postgrest`, `ghcr.io/insforge/insforge-oss`, `denoland/deno`), started by `deploy/setup.sh`; nothing is
built. On insta the backend and PostgREST run **unchanged** as two compute services from the same images, the
database becomes a managed postgres, and files move to a storage service. **Measured end to end on staging, twice,
2026-09-14** (`insforge-oss` v2.3.2, `ghcr.io/insforge/postgres:v15.13.4` serving PG 15.18 → insta pg 16.15): every command below ran; the hosted API
then served the migrated rows, the migrated users with their original passwords, and the migrated files. **Edge functions migrate too**, measured
separately the same day: see the Deno section below. PostgREST is on a **public** URL here, JWT-gated with `anon` as
the fallback role (Supabase's posture, not InsForge's compose default).

*Why managed postgres and not InsForge's own image:* compute exposes HTTP only, so a postgres container on compute is
unreachable by its siblings. Managed pg 16 covers what InsForge needs, measured on staging: the DSN's role is
**superuser** with CREATEROLE, `pg_cron` is in `shared_preload_libraries` with `cron.database_name` = your database,
`CREATE EXTENSION` works for `pgcrypto`, `http`, `pg_cron` (`vector` preinstalled), event triggers and
`ALTER DATABASE … SET` work, LISTEN/NOTIFY works, and the client **must** speak TLS (SNI-routed lane; `sslmode=disable`
lands on the wrong instance). The one thing it lacks is InsForge's `insforge_pg_utils` preload hook, which lets the
non-owner `project_admin` role manage RLS policies on InsForge's own tables and run `CREATE EXTENSION`. RLS behaved
**identically** without it; `CREATE EXTENSION` through InsForge's SQL endpoint returned
`403 permission denied to create extension`. `ALTER ROLE project_admin SUPERUSER` closes that (measured; `GRANT
CREATE ON DATABASE` covers trusted extensions only). **Say what it costs before you do it:** `project_admin` is the
role InsForge runs admin SQL and its dashboard SQL editor as, so making it superuser means anything that can execute
SQL through that path bypasses RLS and every other privilege check — the hook exists precisely to avoid that on a
shared box. Here the connection string insta hands you is already superuser, so the escalation adds no reachable
privilege that the operator did not already hold, and a project that never installs extensions can simply skip this
line and keep `project_admin` unprivileged. There is no narrower supported alternative today: the hook is a
compiled preload library and managed instances cannot load one.

**The four secrets travel.** `JWT_SECRET`, `ENCRYPTION_KEY`, `ACCESS_API_KEY`, `ACCESS_ANON_KEY` from the source
`.env` go onto the target **verbatim**: sessions stay valid, `system.secrets` (JWT keypair, API keys) decrypts, the
app's anon key is unchanged. `ENCRYPTION_KEY` falls back to `JWT_SECRET` when unset, so a source that never set it
must keep `JWT_SECRET` for both reasons. Read them from the file, never print them.

**Four of the lines below are STEPS, not checks, and the difference matters now that verification is
the developer's.** A check confirms the move worked; a step is something that, left out, makes the move
wrong with nothing to notice: the dump-completeness guard (a wrong database name yields an empty file
that restores with zero errors), `UPDATE cron.job SET database` (the dump names the source's database,
so every schedule silently stops), binding **both** bucket names (an older source writes uploads to
local disk while the bucket stays empty), and copying files before dumping. Never drop these on the
grounds that the developer will verify.

**Order matters three times.** (1) **Every source writer stops before EITHER snapshot is taken.** Step 2 of the
ordered cutover applies here in full: the files and the database are two halves of one state, so an upload that
lands between them is a row in the dump with no object behind it, and a delete is an orphan. `docker compose stop
insforge postgrest deno` first; postgres itself stays up, because the dump reads it. **Stopping the containers is
not the whole barrier here:** InsForge schedules are `pg_cron` jobs, and pg_cron fires *inside* postgres, the one
container still running — so a schedule keeps writing across both snapshots unless you deactivate the jobs too.
Deactivate them on the source, and reactivate exactly those on the target after the restore (the dump carries
`cron.job` with its `jobid`s, and every row in it is inactive because you deactivated them before dumping). (2) **Files before the dump,
inside that barrier:** bucket and object metadata live in `storage.buckets` / `storage.objects` and ride the dump,
so a dump taken before the files are copied leaves the target listing nothing (measured; the restore had to be
redone). (3) **PostgREST before the backend:** the backend needs `POSTGREST_BASE_URL` at boot and a compute service
has no URL until its first deploy.

The sequence, as measured (`<v>` = the source's `insforge-oss` tag; deploy the **same** version — the dump carries
`system.migrations`, and a newer image would run further migrations on boot, an older one would refuse):

```bash
# 0. read .env FIRST (compose reads it automatically; your shell does not, and everything below needs it), then
#    stop every source writer
envval() { sed -n "s/^$1=//p" .env | head -1; }      # no `source .env` — values are unquoted and would be executed
JWT_SECRET="$(envval JWT_SECRET)"; ENCRYPTION_KEY="$(envval ENCRYPTION_KEY)"
SRC_DB="$(envval POSTGRES_DB)"; SRC_DB="${SRC_DB:-insforge}"   # compose's own default; NOT necessarily `insforge`
[ -n "$JWT_SECRET" ] || { echo 'no JWT_SECRET in .env — wrong directory?' >&2; exit 1; }
docker compose stop insforge postgrest deno          # postgres stays up: the dump reads it
src() { docker compose exec -T postgres psql -U postgres "$SRC_DB" -v ON_ERROR_STOP=1 "$@"; }   # stop on SQL error:
src -Atc 'select jobid from cron.job where active' > cron-active.txt || exit 1   # psql exits 0 on one otherwise,
src -c 'update cron.job set active = false' || exit 1   # and an empty file would read as "no schedules". The
# `|| exit 1` is the half that matters: ON_ERROR_STOP only sets an exit code, and this block has no `set -e` (which
# would misfire on the `[ -s … ] &&` line later), so without it a failed deactivation just scrolls past — pg_cron
# pg_cron's key is `jobid`, not `id`.               # runs INSIDE postgres, the one container still up, so its jobs
                                                     # would keep writing across both snapshots
# (rolling back to the source means re-running that update with `= true where jobid in (…)` there as well)

# services
insta --agent service add postgres db
insta --agent service add storage files
insta --agent service add compute api --port 7130 --always-on --volume 10   # volume: logs, local-disk fallback
insta --agent service add compute postgrest --port 3000 --always-on

# 1. initialise the managed database the way InsForge's postgres image does on first boot
PG="$(insta --agent postgres url db)"
psql "$PG" -X -v ON_ERROR_STOP=1 -f deploy/docker-init/db/db-init.sql     # roles anon/authenticated/project_admin,
                                                                           # grants, 2 event triggers: 15 stmts, 0 errors
# jwt.sql says `ALTER DATABASE postgres SET …`. A managed instance HAS a database named postgres, so verbatim it
# SUCCEEDS SILENTLY against the wrong database (measured). Retarget it to the current one:
{ echo 'SELECT current_database() AS dbname \gset'
  sed 's/ALTER DATABASE postgres /ALTER DATABASE :"dbname" /' deploy/docker-init/db/jwt.sql
} | JWT_SECRET="$JWT_SECRET" JWT_EXP=3600 psql "$PG" -X -v ON_ERROR_STOP=1 -f -
# postgresql.conf cannot be mounted; its GUCs become per-database settings, same values as the conf:
DB="$(psql "$PG" -Atc 'select current_database()')"
psql "$PG" -v ON_ERROR_STOP=1 \
  -c "ALTER DATABASE \"$DB\" SET app.encryption_key TO '${ENCRYPTION_KEY:-$JWT_SECRET}'" \
  -c "ALTER DATABASE \"$DB\" SET insforge.policy_grant_role TO 'project_admin'" \
  -c "ALTER DATABASE \"$DB\" SET insforge.extension_grant_role TO 'project_admin'" \
  -c "ALTER DATABASE \"$DB\" SET insforge.policy_grant_tables TO '<value from postgresql.conf>'" \
  -c "ALTER DATABASE \"$DB\" SET insforge.internal_schemas TO '<value from postgresql.conf>'" \
  -c "ALTER ROLE project_admin SUPERUSER"                                  # stands in for insforge_pg_utils

# 2. secrets and bindings (values from the source .env, from stdin — never as arguments)
for n in JWT_SECRET ENCRYPTION_KEY ACCESS_API_KEY ACCESS_ANON_KEY ROOT_ADMIN_USERNAME ROOT_ADMIN_PASSWORD \
         FLY_API_TOKEN FLY_ORG VERCEL_TOKEN VERCEL_TEAM_ID VERCEL_PROJECT_ID; do   # the last five: see the
                                                    # compute note below. Names absent from .env are skipped.
  v="$(envval "$n")"; [ -n "$v" ] || continue     # a name absent from .env must stay absent here: setting an EMPTY
  printf '%s' "$v" | insta --agent secrets set "$n" --service compute/api   # ENCRYPTION_KEY defeats its own
done                                              # fallback to JWT_SECRET and breaks system.secrets decryption
insta --agent secrets bind PGRST_DB_URI postgres/db --to compute/postgrest   # PostgREST takes the DSN as-is (sslmode inside)
grep '^JWT_SECRET=' .env | cut -d= -f2- | insta --agent secrets set PGRST_JWT_SECRET --service compute/postgrest
insta --agent secrets set PGRST_DB_SCHEMA public --service compute/postgrest # + PGRST_DB_ANON_ROLE anon, PGRST_DB_POOL 50,
                                          # PGRST_DB_CHANNEL_ENABLED true, PGRST_DB_CHANNEL pgrst, PGRST_SERVER_PORT 3000: copy the compose file
insta --agent secrets bind DATABASE_URL postgres/db --to compute/api        # its bootstrap scripts read this…
# …but the runtime reads POSTGRES_HOST/PORT/DB/USER/PASSWORD. Split the DSN in-process, never print it:
python3 - "$PG" <<'PY2' | while IFS== read -r k v; do printf '%s' "$v" | insta --agent secrets set "$k" --service compute/api; done
import sys, urllib.parse as u; d = u.urlsplit(sys.argv[1])
for k, v in (("POSTGRES_HOST", d.hostname), ("POSTGRES_PORT", d.port or 5432), ("POSTGRES_DB", d.path.lstrip("/")),
             ("POSTGRES_USER", u.unquote(d.username or "")), ("POSTGRES_PASSWORD", u.unquote(d.password or ""))): print(f"{k}={v}")
PY2
insta --agent secrets set PGSSLMODE require --service compute/api           # node-postgres reads it; the lane requires TLS
insta --agent secrets bind S3_ACCESS_KEY_ID     storage/files --source-name AWS_ACCESS_KEY_ID     --to compute/api
insta --agent secrets bind S3_SECRET_ACCESS_KEY storage/files --source-name AWS_SECRET_ACCESS_KEY --to compute/api
insta --agent secrets bind S3_BUCKET            storage/files --source-name BUCKET_NAME           --to compute/api
insta --agent secrets bind AWS_S3_BUCKET       storage/files --source-name BUCKET_NAME           --to compute/api
# BOTH names, always. `S3_BUCKET` only exists from 2.3.x (`app.config.ts`: 2.2.6 reads `AWS_S3_BUCKET`, 2.3.2 reads
# `S3_BUCKET || AWS_S3_BUCKET`), and a source below that **fails SILENTLY**: with only `S3_BUCKET` bound, uploads
# answer 201, rows land in `storage.objects`, and the bytes go to the container's local disk while the bucket stays
# empty (measured on 2.2.6). Verify with `insta --agent storage list --service files` after one upload, not with
# the API's status code.
insta --agent secrets bind S3_ENDPOINT_URL      storage/files --source-name AWS_ENDPOINT_URL_S3   --to compute/api
insta --agent secrets bind S3_REGION            storage/files --source-name AWS_REGION            --to compute/api
insta --agent secrets set S3_FORCE_PATH_STYLE true --service compute/api
insta --agent secrets set S3_USE_PRESIGNED_URLS true --service compute/api
insta --agent secrets set DENO_RUNTIME_URL http://deno.invalid:7133 --service compute/api   # or the functions service URL
insta --agent secrets set INSFORGE_TELEMETRY_DISABLED 1 --service compute/api

# 3. files FIRST (writers already stopped in step 0): out of the source volume, into the bucket under InsForge's
#    key layout ${APP_KEY:-local}/<bucket>/<key>
docker compose cp insforge:/insforge-storage/. ./storage-data/               # on disk: <bucket>/<key>
eval "$(insta --agent secrets --print --json --service compute/api | jq -r \
  '"export AWS_ACCESS_KEY_ID=\(.S3_ACCESS_KEY_ID|@sh) AWS_SECRET_ACCESS_KEY=\(.S3_SECRET_ACCESS_KEY|@sh) S3_BUCKET=\(.S3_BUCKET|@sh) S3_ENDPOINT_URL=\(.S3_ENDPOINT_URL|@sh)"')"
aws s3 sync ./storage-data "s3://$S3_BUCKET/local/" --endpoint-url "$S3_ENDPOINT_URL"   # measured: etags equal to source

# 4. THEN the database, dumped the way InsForge's deploy/backup.sh dumps it: plain, WITH owners and privileges
docker compose exec -T postgres pg_dump -U postgres "$SRC_DB" \
  | awk '!d && /^SET transaction_timeout/ {d=1; next} /^\\restrict / {next} /^\\unrestrict / {next} {print}' \
  > dump.sql || exit 1                               # $SRC_DB, not a literal
grep -q '^-- PostgreSQL database dump complete' dump.sql \
  || { echo "dump.sql is empty or truncated — read pg_dump's stderr; \$SRC_DB was '$SRC_DB'" >&2; exit 1; }
# **Filter even though the server is 15.** `ghcr.io/insforge/postgres:v15.13.4` ships a pg_dump **18**, so the
# dump carries `SET transaction_timeout` (a PG17 GUC) and `\restrict`/`\unrestrict` no matter that the server is
# 15. Measured: without the filter the restore reports `errs=1`,
# `ERROR: unrecognized configuration parameter "transaction_timeout"`, and the gate below sends you to a fresh
# postgres service over a no-op session setting. The awk is step 3's, unchanged.
# Both guards are the point: pg_dump writes its errors to STDERR, so a wrong database name leaves dump.sql empty,
# and an empty file restores with 0 errors — the stated pass condition, met against an empty database. The trailing
# marker also catches a dump truncated by a disk filling up.
psql "$PG" -X -v ON_ERROR_STOP=0 -f dump.sql 2>&1 | tee restore.log          # 0, not 1: collect EVERY error, not the first
errs="$(grep -cE '^(psql:.*)?ERROR' restore.log || true)"                    # measured: 0 (791 stmts; 96 OWNER TO, 282 GRANTs)
[ "$errs" = 0 ] || { echo "restore: $errs errors — read restore.log, fix the cause, restore into a FRESH postgres service" >&2; exit 1; }
psql "$PG" -c "UPDATE cron.job SET database = current_database()"           # the dump names the source database (UPDATE 2)
[ -s cron-active.txt ] && psql "$PG" -v ON_ERROR_STOP=1 -c "UPDATE cron.job SET active = true WHERE jobid IN ($(paste -sd, cron-active.txt))"
                                                                             # step 0 deactivated these; ids travel in the dump

# 5. deploy PostgREST, feed its URL to the backend, deploy the backend, tell it its own URL
insta --agent deploy --image postgrest/postgrest:v12.2.12 --port 3000 --group postgrest
insta --agent secrets set POSTGREST_BASE_URL "https://<postgrest host from service list>" --service compute/api
                                          # prints `= compute/api (no-image)`: nothing is deployed there YET, not a failure
insta --agent deploy --image ghcr.io/insforge/insforge-oss:<v> --port 7130 --group api   # boots, `migrate:up` finds the ledger complete
insta --agent secrets set API_BASE_URL "https://<api host>" --service compute/api   # + VITE_API_BASE_URL, same value
                                          # CLI >= 0.0.78: `secrets set --service` redeploys compute/api itself.
                                          # On an older build add: insta --agent compute restart api
```

**One more thing to tell the user before the cutover:** the target inherits the source's auth
configuration, so a source with email verification on and no SMTP configured produces a target where existing users
are fine but **new signups cannot log in** (`403 Email verification required`, `accessToken: null`). Measured.
Configure SMTP or turn verification off before you hand the app over.

*Pass:* the restore reported zero errors, **the backend booted on the source's own version** —
`GET /api/health` returns `{"status":"ok","version":"<v>"}` and the boot log says
`No migrations to run! Migrations complete!` — and `system.migrations` counts match. That third one is
nearly free and worth keeping *here* specifically: InsForge owns this schema, so its own ledger
agreeing is the schema's author confirming the restore, which no generic app can offer. Everything
past that — do my bookings show up, can my users sign in, do my files download — is the developer's,
as in step 4.

**Two properties this path has, measured rather than re-checked per migration.** Say them; do not turn
them into gates. (a) **Sessions survive**: on both runs `ANON_KEY`, `API_KEY`, `JWT_PRIVATE_KEY` and
`JWT_KEY_ID` came back byte-identical on the target and a fresh login minted RS256 under the source's
own `kid`, so nobody logs in again and no OAuth or API key is re-entered. (b) **Files arrive intact**:
public objects download anonymously through a presigned redirect, private ones 401 anonymous and 200
with a session, sha256 equal to source.

Then the app: change `baseUrl` in `createClient` to the api host — keys unchanged.

**Edge functions: a fourth compute service, and they work.** Measured on staging 2026-09-14, four functions
including one inserted **straight into `functions.definitions` by SQL** — exactly what `pg_restore` does — which
answered 200 with nothing restarted. The host is stateless and reads that table per request, so function code needs
no migration of its own beyond the dump it already rides in.

*Why it takes a build.* No deployment target runs a prebuilt image here: compose mounts `functions/` into the stock
`denoland/deno:alpine-2.0.6` and supplies a `command:`, Railway builds from the repo and overrides the start
command, Zeabur inlines `server.ts` into its template. `deploy/Dockerfile.deno` exists but **has no `CMD`** — it was
never meant to run alone — and `deno.json` has no `tasks.start`, so nixpacks detects the runtime and stops:
`setup: deno`, `start:` empty, `Error: No start command could be found` (measured). Until this platform can set a
start command, you supply one in a Dockerfile:

```bash
SRC=<insforge checkout>; TAG=<the tag the backend runs>   # match the backend's version, not `main`
mkdir -p deno-build && cd deno-build
git -C "$SRC" archive "$TAG" functions | tar -x           # NO --strip-components: the Dockerfile does
git -C "$SRC" show "$TAG":deploy/Dockerfile.deno > Dockerfile   # `COPY functions /app/functions`
cat >> Dockerfile <<'EOF'
# Upstream ends at `USER deno` and stops there: no CMD, because compose supplies `command:`.
# These four lines are the whole of what this platform is missing, written into the image.
ENV DENO_DIR=/deno-dir
RUN deno cache --no-lock /app/functions/server.ts
EXPOSE 7133
CMD ["deno","run","--no-lock","--unstable-worker-options","--allow-net","--allow-env",\
     "--allow-read=./functions/worker-template.js","functions/server.ts"]
EOF
insta --agent build .                                     # from INSIDE deno-build. Verdict must read
                                                          # `deployable`, not `needs-attention`
insta --agent service add compute deno --port 7133 --always-on

# Secrets are per-service: nothing set on compute/api reaches compute/deno. Copy the ones it shares,
# straight across, without either value passing through your terminal. **The trap is the load-bearing half**:
# mktemp already creates 0600 whatever the umask, but the guard below exits, and without the trap the dump of
# every credential stays on disk.
umask 077   # belt and braces; mktemp does not need it
API_ENV="$(mktemp -t insta-api-env)"        # OUTSIDE deno-build: `deploy .` uploads that whole
trap 'rm -f "$API_ENV"' EXIT INT TERM       # directory to the remote builder, and a secrets dump
insta --agent secrets --print --json --service compute/api > "$API_ENV"   # inside it would ride along
for n in POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
         JWT_SECRET POSTGREST_BASE_URL; do
  v="$(jq -r --arg k "$n" '.[$k] // empty' "$API_ENV")"
  [ -n "$v" ] || { echo "compute/api has no $n" >&2; exit 1; }
  printf '%s' "$v" | insta --agent secrets set "$n" --service compute/deno
done
# ENCRYPTION_KEY: copy it **if and only if the source has one**. Both halves matter and they are not in
# tension. A source that never set one is a supported shape: host and backend both fall back to JWT_SECRET,
# together. A source that DID set one and a host that does not get it is the failure below — the two sides
# then use different keys. Setting it empty produces that same split.
enc="$(jq -r '.ENCRYPTION_KEY // empty' "$API_ENV")"
[ -z "$enc" ] || printf '%s' "$enc" | insta --agent secrets set ENCRYPTION_KEY --service compute/deno
for kv in PORT=7133 DENO_ENV=production WORKER_TIMEOUT_MS=60000; do   # DENO_DIR comes from the image
  printf '%s' "${kv#*=}" | insta --agent secrets set "${kv%%=*}" --service compute/deno
done                       # each prints `= compute/deno (no-image)` until the deploy below — expected, not a failure

insta --agent deploy . --port 7133 --group deno           # still inside deno-build
printf '%s' "https://<deno host>" | insta --agent secrets set DENO_RUNTIME_URL --service compute/api
                          # CLI >= 0.0.78: redeploys compute/api itself, and the backend then proxies
                          # /functions/:slug to that URL. On an older build add: insta --agent compute restart api
```

Three measured details. **`ENCRYPTION_KEY` is required, not optional**: the host decrypts function secrets with
`ENCRYPTION_KEY || JWT_SECRET`, so giving it only `JWT_SECRET` when the source set both means it silently decrypts
nothing. **`PGSSLMODE` is a no-op here** — `functions/server.ts` builds its config from the five `POSTGRES_*` and
never reads it; TLS works because the Deno driver negotiates it. **Cold starts cost about a second, and there is no
tested fix**: each cold worker does `await import('npm:@insforge/sdk')`, roughly 40 registry downloads on first
invocation (1471 ms against ~200 ms warm), repeated after every restart. The obvious answer, a volume for the
module cache, does **not** work as written: insta volumes mount at `/data` and arrive empty (the disk
row in `../migrate.md` says a fresh one holds `lost+found`), so an image that prepares and chowns `/data` at build time has that
preparation hidden by the mount, and the container — which runs as the non-root `deno` user — then cannot write
there. Fixing it needs a runtime chown before dropping privileges, which the measured run did not do. Leave the
volume off unless you are willing to test that.

**One thing the dump breaks, and you must fix it by hand.** `INSFORGE_BASE_URL` and `INSFORGE_INTERNAL_URL` are
**reserved** secrets carrying the source's compose-era addresses (`http://localhost:<APP_PORT>`,
`http://insforge:7130`). The API refuses to update a reserved secret (`Cannot update reserved secret`), and the
rewrite in `function.service.ts` is gated on `isCloudEnvironment()`, so it never runs here. Every function following
InsForge's documented `baseUrl: Deno.env.get('INSFORGE_BASE_URL')` pattern dials localhost and fails. The values must be re-encrypted in place in `system.secrets`, with the same scheme the backend
reads: AES-256-GCM, key `SHA256(ENCRYPTION_KEY)`, stored as `iv:authTag:ciphertext`
(`backend/src/infra/security/encryption.manager.ts`).

**There is no vetted command for this here, on purpose.** It is a direct ciphertext write to the secret store of a
database you have just migrated, and nothing in this runbook has been executed against it. Do not improvise one
against production. Work it out on a branch first, and note that
**`branch create` does not switch to it** — without the switch every command below still runs against `main`,
which is the one outcome this step exists to prevent:

```bash
insta --agent branch create fix-urls        # forks the postgres (CoW) and the compute services
insta --agent branch switch fix-urls        # REQUIRED: create alone leaves you on main
insta --agent status                        # confirm `branch fix-urls` before touching anything
```

The branch's api and deno come up already running the parent's image (`references/branching.md`), so there is
nothing to deploy to make them serve. **What does not follow is any value you set by hand.** `secrets bind` rules
are remapped to the branch's services; a `secrets set` value is copied verbatim. Step 2 above creates a lot of the
second kind, and on the branch every one of them still addresses **main**:

| still points at main | where | remapped? |
| --- | --- | --- |
| `POSTGRES_HOST` `PORT` `DB` `USER` `PASSWORD` | compute/api **and** compute/deno | no — literals, split from the DSN by hand |
| `POSTGREST_BASE_URL` | compute/api, compute/deno | no |
| `DENO_RUNTIME_URL` | compute/api | no |
| `DATABASE_URL`, `PGRST_DB_URI` | api, postgrest | **yes** — these two are bindings |

**Re-point all of them and restart both services before you touch anything.** Left alone, this step does the exact
opposite of its purpose: the backend's runtime reads the five `POSTGRES_*`, not `DATABASE_URL`, so a "branch test"
writes the ciphertext into **main's** `system.secrets` against **main's** database. Take the branch's own DSN from
`insta --agent postgres url "$PG" --branch fix-urls`, split it the same way step 2 does, set the five on both
services and the two URLs on api, then start or restart each one (`compute start` first if it is asleep, which it
is on insta-oss).

**Prove it before the write, not after**: the host in the branch api's `POSTGRES_HOST` must equal the host in the
branch's DSN, and must differ from main's.

```bash
insta --agent secrets --print --json --service compute/api --branch fix-urls | jq -r .POSTGRES_HOST
insta --agent postgres url "$PG" --branch fix-urls | sed -E 's#^([a-z+]+://)[^@]*@#\1***@#'
```

Then work out the update against
the branch's database, read `ENCRYPTION_KEY` from the service's own secrets rather than retyping it, write only
the two named rows, and confirm by calling a function that reads `INSFORGE_BASE_URL` rather than by selecting the
plaintext back. Only once that passes, repeat it on `main` with `--branch main`.

**Ask where the app itself runs.** A self-hosted InsForge can host apps three ways, and the answer changes what
you owe the user. `providers/compute/docker.provider.ts` runs containers through a **mounted Docker socket** on
their own machine. `providers/compute/fly.provider.ts` runs them in the user's **own Fly account** — its comment
says self-hosters enable compute by setting `FLY_API_TOKEN` and `FLY_ORG`, which is why those two are in the
secret loop above. `providers/deployments/vercel.provider.ts` pushes frontends, and needs `VERCEL_TOKEN`, `VERCEL_TEAM_ID` and
`VERCEL_PROJECT_ID` in the backend's environment or it refuses every management call
(`VERCEL_TOKEN not found in environment variables`).

**Carry all five when they exist**, for one reason that covers both: those resources belong to the user and keep
serving, the `compute` and `deployments` schema rows that reference them ride the dump, and without the
credentials the new backend can see the rows and cannot inspect, redeploy or otherwise manage what they point at.
The source is stopped, so only one InsForge is ever driving that Fly account or that Vercel project.

A Vercel-hosted frontend needs one more thing the credentials do not give it: its own `baseUrl` points at the old
InsForge, so it must be **redeployed** after the change, through the migrated backend or through Vercel directly.
Until it is, the frontend serves fine and talks to a backend that is stopped.

The Docker-socket case is the one with work left: those containers were on the machine the migration stops, so
nothing is left serving them. That is **optional work after the migration, not part of it** — a compute service
like any other, `insta --agent deploy <dir> --port <n>` from the app's checkout. Offer it, do not assume it, and
do not let it delay the cutover. If step 1 of the ordered cutover
proved the stack on a first database and you restore into a fresh one, rebind **both** `DATABASE_URL` (api) and
`PGRST_DB_URI` (postgrest) and re-set the five `POSTGRES_*` — the `$PG` trap applies here twice. Two small
measured annoyances: InsForge admin tokens expire after 900 s (`"Invalid token"` on reuse), and PostgREST's schema
cache lags a `CREATE TABLE` by about a second (first insert 404, then 201).

---

**From InsForge Cloud.** The shape above holds and seven things change. **The migration is measured, on
2026-09-14** against a real cloud project (backend 2.2.6, PG 15.18 → insta pg 16): every table row-for-row
identical, users, migrations and `system.secrets` counts equal, anon reads 200 through both the InsForge API and
PostgREST. **The commands are a transcription of that run, not a recording of it**, and re-checking them against
`@insforge/cli` 0.2.8 found three that cannot run as written: a `connectionString` key that the CLI spells
`connectionURL`, `.data`-wrapped S3 fields that are flat, and a line continuation killed by a trailing comment,
which silently dropped `AWS_ACCESS_KEY_ID` (reproduced). They are corrected below against the CLI's own output
shapes, and **the corrected forms have not been re-executed against a cloud project.** Read the outcome as
measured and the sequence as reviewed.

1. **There is no `.env` and no container — the backend serves the migration inputs.** `secrets get <KEY>` returns
   `JWT_SECRET`, `ANON_KEY`, `API_KEY` and `JWT_PRIVATE_KEY`; `db connection-string` (cloud only) returns the DSN
   for a host `pg_dump` over TLS. **Both print the credential to stdout, so neither may be run bare** — the rule
   `../migrate.md` sets for every credential applies here: pipe each value straight into its destination, and
   capture the DSN into a mode-600 file you never `cat`:

   ```bash
   umask 077                                         # everything written below is 600
   ifc() { npx -y @insforge/cli --json "$@"; }
   work="$(mktemp -d)"; key_id=""                    # ONE trap for the whole path: the DSN, the derived libpq
   cleanup() {                                       # env and the minted S3 key must not outlive this shell,
     [ -n "$key_id" ] && ifc storage s3-keys delete "$key_id" >/dev/null 2>&1   # on success OR on any exit.
     rm -rf "$work"
   }
   trap cleanup EXIT INT TERM                        # set BEFORE anything sensitive exists, not after
   for p in JWT_SECRET:JWT_SECRET API_KEY:ACCESS_API_KEY ANON_KEY:ACCESS_ANON_KEY; do
     v="$(ifc secrets get "${p%%:*}" | jq -r '.value // empty')"   # `// empty` prints NOTHING for a missing key.
     [ -n "$v" ] || { echo "source returned no ${p%%:*}" >&2; exit 1; }   # `jq -e` would still print `null`, and
     printf '%s' "$v" | insta --agent secrets set "${p##*:}" --service compute/api || exit 1   # with no pipefail
   done                                              # the status is `secrets set`'s, so CHECK it: an unchecked
                                                     # write scrolls past and the target keeps the wrong key.
   # ROOT_ADMIN_* cannot be read from the source (point 2), and without them the first deploy 502s with nothing
   # serving. **The user picks the password; do not generate one.** They are the dashboard's only admin login and
   # insta has no `secrets get` — `secrets list` returns names, not values — so anything minted here is gone the
   # moment this shell exits. Take it from the environment, which keeps it out of argv the way the PG* vars below do.
   [ -n "$ROOT_ADMIN_PASSWORD" ] || { echo 'ask the user to choose ROOT_ADMIN_PASSWORD and export it first: it cannot be read back later' >&2; exit 1; }
   printf 'admin' | insta --agent secrets set ROOT_ADMIN_USERNAME --service compute/api || exit 1
   printf '%s' "$ROOT_ADMIN_PASSWORD" | insta --agent secrets set ROOT_ADMIN_PASSWORD --service compute/api || exit 1

   # The CLI spells this key `connectionURL` (`outputJson({ connectionURL: url })`, cli 0.2.8). With
   # `.connectionString` the jq yields empty and the guard below stops every cloud migration dead.
   ifc db connection-string | jq -r '.connectionURL // empty' > "$work/src.dsn"
   [ -s "$work/src.dsn" ] || { echo 'no connection string — is this a cloud project, and is its backend up?' >&2; exit 1; }

   # libpq env, never argv: `psql "$(cat src.dsn)"` expands BEFORE psql runs, so the DSN lands in the command line
   # where `ps` shows it to every local user. PGHOST/PGPASSWORD/… do not appear there.
   python3 - "$work/src.dsn" > "$work/src.pgenv" <<'PY2'
   import sys, shlex, urllib.parse as u
   d = u.urlsplit(open(sys.argv[1]).read().strip()); q = dict(u.parse_qsl(d.query))
   for k, v in (("PGHOST", d.hostname), ("PGPORT", d.port or 5432), ("PGDATABASE", (d.path or "/").lstrip("/")),
                ("PGUSER", u.unquote(d.username or "")), ("PGPASSWORD", u.unquote(d.password or "")),
                ("PGSSLMODE", q.get("sslmode", "require"))):
       print(f"export {k}={shlex.quote(str(v))}")
   PY2
   . "$work/src.pgenv"                               # psql and pg_dump below take NO connection argument
   SRC() { psql -X "$@"; }                           # …and neither does the dump: `pg_dump > dump-raw.sql`
   ```

   **`ENCRYPTION_KEY` is absent on cloud, and must stay absent** — measured,
   `sha256(current_setting('app.encryption_key'))` equals `sha256(JWT_SECRET)`, i.e. the cloud runs on the
   documented fallback, so carrying `JWT_SECRET` alone is sufficient. It is sufficient in the strong sense: on the
   target `ANON_KEY`, `API_KEY`, `JWT_PRIVATE_KEY` and `JWT_KEY_ID` all came back **byte-identical**, and a fresh
   login minted RS256 under the *source's* `kid` — **no user has to log in again**. Everything is gated on that one
   HTTP surface, so `curl -fsS <host>/api/health` must be 200 before you start; if it is not, the migration cannot
   begin and only the project's owner can fix it. The secret loop in step 2 above therefore sets three names here,
   not six: there is no `ENCRYPTION_KEY` and no `ROOT_ADMIN_*` to read.
2. **`ROOT_ADMIN_USERNAME` and `ROOT_ADMIN_PASSWORD` are not retrievable, and the backend refuses to boot without
   them.** They live only in the source's env (`auth.service.ts` compares against `process.env`) and are in no dump.
   Have the **user** choose new ones; nothing is lost, because they authenticate the dashboard's root admin and not
   any user row. Do not mint the password yourself: insta exposes no `secrets get`, so a generated value is
   unrecoverable once the migration shell exits and the user is locked out of their own dashboard.
   **The failure is badly disguised:** a first deploy without them fails as
   `the compute provider could not roll the deploy — the previous version keeps serving (HTTP 502)` with nothing
   serving at all. `insta --agent compute logs <svc>` carries the real line.
3. **The files come out over the S3 gateway — there is no volume to copy.** Skipping this is the one way to
   produce a migration that looks clean and is not: the dump carries `storage.buckets` and `storage.objects`, so a
   target restored without the bytes lists every file and serves none. InsForge Storage speaks S3 at
   `https://<app-key>.<region>.insforge.app/storage/v1/s3` (2.0.9+, **path-style only**, cloud only). Minting a key
   there is **the one write this path makes on the source**; delete it when you are done.

   ```bash
   # Same shell as the block above: `$work`, `key_id` and the EXIT/INT/TERM trap that revokes the key are already
   # in place. Assigning key_id is what arms the revoke, so it comes immediately after the create.
   ifc storage s3-keys create --description migration > "$work/src-s3.json"   # secret shown ONCE
   key_id="$(jq -r '.id // empty' "$work/src-s3.json")"
   [ -n "$key_id" ] || { echo 'no id in the s3-keys response — cannot guarantee revocation' >&2; exit 1; }
   SRC_EP="https://<app-key>.<region>.insforge.app/storage/v1/s3"
   src_n="$(SRC -Atc 'select count(*) from storage.objects')"           # count BEFORE, from the source itself
   # `--json` gives a bare array on some versions and {"buckets": …} on others; the CLI itself accepts both.
   for b in $(ifc storage buckets | jq -r '(.buckets // .)[].name'); do
     # NOTHING may follow the `\`. A backslash before a space escapes the SPACE, not the newline, so a trailing
     # comment ends the command early and `aws` runs with AWS_ACCESS_KEY_ID unset (reproduced, not theorised).
     AWS_ACCESS_KEY_ID="$(jq -r .accessKeyId "$work/src-s3.json")" \
     AWS_SECRET_ACCESS_KEY="$(jq -r .secretAccessKey "$work/src-s3.json")" \
       aws s3 sync "s3://$b/" "./storage-data/$b/" --endpoint-url "$SRC_EP" || exit 1
   done
   [ "$(find ./storage-data -type f | wc -l | tr -d ' ')" = "$src_n" ] \
     || { echo "downloaded $(find ./storage-data -type f | wc -l) of $src_n objects — do NOT dump" >&2; exit 1; }
   ```

   The gateway is path-style only, and a custom `--endpoint-url` already addresses that way: measured on
   aws-cli 2.34.16 against a local listener, `s3://mybucket` went out as `Host: <endpoint>` and path `/mybucket`,
   with `AWS_S3_ADDRESSING_STYLE=path` making no difference (it is not a botocore variable). Nothing to set, but if
   a future client regresses, the documented knob is `aws configure set default.s3.addressing_style path`.

   Then upload with the same `aws s3 sync … s3://$S3_BUCKET/local/` that step 3 of the sequence above uses, and
   re-check the count on the target before moving on. **Both checks are fail-closed on purpose:** `aws s3 sync`
   exits 0 on an empty source, and so does a restore of metadata with no bytes behind it. Measured only in part —
   the cloud project tested had **no objects**, so the gateway path above is derived from InsForge's own S3
   documentation and verified on the target side only. Treat a cloud source that holds objects as **unproven**: run
   the two counts, and stop if they disagree.
4. **You cannot quiesce a cloud source, so read the exposure and be willing to stop.** There is no
   `compose stop`, no project pause, and deactivating `cron.job` would itself be a write on someone's production
   database, so step 0's barrier above has no equivalent here. Count the exposure through the DSN **before either
   snapshot**:

   ```bash
   SRC -Atc "select count(*) from cron.job where active and jobname not like 'insforge_%'" \
     | { read -r n; [ "$n" = 0 ] || { echo "$n active user schedule(s): this source cannot be snapshotted consistently" >&2; exit 1; }; }
   ```

   That is a **hard stop, not a warning**. A schedule that writes application rows fires between the file copy and
   the dump and there is no way to hold it, so the result is a migration that reports zero errors and is wrong.
   Either the owner disables those jobs on the source first, accepting that this is a write on their production
   database, or the migration does not run. The measured source passed this check with 2 internal cleanup jobs and
   no user schedules. With the check clear, freeze at the application level and keep the window short.
5. **Read the `insforge.*` GUCs off the live source, not out of the repo.** They drift:
   `select current_setting('insforge.internal_schemas', true)` on the measured source listed a schema the checked-in
   `postgresql.conf` does not. `db query --unrestricted` is **disabled** on cloud projects and the restricted mode
   denies the `cron` schema, so use the DSN for anything beyond ordinary reads.
6. **Deploy the tag, not the version string.** The API reports `service_version` `2.2.6`; the image is
   `ghcr.io/insforge/insforge-oss:v2.2.6` and the bare number 404s.
7. **The migrated project stops being a cloud project, and InsForge itself behaves differently.**
   `isCloudEnvironment()` (`backend/src/utils/environment.ts`) is true only when `AWS_INSTANCE_PROFILE_NAME` is
   set, which it is not here — so the result is a **self-hosted InsForge holding cloud data**, and the routes that
   branch on it flip. What the user LOSES, because the cloud control plane provided it and the container does not:
   **shared OAuth keys** (`isOAuthSharedKeysAvailable()` is `isCloudEnvironment()`, and
   `auth/oauth.routes.ts:114,166` refuses `useSharedKey` with `400 Shared OAuth keys are not enabled in this
   environment`, so every social login needs its own client id and secret), the managed OpenRouter key behind the
   AI gateway, the managed webscraper credentials, and **analytics**, which is cloud-only by construction:
   `providers/analytics/posthog.provider.ts` answers
   `501 PostHog integration is only available on Insforge Cloud, not in self-hosted mode.` and the history itself
   lives in InsForge's PostHog, not in the dump. Usage and billing history stay with the old account. What it
   GAINS: `/api/database/backups` and `/api/database/config`, which the backend mounts **only** under
   `!isCloudEnvironment()` (`api/routes/database/index.routes.ts:26`, whose own comment says the cloud control
   plane owns that scheduling). Enumerate this for the user **before** the cutover, not after.

**Re-registering the OAuth clients costs most users nothing, and for one provider it depends on the source's
cooperation.** Identities key on `provider` + `provider_account_id` (`000_create-base-tables.sql:106,112`), and
that value is whatever the provider returns. **Google** hands back `payload.sub` and **GitHub** its numeric user
id, both the same for a person whichever client asks, so those accounts survive a new client untouched — and those
two are exactly the pair cloud seeds by default (`utils/seed.ts:80-87`, `useSharedKey: true`). **Apple** scopes its
`sub` to the developer *team*, so a new team yields a new id: the same human signs in and lands on a NEW account
while the old one keeps its data, and for a Hide My Email user the relay address is team-scoped too, so the two
accounts share no field at all.

**That is not automatically unfixable.** Apple documents a user migration for exactly this
([TN3159](https://developer.apple.com/documentation/technotes/tn3159-migrating-sign-in-with-apple-users-for-an-app-transfer)):
the *outgoing* team exchanges each `sub` for a transfer identifier, and after the app or Services ID moves, the
receiving team exchanges those identifiers for its own `sub` and relay address — private relay users included. Two
conditions decide whether it is available to you, and both are about the source, not about you. The transfer runs
from the **source team's** credentials, so someone at InsForge has to run it. And it moves an app or Services ID
between teams, which a Services ID shared across many customers' projects cannot do for one of them. So: a project
that configured its **own** Apple client loses nothing, because the client does not change. A project on InsForge's
**shared** Apple client needs InsForge to run TN3159, and only if that is refused or impossible is the loss real —
at which point it is a hard stop worth raising before anything is copied, not an account merge you can build
afterwards.

Apple is never seeded, so it is present only if the project added it. **Run
`select provider, use_shared_key from auth.oauth_configs` during the inventory** and say what you find; check
Microsoft and LinkedIn yourself rather than assuming they behave like Google.
