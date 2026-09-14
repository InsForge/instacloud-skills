# The remote MCP server (`insta-cloud`)

InstaCloud's control plane is also exposed as a **remote MCP server** — Streamable HTTP at
`https://mcp.instacloud.com/mcp` — so MCP-capable agents (Claude Code, Claude.ai / ChatGPT
connectors, Cursor) can drive projects with native tool calls instead of shelling out to the CLI.
It is a stateless bridge over the same platform API the CLI uses: same auth, same governance
gates, same audit trail.

## When to use which

**The skill + CLI is the default — use the MCP tools only when the CLI can't be invoked**:
hosted agents with no shell (Claude.ai / ChatGPT connectors), or a machine where the CLI isn't
installed and can't be. When you do have a shell, prefer the CLI even if MCP tools are also
connected — it carries linked-repo context and covers everything except a few MCP-only
read-only diagnostics (`insta_runtime_health`, `insta_operations`, and `insta_db_stats`'s
`insight`/`activity`/`query-stats` kinds — its `metrics` kind is `insta --agent db stats`; see the
mapping table below), which are fine to call from any client. **The CLI is the only path** for
the things a remote server cannot or must not do:

| Capability | Why CLI-only |
|---|---|
| `insta --agent login` / auth / API-token CRUD | credential minting is deliberately not a remote tool |
| `insta --agent secrets` (pull values → `.env`) / `insta --agent run` | secret **values** never flow out of MCP — names only, values in |
| `insta --agent db url` / `insta --agent db connect` (postgres DSN) | same rule — the DSN is a value read, so it only exists on the CLI |
| `insta --agent deploy <dir>` (source builds) | needs a local build context; `insta_deploy` takes prebuilt image URLs only |
| `insta --agent observe` hook / `insta --agent setup` | local-machine operations |
| `insta --agent db limits` (database machine spec) | not yet exposed as an MCP tool |

## Connecting

`insta --agent setup agent` registers the server with Claude Code automatically (user scope). The default
is **OAuth — no credential is written**: registration is just

```bash
claude mcp add --transport http --scope user insta-cloud https://mcp.instacloud.com/mcp
```

and on first `/mcp` use Claude discovers the platform's authorization server (RFC 9728 → Better
Auth MCP plugin, dynamic client registration) and runs the browser flow — managed, expiring,
revocable tokens, nothing static on disk.

Setup also writes an OAuth (URL-only) entry into the config of **every other detected
MCP-capable agent** — Cursor, OpenAI Codex, OpenCode, GitHub Copilot, Factory Droid — and
`insta --agent mcp install --agent <slug>` targets one explicitly. Merges never clobber existing config
entries.

**Headless machines / CI:** `--mcp-token` is a Claude Code registration option, not a login bypass.
It requests a durable `insta_` token named `mcp-<hostname>` from the platform and stores it in an
`Authorization: Bearer` header. It needs both a logged-in CLI session and permission to create
tokens. Signed agent requests currently cannot create tokens (`403 unclassified_agent_action`);
logging in again does not grant that permission. Report the denial and stop this registration
attempt. Do not remove `--agent`, switch identity, or call the token API directly to get around it.

For unattended MCP, arrange supported authentication before the agent starts: complete the
client's OAuth flow, or have the authorized test harness configure an approved credential where
the client supports it. The credential must not go in the agent prompt or logs. URL-only OAuth
registration is not proof of authentication; verify the connection with an actual tool call.

`--mcp-token` does not convert an existing registration or configure token headers for other
clients. Existing entries stay unchanged. A failed token request or incomplete Claude registration
is an error, even if skills or another client's OAuth entry were installed successfully. On older
CLI versions (including 0.0.66), token failures can misleadingly print `needs a login` and exit 0;
do not treat that output as success.

## Environments

The URL above is production. The MCP host and its **registration name** are resolved from the
CLI's current environment, so the two can never drift apart:

| Environment | MCP server | Registers as |
|---|---|---|
| `prod` (default) | `https://mcp.instacloud.com/mcp` | `insta-cloud` |
| `staging` | `https://mcp.staging.instacloud.com/mcp` | `insta-cloud-staging` |

The distinct names matter: registration is idempotent by name, so a shared name would leave a
staging install silently pointed at the prod server. Because the names differ, **both can be
registered on one machine at once** — check which you're talking to with `insta --agent env`.

`insta --agent setup agent --env staging` (or `curl -fsSL agents.staging.instacloud.com | sh`) switches
the environment and registers staging's server in one step (CLI ≥ 0.0.38 — bare `setup agent`
always targets prod, so a bare re-run after `env use staging` would switch the machine back).
`INSTA_MCP_URL` still overrides outright, for a self-hosted or tunnelled server.

