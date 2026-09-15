**Fly.** Read `../migrate.md` first: its ordered cutover is the procedure and this file is only what Fly
adds to it. The easiest source of the four, and the only one that is not a Postgres downgrade: Fly
Managed Postgres runs **16**, the same major as insta's, so step 3 needs no filter. A Fly app also
already has a `Dockerfile` and a `fly.toml`, so `insta --agent deploy . --port <n>` from the local
checkout works **on every plane** — the flyctl lane builds the Dockerfile on Fly-backed compute, the
archive lane builds it on the build gateway for insta-compute — and needs no GitHub connection. A CLI
that predates the archive lane answers `source builds are not supported on the insta-compute
provider yet`: `insta upgrade`. **`$SOURCE_URL` in step 3 is the one thing you have to supply yourself:**
Fly Managed Postgres answers on Fly's private network, not the public internet, so run
`fly proxy 5432 -a <pg-app>` and dump over `localhost`, or run `pg_dump` from inside a Fly machine. `internal_port` in `fly.toml` is the `--port` value. `[env]`
entries become plain secrets **except `PORT`**, which this platform injects itself and the cutover tells
you to drop. Note the builder **ignores the repo's `fly.toml`** on the insta-compute
lane (`instaflybuilder` writes its own; the comment says caller config never reaches it), so nothing
in that file affects the build here. `[processes]` maps onto compute services, and
A volume carries the caveat in `migrate/railway.md`: creating one on the target copies nothing, so
download the source's contents while its service is still running. **The one real obstacle is secrets:** `fly secrets list`
returns names and digests only, because "the actual value of the secret is only available to the
application", so there is no export. Read them off the running machine before you stop it, **one name at a time, never the whole env**, and
piped so the value never reaches your output:

```bash
fly ssh console -a <app> -C 'printenv <NAME>' | tr -d '\r\n' | insta --agent secrets set <NAME>
```

`insta --agent secrets set` reads stdin, so nothing is displayed and nothing enters shell history. **Never
`fly ssh console -C env`**: it dumps every credential the app holds into your transcript at once.
And never run the `printenv` on its own to "check" a value first; that is the leak. If you cannot
pipe, have the user re-enter the value instead.
