# Storage buckets

`insta --agent services add storage <name>` gives the branch a **private, S3-compatible bucket**. There is
no vendor SDK and no InstaCloud storage client — point any S3 library at the bound credentials and
it works. This page is the part that isn't obvious: how bytes actually get in and out, and the
handful of things that bite first.

## What you get

Adding the service mints these credentials under the storage service:

| Variable | Example |
| --- | --- |
| `BUCKET_NAME` | `insta-b5f7e21d-…-f1de1ba6` |
| `AWS_ACCESS_KEY_ID` | `tid_…` |
| `AWS_SECRET_ACCESS_KEY` | `tsec_…` |
| `AWS_ENDPOINT_URL_S3` | `https://t3.storage.dev` |
| `AWS_REGION` | `auto` |

They do **not** automatically appear in every compute service. Bind the names your app needs into
the target compute service, then deploy/redeploy:

```bash
insta --agent secrets bind BUCKET_NAME storage/files --source-name BUCKET_NAME --to compute/app
insta --agent secrets bind AWS_ACCESS_KEY_ID storage/files --source-name AWS_ACCESS_KEY_ID --to compute/app
insta --agent secrets bind AWS_SECRET_ACCESS_KEY storage/files --source-name AWS_SECRET_ACCESS_KEY --to compute/app
insta --agent secrets bind AWS_ENDPOINT_URL_S3 storage/files --source-name AWS_ENDPOINT_URL_S3 --to compute/app
insta --agent secrets bind AWS_REGION storage/files --source-name AWS_REGION --to compute/app
```

Never bake these into an image; after binding, they arrive as runtime env on deploy.

## Writing and reading objects

Nothing InstaCloud-specific. Two rules cover it: **set the endpoint explicitly**, and leave the
region as `auto`.

```js
// Node — @aws-sdk/client-s3
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'

const s3 = new S3Client({
  endpoint: process.env.AWS_ENDPOINT_URL_S3,   // required — without it the SDK talks to real AWS
  region: process.env.AWS_REGION,              // 'auto'
})                                             // key/secret come from AWS_* automatically

await s3.send(new PutObjectCommand({
  Bucket: process.env.BUCKET_NAME,
  Key: 'avatars/u1.png',
  Body: bytes,
  ContentType: 'image/png',
}))
```

```python
# Python — boto3
import boto3, os
s3 = boto3.client('s3', endpoint_url=os.environ['AWS_ENDPOINT_URL_S3'], region_name=os.environ['AWS_REGION'])
s3.put_object(Bucket=os.environ['BUCKET_NAME'], Key='avatars/u1.png', Body=data, ContentType='image/png')
```

The same credentials drive any S3 tool, which is the quickest way to seed or inspect a bucket
(these examples assume an environment where the `AWS_*`/`BUCKET_NAME` values are already
bound/configured. There is no storage equivalent of `insta --agent db url`, but the branch's
**primary** storage service's `AWS_*`/`BUCKET_NAME` do arrive in `insta --agent secrets` /
`insta --agent run`, so a local `.env` usually has them already; a **non-primary** bucket's
credentials have to be bound to a compute service):

```bash
aws s3 ls "s3://$BUCKET_NAME" --recursive --endpoint-url "$AWS_ENDPOINT_URL_S3"
aws s3 cp ./dist "s3://$BUCKET_NAME/dist" --recursive --endpoint-url "$AWS_ENDPOINT_URL_S3"
rclone copy ./dist insta:$BUCKET_NAME/dist       # with the same key/secret/endpoint configured
```

## The traps

1. **Forgetting the endpoint.** An S3 client with credentials but no `endpoint` silently talks to
   real AWS and fails on a bucket that isn't yours. This is the single most common mistake.
2. **Assuming a bucket is shared across branches — or assuming it never is.** Normally each branch
   gets its **own** bucket (CoW-forked from the parent at `insta --agent branch create`) with its **own**
   scoped key, so a leaked branch credential cannot reach production data. **The exception is a
   legacy project whose root bucket predates snapshots: it keeps one shared bucket, with no storage
   isolation at all** — a branch writes straight into production's objects. `insta --agent manifest` shows
   what a branch really has, and it is the only way to know which case you are in. Either way, read
   `BUCKET_NAME` from env per branch rather than hardcoding a name you saw once.
3. **Expecting a branch's files to be promoted.** They are not. `insta --agent branch merge` creates missing
   services on the target **fresh and empty — no data is copied**, the same rule that applies to
   databases. Files uploaded while testing on a branch stay there; extract anything worth keeping
   before `branch delete`. See [branching.md](branching.md).
4. **Uploading without a `ContentType`.** S3 stores what you send and serves it back. Omit it and the
   object comes back as `application/octet-stream`, which makes a browser download it instead of
   showing it — so the console's preview, and any `<img src>` you point at a presigned URL, silently
   degrade. Always set it.
5. **Expecting to undelete.** There is no object versioning and no recycle bin. `insta --agent storage
   delete` and any S3 `DeleteObject` are permanent, and deleting a key that was never there still
   reports success — so success is not proof the file existed.
6. **Expecting search.** S3 filters by **key prefix** only; there is no substring match, in the CLI,
   the console, or the API. Design keys so the prefix is the thing you will want to filter on
   (`avatars/2026/…`, not `2026-avatars-…`).

## Public vs private

Buckets are private by default: reads need the credentials or a presigned URL. Flip a bucket to
anonymous public-read with

```bash
insta --agent services set-access storage <name> public   # or private
```

Public is a whole-bucket switch, not per-object. When only *some* files should be reachable, keep the
bucket private and have your own backend hand out a short-lived URL per request — the caller never
sees the credentials, and the link expires:

```js
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3'
import { getSignedUrl } from '@aws-sdk/s3-request-presigner'

const s3 = new S3Client({ endpoint: process.env.AWS_ENDPOINT_URL_S3, region: process.env.AWS_REGION })

// Your route does the authorization, then signs. 5 minutes is plenty for a redirect.
export async function fileUrl(key) {
  return getSignedUrl(s3, new GetObjectCommand({ Bucket: process.env.BUCKET_NAME, Key: key }), {
    expiresIn: 300,
  })
}
```

That is the same mechanism the console and `insta --agent storage get` use, so a private bucket is not a
limitation on serving files — only on serving them anonymously and forever.

## Managing a bucket without an S3 client

The platform exposes the objects directly, so the CLI, the console and MCP can all reach them:

```bash
insta --agent storage list                      # keys, size, last modified (--prefix to filter, --cursor to page)
insta --agent storage get <key> -o ./file       # short-lived presigned URL; bytes come straight from the provider
insta --agent storage delete <key>              # immediate and irreversible, no prompt
```

The console's storage service detail browses the same objects with preview, download, and single or
bulk delete. Agents get `insta_storage_list` / `insta_storage_download_url` / `insta_storage_delete`
over MCP — note the download tool returns a **URL, not bytes**.

Every path is governed (see [governance.md](governance.md)):

| Action | Covers |
| --- | --- |
| `storage.read` | listing, download, preview |
| `storage.write` | upload |
| `storage.delete` | single and bulk delete |

**Upload is console-only for now.** The browser uploads straight to the provider under a signed
policy that pins the content type and caps the size, so nothing streams through the control plane.
The CLI and MCP have no upload yet — from a script, use an S3 client or `aws s3 cp` as above.
