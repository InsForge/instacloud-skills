# Framework deploy recipes

Copy the recipe for the app's framework **before writing a Dockerfile from scratch** — each one
has the four first-deploy traps already solved, so `insta --agent deploy .` works on the first try.

## The four traps (why first deploys fail)

Every recipe below encodes these. If you hand-write a Dockerfile, get all four right:

1. **Bind `0.0.0.0`, never loopback (`127.0.0.1` or `::1`).** This accepts IPv4 connections from
   the router and readiness checks. `::` also works when the app and OS accept IPv4-mapped
   connections; a successful IPv6 bind alone does not establish dual-stack support. Do not enable
   IPv6-only mode. Set Next's standalone `HOSTNAME=0.0.0.0` explicitly.
2. **`EXPOSE <port>` in the Dockerfile.** `insta --agent deploy` derives `--port` from the last `EXPOSE`;
   without it the service wires to 8080 and refuses every request. Keep `EXPOSE` == the listen port.
3. **`PORT` env == the exposed port.** Read `process.env.PORT` and default it to the same number you
   `EXPOSE`. (The platform injects `PORT`; a mismatch is the classic 502.)
4. **Build only what runs.** Multi-stage: build in one layer, copy just the runtime output into a
   slim final image. Keeps images small and start fast.

Credentials arrive via injected env only after they are visible to the compute service: user config
from `insta --agent secrets set`, plus provider credentials you explicitly bind with `insta --agent secrets bind`
(`DATABASE_URL`, `BUCKET_NAME`, the `AWS_*` S3 bundle, `REDIS_URL`, `MYSQL_URL`, `MONGODB_URL`, …).
Never bake them into the image.

## Next.js (App Router or Pages) — the common case

`next.config.mjs` **must** set standalone output:

```js
/** @type {import('next').NextConfig} */
export default { output: 'standalone' }
```

`Dockerfile`:

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

Then: `insta --agent deploy .` (port auto-derives from `EXPOSE 3000`). Route handlers read `process.env`
for `DATABASE_URL` / the S3 bundle. Pool Postgres at module scope; set `idleTimeoutMillis` under
the database's scale-to-zero suspend window so an idle-suspended DB doesn't leave a dead socket.

## Node/Express (API or full-stack, backend serves the built SPA)

```js
app.listen(process.env.PORT || 3000, '0.0.0.0', () => console.log('up'))
```

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY . .
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "start"]
```

## Vite / static SPA (served by a tiny Node static server)

Build to `dist/`, serve it with a static server so client routes fall back to
`index.html`. Simplest is a 15-line Express static server (bind `0.0.0.0`, `EXPOSE 3000`) using the
Node recipe above with `app.use(express.static('dist'))` + a `* → dist/index.html` fallback.
Deploy it as its own compute service; point it at the API via a build-time env var.

## Python / FastAPI (uvicorn)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
```

## After any deploy — verify (non-negotiable)

`curl` the printed URL's health path until it's 200 (cold start takes a few seconds). A 404/502
that never clears can mean trap #1 (loopback or IPv6-only binding) or #3 (PORT≠EXPOSE) — check
`insta --agent logs compute`, which prints the platform's "instance refused connection" hint.
