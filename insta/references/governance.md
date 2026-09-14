# Governance & audit

`agent-policy` is the sole governance policy. Human requests use normal RBAC; old policy rules
are archived and no longer enforced. Use `insta --agent` for managed project operations. Platform verifies the logged-in user plus the
local agent session, then applies project agent policy. MCP calls carry server-signed assertions
and use the same policy. Missing or invalid agent evidence fails closed; run `insta --agent setup agent`
to refresh the linked directory's session, never retry as human.

## The gates

All projects start with explicit `full_access` (all classified project operations allowed within
user RBAC). `read_only` denies mutations and allows sensitive reads. In `branch_developer`, all
classified protected-branch writes are denied, including merge targets and indirect service writes.
Developers explicitly select protected branches; names like `main` are not automatically protected.
The unprotected-branch defaults are:

| Action | Default | Guards |
| --- | --- | --- |
| `project.delete` | **deny** | destroying every resource |
| `secrets.read` | allow | plaintext bundle reads — user secrets **and** each type's primary service credentials (`insta --agent secrets` / `insta --agent run`) — the postgres DSN (`insta --agent db url` / `insta --agent db connect`), and names-only binding/source views; also gates `compute exec`, paired with `deploy` |
| `secrets.write` | allow | user-secret changes and provider credential bind/unbind |
| `deploy` | allow | code reaching compute (and the build-token mint); also gates `compute restart` (which lands configuration through the same path) and `compute exec`, the latter paired with `secrets.read` |
| `branch.delete` | **approve** | tearing down an environment |
| `service.remove` | **approve** | deleting a service; also gates compute volume delete |
| `service.add`, `service.rename`, `branch.create` | allow | ordinary development |
| `service.scale`, `service.upgrade`, `service.setAccess`, `project.update` | **approve** | capacity, public access and project settings |
| `storage.read` | allow | listing a bucket, downloading, previewing |
| `storage.write` | allow | uploading an object |
| `storage.delete`, `db.restore`, explicitly classified `db.destructive` | **approve** | deletion/restoration |
| `domain.purchase` | **approve** | `insta domain buy` — it spends the org's money at a registrar, and a registration is non-refundable. Approval only unblocks the order: the human still has to pay the Stripe Checkout link it answers |
| `agent_policy.update`, `branch.protection.update`, project administration | **deny** | an agent cannot loosen its own restrictions |

Decisions: `allow` (proceed) · `deny` (hard no) · `approve` (human in the loop).

Compound requests (service PATCH, compute exec, template deploy) evaluate every action before any
side effect: `deny > approve > allow`. One agent approval binds the complete action set, actor,
resources, parameters and body hash. Consuming it authorizes that exact request once.

V1 does not parse SQL: the existing `db.query` console action is classified as a sensitive read,
including when its SQL writes data. Sensitive credential reads also permit direct database access.
Do not interpret `read_only` or protected branches as SQL-level isolation. Likewise, an agent with
user credentials and unrestricted shell can issue unmarked HTTP; this version governs the official
toolchains, not deliberate credential bypass.

```bash
insta --agent agent-policy get --json
# Human/admin configuration only — relay these commands; do not execute as an agent:
insta agent-policy set branch-developer
insta agent-policy protect-branch main
```

## The approval flow (relay procedure — CRITICAL)

A gated action returns **"approval required" + an approval id** (HTTP 202; the action did NOT run):

1. **Relay to the human immediately and verbatim**: the exact line, e.g.
   `insta approvals approve 7c3c9b68-…` in a human terminal. This approves one exact request;
   `--always` is no longer supported. Lasting changes require explicit `agent-policy` configuration.
   Don't summarize it away, don't retry in a loop, don't report failure without surfacing it.
2. Only a **human admin** can approve (`insta --agent approvals list --status pending --json`
   includes immutable request context). Agent CLI/MCP cannot approve their own requests.
3. Grants are **single-use**: after approval, **re-run the unchanged original command**, with the
   same session and source mode. Changing the resource or parameters requires a new approval.
4. `deny` policy = a hard no: report it and stop. Working around a gate (editing state, bypassing
   the CLI) is never acceptable — the gate is the product's safety model.

## The audit timeline

```bash
insta --agent events [--branch <b>] [--limit <n>] [--json]
```

One per-project timeline containing: resource side-effects (creates, deploys + URLs, deletes),
every govern decision (pending/approved/denied, policy changes), and ingested agent findings.
Use it to answer "what happened to this project and who allowed it" — e.g. after any incident,
before deleting anything, or when a human asks what an agent did.

## The observe hook (credential audit for YOUR tool calls)

Auto-installed on `project create`/`link` (PostToolUse hook for Claude Code / Codex):

- Scans each tool call for credential exposure — AWS / GitHub / Stripe / LLM / DB URLs / JWTs /
  private keys — and appends **redacted fingerprints** (never raw secrets) to `./.insta/audit.jsonl`.
- `insta --agent observe report [--json]` — review locally. `insta --agent observe sync` — upload findings into
  the project timeline (idempotent, deduped).
- Agent etiquette on top of the hook: treat `./.env` as the only credential source; never print
  secret values into chat, logs, code, or commits; if the report shows a leak finding, surface it
  to the human rather than burying it.

## Patterns for agents

- **Before destructive work** (`project delete`, `branch delete` of someone else's branch): check
  `insta --agent events` for recent activity and say what will be destroyed when relaying the approval.
- **Repeated gates:** explain the recurring action to the human; an admin may explicitly change an
  eligible agent-policy rule. Never loosen policy just to get your own request through.
- **After approval, verify:** the grant being consumed shows up in `insta --agent events` — confirm the
  re-run actually happened before reporting the task complete.
