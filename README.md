# DC Network Engineer — AI Agent + MCP Gateway

An autonomous AI network engineer agent powered by LangChain/LangGraph, deployed on **GreenNode AgentBase** platform, with a local **MCP (Model Context Protocol) server** providing real-time access to Juniper datacenter devices via NETCONF.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           GreenNode Cloud Platform                              │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────┐                  │
│  │  DC Network Engineer Agent (dc-network-engineer-agent/)   │                  │
│  │  ┌──────────────────────────────────────────────────────┐ │                  │
│  │  │  main.py ── LangChain Agent + Memory + Planning      │ │                  │
│  │  │  ├── system_prompt.py   (Senior Network Engineer)    │ │                  │
│  │  │  ├── mcp_client.py      (Auto-discover MCP tools)   │ │                  │
│  │  │  ├── telegram_bot.py    (Telegram integration)       │ │                  │
│  │  │  └── markdown_converter.py (MD → Telegram HTML)      │ │                  │
│  │  └──────────────────────────────────────────────────────┘ │                  │
│  │  Public IP: 61.28.236.0/24 (floating, not fixed)          │                  │
│  └──────────────────────┬────────────────────────────────────┘                  │
│                         │ MCP over SSE (HTTP)                                   │
└─────────────────────────┼───────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  SRX1500 Firewall (LAB_2BW11.18_SRX1500.STF.GW-N0)                            │
│  Static NAT: 49.213.77.221 (public) ──► 192.168.100.181 (LAN)                 │
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
│  IP LAN: 192.168.100.181 │ 10.116.0.181                                        │
│                          │ NETCONF (SSH/830)                                    │
│                          ▼                                                      │
│  ┌───────────────────────────────────────────────────────────┐                  │
│  │  Lab Network Devices (10.116.0.0/22)                      │                  │
│  │  ├── LAB-QFX10K8-GW-01      (QFX10008, DC Gateway)       │                  │
│  │  ├── LAB-EX4400-01-VNPT     (EX4400, VNPT Access)        │                  │
│  │  ├── LAB-EX4400-TOR         (EX4400, ToR Switch)          │                  │
│  │  ├── QFX5120-32C_STL.GW.01  (Core Leaf 01)               │                  │
│  │  ├── QFX5120-32C_STL.GW.02  (Core Leaf 02)               │                  │
│  │  ├── QFX5120-48Y_STL.GW.01  (Core Spine 01)              │                  │
│  │  └── SRX1500.STF.GW-N0      (Firewall Gateway)           │                  │
│  └───────────────────────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Network Flow

```
Agent (GreenNode Cloud, 61.28.236.0/24)
  │
  │  HTTP/SSE ──► 49.213.77.221:8000
  │
  ▼
SRX1500 Firewall
  │  Static NAT: 49.213.77.221 ──► 192.168.100.181
  │
  ▼
MCP Server (192.168.100.181 / 10.116.0.181)
  │
  │  NETCONF (SSH port 830 or 22)
  │
  ▼
Lab Network Devices (10.116.0.0/22)
```

> **Note:** Agent public IP is from the range `61.28.236.0/24` but uses a floating IP, so the exact IP is not fixed. Firewall rules on SRX1500 should allow this range.

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
│   ├── system_prompt.py               # Senior Network Engineer system prompt
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

### DC Network Engineer Skills (`dc-network-engineer-skills/`)

Domain knowledge that turns the AI agent into a **Senior Network Engineer**. Covers: physical DC infrastructure, cabling, TCP/IP, internet routing, Juniper expertise (EVPN-VXLAN, SRX, MC-LAG), and operational workflows. See [dc-network-engineer-skills/README.md](dc-network-engineer-skills/README.md) for details.

### GreenNode AgentBase Skills (`greennode-agentbase-skills/`)

Platform lifecycle management skills for **GreenNode AgentBase** — scaffold, configure, code, test, deploy, monitor, and teardown agents. See [greennode-agentbase-skills/README.md](greennode-agentbase-skills/README.md) for the full skills index.

---

## MCP Tools (Auto-discovered)

The agent auto-discovers tools from the MCP server at startup. Currently available:

| Tool | Description |
|------|-------------|
| `get_devices_list` | List all registered datacenter devices |
| `get_device_detail` | Device operational state, uptime, specs |
| `get_device_hardware` | Chassis hardware inventory |
| `get_network_topology` | Live LLDP topology discovery |
| `get_device_configuration_list` | Configuration commit history |
| `get_device_configuration_detail` | Active/filtered configuration |
| `get_device_operation_list` | Suggested operational commands |
| `get_device_operation_detail` | Live CLI command output |
| `edit_device_configuration` | Apply & commit config changes |
| `ping_from_device` | Ping from a device |
| `compare_device_configs` | Config diff vs rollback |
| `check_device_alarms` | System & chassis alarms |
| `get_interface_diagnostics` | Optics Rx/Tx power & temperature |

---

## Security Notes

- **Never commit `.env` files** — they contain secrets (API keys, passwords, tokens)
- NETCONF credentials are stored in `mcp-server/.env`, not in source code
- Agent credentials (LLM keys, Telegram token) are in `dc-network-engineer-agent/.env`
- GreenNode deployment credentials are in `.greennode.json` (gitignored)
- The SRX1500 firewall should whitelist the GreenNode agent IP range (`61.28.236.0/24`)
