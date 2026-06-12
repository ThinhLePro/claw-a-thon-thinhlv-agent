---
name: dc-juniper-mclag
description: "MC-LAG (Multi-Chassis Link Aggregation Group) expert. Covers MC-LAG protocol fundamentals (ICCP, ICL), operating principles, comparison with other HA technologies (MLAG, vPC, VSS, IRF, Virtual Chassis, EVPN ESI), configuration on Juniper QFX/EX, and known issues. Trigger: MC-LAG, MCLAG, ICCP, ICL, multi-chassis, dual-homing, multi-chassis link aggregation, redundancy, link aggregation HA."
---

# MC-LAG Technologies

Expert knowledge on MC-LAG (Multi-Chassis Link Aggregation Group) protocols, configuration, and operational considerations.

## Interaction Guidelines

- Always compare MC-LAG with **EVPN ESI multi-homing** — explain when each is preferred.
- Show **both sides** of the MC-LAG configuration (both chassis).
- For troubleshooting, check **ICCP status**, **ICL link health**, and **LACP convergence**.

## Topics Covered

| Topic | Reference File |
|---|---|
| MC-LAG fundamentals (ICCP, ICL, principles) | `references/mclag-fundamentals.md` |
| MC-LAG configuration on Juniper | `references/mclag-config.md` |
| MC-LAG known issues & best practices | `references/mclag-issues.md` |

---

Read the appropriate reference file based on the user's question before responding.
