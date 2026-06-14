# Network Engineer — AI Agent + MCP Gateway

An autonomous AI network engineer agent powered by LangChain/LangGraph, deployed on **GreenNode AgentBase** platform, with a local **MCP (Model Context Protocol) server** providing real-time access to Juniper datacenter devices via NETCONF.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           GreenNode Cloud Platform                              │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────┐                  │
│  │  Network Engineer Agent (dc-network-engineer-agent/)      │                  │
│  │  ┌──────────────────────────────────────────────────────┐ │                  │
│  │  │  main.py ── LangChain Agent + Memory + Planning      │ │                  │
│  │  │  ├── system_prompt.py   (Network Engineer)                  │ │                  │
│  │  │  ├── mcp_client.py      (Auto-discover MCP tools)   │ │                  │
│  │  │  ├── telegram_bot.py    (Telegram integration)       │ │                  │
│  │  │  └── markdown_converter.py (MD → Telegram HTML)      │ │                  │
│  │  └──────────────────────────────────────────────────────┘ │                  │
│  │  Public IP: IP Public Range (floating, not fixed)         │                  │
│  └──────────────────────┬────────────────────────────────────┘                  │
│                         │ MCP over SSE (HTTP)                                   │
└─────────────────────────┼───────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Firewall Device (firewall-gateway)                                           │
│  Static NAT: IP Public (public) ──► IP LAN (LAN)                              │
└─────────────────────────┬───────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        On-Premises MCP Server                                   │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────┐                  │
│  │  MCP Server (mcp-server/) — Docker container              │                  │
│  │  ├── mcp_server.py   (FastMCP + Juniper NETCONF tools)   │                  │
│  │  ├── Port: 8000/SSE                                       │                  │
│  │  └── Loads: shared/devices.json                           │                  │
│  └──────────────────────┬────────────────────────────────────┘                  │
│  IP LAN: IP LAN │ IP Lab                                                             │
│                          │ NETCONF (SSH/830)                                    │
│                          ▼                                                      │
│  ┌───────────────────────────────────────────────────────────┐                  │
│  │  Lab Network Devices (IP LAN range)                       │                  │
│  │  ├── network-gateway-01     (QFX10008, DC Gateway)       │                  │
│  │  ├── vnpt-access-switch-01  (EX4400, VNPT Access)        │                  │
│  │  ├── tor-access-switch-01   (EX4400, ToR Switch)          │                  │
│  │  ├── core-leaf-01           (Core Leaf 01)               │                  │
│  │  ├── core-leaf-02           (Core Leaf 02)               │                  │
│  │  ├── core-spine-01          (Core Spine 01)              │                  │
│  │  └── firewall-gateway-01    (Firewall Gateway)           │                  │
│  └───────────────────────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Network Flow

```
Agent (GreenNode Cloud, IP Public Range)
  │
  │  HTTP/SSE ──► IP Public:8000
  │
  ▼
Firewall Device
  │  Static NAT: IP Public ──► IP LAN
  │
  ▼
MCP Server (IP LAN / IP Lab)
  │
  │  NETCONF (SSH port 830 or 22)
  │
  ▼
Lab Network Devices (IP LAN range)
```

> **Note:** Agent public IP is from the range `IP Public Range` but uses a floating IP, so the exact IP is not fixed. Firewall rules on the firewall device should allow this range.

---

## Project Structure

```
claw-a-thon-thinhlv-agent/
├── README.md                          # This file
├── docker-compose.yml                 # Run MCP server (agent deploys to GreenNode)
│
├── shared/                            # Shared configuration
│   └── devices.json                   # Device inventory (single source of truth)
│
├── dc-network-engineer-agent/         # 🤖 Agent — deploys to GreenNode
│   ├── main.py                        # Entry point: agent + HTTP server
│   ├── system_prompt.py               # Network Engineer system prompt
│   ├── mcp_client.py                  # Auto-discover MCP tools from server
│   ├── telegram_bot.py                # Telegram bot integration
│   ├── markdown_converter.py          # Markdown → Telegram HTML converter
│   ├── .env.example                   # Environment variables template
│   ├── Dockerfile                     # Container build
│   ├── requirements.txt               # Python dependencies
│   └── .greennode.json                # GreenNode deployment credentials
│
├── mcp-server/                        # 🔌 MCP Server — runs on-prem (Docker)
│   ├── mcp_server.py                  # FastMCP + Juniper NETCONF tools
│   ├── .env.example                   # Environment variables template
│   ├── Dockerfile                     # Container build
│   └── requirements.txt               # Python dependencies
│
├── dc-network-engineer-skills/        # 📚 SKILL.md knowledge base
│   └── .claude/skills/                # Network engineering domain skills
│       ├── dc-overview/               # Platform reference & skill router
│       ├── dc-infrastructure/         # DC physical infrastructure (power, cooling, racks)
│       ├── dc-cabling/                # Fiber, copper, transceivers, patch panels
│       ├── dc-tcpip/                  # TCP/IP deep dive & packet analysis
│       ├── dc-routing/                # BGP, ISP peering, DDoS protection
│       ├── dc-juniper-basics/         # JunOS CLI, routing, policies
│       ├── dc-juniper-evpn/           # EVPN-VXLAN & IP Fabric design
│       ├── dc-juniper-firewall/       # SRX, NAT, IPSec, clustering
│       ├── dc-juniper-mclag/          # MC-LAG protocols & HA
│       ├── dc-operations/             # Daily SOPs & change management
│       ├── dc-troubleshoot/           # Incident response & monitoring
│       └── dc-planning/               # Network design & audit
│
└── greennode-agentbase-skills/        # 🛠️ GreenNode Platform skills
    └── .claude/skills/                # AgentBase lifecycle management
        ├── agentbase-wizard/          # Guided scaffold → deploy wizard
        ├── agentbase-deploy/          # Build, push, deploy
        ├── agentbase-identity/        # Agent identities & auth
        ├── agentbase-llm/             # Platform LLM access
        ├── agentbase-memory/          # Conversation & semantic memory
        ├── agentbase-monitor/         # Logs, metrics, dashboard
        ├── agentbase-gateway/         # Resource Gateway (MCP)
        ├── agentbase-policy/          # Authorization policies
        └── agentbase-teardown/        # Delete all resources
```

