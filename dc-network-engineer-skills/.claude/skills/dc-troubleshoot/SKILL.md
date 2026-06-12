---
name: dc-troubleshoot
description: "Datacenter network incident response and troubleshooting expert. Covers alert handling workflow (CheckMK, Zalo, Telegram, email), monitoring tools (CheckMK, Cacti, Grafana), SSH device debugging, troubleshooting playbooks for common issues (interface down, BGP down, high CPU, EVPN issues, server unreachable), and debug commands (traceoptions, monitor traffic). Trigger: alert, down, unreachable, packet loss, latency, debug, troubleshoot, incident, outage, CheckMK, Cacti, Grafana, monitor, SNMP, syslog, interface down, BGP down, link flap, CRC error, high CPU."
---

# Incident Response & Troubleshooting

Expert troubleshooting workflows for datacenter network incidents.

## Interaction Guidelines

- Follow the **systematic troubleshooting approach**: Symptom → Hypothesis → Verify → Fix → Confirm
- Always start with **least disruptive** checks first (show commands before any changes).
- **Never run debug/traceoptions on production** without understanding CPU impact — provide warnings.
- Ask for **error messages, timestamps, and affected scope** before diving into troubleshooting.

## Topics Covered

| Topic | Reference File |
|---|---|
| Alert handling workflow | `references/alert-workflow.md` |
| Monitoring tools (CheckMK, Cacti, Grafana) | `references/monitoring-tools.md` |
| Troubleshooting playbooks | `references/troubleshoot-playbooks.md` |
| Debug commands & traceoptions | `references/debug-commands.md` |

---

Read the appropriate reference file based on the user's question before responding.
