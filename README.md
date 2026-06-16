# Hierarchical Multi-Agent Network NOC — AI Agents + MCP Gateway

An autonomous, hierarchical Multi-Agent Network Operations Center (NOC) system powered by LangChain, deployed on **GreenNode AgentBase**, with a local **MCP (Model Context Protocol) server** providing real-time access to Juniper datacenter devices via NETCONF.

The system transitions from a single agent design to a team of 4 specialized AI agents orchestrated by a NOC Supervisor Agent.

---

## Architecture Overview

```
                 ┌────────────────────────────────────────────────────────┐
                 │                Telegram Bot / Prometheus Alerts        │
                 └───────────────────────────┬────────────────────────────┘
                                             │ User / Webhook Event
                                             ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                              GreenNode Cloud Platform                                  │
 │                                                                                        │
 │      ┌──────────────────────────────────────────────────────────────────────────┐      │
 │      │                 NOC Supervisor Agent (Entrypoint)                        │      │
 │      │                 [supervisor-network-engineer-agent]                      │      │
 │      │                 - Decides next action (intent routing)                   │      │
 │      │                 - Maintains loop limit & manages global state            │      │
 │      └───────────┬────────────────────────┬────────────────────────┬────────────┘      │
 │                  │                        │                        │                   │
 │                  ▼                        ▼                        ▼                   │
 │       ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐       │
 │       │   Triage/Analytics   │ │    Expert Engineer   │ │  Customer Advisory   │       │
 │       │       Agent          │ │        Agent           │ │        Agent           │       │
 │       │ [analytics-network-  │ │  [expert-engineer-   │ │ [customer-advisory-  │       │
 │       │   engineer-agent]    │ │       agent]         │ │       agent]         │       │
 │       │  - Filters alerts    │ │ - Runs diagnostics   │ │ - Prepares RCA/SOP   │       │
 │       │  - Incident triage   │ │ - Executes changes   │ │ - L3 notifications   │       │
 │       │  - Creates Jira task │ │ - NETCONF CLI tools  │ │ - Closes Jira task   │       │
 │       └──────────┬───────────┘ └──────────┬───────────┘ └──────────┬───────────┘       │
 └──────────────────┼────────────────────────┼────────────────────────┼───────────────────┘
                    │                        │                        │
                    ├────────────────────────┴────────────────────────┤ SSE / HTTP
                    ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                              On-Premises Infrastructure                                │
 │                                                                                        │
 │     ┌──────────────────────────────────────────────────────────────────────────┐       │
 │     │                        On-Premises MCP Server                            │       │
 │     │                        - FastMCP Server + NETCONF CLI Wrapper            │       │
 │     │                        - Loads: shared/devices.json & shared/db/*.db     │       │
 │     └─────────────────────────────────────┬────────────────────────────────────┘       │
 │                                           │ NETCONF (SSH 830/22)                       │
 │                                           ▼                                            │
 │     ┌──────────────────────────────────────────────────────────────────────────┐       │
 │     │                      Lab Network Devices (QFX, EX, SRX)                  │       │
 │     └──────────────────────────────────────────────────────────────────────────┘       │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

### Agent Roles & Hierarchy

1.  **NOC Supervisor Agent** (`supervisor-network-engineer-agent`):
    *   **Role**: Router / Orchestrator.
    *   **Responsibility**: Receives incoming user commands (via Telegram) or Prometheus Alertmanager webhooks. Uses a router LLM to analyze the incident state and delegate the task to the correct worker agent, or replies directly for general design/audit queries. It enforces a safety loop limit of 5 turns before auto-escalating to Level 3.
2.  **Triage/Analytics Agent** (`analytics-network-engineer-agent`):
    *   **Role**: Incident Triager.
    *   **Responsibility**: Validates alerts, reviews hardware/software states, checks for link flapping, and creates the mandatory Jira ticket on the KAN board.
3.  **Expert Engineer Agent** (`expert-engineer-agent`):
    *   **Role**: Deep Diagnostician & Executor.
    *   **Responsibility**: Connects to datacenter switches/routers using NETCONF MCP tools, runs complex troubleshooting workflows, designs configuration changes, and updates Jira with detailed technical notes.
4.  **Customer Advisory Agent** (`customer-advisory-agent`):
    *   **Role**: L3 Engineer / Customer Communicator.
    *   **Responsibility**: Reviews the resolved incident logs, drafts customer-facing reports (Root Cause Analysis - RCA), prepares self-help guidelines (SOPs), sends out notifications via Telegram, and transitions the Jira ticket to **DONE**.

### State & Orchestration Flow

*   **Redis State Cache**: The global state of the conversation and incident metadata is cached in a centralized Redis database.
*   **Routing Directory**: Worker URL endpoints are dynamically registered in Redis under `agent:url:<agent_name>` upon deployment.
*   **Asynchronous Hand-off**: The supervisor agent invokes worker agents using asynchronous HTTP POST requests, which callback to the supervisor once their subtasks are completed.

---

## Project Structure

```
claw-a-thon-thinhlv-agent/
├── README.md                              # This file
├── docker-compose.yml                     # Runs MCP server & monitoring locally
├── deploy_all.sh                          # Automatically builds, pushes, and deploys all 4 agents to GreenNode
│
├── shared/                                # Shared modules and configurations
│   ├── devices.json                       # Single source of truth for datacenter device inventory
│   ├── scan_results.json                  # Output of live scanned device parameters
│   ├── approve_ticket.py                  # CLI utility to simulate webhook approvals from Jira
│   └── db/
│       ├── init_network_assets.py         # Initializes the network assets database
│       └── network_assets.db              # Network Assets SQLite DB (gitignored)
│
├── supervisor-network-engineer-agent/      # 👑 Entrypoint & NOC Coordinator Agent
│   ├── main.py                            # Runs web service, Telegram bot, and routing loops
│   ├── system_prompt.py                   # Intent routing guidelines
│   ├── telegram_bot.py                    # Telegram long-polling integration
│   ├── markdown_converter.py              # MD to Telegram HTML converter
│   └── Dockerfile
│
├── analytics-network-engineer-agent/      # 🔍 Alert Triager & Jira Ticket Creator
│   ├── main.py                            # Agent loop
│   ├── system_prompt.py                   # Triage prompt
│   ├── agent_tools.py                     # Custom tools for alert analysis
│   └── Dockerfile
│
├── expert-engineer-agent/                 # ⚙️ Deep Diagnostic & Config Executor
│   ├── main.py                            # Agent loop
│   ├── system_prompt.py                   # Expert troubleshooting guidelines
│   ├── agent_tools.py                     # Wrapper for Netmiko/NETCONF tools
│   └── Dockerfile
│
├── customer-advisory-agent/               # 📝 L3 Customer Advisory & RCA Creator
│   ├── main.py                            # Agent loop
│   ├── system_prompt.py                   # RCA reporting & closing guidelines
│   ├── agent_tools.py                     # Customer communication & notify tools
│   └── Dockerfile
│
├── mcp-server/                            # 🔌 On-Premises MCP Gateway
│   ├── mcp_server.py                      # FastMCP server exposing NETCONF commands
│   ├── requirements.txt                   # MCP server dependencies
│   └── Dockerfile
│
└── greennode-agentbase-skills/            # 🛠️ Platform Deployment Skills
```

---

## Quick Start

### 1. Start MCP Server (on-premises machine)

```bash
# Configure credentials
cp mcp-server/.env.example mcp-server/.env
# Edit mcp-server/.env — set NETCONF_PASSWORD and devices paths

