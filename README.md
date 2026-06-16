# Hierarchical Multi-Agent Network NOC — AI Agents + MCP Gateway

An autonomous, hierarchical Multi-Agent Network Operations Center (NOC) system powered by LangChain, deployed on **GreenNode AgentBase**, with a local **MCP (Model Context Protocol) server** providing real-time access to Juniper datacenter devices via NETCONF.

The system transitions from a single agent design to a team of 4 specialized AI agents orchestrated by a NOC Supervisor Agent.

---

## Architecture Overview

```
                 ┌────────────────────────────────────────────────────────┐
                 │        Slack App (Socket Mode) / Prometheus Alerts     │
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
 │     │                      Lab Network Devices (MX, QFX, EX, SRX)              │       │
 │     └──────────────────────────────────────────────────────────────────────────┘       │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

### Agent Roles & Hierarchy

1.  **NOC Supervisor Agent** (`supervisor-network-engineer-agent`):
    *   **Role**: Router / Orchestrator.
    *   **Responsibility**: Receives incoming user commands (via Slack `#all-customer-001`) or Prometheus Alertmanager webhooks (pushed to `#noc-l3-alerts`). Uses a router LLM to analyze the incident state and delegate the task to the correct worker agent while dynamically generating contextual transition messages to inform the user. It enforces a safety loop limit of 5 turns before auto-escalating to Level 3.
2.  **Triage/Analytics Agent** (`analytics-network-engineer-agent`):
    *   **Role**: Incident Triager.
    *   **Responsibility**: Validates alerts, reviews hardware/software states, checks for link flapping, and creates the mandatory Jira ticket on the KAN board.
3.  **Expert Engineer Agent** (`expert-engineer-agent`):
    *   **Role**: Deep Diagnostician & Executor.
    *   **Responsibility**: Connects to datacenter switches/routers using NETCONF MCP tools, runs complex troubleshooting workflows, designs configuration changes, and updates Jira with detailed technical notes.
4.  **Customer Advisory Agent** (`customer-advisory-agent`):
    *   **Role**: L3 Engineer Escalation & Customer Communicator.
    *   **Responsibility**: Reviews the resolved incident logs, drafts customer-facing reports (Root Cause Analysis - RCA), and prepares self-help guidelines. Crucially, it manages two distinct notification channels: replying contextually to the **Customer** session, and escalating unresolved or limit-exceeded incidents to the internal **L3 Engineer** group via Slack. Finally, it transitions the Jira ticket to **DONE**.

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
│   ├── main.py                            # Runs web service, Slack bot, Email gateway, and routing loops
│   ├── system_prompt.py                   # Intent routing guidelines
│   ├── slack_bot.py                       # Slack Socket Mode integration & channel routing
│   ├── email_gateway.py                   # IMAP background thread email client gateway
│   ├── markdown_converter.py              # MD to HTML/Slack text converter
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
      │                                                 (User Clicks Approve in Slack #noc-cab-approvals)
      │                                                                     │
      ├─────────────────────────────────────────────────────────────────────┘
      │
      ▼
[Supervisor] ──► [Customer Advisory Agent] ──► (Post RCA/SOP Report) ──► [DONE]
```

---

## Slack Integration & Channel Architecture

To enforce Segregation of Duties and maintain strict confidentiality between client communication and L3 operational triage, the workspace is partitioned into 3 channels:

1. **`#all-customer-001` (ID: `C0BAVG5CLNN`) [Public]:** For customer updates and public bot interactions.
2. **`#noc-l3-alerts` (ID: `C0BAPPKR8RZ`) [Private]:** For Prometheus/Loki core alarms and P1 critical incident escalations.
3. **`#noc-cab-approvals` (ID: `C0BBQDECATS`) [Private]:** For L3 Change Advisory Board configuration approval workflows using Block Kit buttons.

---

## Slack & Web-Reading Tools

The worker agents are equipped with Slack utility and web-reading tools to leverage their newly granted workspace scopes:

*   `slack_view_profile(user_id)`: Retrieve detailed profile info of a Slack member (name, email, timezone, status).
*   `slack_react_message(channel_id, message_ts, emoji_name)`: React with an emoji (e.g. `thumbsup`, `white_check_mark`) to Slack messages.
*   `slack_view_status(user_id)`: Check user presence status (active/away).
*   `slack_send_file(channel_id, file_path, title, initial_comment)`: Upload diagnostic configurations, logs, or snapshots directly from the agent workspace to a Slack channel.
*   `slack_read_file(file_id)`: Read textual logs or configurations shared by L3 engineers.
*   `read_url(url)`: Download and strip HTML files/documentation into clean plain text for AI reading.

---

## Security Notes

*   **Secrets & Credentials**: Always keep your environment-specific passwords, Slack tokens, and Jira API Tokens in `.env` files. Ensure they are gitignored and never hardcoded in source files.
*   **Webhook Signing**: Simulate JIRA approvals locally using the HMAC SHA256 signatures helper script [approve_ticket.py](file:///home/thinhle/claw-a-thon-thinhlv-agent/shared/approve_ticket.py).

---

## Email Inbound Gateway

The Supervisor Agent includes an **Email Gateway** (`email_gateway.py`) that runs in a background thread:
*   **IMAP Polling**: Polls the inbox of `claw.a.thon.noc.agent.greennode01@gmail.com` every 10 seconds for unread emails.
*   **De-duplication & Loop Prevention**: Uses Redis cache to deduplicate emails using `Message-ID` with a 30-day TTL, and filters out auto-replies or bulk mail (precedence header).
*   **Body Parsing**: Extracts plain/HTML body elements and cleans signature/reply history via `email_reply_parser` and `BeautifulSoup`.
*   **Rate Limiting**: Restricts users to a maximum of 5 requests per minute using Redis counters.
*   **SMTP Replies**: Automatically drafts and emails responses back to the sender under the referenced email thread.

---

## Interactive NOC Inbound Request Parser Dashboard

To visualize and manually test the Natural Language parsing abilities of the NOC Supervisor, an interactive web interface is hosted on the MCP Server container:
*   **URL**: `http://localhost:8980/admin/`
*   **Features**:
    *   Pre-loaded mock scenarios (peering links down, interface config dump requests, routine maintenance scheduling).
    *   Simulates the intent classifier, target device extractor, priority levels assignment, and displays the designated worker agent.
    *   Automatically drafts title and body templates for direct Jira ticket creations.


