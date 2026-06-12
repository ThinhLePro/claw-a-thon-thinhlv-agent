---
name: dc-operations
description: "Datacenter network daily operations, SOPs, and regulatory procedures. Covers standard operating procedures for VLAN management, ACL/security policy, server bonding (LACP), new switch deployment, change management, scheduled maintenance, incident response, monitoring/alerting, and IP/IPAM management. Trigger: VLAN, add VLAN, trunk, bonding, LACP, deploy switch, change request, maintenance, incident, monitoring, alert, IP allocation, SOP, quy định, quy trình vận hành."
---

# DC Network Operations — SOPs & Quy Định Vận Hành

Toàn bộ quy trình vận hành chuẩn (SOP) và quy định cho hạ tầng DC network.

## Interaction Guidelines

- For every configuration change, provide:
  1. **Pre-check** commands (verify current state)
  2. **Configuration** commands (the change itself)
  3. **Post-check** commands (verify the change worked)
  4. **Rollback plan** (how to undo if something goes wrong)
- Always recommend `commit confirmed` for production changes.
- Ask clarifying questions: which switch? which interface? which VLAN?
- Reference the appropriate SOP document for each task.

## Topics Covered

| Topic | Reference File |
|---|---|
| VLAN management (add, change, trunk, naming, ID allocation) | `references/sop-vlan-management.md` |
| ACL & security policy (firewall filter, prefix-list, RE protection) | `references/sop-acl-security.md` |
| Server bonding (LACP, MC-LAG, ESI-LAG) | `references/sop-server-bonding.md` |
| New switch deployment (Day 0/Day 1 config, verification) | `references/sop-new-switch.md` |
| Change management process (CR workflow, risk, rollback) | `references/sop-change-management.md` |
| Bảo trì định kỳ (health check, backup, firmware) | `references/sop-maintenance.md` |
| Xử lý sự cố (incident response, escalation, RCA) | `references/sop-incident-response.md` |
| Giám sát & cảnh báo (SNMP, syslog, thresholds, dashboards) | `references/sop-monitoring.md` |
| Quản lý IP/IPAM (allocation, subnet planning, decommission) | `references/sop-ip-management.md` |

---

Read the appropriate reference file based on the user's question before responding.