# Run using Docker Compose
docker compose up -d mcp-server

# Verify health
curl http://localhost:8980/sse
```

### 2. Deploy the Hierarchical Agent NOC

We provide a deployment script to build, push, deploy, and register all 4 agents in one command:

```bash
# 1. Ensure GreenNode credentials are in .greennode.json at the root of the project
# 2. Configure .env file for each agent (or copy from examples)
# 3. Deploy all 4 agents to GreenNode Cloud Platform:
./deploy_all.sh
```

The `deploy_all.sh` script will:
*   Build Docker images for `supervisor-network-engineer-agent`, `analytics-network-engineer-agent`, `expert-engineer-agent`, and `customer-advisory-agent`.
*   Push images to your VNG Cloud Container Registry.
*   Deploy them as GreenNode AgentBase runtimes.
*   Query the dynamic endpoint URLs and register them in Redis.

---

## MCP Tools (Auto-discovered)

Worker agents auto-discover tools from the MCP server at startup. Currently available tools:

| Tool | Description |
|------|-------------|
| `get_devices_list` | List all registered datacenter devices |
| `reload_devices` | Reload device inventory from configuration file |
| `get_device_detail` | Device spec, uptime, role and properties |
| `get_device_configuration_list` | Configuration commit history list |
| `get_device_configuration_detail` | Active/filtered configuration detail |
| `view_network_status` | Run live operational read-only CLI commands on devices |
| `get_device_operation_list` | Suggested operational commands for a device |
| `lookup_command_dictionary` | Look up exact CLI command syntax, templates and risk levels |
| `propose_network_change` | Propose device configuration change via Jira ticket |
| `query_knowledge_base` | Search internal RAG database (Juniper articles and reference books) |
| `get_device_hardware` | Chassis hardware inventory |
| `get_network_topology` | Live LLDP topology discovery |
| `ping_from_device` | Ping destination host directly from a network device |
| `compare_device_configs` | Compare active config vs rollback index |
| `check_device_alarms` | System & chassis active alarms |
| `get_interface_diagnostics` | Optics transceiver Rx/Tx power & temperature diagnostics |
| `git_operation` | Run Git commands (clone, status, commit, push, pull, log, diff, etc.) |
| `get_device_status` | Query SNMP status (UP/DOWN) from Prometheus |
| `get_interface_traffic` | Get interface traffic throughput from Prometheus |
| `get_device_logs` | Query device syslogs from Loki |

---

## Jira Integration & Task Lifecycle

The agents are integrated with the team's Jira Kanban board (Project **KAN**). They automatically track, log, and update operational tasks.

### Jira Tools
The workers use standard tools to interact with Jira REST API v3:
- `create_jira_task(summary, description)`: Creates a new Task on the KAN board and returns the Issue Key (e.g., `KAN-15`).
- `update_task_status(issue_key, target_status)`: Transition task state to: `IN_PROGRESS`, `WAITING`, `ERROR`, or `DONE`.
- `add_task_comment(issue_key, comment_body)`: Appends updates, CLI logs, diffs, or troubleshooting reports to the ticket.

### Workflow Protocol

```
[Start Alert] 
      │
      ▼
[Supervisor] ──► [Analytics Agent] ──► (Create Jira Task KAN-XX) ──► (Status: TODO)
                                                                            │
                                                                            ▼
[Supervisor] ◄─────────────────────────────────────────────────────── [IN_PROGRESS]
      │
      ▼
[Expert Agent] ──► (Run Diagnostics/Fixes via MCP)
      │
      ├─► (Configuration Change Needed) ──► (Show Config Diff) ──► [WAITING FOR APPROVAL]
      │                                                                     │
      │                                                                     ▼
      │                                                           (User Approves / Webhook)
      │                                                                     │
      ├─────────────────────────────────────────────────────────────────────┘
      │
      ▼
[Supervisor] ──► [Customer Advisory Agent] ──► (Post RCA/SOP Report) ──► [DONE]
```

---

## Security Notes

*   **Secrets & Credentials**: Always keep your environment-specific passwords, Slack tokens, and Jira API Tokens in `.env` files. Ensure they are gitignored and never hardcoded in source files.
*   **Webhook Signing**: Simulate JIRA approvals locally using the HMAC SHA256 signatures helper script [approve_ticket.py](file:///home/thinhle/claw-a-thon-thinhlv-agent/shared/approve_ticket.py).