New/renamed tools need a **fresh agent session** to appear — reconnecting an existing session
won't pick them up.

## Tool ↔ CLI mapping

Naming is `insta_<noun>_<verb>`; every tool takes **explicit `projectId` / `branch` args** — the
server is stateless, there is no "current project" like `./.insta/project.json`. Get the
`projectId` from `insta_project_list` (or `.insta/project.json` if you're in a linked repo).

| CLI | MCP tool |
|---|---|
| `insta --agent status` (am I connected?) | `insta_whoami` |
| `insta --agent org list` / `create` | `insta_org_list` / `insta_org_create` |
| `insta --agent project list/create/delete` | `insta_project_list` / `insta_project_create` / `insta_project_get` / `insta_project_delete` |
| region discovery | `insta_regions` |
| `insta --agent services add/list/remove/rename` [`--branch`] | `insta_service_add` / `insta_service_list` / `insta_service_remove` / `insta_service_rename` (all take `branch?`; add takes `public?` for storage) |
| services public/private toggle | `insta_service_access` |
| `insta --agent services scale/upgrade` | `insta_service_scale` / `insta_service_upgrade` |
| `insta --agent compute start\|stop\|suspend\|restart` / `status` | `insta_compute_control` / `insta_compute_status` — `restart` needs a deployed insta-mcp carrying it; older servers reject the verb at schema validation |
| `insta --agent compute exec [service] -- <command>` | `insta_compute_exec` (`name?`/`branch?`/`command`/`timeoutSec?`) |
| `insta --agent compute limits/always-on/volume` | `insta_compute_limits` / `insta_compute_always_on` / `insta_volume` (read/grow: compute + managed fly DBs; remove: compute only, destroys the disk and its data) |
| `insta --agent compute set-domain/check-domain/remove-domain` | `insta_domain_set` / `insta_domain_check` / `insta_domain_remove` |
| `insta --agent branch create/list/merge/delete` | `insta_branch_create` / `insta_branch_list` / `insta_branch_merge` / `insta_branch_delete` |
| `insta --agent manifest` | `insta_manifest` (env view — **no secret values**) |
| `insta --agent secrets list/set/unset` | `insta_secrets_list` (names only) / `insta_secrets_set` / `insta_secrets_unset` |
| `insta --agent secrets sources/bindings/bind/unbind` | `insta_secret_sources` / `insta_secret_bindings` / `insta_secret_bind` / `insta_secret_unbind` (provider credential binding; names only, no secret values) |
| `insta --agent deploy --image <url>` | `insta_deploy` (image-only) |
| `insta --agent metrics/logs/events` | `insta_metrics` / `insta_logs` / `insta_deploy_events` / `insta_events` |
| runtime health / db provider operations (no CLI equivalent) | `insta_runtime_health` / `insta_operations` (database provider operations, not a general operations feed; for watching a postgres branch or restore settle) |
| `insta --agent db stats` (`metrics` kind; `insight`/`activity`/`query-stats` are MCP-only) | `insta_db_stats` (read-only; `kind` = metrics, insight, activity, query-stats) |
| `insta --agent usage` / `billing` | `insta_usage` / `insta_org_usage` (org-level, optional `from`/`to`) / `insta_billing_summary` / `insta_billing_overview` (org-level, current cycle only) |
| `insta --agent billing upgrade/portal` | `insta_billing_checkout` / `insta_billing_portal` — return a Stripe **URL for the human**; relay it, never claim payment happened |
| `insta --agent agent-policy get/set` | `insta_agent_policy_get` / `insta_agent_policy_set` (admin-only; restricted agents cannot change policy) |
| `insta --agent approvals list` | `insta_approvals_list`; approve/deny require a human terminal and are rejected through MCP |
| storage browse/download/delete | `insta_storage_list` / `insta_storage_download_url` / `insta_storage_delete` (no upload yet) |
| `insta --agent template list/info/deploy` | `insta_template_search` / `insta_template_get` / `insta_template_deploy` / `insta_template_deployment_status` |
| `insta --agent feedback` | `insta_feedback` (same fields; pass `projectId`/`branch` explicitly — see [cli-reference.md → Feedback](../cli-reference.md#feedback)) |

## Behavior that carries over from the CLI

- **Governance is identical.** Gated tools return `approval_required` + an `approvalId` instead of
  an error — run the same approval relay you'd run for the CLI (tell the human, wait, retry).
  Never treat `approval_required` as failure.
- **Custom-domain results include DNS records** for the developer's own registrar — relay them
  verbatim, like the CLI's printed table.
- Paid-tier gates (`scale`, `upgrade`) and branch caps (≤10) are enforced by the platform and
  surface as structured errors, same as the CLI.
