# GreenNode AgentBase Skills

A bundle of [SKILL.md](https://www.mintlify.com/blog/skill-md)-compatible skills that drive the full **GreenNode AgentBase** lifecycle — scaffold → configure → code → test → deploy → monitor → teardown — from inside your AI coding tool.

Drop them into **Claude Code**, **Cursor**, **OpenAI Codex**, or any other SKILL.md-aware client and you get slash commands like `/agentbase-wizard`, `/agentbase-deploy`, `/agentbase-monitor`. The skills are plain Markdown + shell — no client-specific runtime — so the **full lifecycle works in every tool that can read SKILL.md and run a shell**.

---

## TL;DR — Install in 30 Seconds

```bash
git clone https://github.com/vngcloud/greennode-agentbase-skills.git

# Pick the install target for your tool (see table below)
#   Claude Code  → ~/.claude/skills        or  <project>/.claude/skills
#   Cursor       → ~/.cursor/skills        or  <project>/.cursor/skills
#   Codex        → ~/.agents/skills        or  <project>/.agents/skills

mkdir -p ~/.claude/skills
cp -r greennode-agentbase-skills/.claude/skills/* ~/.claude/skills/
```

Then restart your tool and type `/agentbase-wizard` (or just say *"build me a Telegram bot"*).

---

## Install Per Tool

All skills live under `.claude/skills/`. They are plain folders with a `SKILL.md` file inside — no build step. Each client auto-discovers them from a known directory.

### 1. Claude Code

The native home for these skills.

```bash
# Global (recommended — available in every project)
mkdir -p ~/.claude/skills
cp -r greennode-agentbase-skills/.claude/skills/* ~/.claude/skills/

# OR project-scoped
mkdir -p <your-project>/.claude/skills
cp -r greennode-agentbase-skills/.claude/skills/* <your-project>/.claude/skills/
```

Launch and use:

```bash
cd <your-project> && claude
> /agentbase-wizard          # slash command
> "deploy my agent"           # or just describe intent — Claude picks the skill
```

> **Tip:** `claude` will auto-load every `SKILL.md` it finds. To verify, run `/help` and look for the skills section.

### 2. Cursor

Cursor's skills support and exact path have evolved across releases — **check your version's docs** for the correct skills directory before installing. Typical layout:

```bash
mkdir -p ~/.cursor/skills
cp -r greennode-agentbase-skills/.claude/skills/* ~/.cursor/skills/
# or project-scoped: <your-project>/.cursor/skills/
```

Open Cursor → Agent chat → type `/` to search skills. Agent mode runs bash / curl, so deploy / monitor / teardown work end-to-end.

### 3. OpenAI Codex

```bash
export OPENAI_API_KEY="..."
cd <your-project> && codex
```

Codex CLI reads SKILL.md-style files; **the exact discovery path depends on your Codex version** (commonly `~/.agents/skills/` or `<project>/.agents/skills/` — check your version's docs). Once discovered, the CLI executes shell + HTTP calls, so the full lifecycle works.

### 4. Other SKILL.md-compatible Clients

Any client that (a) reads SKILL.md frontmatter (`name`, `description`) and (b) can run shell commands will work. Point the client at the `.claude/skills/` directory or copy folders into whatever skills path it expects.

### Compatibility Matrix

The skills are **tool-agnostic** — they're just Markdown procedures plus `bash` / `curl` calls to the GreenNode REST APIs. Every SKILL.md-aware client with shell access can run them end-to-end. Differences below are about **UX**, not capability.

| | Claude Code | Cursor | Codex | Other SKILL.md clients |
|---|:-:|:-:|:-:|:-:|
| Typical skills directory | `.claude/skills/` | `.cursor/skills/` | `.agents/skills/` | client-specific |
| Invocation | `/skill-name` | `/skill-name` (Agent) | natural language / CLI | varies |
| Auto-routing by description | ✅ native | ✅ | ✅ | depends on client |
| Runs shell / HTTP from skills | ✅ | ✅ (Agent mode) | ✅ | requires shell tool |
| Full deploy & monitor pipeline | ✅ | ✅ | ✅ | ✅ if shell available |

> The skills are authored and tuned primarily on Claude Code — that's where routing and prompts are validated. Functionally though, every tool with shell access can run them; Cursor / Codex / other clients just don't have a dedicated test pass yet.

---

## Prerequisites

Before any skill that hits the platform, set GreenNode IAM credentials:

```bash
export GREENNODE_CLIENT_ID="<service-account-client-id>"
export GREENNODE_CLIENT_SECRET="<service-account-secret>"
```

Put them in your shell profile or in a project-local `.env` (never commit it — `.env.example` is the tracked template).

Skills that only read local files (e.g. `agentbase-wizard init`) work without credentials.

---

## Skills Index

| Skill | What it does |
|---|---|
| `/agentbase-wizard` | **Start here.** Guided 9-step lifecycle: scaffold → configure → code → test → deploy → verify. Also handles `init`, `test`, `resume`. |
| `/agentbase` | Platform reference — architecture, services, IAM, "which skill should I use". |
| `/agentbase-identity` | Register agent identities; store API keys / OAuth2 credentials for external services (OpenAI, Google, Slack, …). |
| `/agentbase-llm` | Manage **platform** LLM access — API keys, model catalog, rate limits, OpenAI-compatible endpoint. |
| `/agentbase-memory` | Conversation history, semantic memory, long-term memory stores (LangChain/LangGraph integration). |
| `/agentbase-deploy` | Build & push Docker image, create/update Custom Agent runtimes (PUBLIC/VPC), deploy OpenClaw Telegram/Zalo bots, manage the Container Registry. |
| `/agentbase-monitor` | Runtime logs, endpoint logs, CPU/RAM metrics, unified resource dashboard. |
| `/agentbase-gateway` | Resource Gateway (MCP) CRUD; inbound auth (NONE / IAM / JWT); per-target outbound auth (APIKEY / OAUTH 2LO / 3LO); VPC routes; Policy Group binding. |
| `/agentbase-policy` | Authorization policies — Policy Groups, Policies, and `statement` bodies (effect / principal / actions / resources / condition). Enforced today on the Resource Gateway. |
| `/agentbase-teardown` | Delete **all** resources for a project. Always supports `--dry-run`. |

### Lifecycle Map

```
┌────────────────────────────────────────────────────────┐
│ GET STARTED                                            │
│   /agentbase-wizard ────── guided A → Z                │
│   /agentbase ───────────── platform reference          │
├────────────────────────────────────────────────────────┤
│ BUILD & CONFIGURE                                      │
│   /agentbase-wizard init ── scaffold project           │
│   /agentbase-llm ────────── platform LLM access        │
│   /agentbase-identity ───── identities & external auth │
│   /agentbase-memory ─────── memory stores              │
├────────────────────────────────────────────────────────┤
│ TEST & DEPLOY                                          │
│   /agentbase-wizard test ── validate / local / docker  │
│   /agentbase-deploy ─────── build, push, deploy        │
├────────────────────────────────────────────────────────┤
│ OPERATE                                                │
│   /agentbase-monitor ────── logs, metrics, dashboard   │
│   /agentbase-gateway ────── Resource Gateway (MCP)     │
│   /agentbase-policy ─────── access policies            │
├────────────────────────────────────────────────────────┤
│ ADVANCED                                               │
│   /agentbase-deploy cr ──── Container Registry         │
│   /agentbase-teardown ───── delete everything          │
└────────────────────────────────────────────────────────┘
```

### Common Subcommands

```text
/agentbase-wizard   [init <name> [--langchain|--langgraph] | test [validate|local|docker|preflight] | resume | step-N | reset]
/agentbase-identity identity <create|list|get|update|delete>          [name]
                    auth     <apikey|delegated|oauth2> <create|list|get|update|delete|retrieve> [name]
/agentbase-llm      <api-keys|models> <create|list|get|update|delete|enable|disable|rate-limit> [name-or-uuid]
/agentbase-memory   memory  <create|list|get|delete> [id]
                    events  <list|create|delete>
                    records <browse|search|generate-from-session|generate-from-content|insert|delete>
/agentbase-deploy   Custom Agent: build → push → deploy, runtime CRUD, scale, versions
                    OpenClaw:     create|list|start|stop|switch-version (Telegram/Zalo templates)
                    Container Registry: repo info, credentials, images, artifacts
/agentbase-monitor  <runtime-logs|endpoint-logs|metrics|dashboard> [runtime-id] [endpoint-id]
/agentbase-gateway  <create|list|get|update|delete|routes|repair|flavors> [gateway-name]
/agentbase-policy   <group|policy> <create|list|get|update|delete> [group-id-or-name] [policy-id-or-name]
/agentbase-teardown <project-name> [--dry-run]
```

> These skills are driven by natural language — the syntax above is a quick reference, not a strict CLI. Tell the model what you want and it picks the right operation.

---

## End-to-End Example — Build a Chatbot

```bash
/agentbase-wizard init my-chatbot --langgraph   # scaffold
/agentbase-llm api-keys create my-chatbot-key   # platform LLM key
/agentbase-memory create                         # optional memory store
/agentbase-wizard test local                     # smoke test locally
/agentbase-deploy deploy                         # build → push → deploy
/agentbase-monitor runtime-logs <runtime-id>     # watch it run
```

Or, first time, just:

```text
/agentbase-wizard
```

…and follow the prompts.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Skill doesn't appear | Confirm the file is at `<skills-dir>/<skill-name>/SKILL.md` with valid `name` + `description` frontmatter, then restart the tool. |
| `401 Unauthorized` | `GREENNODE_CLIENT_ID` / `GREENNODE_CLIENT_SECRET` missing, expired, or service account lacks IAM policies. |
| `OOMKilled` during deploy | Pick a larger flavor — ask `/agentbase-deploy` to list eligible flavors and resize the runtime. |
| Want to resume a half-finished session | State persists in `.agentbase-state.json` — run `/agentbase-wizard resume`. |
| Different skill behavior across tools | Tightest validator wins (typically Claude Desktop). Re-read the SKILL.md frontmatter; description length / characters may need trimming. |

---

## Repo Layout

```
greennode-agentbase-skills/
├── .claude/skills/             # <-- the skills you install
│   ├── agentbase/              # platform reference
│   ├── agentbase-wizard/       # guided full-lifecycle wizard
│   ├── agentbase-deploy/       # build, push, deploy + Container Registry + OpenClaw
│   ├── agentbase-identity/     # agent identities & outbound auth
│   ├── agentbase-llm/          # platform LLM API keys & models
│   ├── agentbase-memory/       # conversation + semantic memory
│   ├── agentbase-monitor/      # logs, metrics, dashboard
│   ├── agentbase-gateway/      # Resource Gateway (MCP)
│   ├── agentbase-policy/       # authorization policies
│   └── agentbase-teardown/     # delete all resources
└── README.md
```

Each skill folder contains a `SKILL.md` (the contract read by the AI tool) and any helper `scripts/` or `references/` it needs.

---

## Contributing & Extending

- Each skill is just a folder with a `SKILL.md` file — copy an existing one as a template.
- Frontmatter (`name`, `description`) is a public contract — renaming breaks downstream tools. Update `README.md` cross-references when you rename.
- Skill descriptions must satisfy the **tightest** client validator (typically Claude Desktop's character limit). Verify before committing.
- Test the skill end-to-end in Claude Code (or your target client) before opening a PR — descriptions drive auto-routing, so a small wording change can shift which skill is picked.

---

## Important Notes

1. **Verify IAM credentials first** — the majority of platform errors are missing `GREENNODE_CLIENT_ID` / `GREENNODE_CLIENT_SECRET` or insufficient policies.
2. **Validate before deploy** — `/agentbase-wizard test validate`.
3. **Always `--dry-run` teardown** before the real delete.
4. **Never commit `.env`** — only `.env.example` is tracked.
5. **First time? Use `/agentbase-wizard`** — it covers the full 9-step path.
