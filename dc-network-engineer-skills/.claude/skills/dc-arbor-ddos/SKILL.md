---
name: dc-arbor-ddos
description: "NETSCOUT Arbor DDoS protection expert. Covers Arbor Sightline (formerly Peakflow SP) for traffic monitoring, anomaly detection, alert management, and BGP-based mitigation triggering. Covers Arbor AED (Availability Protection System, formerly TMS/Pravail APS) for inline and out-of-band traffic scrubbing, mitigation templates, protection groups, countermeasure tuning, and cloud signaling. Includes daily operations, alert triage, mitigation lifecycle, integration with BGP (RTBH, Flowspec, TMS diversion), and troubleshooting common issues. Trigger: Arbor, Sightline, Peakflow, AED, TMS, Pravail, DDoS mitigation, scrubbing, anomaly detection, traffic baseline, managed object, protection group, countermeasure, mitigation template, cloud signaling, ATLAS, ASERT, NETSCOUT, traffic anomaly, volumetric attack, application attack, bot detection."
---

# NETSCOUT Arbor DDoS Protection — Sightline & AED

Expert knowledge on operating and troubleshooting NETSCOUT Arbor Sightline (traffic visibility & detection) and Arbor AED (inline/diversion-based mitigation) for datacenter DDoS protection.

## Interaction Guidelines

- When discussing alerts, always walk through the **full triage workflow**: alert → classification → action decision → mitigation → verification → closure.
- For mitigation, always specify **which device handles what**: Sightline detects → triggers mitigation on AED/TMS.
- Explain the **integration points** with network infrastructure (BGP, Flowspec, routers).
- Use **bilingual terminology** — English primary with Vietnamese context (Tiếng Việt bổ sung).
- Chỉ **hướng dẫn quy trình**, không tự động thao tác trên thiết bị production.
- For countermeasure tuning, always recommend **starting with monitoring mode** before enforcing.

## Topics Covered

| Topic | Reference File |
|---|---|
| Arbor Sightline — architecture, traffic monitoring, anomaly detection | `references/arbor-sightline.md` |
| Arbor AED — inline mitigation, countermeasures, protection groups | `references/arbor-aed.md` |
| Daily operations, alert triage, mitigation lifecycle | `references/arbor-operations.md` |
| Troubleshooting common issues | `references/arbor-troubleshooting.md` |
| Integration with BGP, routers, and cloud signaling | `references/arbor-integration.md` |
| APS countermeasures — all protection settings, filter lists, profiling | `references/aps-countermeasures.md` |
| APS deployment — inline/monitor, placement, HA, cloud signaling | `references/aps-deployment.md` |

## Quick Routing

- If user asks about **BGP Flowspec / RTBH on router** → redirect to `/dc-routing` (references/ddos-protection.md)
- If user asks about **firewall policies (SRX)** → redirect to `/dc-juniper-firewall`
- If user asks about **network design for DDoS** → redirect to `/dc-planning`
- If user asks about **packet analysis of attack traffic** → redirect to `/dc-tcpip` (references/packet-analysis.md)

---

Read the appropriate reference file based on the user's question before responding.
