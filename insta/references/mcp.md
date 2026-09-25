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
read-only diagnostics (`insta_list_service_statuses`, `insta_list_postgres_operations`, and
`insta_get_postgres_stats`'s `insight`/`activity`/`query-stats` kinds — its `metrics` kind is
`insta --agent postgres stats`; see the mapping table below), which are fine to call from any
client. **The CLI is the only path** for the things a remote server cannot or must not do:

| Capability | Why CLI-only |
|---|---|
| `insta --agent login` / auth / API-token CRUD | credential minting is deliberately not a remote tool |
| `insta --agent secrets` (pull values → `.env`) / `insta --agent run` | secret **values** never flow out of MCP — names only, values in |
| `insta --agent postgres url` / `insta --agent postgres connect` (postgres DSN) | same rule — the DSN is a value read, so it only exists on the CLI |
| `insta --agent deploy <dir>` (source builds) | needs a local build context; `insta_deploy` takes prebuilt image URLs only |
| `insta --agent agent observe` hook / `insta --agent agent setup` | local-machine operations |
| `insta --agent postgres limits` (database machine spec) | not yet exposed as an MCP tool |

## Connecting

`insta --agent agent setup` registers the server with Claude Code automatically (user scope). The default
is **OAuth — no credential is written**: registration is just

```bash
claude mcp add --transport http --scope user insta-cloud https://mcp.instacloud.com/mcp
```

and on first `/mcp` use Claude discovers the platform's authorization server (RFC 9728 → Better
Auth MCP plugin, dynamic client registration) and runs the browser flow — managed, expiring,
revocable tokens, nothing static on disk.

Setup also writes an OAuth (URL-only) entry into the config of **every other detected
MCP-capable agent** — Cursor, OpenAI Codex, OpenCode, GitHub Copilot, Factory Droid — and
`insta --agent config install-mcp --agent <slug>` targets one explicitly. Merges never clobber existing config
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

`insta --agent agent setup --env staging` (or `curl -fsSL agents.staging.instacloud.com | sh`) switches
the environment and registers staging's server in one step (CLI ≥ 0.0.38 — bare `agent setup`
always targets prod, so a bare re-run after `env use staging` would switch the machine back).
`INSTA_MCP_URL` still overrides outright, for a self-hosted or tunnelled server.

New/renamed tools need a **fresh agent session** to appear — reconnecting an existing session
won't pick them up.

## Tool ↔ CLI mapping