---

## Quick Start

### 1. Start MCP Server (on-prem machine)

```bash
# Configure credentials
cp mcp-server/.env.example mcp-server/.env
# Edit mcp-server/.env — set NETCONF_PASSWORD

# Run with Docker Compose
docker compose up -d mcp-server

# Verify
curl http://localhost:8000/sse
```

### 2. Deploy Agent to GreenNode

```bash
cd dc-network-engineer-agent

# Configure environment
cp .env.example .env
# Edit .env — set LLM keys, MEMORY_ID, MCP_SERVER_URL, TELEGRAM_BOT_TOKEN

# Deploy using GreenNode AgentBase skills
# (from Claude Code or any SKILL.md-compatible tool)
/agentbase-wizard
```

### 3. Test Locally (optional)

```bash
# Uncomment agent section in docker-compose.yml, then:
docker compose up --build
```

---

## Skills Reference

### Network Engineer Skills (`dc-network-engineer-skills/`)

Domain knowledge that turns the AI agent into a **Network Engineer**. Covers: physical DC infrastructure, cabling, TCP/IP, internet routing, Juniper expertise (EVPN-VXLAN, SRX, MC-LAG), and operational workflows. See [dc-network-engineer-skills/README.md](dc-network-engineer-skills/README.md) for details.

### GreenNode AgentBase Skills (`greennode-agentbase-skills/`)

Platform lifecycle management skills for **GreenNode AgentBase** — scaffold, configure, code, test, deploy, monitor, and teardown agents. See [greennode-agentbase-skills/README.md](greennode-agentbase-skills/README.md) for the full skills index.

---

## MCP Tools (Auto-discovered)

The agent auto-discovers tools from the MCP server at startup. Currently available:

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

The agent is integrated with the team's Jira Kanban board (Project **KAN**). It automatically tracks, logs, and updates operational tasks to maintain transparency and SLA compliance.

### Jira Tools
The agent uses the following custom tools to interact with Jira REST API v3:
- `create_jira_task(summary, description)`: Creates a new Task on the KAN board and returns the Issue Key (e.g., `KAN-15`).
- `update_task_status(issue_key, target_status)`: Transition task state to: `IN_PROGRESS`, `WAITING`, `ERROR`, or `DONE`.
- `add_task_comment(issue_key, comment_body)`: Appends updates, CLI logs, diffs, or troubleshooting reports to the ticket.

### Workflow Protocol
Each request received by the agent is classified into two categories:

1. **Category A: Direct Response (No Ticket)**
   - Knowledge queries / explanations (e.g., "What is BGP community?", explaining EVPN).
   - Simple read-only operations (e.g., `show interfaces`, checking BGP neighbor status).
   - Casual conversation or confirmation.
   
2. **Category B: Mandatory Jira Ticket**
   - **Configuration Changes**: Adding/modifying/deleting VLANs, interfaces, firewalls, routing policy, BGP peers.
   - **Incident Resolution**: Interface down, BGP flapping, packet loss, high latency.
   - **Customer Requests**: Circuit provisioning, IP assignment, port opening, bandwidth changes.
   - **Maintenance & Planning**: Upgrades, backups, capacity analysis, config audits.

### Lifecycle Transition States
```
[Start] -> create_jira_task -> [KAN-XX (Status: TODO)]
                                      │
                                      ▼
                             update_task_status
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
      [IN_PROGRESS] ──► (Run Ops/CLI/Config) ──► (Create Diff / Review Needed)
              │                                               │
              │                                               ▼
              │                                      update_task_status
              │                                               │
              │                                               ▼
              │                                           [WAITING]
              │                                               │
              │                                               ▼
              │                                        (User Approves)
              │                                               │
              ├───────────────────────────────────────────────┘
              ▼
      add_task_comment (Post outputs/reports)
              │
              ├────────────────────────┬──────────────────────┐
              ▼                        ▼                      ▼
      update_task_status       update_task_status      (More steps)
              │                        │                      │
              ▼                        ▼                      ▼
           [DONE]                   [ERROR]             [IN_PROGRESS]
```

- **IN_PROGRESS**: Transitioned immediately before starting work.
- **WAITING**: Transitioned when waiting for user approval (e.g., showing a config diff before committing changes).
- **ERROR**: Transitioned if tools fail or unexpected errors occur, appending error details.
- **DONE**: Transitioned upon successful completion, appending a final summary report.

---

## Security Notes

- **Never commit `.env` files** — they contain secrets (API keys, passwords, tokens)
- NETCONF credentials are stored in `mcp-server/.env`, not in source code
- Agent credentials (LLM keys, Telegram token) are in `dc-network-engineer-agent/.env`
- GreenNode deployment credentials are in `.greennode.json` (gitignored)
- The firewall device should whitelist the GreenNode agent IP range (`IP Public Range`)
