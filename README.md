# InstaCloud Skills

[![License](https://img.shields.io/badge/License-Apache%202.0-orange.svg)](LICENSE)

The `insta` agent skill: what a coding agent needs to know to run cloud infrastructure
through [InstaCloud](https://github.com/InsForge/insta-cli) — provisioning services,
deploying apps, forking a whole environment per branch, wiring credentials into an app,
passing governance approvals, and giving several agents a sandbox each.

Skills are Markdown following the [Agent Skills](https://agentskills.io/) format, so they
work in Claude Code, Codex, Cursor, OpenCode, Copilot, Gemini CLI, Windsurf and anything
else that reads a `skills/` directory.

## Install

The `insta` CLI installs this skill for you:

```bash
insta --agent agent setup
```

That copies the skill user-globally for every coding agent on the machine and registers the
InstaCloud MCP server. `insta --agent project create` and `insta --agent project link` additionally install
the stack skills a project needs (Tigris, Better Auth) into the project
itself, along with the `insta --agent agent observe` credential-audit hook — see
[governance.md](insta/references/governance.md).

To install the skill on its own:

```bash
npx skills add InsForge/instacloud-skills -s insta
```

Or copy it into your agent's skills directory:

```bash
mkdir -p ~/.claude/skills && cp -r insta ~/.claude/skills/insta
```

## What's inside

```
insta/
├── SKILL.md              entry point: the model, setup, the two non-negotiables, governance
├── cli-reference.md      every command, with flags, approval gates and plan limits
└── references/
    ├── setup.md          CLI install, auth, a first project and its services
    ├── deploy.md         source and image deploys, ports, custom domains
    ├── frameworks.md     deploy recipes per framework
    ├── storage.md        S3-compatible buckets: credentials, reading and writing objects, the traps
    ├── branching.md      branch environments and the data that comes with them
    ├── governance.md     approvals, policy, the credential audit
    ├── operate.md        status, triage and recovery
    ├── migrate.md        moving an app in from Heroku/Railway/Fly/Render: the ordered cutover
    ├── migrate/          what each source adds to that cutover: render.md, railway.md, fly.md, insforge.md
    └── mcp.md            the remote insta-cloud MCP server
```

`SKILL.md` is what the agent loads first; it routes to a reference when a task needs the
detail. `cli-reference.md` is the canonical description of the CLI surface — the
[insta-cli](https://github.com/InsForge/insta-cli) repo links here for flags rather than
keeping a second copy, and a command or flag change there is not finished until it lands
here.

## Environments

InstaCloud runs two separate deployments, and each gets its own branch of this repository:

| Environment | Skill source |
|---|---|
| `prod` | `InsForge/instacloud-skills` (`main`) |
| `staging` | `InsForge/instacloud-skills#devel` |

`insta --agent agent setup` installs prod's skill text by default — bare `agent setup` always targets
prod (CLI ≥ 0.0.38), switching a staging-leftover machine back. `insta --agent agent setup --env staging`
is the explicit staging setup; it installs the `#devel` skill text that describes the staging
control plane.

Use the `#ref` form when pinning a branch by hand. `owner/repo@ref` looks equivalent, but
the skills tool parses `@` as a skill-name filter and silently leaves you on the default
branch — while still echoing the ref back in its progress output, so it reads as though it
worked.

## Authoring

- **Reference the `insta` CLI, not provider APIs.** Skills say which `insta` command to run.
  Provider-specific knowledge belongs behind the CLI and the control plane.
- **One skill, one capability.** Split large topics by task.
- **Include failure modes.** A skill earns its keep by teaching what goes wrong and how to
  recover.
- **Keep examples runnable.** Agents execute the code blocks.
- **Include `--agent` in every agent CLI invocation**, including npx examples. Bare human-admin
  approval/configuration commands are relay-only exceptions, never instructions for the agent to run.

A skill is a `SKILL.md` with YAML frontmatter:

```markdown
---
name: <skill-name>
description: <one line; the agent uses this to decide whether to load the skill>
---

# <title>

<instructions, examples, failure modes, the `insta` commands to run>
```

## License

Apache 2.0. See [LICENSE](LICENSE).