Naming is `insta_<verb>_<noun>`; every tool takes **explicit `projectId` / `branch` args** — the
server is stateless, there is no "current project" like `./.insta/project.json`. Get the
`projectId` from `insta_list_projects` (or `.insta/project.json` if you're in a linked repo).

| CLI | MCP tool |
|---|---|
| `insta --agent status` (am I connected?) | `insta_whoami` |
| `insta --agent org list` / `create` | `insta_list_orgs` / `insta_create_org` |
| `insta --agent project list/create/delete` | `insta_list_projects` / `insta_create_project` / `insta_get_project` / `insta_delete_project` |
| region discovery | `insta_list_regions` |
| `insta --agent service add/list/remove/rename` [`--branch`] | `insta_add_service` / `insta_list_services` / `insta_remove_service` / `insta_rename_service` (all take `branch?`; add takes `public?` for storage) |
| `insta --agent storage set-access` | `insta_set_service_access` |
| `insta --agent compute scale` | `insta_scale_service` |
| `insta --agent compute start\|stop\|suspend\|restart` / `status` | `insta_set_compute_state` / `insta_get_service_status` — `restart` needs a deployed insta-mcp carrying it; older servers reject the verb at schema validation |
| `insta --agent compute exec [service] -- <command>` | `insta_exec_compute_command` (`name?`/`branch?`/`command`/`timeoutSec?`) |
| `insta --agent compute limits/always-on/volume` (same shape under `redis\|mysql\|mongodb`) | `insta_get_service` (read: limits, always-on state, start command, volume) / `insta_update_service` (write: `alwaysOn`, `startCommand`, `memoryMb`, `cpu`, `volumeGib`, `volumeMountPath`, one restart. `alwaysOn`/`startCommand` gated `deploy`, the rest gated `service.upgrade`) / `insta_delete_service_volume` (compute only, destructive, deletes the disk and its data) |
| `insta --agent compute start-command` | `insta_update_service` (`startCommand` field, gated `deploy`) |
| `insta --agent domain attach/check/detach` | `insta_attach_domain` / `insta_check_domain` / `insta_detach_domain` |
| `insta --agent branch create/list/merge/delete` | `insta_create_branch` / `insta_list_branches` / `insta_merge_branch` / `insta_delete_branch` |
| `insta --agent agent manifest` | `insta_get_agent_manifest` (env view — **no secret values**) |
| `insta --agent secrets list/set/unset` | `insta_list_secrets` (names only) / `insta_set_secret` / `insta_unset_secret` |
| `insta --agent secrets sources/bindings/bind/unbind` | `insta_list_secret_sources` / `insta_list_secret_bindings` / `insta_bind_secret` / `insta_unbind_secret` (provider credential binding; names only, no secret values) |
| `insta --agent deploy --image <url>` | `insta_deploy` (image-only) |
| `insta --agent <compute\|postgres\|redis\|mysql\|mongodb> metrics/logs` (`--deploy` for deploy events — compute/redis/mysql/mongodb only; postgres has no deploy events) · `insta --agent agent events` | `insta_get_service_metrics` / `insta_get_service_logs` / `insta_list_deploy_events` / `insta_list_agent_events` (metrics and logs take `type`, not `component`. postgres passes `type: postgres`) |
| `insta --agent <redis\|mysql\|mongodb> status` reads the same runtime-health data (filtered to one service); db provider operations have no CLI equivalent | `insta_list_service_statuses` / `insta_list_postgres_operations` (database provider operations, not a general operations feed; for watching a postgres branch or restore settle) |
| `insta --agent postgres stats` (`metrics` kind; `insight`/`activity`/`query-stats` are MCP-only) | `insta_get_postgres_stats` (read-only; `kind` = metrics, insight, activity, query-stats) |
| `insta --agent <redis\|mysql\|mongodb> query` | `insta_query_database` (`argv` for redis, `command` for mysql or mongodb, `database` selects the mongodb database. Not for postgres, use `insta_get_postgres_stats` or the SQL editor) |
| `insta --agent billing usage` / `billing` | `insta_get_billing_usage` / `insta_get_org_usage` (org-level, optional `from`/`to`) / `insta_get_billing_summary` / `insta_get_billing_overview` (org-level, current cycle only) |
| `insta --agent billing subscribe/portal` | `insta_create_billing_checkout` (`tier` = `pro` or `team`) / `insta_create_billing_portal` — return a Stripe **URL for the human**; relay it, never claim payment happened |
| `insta --agent agent policy get/set` | `insta_get_agent_policy` / `insta_set_agent_policy` (admin-only; restricted agents cannot change policy) |
| `insta --agent agent approvals list` | `insta_list_agent_approvals`. Approve and deny are CLI-only, run `insta agent approvals approve/deny <id>` from a human terminal |
| storage browse/download/delete | `insta_list_storage_objects` / `insta_get_storage_download_url` / `insta_delete_storage_object` (no upload yet) |
| `insta --agent template list/info/deploy` (`--region <r>` on `deploy` only) | `insta_search_templates` / `insta_get_template` / `insta_deploy_template` (`region` parameter, slugs from `insta_list_regions`) / `insta_get_template_deployment` |
| `insta --agent feedback` | `insta_send_feedback` (same fields; pass `projectId`/`branch` explicitly — see [cli-reference.md → Feedback](../cli-reference.md#feedback)) |
| `insta --agent feedback status <ticket-id>` | `insta_get_feedback_status` (`ticketId` from `insta_send_feedback`'s `ticket.id`; status only, the replies are in the console) |

## Behavior that carries over from the CLI

- **Governance is identical.** Gated tools return `approval_required` + an `approvalId` instead of
  an error — run the same approval relay you'd run for the CLI (tell the human, wait, retry).
  Never treat `approval_required` as failure.
- **Custom-domain results include DNS records** for the developer's own registrar — relay them
  verbatim, like the CLI's printed table.
- Paid-tier gates (`scale`, `upgrade`) and branch caps (≤10) are enforced by the platform and
  surface as structured errors, same as the CLI.
